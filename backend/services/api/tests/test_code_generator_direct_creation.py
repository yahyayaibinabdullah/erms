"""CG-06/07/10/15 through direct final-creation endpoints."""

from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from .test_code_generator_database import c, generator, resource_type
from .test_code_generation_creation import field
from .test_code_generator_creation_baseline import stage_document, assert_staged_document


def request_body(aggregation,**changes):
    return {"aggregation_id":aggregation["id"],"title":"Generated document",**changes}


def test_missing_submission_key_cannot_create_or_allocate(client,c,aggregation):
    generator(c,pattern="R{SERIAL}")
    c.commit()
    response=client.post("/api/v1/records",json=request_body(aggregation),headers={"Idempotency-Key":""})
    assert response.status_code==428,response.text
    assert response.json()["detail"]["code"]=="creation_submission_key_required"
    assert c.execute("SELECT count(*) AS n FROM records").fetchone()["n"]==0
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"]==0


def test_direct_creation_generates_required_typed_text_after_defaults(client,c,aggregation):
    type_id=resource_type(c)
    required=field(c,type_id,"Contract number",1,required=True)
    static=field(c,type_id,"Static reference",2,default="STATIC",required=True)
    generator(c,pattern="R{SERIAL}")
    generator(c,primary_field=None,type_id=type_id,field_id=required,pattern="C{SERIAL}")
    generator(c,primary_field=None,type_id=type_id,field_id=static,pattern="S{SERIAL}")
    c.commit()
    response=client.post("/api/v1/records",json=request_body(aggregation,type_id=type_id))
    assert response.status_code==201,response.text
    assert response.json()["record_number"]=="R10"
    assert response.json()["field_values"]=={str(required):"C10",str(static):"STATIC"}
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"]==2


def test_manual_values_win_without_advancing_and_ordinary_updates_do_not_generate(client,c,aggregation):
    definition=generator(c,pattern="R{SERIAL}")
    c.commit()
    response=client.post("/api/v1/records",json=request_body(aggregation,record_number=" MANUAL "))
    assert response.status_code==201,response.text
    row=response.json()
    assert row["record_number"]=="MANUAL"
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"]==0
    updated=client.patch(f"/api/v1/records/{row['id']}",json={"description":"Manual edit"},headers={"If-Match":str(row["version"])})
    assert updated.status_code==200,updated.text
    assert updated.json()["record_number"]=="MANUAL"
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters WHERE generator_id=%s",(definition["id"],)).fetchone()["n"]==0


def test_accepted_suggestion_is_exact_or_conflicts_and_preserves_counter(client,c,aggregation):
    definition=generator(c,pattern="R{SERIAL}")
    c.commit()
    body=request_body(aggregation,record_number="R10",generation_intent={"record_number":{"source":"generator","generator_id":definition["id"]}})
    first=client.post("/api/v1/records",json=body)
    assert first.status_code==201,first.text
    assert first.json()["record_number"]=="R10"
    response=client.post("/api/v1/records",json={**body,"title":"Another document"})
    assert response.status_code==409,response.text
    assert response.json()["detail"]["code"]=="code_generator_recommendation_conflict"
    assert c.execute("SELECT last_serial FROM code_generator_counters").fetchone()["last_serial"]==10
    assert c.execute("SELECT count(*) AS n FROM records").fetchone()["n"]==1


def test_lost_response_replay_changed_inputs_deleted_outcome_and_manual_reuse(client,c,aggregation):
    generator(c,pattern="R{SERIAL}")
    c.commit()
    headers={"Idempotency-Key":str(uuid4())}
    body=request_body(aggregation)
    first=client.post("/api/v1/records",json=body,headers=headers)
    assert first.status_code==201,first.text
    repeated=client.post("/api/v1/records",json=body,headers=headers)
    assert repeated.status_code==201,repeated.text
    assert repeated.json()==first.json()
    changed=client.post("/api/v1/records",json={**body,"title":"Different input"},headers=headers)
    assert changed.status_code==409,changed.text
    assert changed.json()["detail"]["code"]=="creation_submission_conflict"
    assert c.execute("SELECT count(*) AS n FROM records").fetchone()["n"]==1
    assert c.execute("SELECT last_serial FROM code_generator_counters").fetchone()["last_serial"]==10
    row=first.json()
    assert client.delete(f"/api/v1/records/{row['id']}",headers={"If-Match":str(row["version"])}).status_code==204
    gone=client.post("/api/v1/records",json=body,headers=headers)
    assert gone.status_code==410,gone.text
    assert gone.json()["detail"]["code"]=="creation_submission_unavailable"
    assert "Creation-Outcome" not in gone.headers
    assert c.execute("SELECT count(*) AS n FROM records").fetchone()["n"]==0
    reused=client.post("/api/v1/records",json=request_body(aggregation,record_number="R10"))
    assert reused.status_code==201,reused.text
    assert c.execute("SELECT last_serial FROM code_generator_counters").fetchone()["last_serial"]==10
    next_record=client.post("/api/v1/records",json=request_body(aggregation))
    assert next_record.status_code==201,next_record.text
    assert next_record.json()["record_number"]=="R20"


def test_root_aggregation_generates_primary_fields_with_classification_owner_and_role(client,c):
    generator(c,kind="aggregation",primary_field="aggregation_number",
        pattern="{CLASSIFICATION_SCHEME_CODE}/{CLASSIFICATION_CODE}/{ORG_UNIT_CODE}/{ROLE_CODE}/{SERIAL}",max_code_length=200)
    generator(c,kind="aggregation",primary_field="title",pattern="Folder {SERIAL}")
    c.commit()
    response=client.post("/api/v1/aggregations",json={"classification_id":1})
    assert response.status_code==201,response.text
    assert response.json()["aggregation_number"]=="TEST/TEST-01/test-root/system-administrator/10"
    assert response.json()["title"]=="Folder 10"
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters WHERE last_serial=10").fetchone()["n"]==2


def test_numberless_blank_draft_saves_and_keeps_automatic_origin_without_allocating(client,c,aggregation):
    definition=generator(c,pattern="R{SERIAL}")
    c.commit()
    response=client.post("/api/v1/record-drafts",json={"aggregation_id":aggregation["id"],"record_number":"","title":""})
    assert response.status_code==201,response.text
    draft=response.json()
    assert draft["record_number"] is None and draft["title"] is None
    origin={"record_number":{"source":"generator","generator_id":definition["id"]}}
    saved=client.patch(f"/api/v1/record-drafts/{draft['id']}",json={"record_number":"R10","generation_intent":origin})
    assert saved.status_code==200,saved.text
    assert client.get(f"/api/v1/record-drafts/{draft['id']}").json()["generation_intent"]==origin
    unrelated=client.patch(f"/api/v1/record-drafts/{draft['id']}",json={"description":"Preserve origin"})
    assert unrelated.json()["generation_intent"]==origin
    manual=client.patch(f"/api/v1/record-drafts/{draft['id']}",json={"record_number":"MANUAL"})
    assert manual.status_code==200,manual.text
    assert manual.json()["generation_intent"]=={}
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"]==0


def test_numberless_final_draft_generates_then_replays_after_draft_is_deleted(client,c,aggregation):
    generator(c,pattern="R{SERIAL}")
    c.commit()
    draft=client.post("/api/v1/record-drafts",json={"aggregation_id":aggregation["id"],"title":"Unnumbered draft"}).json()
    stage_document(client,draft["id"],b"Draft content")
    key={"Idempotency-Key":str(uuid4())}
    path=f"/api/v1/record-drafts/{draft['id']}/commit"
    response=client.post(path,headers=key)
    assert response.status_code==201,response.text
    assert response.json()["record_number"]=="R10"
    assert client.get(f"/api/v1/record-drafts/{draft['id']}").status_code==404
    repeated=client.post(path,headers=key)
    assert repeated.status_code==201,repeated.text
    assert repeated.json()==response.json()
    assert c.execute("SELECT count(*) AS n FROM records").fetchone()["n"]==1
    assert c.execute("SELECT count(*) AS n FROM digital_components").fetchone()["n"]==1
    assert c.execute("SELECT last_serial FROM code_generator_counters").fetchone()["last_serial"]==10


def test_chosen_draft_conflict_preserves_metadata_origin_and_actual_document_bytes(client,c,aggregation):
    definition=generator(c,pattern="R{SERIAL}")
    c.commit()
    occupied=client.post("/api/v1/records",json=request_body(aggregation,record_number="R10"))
    assert occupied.status_code==201,occupied.text
    origin={"record_number":{"source":"generator","generator_id":definition["id"]}}
    created=client.post("/api/v1/record-drafts",json={"aggregation_id":aggregation["id"],"record_number":"R10",
        "title":"Document contains R10","description":"Keep this work","generation_intent":origin})
    assert created.status_code==201,created.text
    draft=created.json()
    component=stage_document(client,draft["id"],b"Document number: R10")
    response=client.post(f"/api/v1/record-drafts/{draft['id']}/commit")
    assert response.status_code==409,response.text
    assert response.json()["detail"]["code"]=="code_generator_recommendation_conflict"
    reopened=client.get(f"/api/v1/record-drafts/{draft['id']}").json()
    for key in ("record_number","title","description","generation_intent"):
        assert reopened[key]==draft[key]
    assert_staged_document(client,draft["id"],component,b"Document number: R10")
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"]==0


def test_capture_prepares_pdf_without_counter_lock_and_conflict_restores_its_draft(client,c,aggregation,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from backend.services.api.messaging import capture,capture_pdf
    from .test_messaging_phase5 import account,post,payload,PREFIX

    other=client.post("/api/v1/aggregations",json={"aggregation_number":"AGG-OTHER","title":"Other parent","classification_id":1})
    assert other.status_code==201,other.text
    definition=generator(c,pattern="R{SERIAL}")
    c.commit()
    admin=client.cookies["erms_session"]
    sender,_,_=account(client)
    source=post(client,sender,payload(1)).json()
    monkeypatch.setattr(capture_pdf,"render",lambda *args,**kwargs:b"fault-injection-only")
    result=client.post(PREFIX+"/"+source["envelope_id"]+"/capture",headers={"Authorization":"Bearer "+admin})
    assert result.status_code==201,result.text
    draft=result.json()
    path=f"/api/v1/record-drafts/{draft['id']}"
    placed=client.patch(path,json={"aggregation_id":aggregation["id"]},headers={"Authorization":"Bearer "+admin})
    assert placed.status_code==200,placed.text
    original_components=client.get(path+"/components",headers={"Authorization":"Bearer "+admin}).json()
    original=capture.finalize_staging
    executor=ThreadPoolExecutor(max_workers=1)
    completed=[]

    def prepare(*args,**kwargs):
        future=executor.submit(client.post,"/api/v1/records",json=request_body(other.json()),
            headers={"Authorization":"Bearer "+admin})
        response=future.result(timeout=10)
        assert response.status_code==201,response.text
        assert response.json()["record_number"]=="R10"
        completed.append(response.json())
        return original(*args,**kwargs)

    monkeypatch.setattr(capture,"finalize_staging",prepare)
    try:
        response=client.post(path+"/commit",headers={"Authorization":"Bearer "+admin})
    finally:
        executor.shutdown(wait=True,cancel_futures=True)
    assert response.status_code==409,response.text
    assert response.json()["detail"]["code"]=="code_generator_recommendation_conflict"
    assert len(completed)==1
    assert client.get(path,headers={"Authorization":"Bearer "+admin}).status_code==200
    assert client.get(path+"/components",headers={"Authorization":"Bearer "+admin}).json()==original_components
    assert c.execute("SELECT last_serial FROM code_generator_counters WHERE generator_id=%s",(definition["id"],)).fetchone()["last_serial"]==10
    assert c.execute("SELECT count(*) AS n FROM message_record_captures").fetchone()["n"]==0


def test_configured_suggestions_use_type_and_live_state_without_allocating(client,c,aggregation):
    type_id=resource_type(c)
    definition=generator(c,type_id=type_id,pattern="R{SERIAL}")
    c.commit()
    params={"parent_aggregation_id":aggregation["id"],"type_id":type_id}
    url="/api/v1/number-suggestions/records"
    first=client.get(url,params=params)
    assert first.status_code==200,first.text
    result=first.json()
    assert result["suggested_number"]=="R10"
    assert result["generation_intent"]=={"source":"generator","generator_id":definition["id"]}
    assert client.get(url,params=params).json()==result
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"]==0
    legacy=client.get(url,params={"parent_aggregation_id":aggregation["id"]})
    assert legacy.status_code==200,legacy.text
    assert legacy.json()["suggested_number"]==aggregation["aggregation_number"]+".1"
    assert legacy.json()["generation_intent"]=={"source":"legacy"}
    created=client.post("/api/v1/records",json=request_body(aggregation,type_id=type_id,record_number="R10",
        generation_intent={"record_number":result["generation_intent"]}))
    assert created.status_code==201,created.text
    assert client.get(url,params=params).json()["suggested_number"]=="R20"
    assert c.execute("SELECT last_serial FROM code_generator_counters").fetchone()["last_serial"]==10


def test_custom_suggestion_accepts_codes_beyond_legacy_limit_and_uses_existing_create_for(client,c,aggregation):
    from .test_code_generator_database import actor
    actor(c)
    second=c.execute("INSERT INTO roles(org_unit_id,code,name) VALUES(%s,'second-creator','Second creator') RETURNING id",
                     (aggregation["owning_org_unit_id"],)).fetchone()["id"]
    c.execute("INSERT INTO user_role_assignments(user_id,role_id) VALUES(1,%s)",(second,))
    generator(c,pattern="{ROLE_CODE}/"+"L"*210+"/{SERIAL}",max_code_length=300)
    c.commit()
    url="/api/v1/number-suggestions/records"
    params={"parent_aggregation_id":aggregation["id"]}
    missing=client.get(url,params=params)
    assert missing.status_code==422,missing.text
    assert missing.json()["detail"]["code"]=="creator_acl_role_selection_required"
    response=client.get(url,params={**params,"creator_acl_role_id":second,"number":"X"*240})
    assert response.status_code==200,response.text
    assert response.json()["suggested_number"]=="second-creator/"+"L"*210+"/10"
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"]==0


def test_configured_suggestion_denies_a_caller_without_target_access(client,c,aggregation):
    from .test_global_privilege_enforcement import _account,_bearer
    generator(c,pattern="R{SERIAL}")
    c.commit()
    token,_,_=_account(client,privileges=("record.create","aggregation.view"),suffix="generator-unrelated")
    response=client.get("/api/v1/number-suggestions/records",params={"parent_aggregation_id":aggregation["id"]},headers=_bearer(token))
    assert response.status_code==404,response.text
    hints=client.get("/api/v1/code-generation/bindings",params={"kind":"record","parent_aggregation_id":aggregation["id"]},headers=_bearer(token))
    assert hints.status_code==404,hints.text
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"]==0


def test_replay_rechecks_current_resource_access_without_creating_again(client,c,aggregation):
    from .test_code_generator_database import actor
    generator(c,pattern="R{SERIAL}")
    c.commit()
    key={"Idempotency-Key":str(uuid4())}
    body=request_body(aggregation)
    created=client.post("/api/v1/records",json=body,headers=key)
    assert created.status_code==201,created.text
    actor(c)
    profile=c.execute("INSERT INTO profiles(code,name) VALUES('GENERATOR_CREATE_ONLY','Create without record view') RETURNING id").fetchone()["id"]
    c.execute("""INSERT INTO profile_privileges(profile_id,privilege_id) SELECT %s,id FROM privileges
        WHERE code IN ('record.create','aggregation.view')""",(profile,))
    c.execute("UPDATE roles SET profile_id=%s,is_information_governance=false WHERE id=1",(profile,))
    c.commit()
    repeated=client.post("/api/v1/records",json=body,headers=key)
    assert repeated.status_code==410,repeated.text
    assert repeated.json()["detail"]["code"]=="creation_submission_unavailable"
    assert c.execute("SELECT count(*) AS n FROM records").fetchone()["n"]==1
    assert c.execute("SELECT last_serial FROM code_generator_counters").fetchone()["last_serial"]==10


def test_completed_replay_precedes_time_dependent_creation_validation(client,c,aggregation,monkeypatch):
    from datetime import datetime,timedelta,timezone
    from backend.services.api import schemas
    generator(c,pattern="R{SERIAL}")
    c.commit()
    key={"Idempotency-Key":str(uuid4())}
    body=request_body(aggregation,date_of_next_review=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
    created=client.post("/api/v1/records",json=body,headers=key)
    assert created.status_code==201,created.text
    # Simulate a later retry after this creation-only temporal rule would fail.
    # The completed operation must be found before validating a new creation.
    monkeypatch.setattr(schemas,"_is_future",lambda value:False)
    repeated=client.post("/api/v1/records",json=body,headers=key)
    assert repeated.status_code==201,repeated.text
    assert repeated.json()==created.json()
    assert c.execute("SELECT count(*) AS n FROM records").fetchone()["n"]==1
    assert client.post("/api/v1/records",json=body).status_code==422


def test_only_confirmed_failed_creation_has_rollback_proof_header(client,c,aggregation):
    generator(c,pattern="R{SERIAL}")
    c.commit()
    headers={"Idempotency-Key":str(uuid4())}
    incomplete=request_body(aggregation,title=None)
    failed=client.post("/api/v1/records",json=incomplete,headers=headers)
    assert failed.status_code==422,failed.text
    assert failed.headers.get("Creation-Outcome")=="not-created"
    assert c.execute("SELECT count(*) AS n FROM resource_creation_requests WHERE operation='record.create'").fetchone()["n"]==0
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"]==0
    completed=client.post("/api/v1/records",json=request_body(aggregation),headers=headers)
    assert completed.status_code==201,completed.text
    assert "Creation-Outcome" not in completed.headers
    changed=client.post("/api/v1/records",json=incomplete,headers=headers)
    assert changed.status_code==409,changed.text
    assert "Creation-Outcome" not in changed.headers


def test_binding_hints_are_authorized_bounded_and_exclude_configuration(client,c,aggregation):
    type_id=resource_type(c)
    fields=[field(c,type_id,f"Reference {index}",index) for index in range(1,106)]
    primary=generator(c,pattern="R{SERIAL}")
    for fid in fields:
        generator(c,primary_field=None,type_id=type_id,field_id=fid,pattern="C{SERIAL}")
    c.commit()
    path="/api/v1/code-generation/bindings"
    params={"kind":"record","parent_aggregation_id":aggregation["id"],"type_id":type_id,"limit":100}
    primary_only=client.get(path,params=params)
    assert primary_only.status_code==200,primary_only.text
    assert primary_only.json()=={"total":1,"items":[{"generator_id":primary["id"],"primary_field":"record_number","field_id":None}]}
    ids=[]
    for page in (fields[:90],fields[90:]):
        response=client.get(path,params={**params,"field_ids":page})
        assert response.status_code==200,response.text
        assert response.json()["total"]==len(page)+1
        ids.extend(row["field_id"] for row in response.json()["items"] if row["field_id"])
        assert all(set(row)=={"generator_id","primary_field","field_id"} for row in response.json()["items"])
    assert ids==fields
    assert client.get(path,params={**params,"field_ids":fields}).status_code==422
    assert client.get(path,params={**params,"parent_aggregation_id":999999}).status_code==404
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"]==0


def test_simultaneous_retries_create_one_resource_and_one_completed_receipt(client,c,aggregation):
    generator(c,pattern="R{SERIAL}")
    c.commit()
    headers={"Idempotency-Key":str(uuid4())}
    body=request_body(aggregation)
    barrier=Barrier(4)
    def submit():
        barrier.wait(timeout=10)
        return client.post("/api/v1/records",json=body,headers=headers)
    with ThreadPoolExecutor(max_workers=4) as workers:
        responses=list(workers.map(lambda _:submit(),range(4)))
    assert all(response.status_code==201 for response in responses),[r.text for r in responses]
    assert all(response.json()==responses[0].json() for response in responses)
    assert c.execute("SELECT count(*) AS n FROM records").fetchone()["n"]==1
    assert c.execute("SELECT count(*) AS n FROM resource_creation_requests WHERE operation='record.create'").fetchone()["n"]==1
    assert c.execute("SELECT last_serial FROM code_generator_counters").fetchone()["last_serial"]==10
    assert c.execute("SELECT count(*) AS n FROM event_history WHERE entity_type='record' AND entity_id=%s AND operation='CREATE'",
                     (responses[0].json()["id"],)).fetchone()["n"]==1


@pytest.mark.parametrize('chosen',[False,True])
def test_manual_insert_racing_final_insert_retries_only_an_unchosen_number(client,c,aggregation,monkeypatch,chosen):
    from backend.services.api import main
    other=client.post('/api/v1/aggregations',json={'aggregation_number':'OTHER','title':'Other parent',
        'classification_id':1,'medium':'mixed'})
    assert other.status_code==201,other.text
    number=generator(c,pattern='R{SERIAL}')
    title=generator(c,primary_field='title',pattern='T{SERIAL}')
    c.commit()
    original=main.create_row
    raced=[]
    def create(connection,table,values,*args,**kwargs):
        if table=='records' and not raced:
            raced.append(True)
            competitor=client.post('/api/v1/records',json=request_body(other.json(),record_number='R10'))
            assert competitor.status_code==201,competitor.text
        return original(connection,table,values,*args,**kwargs)
    monkeypatch.setattr(main,'create_row',create)
    changes={'title':None}
    if chosen:
        changes.update(record_number='R10',generation_intent={'record_number':{'source':'generator','generator_id':number['id']}})
    response=client.post('/api/v1/records',json=request_body(aggregation,**changes))
    if chosen:
        assert response.status_code==409,response.text
        assert response.json()['detail']['code']=='code_generator_recommendation_conflict'
        assert c.execute('SELECT count(*) AS n FROM code_generator_counters').fetchone()['n']==0
        assert c.execute('SELECT count(*) AS n FROM records').fetchone()['n']==1
    else:
        assert response.status_code==201,response.text
        assert response.json()['record_number']=='R20' and response.json()['title']=='T10'
        assert c.execute('SELECT generator_id,last_serial FROM code_generator_counters ORDER BY generator_id').fetchall()==[
            {'generator_id':number['id'],'last_serial':20},{'generator_id':title['id'],'last_serial':10}]
        assert c.execute('SELECT count(*) AS n FROM records').fetchone()['n']==2


@pytest.mark.parametrize('typed',[False,True])
def test_closed_placement_correction_uses_generator_preserves_closure_and_replays(client,c,aggregation,typed):
    generator(c,pattern='R{SERIAL}')
    type_id=resource_type(c) if typed else None
    field_id=field(c,type_id,'Historical reference',1,required=True) if typed else None
    if typed:
        generator(c,primary_field=None,type_id=type_id,field_id=field_id,pattern='C{SERIAL}')
    c.commit()
    draft=client.post('/api/v1/record-drafts',json={'aggregation_id':aggregation['id'],'title':'Historical placement'}).json()
    component=stage_document(client,draft['id'],b'Historical document')
    closed=client.patch(f"/api/v1/aggregations/{aggregation['id']}",json={'date_closed':aggregation['date_created']},
                        headers={'If-Match':str(aggregation['version'])})
    assert closed.status_code==200,closed.text
    path=f"/api/v1/record-drafts/{draft['id']}/commit-placement-correction"
    assert client.post(path).status_code==422
    assert_staged_document(client,draft['id'],component,b'Historical document')
    headers={'Idempotency-Key':str(uuid4()),'X-Change-Reason':'Correct historical filing placement'}
    options={'json':{'type_id':type_id}} if typed else {}
    created=client.post(path,headers=headers,**options)
    assert created.status_code==201,created.text
    assert created.json()['record_number']=='R10'
    if typed:
        assert created.json()['field_values']=={str(field_id):'C10'}
    repeated=client.post(path,headers=headers,**options)
    assert repeated.status_code==201 and repeated.json()==created.json(),repeated.text
    assert client.get(f"/api/v1/aggregations/{aggregation['id']}").json()['date_closed']==closed.json()['date_closed']
    assert c.execute("SELECT count(*) AS n FROM event_history WHERE operation='CLOSED_AGGREGATION_RECORD_CORRECTED'").fetchone()['n']==1
    assert c.execute('SELECT count(*) AS n FROM digital_components').fetchone()['n']==1
    changed=client.patch(f"/api/v1/records/{created.json()['id']}",json={'title':'Not a placement correction'},
                         headers={'If-Match':str(created.json()['version'])})
    assert changed.status_code==409,changed.text
    component_id=c.execute('SELECT id FROM digital_components').fetchone()['id']
    changed_component=client.patch(f'/api/v1/digital-components/{component_id}',json={'file_name':'Changed.pdf'},
                                   headers={'If-Match':'1'})
    assert changed_component.status_code==409,changed_component.text
    assert c.execute("""SELECT count(*) AS n FROM pg_proc function
        CROSS JOIN LATERAL aclexplode(coalesce(function.proacl,acldefault('f',function.proowner))) privilege
        WHERE function.oid='public.begin_closed_record_creation(bigint,bigint)'::regprocedure
          AND privilege.grantee=0 AND privilege.privilege_type='EXECUTE'""").fetchone()['n']==0


def test_receipt_failure_rolls_back_record_counters_draft_promotion_and_files(client,c,aggregation,monkeypatch):
    from fastapi import HTTPException
    from backend.services.api import creation_requests
    generator(c,pattern='R{SERIAL}')
    c.commit()
    draft=client.post('/api/v1/record-drafts',json={'aggregation_id':aggregation['id'],'title':'Keep on failure'}).json()
    component=stage_document(client,draft['id'],b'Keep these bytes')
    path=f"/api/v1/record-drafts/{draft['id']}/commit"
    key={'Idempotency-Key':str(uuid4())}
    def fail(*args,**kwargs):
        raise HTTPException(500,'Completion receipt unavailable')
    with monkeypatch.context() as patch:
        patch.setattr(creation_requests,'complete',fail)
        response=client.post(path,headers=key)
    assert response.status_code==500,response.text
    assert response.headers.get('Creation-Outcome')=='not-created'
    assert c.execute('SELECT count(*) AS n FROM records').fetchone()['n']==0
    assert c.execute('SELECT count(*) AS n FROM code_generator_counters').fetchone()['n']==0
    assert c.execute("SELECT count(*) AS n FROM resource_creation_requests WHERE operation='record_draft.commit'").fetchone()['n']==0
    assert_staged_document(client,draft['id'],component,b'Keep these bytes')
    created=client.post(path,headers=key)
    assert created.status_code==201,created.text
    assert created.json()['record_number']=='R10'


def test_creation_binding_hints_require_parent_access_and_selected_type_use_without_admin_privilege(client,c,aggregation):
    from .test_phase7_mutation_authorization import _grant_principal,_login_as_phase7,_set_aggregation_acl
    type_id=resource_type(c)
    generator(c,pattern='R{SERIAL}')
    c.commit()
    _,role=_grant_principal({'record.create','record.view','aggregation.view'})
    _set_aggregation_acl(aggregation['id'],role,{'aggregation.view','aggregation.add_record'})
    _login_as_phase7(client)
    path='/api/v1/code-generation/bindings'
    params={'kind':'record','parent_aggregation_id':aggregation['id']}
    allowed=client.get(path,params=params)
    assert allowed.status_code==200,allowed.text
    assert allowed.json()['total']==1
    assert client.get('/api/v1/code-generators').status_code==403
    denied=client.get(path,params={**params,'type_id':type_id})
    assert denied.status_code==403,denied.text
    c.execute("INSERT INTO resource_type_role_grants(kind,type_id,role_id,can_use) VALUES('record',%s,%s,false)",(type_id,role))
    c.commit()
    see_only=client.get(path,params={**params,'type_id':type_id})
    assert see_only.status_code==403,see_only.text
    c.execute("UPDATE resource_type_role_grants SET can_use=true WHERE type_id=%s AND role_id=%s",(type_id,role))
    c.commit()
    assert client.get(path,params={**params,'type_id':type_id}).status_code==200


@pytest.mark.parametrize('change',['parent_number','configuration','month','counter'])
def test_chosen_recommendation_is_rechecked_after_context_period_configuration_or_counter_changes(client,c,aggregation,monkeypatch,change):
    from dataclasses import replace
    from datetime import timedelta
    from backend.services.api import main
    from .test_code_generator_database import actor
    pattern=('{YYYY}/{MM}/{PARENT_AGGREGATION_NUMBER}/{SERIAL}' if change=='month' else
             '{PARENT_AGGREGATION_NUMBER}/{SERIAL}')
    definition=generator(c,pattern=pattern,**({'reset_frequency':'monthly'} if change=='month' else {}))
    c.commit()
    suggestion=client.get('/api/v1/number-suggestions/records',params={'parent_aggregation_id':aggregation['id']})
    assert suggestion.status_code==200,suggestion.text
    chosen=suggestion.json()['suggested_number']
    if change=='parent_number':
        updated=client.patch(f"/api/v1/aggregations/{aggregation['id']}",json={'aggregation_number':'NEW-PARENT'},
                             headers={'If-Match':str(aggregation['version'])})
        assert updated.status_code==200,updated.text
    elif change=='configuration':
        actor(c,reason='Change future code format')
        c.execute("UPDATE code_generators SET pattern='NEW/'||pattern WHERE id=%s",(definition['id'],))
        c.commit()
    elif change=='month':
        original=main.generation_context
        monkeypatch.setattr(main,'generation_context',lambda *args,**kwargs: replace(
            (context:=original(*args,**kwargs)),instant=context.instant+timedelta(days=32)))
    else:
        advanced=client.post(f"/api/v1/code-generators/{definition['id']}/counter/advance",
            json={'next_number':'20'},
            headers={'If-Match':'0','X-Change-Reason':'Advance future sequence'})
        assert advanced.status_code==200,advanced.text
    before=c.execute('SELECT * FROM code_generator_counters').fetchall()
    response=client.post('/api/v1/records',json=request_body(aggregation,record_number=chosen,
        generation_intent={'record_number':suggestion.json()['generation_intent']}))
    assert response.status_code==409,response.text
    assert response.json()['detail']['code']=='code_generator_recommendation_conflict'
    assert c.execute('SELECT * FROM code_generator_counters').fetchall()==before
    assert c.execute('SELECT count(*) AS n FROM records').fetchone()['n']==0


@pytest.mark.parametrize('child',[False,True])
def test_typed_root_and_child_aggregations_share_generation_and_descendant_context(client,c,aggregation,child):
    type_id=c.execute("INSERT INTO resource_types(kind,name) VALUES('aggregation',%s) RETURNING id",
                      ('Generated folders-'+uuid4().hex,)).fetchone()['id']
    field_id=c.execute("""INSERT INTO resource_type_fields(kind,type_id,name,display_order,data_type,max_length,required)
        VALUES('aggregation',%s,'Folder reference',1,'text',100,true) RETURNING id""",(type_id,)).fetchone()['id']
    generator(c,kind='aggregation',primary_field='aggregation_number',
        pattern='{CLASSIFICATION_SCHEME_CODE}/{CLASSIFICATION_CODE}/{SERIAL}',scope='classification')
    generator(c,kind='aggregation',primary_field='title',pattern='Folder {SERIAL}')
    generator(c,kind='aggregation',primary_field=None,type_id=type_id,field_id=field_id,
        pattern='{ORG_UNIT_CODE}/{ROLE_CODE}/{SERIAL}',scope='org_unit')
    generator(c,pattern='{PARENT_AGGREGATION_NUMBER}/{CLASSIFICATION_CODE}/{ORG_UNIT_CODE}/{SERIAL}')
    c.commit()
    placement={'parent_aggregation_id':aggregation['id']} if child else {'classification_id':1}
    created=client.post('/api/v1/aggregations',json={'type_id':type_id,**placement})
    assert created.status_code==201,created.text
    folder=created.json()
    assert folder['aggregation_number']=='TEST/TEST-01/10' and folder['title']=='Folder 10'
    assert folder['field_values']=={str(field_id):'test-root/system-administrator/10'}
    assert folder['owning_org_unit_id']==aggregation['owning_org_unit_id']
    descendant=client.post('/api/v1/records',json=request_body(folder))
    assert descendant.status_code==201,descendant.text
    assert descendant.json()['record_number']=='TEST/TEST-01/10/TEST-01/test-root/10'
    counters=c.execute('SELECT generator_id,last_serial FROM code_generator_counters ORDER BY generator_id').fetchall()
    manual=client.post('/api/v1/aggregations',json={'type_id':type_id,**placement,
        'aggregation_number':'MANUAL-FOLDER','title':'Manual folder','field_values':{str(field_id):'MANUAL-REFERENCE'}})
    assert manual.status_code==201,manual.text
    assert c.execute('SELECT generator_id,last_serial FROM code_generator_counters ORDER BY generator_id').fetchall()==counters


@pytest.mark.parametrize('required',[False,True])
def test_later_type_assignment_and_field_edits_never_invoke_a_generator(client,c,aggregation,required):
    row=client.post('/api/v1/records',json=request_body(aggregation,record_number='EXISTING')).json()
    type_id=resource_type(c)
    fid=field(c,type_id,'Later reference',1,required=required)
    definition=generator(c,primary_field=None,type_id=type_id,field_id=fid,pattern='C{SERIAL}')
    c.commit()
    path=f"/api/v1/records/{row['id']}"
    assigned=client.patch(path,json={'type_id':type_id},headers={'If-Match':str(row['version'])})
    assert assigned.status_code==(422 if required else 200),assigned.text
    if required:
        assigned=client.patch(path,json={'type_id':type_id,'field_values':{str(fid):'MANUAL'}},
                              headers={'If-Match':str(row['version'])})
        assert assigned.status_code==200,assigned.text
    current=assigned.json()
    if not required:
        assert current['field_values']=={}
    cleared=client.patch(path,json={'field_values':{str(fid):None}},headers={'If-Match':str(current['version'])})
    assert cleared.status_code==(422 if required else 200),cleared.text
    assert c.execute('SELECT count(*) AS n FROM code_generator_counters WHERE generator_id=%s',
                     (definition['id'],)).fetchone()['n']==0


def test_closed_correction_requires_governance_even_with_global_privileges_and_parent_acl(client,c,aggregation):
    import psycopg
    from .test_code_generator_database import actor
    from .test_global_privilege_enforcement import _account
    from .test_phase7_mutation_authorization import _set_aggregation_acl
    generator(c,pattern='R{SERIAL}')
    c.commit()
    closed=client.patch(f"/api/v1/aggregations/{aggregation['id']}",json={'date_closed':aggregation['date_created']},
                        headers={'If-Match':str(aggregation['version'])})
    assert closed.status_code==200,closed.text
    token,user_id,role=_account(client,privileges=('record.create','record.view','aggregation.view','closure.correct_record_placement'),
                            suffix='correction-without-governance')
    client.headers['Authorization']=f'Bearer {token}'
    actor(c)
    c.execute('UPDATE roles SET org_unit_id=%s WHERE id=%s',(aggregation['owning_org_unit_id'],role))
    c.commit()
    _set_aggregation_acl(aggregation['id'],role,{'aggregation.view','aggregation.add_record'})
    saved_draft=client.post('/api/v1/record-drafts',json={'aggregation_id':aggregation['id'],'title':'No governance bypass'})
    assert saved_draft.status_code==201,saved_draft.text
    draft=saved_draft.json()
    component=stage_document(client,draft['id'],b'Preserve denied creation')
    response=client.post(f"/api/v1/record-drafts/{draft['id']}/commit-placement-correction",
                         headers={'X-Change-Reason':'Requires qualified governance'})
    assert response.status_code==403,response.text
    assert_staged_document(client,draft['id'],component,b'Preserve denied creation')
    assert c.execute('SELECT count(*) AS n FROM records').fetchone()['n']==0
    assert c.execute('SELECT count(*) AS n FROM code_generator_counters').fetchone()['n']==0
    actor(c,user=user_id,reason='Direct SQL also requires qualified governance')
    with pytest.raises(psycopg.errors.InsufficientPrivilege),c.transaction():
        c.execute("SELECT set_config('app.closed_record_placement_correction','authorized',true)")
        c.execute('SELECT begin_closed_record_creation(%s,%s)',(aggregation['id'],aggregation['security_level_id']))


def test_capture_generated_untyped_number_matches_pdf_and_history_failure_rolls_back(client,c,aggregation,monkeypatch):
    """Use real PDF validation; capture history must share creation's rollback."""
    import os
    import subprocess
    from backend.services.api.code_generation import CodeGenerationError
    from backend.services.api.content_storage import configured_storage
    from backend.services.api.messaging import capture
    from .test_messaging_phase5 import account,post,payload,PREFIX

    assert os.environ.get('MESSAGING_PDF_VALIDATOR'),'Use the installed independent PDF validator'
    definition=generator(c,applies_to='untyped',pattern='CAPTURE-{SERIAL}');c.commit()
    admin=client.cookies['erms_session']
    sender,_,_=account(client)
    source=post(client,sender,payload(1)).json()
    headers={'Authorization':'Bearer '+admin}
    response=client.post(PREFIX+'/'+source['envelope_id']+'/capture',headers=headers)
    assert response.status_code==201,response.text
    path=f"/api/v1/record-drafts/{response.json()['id']}"
    assert client.patch(path,json={'aggregation_id':aggregation['id']},headers=headers).status_code==200
    staged=client.get(path+'/components',headers=headers).json()
    original=capture.persist

    def reject_history(*args,**kwargs):
        original(*args,**kwargs)
        raise CodeGenerationError('code_generator_required_value',field='record_number')

    monkeypatch.setattr(capture,'persist',reject_history)
    commit_headers={**headers,'Idempotency-Key':str(uuid4())}
    failed=client.post(path+'/commit',headers=commit_headers)
    assert failed.status_code==422,failed.text
    assert failed.json()['detail']['code']=='code_generator_required_value'
    assert client.get(path+'/components',headers=headers).json()==staged
    assert c.execute('SELECT count(*) AS n FROM records').fetchone()['n']==0
    assert c.execute('SELECT count(*) AS n FROM message_record_captures').fetchone()['n']==0
    assert c.execute('SELECT count(*) AS n FROM code_generator_counters WHERE generator_id=%s',(definition['id'],)).fetchone()['n']==0

    monkeypatch.setattr(capture,'persist',original)
    committed=client.post(path+'/commit',headers=commit_headers)
    assert committed.status_code==201,committed.text
    record=committed.json()
    assert record['record_number']=='CAPTURE-10'
    component=c.execute("""SELECT component.digital_component_id
        FROM message_record_capture_components component JOIN message_record_captures capture ON capture.id=component.capture_id
        WHERE capture.record_id=%s AND component.component_kind='provenance'""",(record['id'],)).fetchone()
    pdf=configured_storage().read(c,component['digital_component_id'])
    text=subprocess.run(['pdftotext','-','-'],input=pdf,capture_output=True,check=True).stdout.decode()
    assert record['record_number'] in text
    replay=client.post(path+'/commit',headers=commit_headers)
    assert replay.status_code==201 and replay.json()==record,replay.text
    assert c.execute('SELECT count(*) AS n FROM message_record_captures').fetchone()['n']==1
    assert c.execute('SELECT last_serial FROM code_generator_counters WHERE generator_id=%s',(definition['id'],)).fetchone()['last_serial']==10
