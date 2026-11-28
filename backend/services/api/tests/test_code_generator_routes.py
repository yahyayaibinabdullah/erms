"""CG-01/02/09/11/12/14 administration through the authenticated API."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import time

import psycopg
from psycopg.rows import dict_row
import pytest

from .test_code_generator_database import actor
from .conftest import _allow_generator_fixture_reset, _restore_generator_fixture


PATH = "/api/v1/code-generators"
ROOT = Path(__file__).resolve().parents[4]


def db():
    return psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row)


@pytest.fixture(autouse=True)
def catalogue_cleanup():
    yield
    with db() as c:
        _allow_generator_fixture_reset(c)
        c.execute("TRUNCATE resource_types CASCADE")
        _restore_generator_fixture(c)


def configuration(**changes):
    return {"name":"Finance document numbers","kind":"record","primary_field":"record_number",
        "pattern":"FIN/{SERIAL}","start":"10","increment":"10","max_code_length":200,**changes}


def create(client, **changes):
    response = client.post(PATH,json=configuration(**changes))
    assert response.status_code == 201,response.text
    return response.json()


def edit(client, row, **changes):
    body = {key:row[key] for key in configuration()}
    body.update(changes)
    return client.put(f"{PATH}/{row['id']}",json=body,
        headers={"If-Match":str(row["version"]),"X-Change-Reason":"Clarify the numbering configuration"})


def simulation(**changes):
    first = {"parent_aggregation_number":"A","classification_code":"3110","classification_scheme_code":"WTH",
             "org_unit_code":"FIN","role_code":"FIN-OFFICER"}
    second = {**first,"parent_aggregation_number":"B","classification_code":"4110","org_unit_code":"HR","role_code":"HR-OFFICER"}
    return {"configuration":configuration(),"sample_date":"2026-11-26","context_a":first,"context_b":second,**changes}


def measured_get(client,path,parameters,monkeypatch,name):
    queries=[]
    original=psycopg.Cursor.execute

    def execute(cursor,query,params=None,*args,**kwargs):
        statement=query.as_string(cursor.connection) if hasattr(query,"as_string") else query
        if isinstance(statement,str) and statement.lstrip().startswith("WITH matching"):
            queries.append((statement,params))
        return original(cursor,query,params,*args,**kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(psycopg.Cursor,"execute",execute)
        started=time.perf_counter()
        response=client.get(path,params=parameters)
        elapsed=time.perf_counter()-started
    assert response.status_code==200,response.text
    assert len(queries)==1
    statement,params=queries[0]
    with db() as c:
        plan=c.execute("EXPLAIN (ANALYZE,BUFFERS,SETTINGS,FORMAT JSON) "+statement,params).fetchone()["QUERY PLAN"]
        directory=ROOT/".runtime/custom-code-generators/administration-metrics"
        directory.mkdir(parents=True,exist_ok=True)
        (directory/f"{c.info.dbname}-{name}.json").write_text(json.dumps({"path":path,"parameters":parameters,
            "complete_http_seconds":elapsed,"expected_total":response.json()["total"],"returned":len(response.json()["items"]),
            "sql":statement,"sql_parameters":params,"plan":plan},indent=2,default=str)+"\n")
    assert elapsed<=3,(name,elapsed)
    return response


def test_create_optional_reason_read_name_and_versioned_rename_keep_counter(client):
    row = create(client,start="900719925474099312345",increment="10")
    assert row["start"] == "900719925474099312345" and row["version"] == 1
    assert client.get(f"{PATH}/{row['id']}").json() == row
    with db() as c:
        event = c.execute("SELECT reason,after_state FROM event_history WHERE entity_type='code_generator'").fetchone()
        assert event["reason"] is None and event["after_state"]["name"] == row["name"]
        actor(c)
        c.execute("""INSERT INTO code_generator_counters(generator_id,scope_kind,scope_id,reset_frequency,period_bucket,last_serial)
                     VALUES(%s,'generator',0,'never','0001-01-01',%s)""",(row["id"],row["start"]))
    body = configuration(name="Finance numbers renamed",start=row["start"])
    for reason in (None,"","  "):
        headers = {"If-Match":"1"}
        if reason is not None:
            headers["X-Change-Reason"] = reason
        response = client.put(f"{PATH}/{row['id']}",json=body,headers=headers)
        assert response.status_code==422,response.text
        assert response.json()["detail"]["code"]=="code_generator_reason_required"
    renamed = edit(client,row,name=body["name"])
    assert renamed.status_code==200,renamed.text
    assert renamed.json()["id"]==row["id"] and renamed.json()["version"]==2
    assert edit(client,row,name="Stale rename").status_code==412
    with db() as c:
        assert str(c.execute("SELECT last_serial FROM code_generator_counters").fetchone()["last_serial"])==row["start"]
        events = c.execute("SELECT before_state,after_state FROM event_history WHERE entity_type='code_generator' ORDER BY id").fetchall()
        assert len(events)==2 and events[0]["after_state"]["name"]==row["name"]
        assert events[1]["before_state"]["name"]==row["name"] and events[1]["after_state"]["name"]==body["name"]


def test_optional_create_reason_is_preserved_and_mutations_require_version(client):
    response = client.post(PATH,json=configuration(),headers={"X-Change-Reason":"Initial imported series"})
    assert response.status_code==201,response.text
    row=response.json()
    assert client.put(f"{PATH}/{row['id']}",json=configuration()).status_code==428
    assert client.delete(f"{PATH}/{row['id']}",headers={"X-Change-Reason":"Retire unused definition"}).status_code==428
    with db() as c:
        assert c.execute("SELECT reason FROM event_history WHERE entity_type='code_generator'").fetchone()["reason"]=="Initial imported series"


@pytest.mark.parametrize("change",[
    {"name":" \t\u00a0"},{"name":None},{"primary_field":"security_level_id"},
    {"start":1.0},{"increment":"0"},{"padding_width":True},{"max_code_length":None},
    {"pattern":"{UNKNOWN}/{SERIAL}"},{"scope":"org_unit"},
    {"reset_frequency":"monthly","pattern":"{YYYY}/{SERIAL}"},
])
def test_invalid_definitions_are_localized_without_writes(client,change):
    response=client.post(PATH,json=configuration(**change))
    assert response.status_code==422,response.text
    detail=response.json()["detail"]
    assert detail["message_key"].startswith("code_generation.error.") and detail["parameters"]=={}
    with db() as c:
        assert c.execute("SELECT count(*) AS n FROM code_generators").fetchone()["n"]==0
        assert c.execute("SELECT count(*) AS n FROM event_history WHERE entity_type='code_generator'").fetchone()["n"]==0


def test_overlap_disable_enable_binding_removal_and_permitted_deletion(client):
    first=create(client)
    rejected=client.post(PATH,json=configuration(name="Overlapping definition"))
    assert rejected.status_code==409,rejected.text
    assert rejected.json()["detail"]["code"]=="code_generator_overlap"
    second=create(client,name="Disabled alternative",enabled=False)
    assert edit(client,second,enabled=True).status_code==409
    disabled=edit(client,first,enabled=False)
    assert disabled.status_code==200,disabled.text
    assert edit(client,second,enabled=True).status_code==200
    unbound=client.delete(f"{PATH}/{first['id']}/binding",headers={"If-Match":"2","X-Change-Reason":"Detach unused target"})
    assert unbound.status_code==200,unbound.text
    assert unbound.json()["primary_field"] is None and unbound.json()["enabled"] is False
    assert client.delete(f"{PATH}/{first['id']}",headers={"If-Match":"3","X-Change-Reason":"Delete unused definition"}).status_code==204
    assert client.get(f"{PATH}/{first['id']}").status_code==404


@pytest.mark.parametrize("scenario,settings,expected",[
    ("same_scope",{},[10,20,30,40,50]),
    ("year_transition",{"pattern":"{YYYY}/{SERIAL}","reset_frequency":"yearly"},[10,20,30,10,20]),
    ("month_transition",{"pattern":"{DATE}/{SERIAL}","reset_frequency":"monthly"},[10,20,30,10,20]),
    ("different_scopes",{"pattern":"{ORG_UNIT_CODE}/{SERIAL}","scope":"org_unit"},[10,20,10,30,20]),
    ("combined",{"pattern":"{ORG_UNIT_CODE}/{YYYY}/{MM}/{SERIAL}","scope":"org_unit","reset_frequency":"monthly"},[10,20,10,10,10]),
])
def test_preview_uses_unsaved_configuration_and_exact_five_isolated_values(client,scenario,settings,expected):
    body=simulation(configuration=configuration(**settings),scenario=scenario)
    result=client.post(f"{PATH}/preview",json=body)
    assert result.status_code==200,result.text
    items=result.json()["items"]
    assert len(items)==5 and [int(v["serial"]) for v in items]==expected
    assert all(v["value"] and v["date"] and v["scope_kind"] for v in items)
    if scenario in {"year_transition","month_transition"}:
        assert items[3]["reset"] is True
    assert result.json()["working_timezone"]=="Asia/Dubai"
    assert client.post(f"{PATH}/preview",json=body).json()==result.json()
    with db() as c:
        for table in ("code_generators","code_generator_counters","resource_creation_requests"):
            assert c.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]==0
        assert c.execute("SELECT count(*) AS n FROM event_history WHERE entity_type='code_generator'").fetchone()["n"]==0


def test_preview_rejects_missing_sample_context_and_length_overflow(client):
    body=simulation(configuration=configuration(pattern="{ROLE_CODE}/{SERIAL}"),context_a={})
    response=client.post(f"{PATH}/preview",json=body)
    assert response.status_code==422,response.text
    assert response.json()["detail"]["code"]=="code_generator_missing_context"
    body=simulation(configuration=configuration(pattern="{ORG_UNIT_CODE}/{SERIAL}",max_code_length=6),context_a={"org_unit_code":"FINANCE"})
    response=client.post(f"{PATH}/preview",json=body)
    assert response.status_code==422,response.text
    assert response.json()["detail"]["code"]=="code_generator_length_exceeded"
    assert response.json()["detail"]["parameters"]=={}


def test_independent_number_patterns_are_advisory_and_preview_excludes_itself(client):
    from .test_code_generator_database import resource_type
    with db() as c:
        actor(c)
        first_type=resource_type(c,'First series')
        second_type=resource_type(c,'Second series')
    first=create(client,type_id=first_type)
    assert first['warnings']==[]
    own=simulation(configuration=configuration(type_id=first_type),generator_id=first['id'])
    assert client.post(f'{PATH}/preview',json=own).json()['warnings']==[]
    independent=simulation(configuration=configuration(type_id=second_type))
    preview=client.post(f'{PATH}/preview',json=independent)
    assert preview.status_code==200,preview.text
    assert preview.json()['warnings']==['independent_number_pattern']
    second=create(client,type_id=second_type)
    assert second['warnings']==['independent_number_pattern']
    assert client.get(f"{PATH}/{first['id']}").json()['warnings']==['independent_number_pattern']
    assert edit(client,second,enabled=False).json()['warnings']==[]
    assert client.get(f"{PATH}/{first['id']}").json()['warnings']==[]
    unrelated=simulation(configuration=configuration(primary_field='title'))
    assert client.post(f'{PATH}/preview',json=unrelated).json()['warnings']==[]
    with db() as c:
        assert c.execute('SELECT count(*) AS n FROM code_generator_counters').fetchone()['n']==0


def test_counter_peek_unused_version_zero_adjustment_and_protected_retirement(client):
    row=create(client)
    path=f"{PATH}/{row['id']}/counter"
    state=client.get(path).json()
    assert state["next_number"]=="10" and state["version"]==0
    with db() as c:
        assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"]==0
    assert client.post(path+"/advance",json={"next_number":"501"},headers={"X-Change-Reason":"Imported series"}).status_code==428
    assert client.post(path+"/advance",json={"next_number":"501"},headers={"If-Match":"0"}).status_code==422
    response=client.post(path+"/advance",json={"next_number":"501"},headers={"If-Match":'W/"0"',"X-Change-Reason":"Imported series"})
    assert response.status_code==200,response.text
    assert response.json()["next_number"]=="501" and response.json()["version"]==1
    assert client.post(path+"/advance",json={"next_number":"601"},headers={"If-Match":"0","X-Change-Reason":"Stale import"}).status_code==412
    assert client.post(path+"/advance",json={"next_number":"500"},headers={"If-Match":"1","X-Change-Reason":"Wrong direction"}).status_code==422
    assert client.delete(f"{PATH}/{row['id']}",headers={"If-Match":"1","X-Change-Reason":"Try deletion"}).status_code==409
    assert client.delete(f"{PATH}/{row['id']}/binding",headers={"If-Match":"1","X-Change-Reason":"Retire binding"}).status_code==200
    assert client.get(path).json()["next_number"]=="501"


def test_every_administration_route_denies_a_signed_in_nonadministrator(client):
    row=create(client)
    with db() as c:
        c.execute("UPDATE roles SET profile_id=(SELECT id FROM profiles WHERE code='INFO_GOV_OFFICER') WHERE id=1")
    calls=[("GET",PATH,None),("GET",f"{PATH}/{row['id']}",None),("POST",PATH,configuration()),
        ("PUT",f"{PATH}/{row['id']}",configuration()),("DELETE",f"{PATH}/{row['id']}",None),
        ("DELETE",f"{PATH}/{row['id']}/binding",None),("POST",f"{PATH}/preview",simulation()),
        ("GET",f"{PATH}/targets/primary?kind=record",None),("GET",f"{PATH}/targets/types?kind=record",None),
        ("GET",f"{PATH}/targets/fields?kind=record&type_id=1",None),
        ("GET",f"{PATH}/targets/types?kind=record&descending=true",None),
        ("GET",f"{PATH}/targets/fields?kind=record&type_id=1&descending=true",None),
        ("GET",f"{PATH}/{row['id']}/counters",None),
        ("GET",f"{PATH}/{row['id']}/counter",None),("POST",f"{PATH}/{row['id']}/counter/advance",{"next_number":"501"})]
    for method,path,body in calls:
        response=client.request(method,path,json=body,headers={"If-Match":"1","X-Change-Reason":"Denied operation"})
        assert response.status_code==403,(method,path,response.text)


def test_definition_listing_filters_sorting_and_pages_remain_bounded(client,monkeypatch):
    with db() as c:
        actor(c)
        with c.cursor() as cursor:
            cursor.executemany("""INSERT INTO code_generators(name,kind,primary_field,pattern,max_code_length,enabled)
                VALUES(%s,'record','record_number','{SERIAL}',40,false)""",[(f"Series {i:03}",) for i in range(127)])
    assert client.get(PATH+"?limit=101").status_code==422
    seen=[]
    for offset in (0,50,100):
        parameters={"limit":50,"offset":offset,"q":"Series","enabled":"false"}
        page=measured_get(client,PATH,parameters,monkeypatch,"definitions") if offset==0 else client.get(PATH,params=parameters)
        assert page.status_code==200,page.text
        assert page.json()["total"]==127
        seen.extend(row["name"] for row in page.json()["items"])
    assert seen==[f"Series {i:03}" for i in range(127)]
    assert client.get(PATH,params={"q":"absent"}).json()=={"items":[],"total":0}
    assert client.get(PATH,params={"offset":150}).json()=={"items":[],"total":127}
    descending=client.get(PATH,params={"descending":"true","limit":2}).json()["items"]
    assert [item["name"] for item in descending]==["Series 126","Series 125"]


def test_settings_administrator_can_select_definitions_without_business_or_type_edit_access(client, record):
    primary=client.get(PATH+"/targets/primary",params={"kind":"record"})
    assert primary.status_code==200,primary.text
    assert {item["key"] for item in primary.json()["items"]}=={"record_number","title","description"}
    assert {item["key"] for item in client.get(PATH+"/targets/primary",params={"kind":"aggregation"}).json()["items"]}=={
        "aggregation_number","title","description","assigned_location","current_location"}
    with db() as c:
        actor(c)
        type_id=c.execute("INSERT INTO resource_types(kind,name) VALUES('record','Contract') RETURNING id").fetchone()["id"]
        text=c.execute("""INSERT INTO resource_type_fields(kind,type_id,name,display_order,data_type,max_length)
            VALUES('record',%s,'Contract number',1,'text',50) RETURNING id""",(type_id,)).fetchone()["id"]
        integer=c.execute("""INSERT INTO resource_type_fields(kind,type_id,name,display_order,data_type)
            VALUES('record',%s,'Year count',2,'integer') RETURNING id""",(type_id,)).fetchone()["id"]
        profile=c.execute("INSERT INTO profiles(code,name) VALUES('GENERATOR_SETTINGS_TEST','Generator settings only') RETURNING id").fetchone()["id"]
        c.execute("INSERT INTO profile_privileges(profile_id,privilege_id) SELECT %s,id FROM privileges WHERE code='app.settings.manage'",(profile,))
        c.execute("UPDATE roles SET profile_id=%s WHERE id=1",(profile,))
    types=client.get(PATH+"/targets/types",params={"kind":"record","q":"Contract","descending":True})
    assert types.status_code==200,types.text
    assert types.json()["items"][0]["id"]==type_id
    fields=client.get(PATH+"/targets/fields",params={"kind":"record","type_id":type_id,"descending":True})
    assert fields.status_code==200,fields.text
    assert [f["id"] for f in fields.json()["items"]]==[text]
    row=create(client,primary_field=None,type_id=type_id,field_id=text,max_code_length=50)
    assert row["target_snapshot"]["field_name"]=="Contract number"
    assert client.get("/api/v1/event-history",params={"entity_type":"code_generator","entity_id":row["id"]}).status_code==403
    assert client.post(PATH,json=configuration(primary_field=None,type_id=type_id,field_id=integer)).status_code==422
    assert client.get(f"/api/v1/records/{record['id']}").status_code==404
    assert client.put(f"/api/v1/record-types/{type_id}",json={"name":"Unauthorized rename"},headers={"If-Match":"1"}).status_code==403


def test_type_and_field_selectors_page_past_one_hundred_and_keep_selected_values(client,monkeypatch):
    with db() as c:
        actor(c)
        with c.cursor() as cursor:
            cursor.executemany("INSERT INTO resource_types(kind,name) VALUES('record',%s)",[(f"Type {i:03}",) for i in range(125)])
        ids=c.execute("SELECT id FROM resource_types WHERE kind='record' ORDER BY name COLLATE \"C\",id").fetchall()
        chosen=ids[-1]["id"]
        with c.cursor() as cursor:
            cursor.executemany("""INSERT INTO resource_type_fields(kind,type_id,name,display_order,data_type,max_length)
                VALUES('record',%s,%s,%s,'text',60)""",[(chosen,f"Field {i:03}",i+1) for i in range(125)])
    for url,params in (("/targets/types",{"kind":"record"}),("/targets/fields",{"kind":"record","type_id":chosen})):
        values=[]
        for offset in (0,50,100):
            parameters={**params,"limit":50,"offset":offset}
            response=measured_get(client,PATH+url,parameters,monkeypatch,url.split("/")[-1]) if offset==0 else client.get(PATH+url,params=parameters)
            assert response.status_code==200,response.text
            assert response.json()["total"]==125
            values.extend(response.json()["items"])
        assert len({item["id"] for item in values})==125
        reverse=[]
        for repeat in range(3):
            response=measured_get(client,PATH+url,{**params,"limit":50,"offset":0,"descending":True},
                                 monkeypatch,f"{url.split('/')[-1]}-descending-{repeat}")
            assert [v["id"] for v in response.json()["items"]]==[v["id"] for v in values[::-1][:50]]
            if repeat==0:reverse.extend(response.json()["items"])
        for offset in (50,100):
            response=client.get(PATH+url,params={**params,"limit":50,"offset":offset,"descending":True})
            assert response.status_code==200,response.text
            reverse.extend(response.json()["items"])
        assert [v["id"] for v in reverse]==[v["id"] for v in values[::-1]]
        pinned=client.get(PATH+url,params={**params,"selected":values[0]["id"],"descending":True,"limit":2})
        assert [v["id"] for v in pinned.json()["items"]]==[values[0]["id"],values[-1]["id"]]
        assert client.get(PATH+url,params={**params,"q":"absent"}).json()=={"items":[],"total":0}
        selected=client.get(PATH+url,params={**params,"q":"absent","selected":values[-1]["id"],"limit":1})
        assert selected.status_code==200,selected.text
        assert [item["id"] for item in selected.json()["items"]]==[values[-1]["id"]]


def test_adjustment_is_specific_to_scope_and_full_month(client):
    row=create(client,scope="org_unit",pattern="{ORG_UNIT_CODE}/{YYYY}/{MM}/{SERIAL}",reset_frequency="monthly")
    path=f"{PATH}/{row['id']}/counter"
    key={"scope_kind":"org_unit","scope_id":7,"reset_frequency":"monthly","period_bucket":"2026-01-01"}
    response=client.post(path+"/advance",json={**key,"next_number":"501"},
        headers={"If-Match":"0","X-Change-Reason":"Continue January import"})
    assert response.status_code==200,response.text
    assert client.get(path,params=key).json()["next_number"]=="501"
    for other in ({**key,"scope_id":8},{**key,"period_bucket":"2027-01-01"}):
        result=client.get(path,params=other)
        assert result.status_code==200,result.text
        assert result.json()["next_number"]=="10" and result.json()["version"]==0
    assert client.get(path,params={**key,"period_bucket":"2026-01-02"}).status_code==422
    saved=client.get(f"{PATH}/{row['id']}/counters",params={"scope_kind":"org_unit"})
    assert saved.status_code==200,saved.text
    assert saved.json()["total"]==1 and saved.json()["items"][0]["next_number"]=="501"
    assert client.get(f"{PATH}/{row['id']}/counters",params={"scope_id":8}).json()=={"items":[],"total":0}
    with db() as c:
        assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"]==1


def test_audit_failure_rolls_back_api_creation_edit_and_adjustment(client):
    row=create(client)
    with db() as c:
        c.execute("""CREATE FUNCTION generator_route_audit_failure() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'generator audit fixture failure'; END $$""")
        c.execute("""CREATE TRIGGER generator_route_audit_failure BEFORE INSERT ON event_history
            FOR EACH ROW WHEN(NEW.entity_type='code_generator') EXECUTE FUNCTION generator_route_audit_failure()""")
    try:
        assert client.post(PATH,json=configuration(primary_field="title")).status_code>=400
        assert edit(client,row,name="Must roll back").status_code>=400
        assert client.post(f"{PATH}/{row['id']}/counter/advance",json={"next_number":"501"},
            headers={"If-Match":"0","X-Change-Reason":"Must roll back"}).status_code>=400
        assert client.get(f"{PATH}/{row['id']}").json()==row
        with db() as c:
            assert c.execute("SELECT count(*) AS n FROM code_generators").fetchone()["n"]==1
            assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"]==0
            assert c.execute("SELECT count(*) AS n FROM event_history WHERE entity_type='code_generator'").fetchone()["n"]==1
    finally:
        with db() as c:
            c.execute("DROP TRIGGER generator_route_audit_failure ON event_history")
            c.execute("DROP FUNCTION generator_route_audit_failure()")


def test_two_simultaneous_api_edits_cannot_overwrite_one_version(client):
    row=create(client)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures=[executor.submit(edit,client,row,name=name) for name in ("First rename","Second rename")]
        responses=[future.result(timeout=15) for future in futures]
    assert sorted(response.status_code for response in responses)==[200,412]
    with db() as c:
        assert c.execute("SELECT count(*) AS n FROM event_history WHERE entity_type='code_generator'").fetchone()["n"]==2


def test_counter_listing_reaches_every_saved_scope_with_server_pagination(client,monkeypatch):
    row=create(client,scope="org_unit",pattern="{ORG_UNIT_CODE}/{SERIAL}")
    with db() as c:
        actor(c)
        with c.cursor() as cursor:
            cursor.executemany("""INSERT INTO code_generator_counters(generator_id,scope_kind,scope_id,reset_frequency,period_bucket,last_serial)
                VALUES(%s,'org_unit',%s,'never','0001-01-01',10)""",[(row["id"],i) for i in range(1,126)])
    path=f"{PATH}/{row['id']}/counters"
    scopes=[]
    for offset in (0,50,100):
        parameters={"limit":50,"offset":offset}
        response=measured_get(client,path,parameters,monkeypatch,"counters") if offset==0 else client.get(path,params=parameters)
        assert response.status_code==200,response.text
        assert response.json()["total"]==125
        scopes.extend(item["scope_id"] for item in response.json()["items"])
        assert all(item["next_number"]=="20" for item in response.json()["items"])
    assert scopes==list(range(1,126))
