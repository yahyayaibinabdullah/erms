"""Completed results retain identity without retaining erased descriptions."""

import json
from pathlib import Path
import time
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
import pytest

from backend.services.api.disposition import destruction
from .test_disposition_destruction import prepared,request
from .test_disposition_membership import actor,db
from .test_code_generator_database import c,generator


def receipt(c,kind,response,operation="record.create"):
    key=uuid4()
    result={"kind":kind,"resource_ids":[response["id"]],"response":response}
    c.execute("""INSERT INTO resource_creation_requests(caller_user_id,operation,submission_key,fingerprint,result)
        VALUES(1,%s,%s,%s,%s)""",(operation,key,"a"*64,Jsonb(result)))
    return key,result


def test_receipt_index_preserves_valid_long_manual_text_and_cannot_redact_outside_destruction(client,c,aggregation):
    generator(c,pattern="R{SERIAL}")
    generator(c,primary_field="title",pattern="Title {SERIAL}",max_code_length=20)
    c.commit()
    title="Long manual title "+"x"*20_000
    created=client.post("/api/v1/records",json={"aggregation_id":aggregation["id"],"title":title})
    assert created.status_code==201,created.text
    assert created.json()["title"]==title
    row=c.execute("SELECT submission_key,result FROM resource_creation_requests WHERE operation='record.create'").fetchone()
    assert row["result"]["response"]["title"]==title
    with pytest.raises(psycopg.errors.InsufficientPrivilege),c.transaction():
        c.execute("UPDATE resource_creation_requests SET result=result||jsonb_build_object('response',NULL,'unavailable',true) WHERE submission_key=%s",(row["submission_key"],))
    assert c.execute("SELECT creation_response_resource_id(result) AS id FROM resource_creation_requests WHERE submission_key=%s",(row["submission_key"],)).fetchone()["id"]==created.json()["id"]


def test_canonical_erasure_redacts_only_related_metadata_and_keeps_completed_identity(client,monkeypatch):
    with db() as c:
        job,root,manager=prepared(c,monkeypatch)
        source=c.execute("SELECT to_jsonb(r) AS response FROM records r WHERE aggregation_id IN (SELECT disposition_private.unit_ids(%s)) ORDER BY id LIMIT 1",(root,)).fetchone()["response"]
        source["description"]="Confidential creation-response snapshot"
        key,original=receipt(c,"record",source)
        c.execute("SELECT set_config('app.creator_acl_role_id','1',true)")
        other_root=c.execute("""INSERT INTO aggregations(aggregation_number,title,classification_id,medium,owning_org_unit_id)
            SELECT 'UNRELATED-ROOT','Unrelated parent',1,'digital',org_unit_id FROM roles WHERE id=1 RETURNING id""").fetchone()["id"]
        other=c.execute("""WITH added AS (INSERT INTO records(aggregation_id,record_number,title,medium)
            VALUES(%s,'UNRELATED-RECORD','Unrelated content','digital') RETURNING *) SELECT to_jsonb(added) AS response FROM added""",(other_root,)).fetchone()["response"]
        other_key,other_result=receipt(c,"record",other)
        count_key=uuid4()
        count_result={"kind":"record","resource_ids":[source["id"]],"response":{"count":1}}
        c.execute("""INSERT INTO resource_creation_requests(caller_user_id,operation,submission_key,fingerprint,result)
            VALUES(1,'record.file_drop',%s,%s,%s)""",(count_key,"b"*64,Jsonb(count_result)))
        c.execute("""INSERT INTO resource_creation_requests(caller_user_id,operation,submission_key,fingerprint,result)
            SELECT 1,'record.create',gen_random_uuid(),lpad(to_hex(n),64,'0'),
                jsonb_build_object('kind','record','resource_ids',jsonb_build_array(1000000+n),
                    'response',jsonb_build_object('id',1000000+n,'title','Unrelated benchmark response'))
            FROM generate_series(1,5000) n""")
        c.execute("ANALYZE resource_creation_requests")
        plan=c.execute("""EXPLAIN (ANALYZE,BUFFERS,SETTINGS,FORMAT JSON)
            SELECT caller_user_id,operation,submission_key FROM resource_creation_requests
            WHERE result->>'kind'='record' AND creation_response_resource_id(result)=%s
              AND creation_response_resource_id(result) IS NOT NULL""",(source["id"],)).fetchone()["QUERY PLAN"]
        request(c,job,manager)
        database_name=c.info.dbname
    started=time.perf_counter()
    assert destruction.process_one(db)
    elapsed=time.perf_counter()-started
    with db() as c:
        changed=c.execute("SELECT * FROM resource_creation_requests WHERE submission_key=%s",(key,)).fetchone()
        assert changed["result"]=={**original,"response":None,"unavailable":True}
        assert changed["fingerprint"]=="a"*64 and changed["caller_user_id"]==1
        assert "Confidential" not in json.dumps(changed["result"])
        assert c.execute("SELECT result FROM resource_creation_requests WHERE submission_key=%s",(other_key,)).fetchone()["result"]==other_result
        assert c.execute("SELECT result FROM resource_creation_requests WHERE submission_key=%s",(count_key,)).fetchone()["result"]==count_result
        assert c.execute("SELECT count(*) AS n FROM resource_creation_requests").fetchone()["n"]==5003
        assert c.execute("SELECT state FROM disposition_destruction_runs").fetchone()["state"]=="succeeded"
    directory=Path(__file__).resolve().parents[4]/".runtime/custom-code-generators/erasure-metrics"
    directory.mkdir(parents=True,exist_ok=True)
    (directory/f"{database_name}.json").write_text(json.dumps({"receipts":5003,"related_metadata_receipts":1,
        "complete_erasure_worker_seconds":elapsed,"response_identity_plan":plan},indent=2,default=str)+"\n")
