"""Always-new direct file-drop numbers, atomic batches and exact retry inputs."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.services.api import main
from backend.services.api.content_storage import configured_storage
from .test_code_generator_database import c,generator,resource_type
from .test_code_generation_creation import field
from .test_aggregation_file_drop import drop


@pytest.mark.parametrize("separate,count",[(True,2),(False,1)])
def test_file_drop_gets_configured_codes_and_preserves_component_bytes(client,c,aggregation,separate,count):
    generator(c,pattern="R{SERIAL}")
    c.commit()
    response=drop(client,aggregation,separate=separate)
    assert response.status_code==201,response.text
    assert response.json()=={"count":count}
    rows=c.execute("SELECT id,record_number FROM records ORDER BY id").fetchall()
    assert [row["record_number"] for row in rows]==[f"R{i*10}" for i in range(1,count+1)]
    assert c.execute("SELECT last_serial FROM code_generator_counters").fetchone()["last_serial"]==count*10
    components=c.execute("SELECT id FROM digital_components ORDER BY record_id,component_order").fetchall()
    assert [configured_storage().read(c,row["id"]) for row in components]==[b"first",b"second"]
    assert c.execute("SELECT count(*) AS n FROM record_drafts").fetchone()["n"]==0


def test_combined_drop_can_generate_its_blank_title_and_required_typed_text(client,c,aggregation):
    type_id=resource_type(c)
    text=field(c,type_id,"Contract number",1,required=True)
    generator(c,pattern="R{SERIAL}")
    generator(c,primary_field="title",pattern="Combined {SERIAL}")
    generator(c,primary_field=None,type_id=type_id,field_id=text,pattern="C{SERIAL}")
    c.commit()
    response=drop(client,aggregation,separate=False,data={"title":"","type_id":str(type_id)})
    assert response.status_code==201,response.text
    row=c.execute("SELECT id,record_number,title FROM records").fetchone()
    assert row["record_number"]=="R10" and row["title"]=="Combined 10"
    assert c.execute("SELECT resource_field_json(value) AS value FROM resource_type_values WHERE field_id=%s",(text,)).fetchone()["value"]=="C10"
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters WHERE last_serial=10").fetchone()["n"]==3


def test_same_file_drop_replays_and_changed_file_bytes_conflict(client,c,aggregation):
    generator(c,pattern="R{SERIAL}")
    c.commit()
    headers={"Idempotency-Key":str(uuid4())}
    first=drop(client,aggregation,headers=headers)
    assert first.status_code==201,first.text
    again=drop(client,aggregation,headers=headers)
    assert again.status_code==201,again.text
    assert again.json()==first.json()
    changed=drop(client,aggregation,headers=headers,files=[("files",("first.txt",b"changed","text/plain")),
        ("files",("second.txt",b"second","text/plain"))])
    assert changed.status_code==409,changed.text
    assert changed.json()["detail"]["code"]=="creation_submission_conflict"
    assert c.execute("SELECT count(*) AS n FROM records").fetchone()["n"]==2
    assert c.execute("SELECT count(*) AS n FROM digital_components").fetchone()["n"]==2
    assert c.execute("SELECT last_serial FROM code_generator_counters").fetchone()["last_serial"]==20
    assert c.execute("SELECT count(*) AS n FROM record_drafts").fetchone()["n"]==0


def test_failed_second_component_rolls_back_all_generated_fields_and_batch_receipt(client,c,aggregation,monkeypatch):
    generator(c,pattern="R{SERIAL}")
    c.commit()
    original=main._store_uploaded_component

    def fail(connection,record_id,file,*args,**kwargs):
        if file.file_name=="second.txt":
            raise HTTPException(422,detail="Second component fixture failure")
        return original(connection,record_id,file,*args,**kwargs)

    monkeypatch.setattr(main,"_store_uploaded_component",fail)
    response=drop(client,aggregation)
    assert response.status_code==422,response.text
    for table in ("records","digital_components","digital_component_blobs","code_generator_counters","record_drafts"):
        assert c.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]==0
    assert c.execute("SELECT count(*) AS n FROM resource_creation_requests WHERE operation='record.file_drop'").fetchone()["n"]==0
