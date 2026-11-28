"""Field codes identify definitions within one type. Values continue to use field IDs."""
import os
from pathlib import Path

import psycopg
import pytest

from .test_phase7_mutation_authorization import _grant_principal, _login_as_phase7
from .test_resource_type_access import catalogue, ok


@pytest.mark.parametrize("kind", ["aggregation", "record"])
def test_field_code_administration(client, catalogue, kind):
    root = f"/api/v1/{kind}-types"
    path = root + "/" + str(ok(client.post(root, json={"name": "Contracts"}), 201)["id"])
    fields = path + "/fields"

    def headers():
        return {"If-Match": str(ok(client.get(path))["version"])}

    def create(name, **extra):
        return client.post(fields, headers=headers(), json={"name": name, "data_type": "date", **extra})

    field = ok(create("Date - End of Service"), 201)
    assert field["code"] == "DATE_END_OF_SERVICE"
    target = fields + "/" + str(field["id"])
    second = ok(create("Signed", code="  --sig. ١!! "), 201)
    assert second["code"] == "SIG_١"
    page = {"sort": "code", "paged": True, "limit": 1, "offset": 1}
    assert ok(client.get(fields, params=page))["items"][0]["id"] == second["id"]
    assert ok(client.get(fields, params={**page, "descending": True}))["items"][0]["id"] == field["id"]
    stale = headers()
    assert ok(client.put(target, headers=stale, json={"name": "End date", "data_type": "date"}))["code"] == field["code"]
    assert client.put(target, headers=stale, json={"name": "End date", "data_type": "date", "code": "New"}).status_code == 412
    version = headers()
    for value, status, reason in [("Sig_١", 409, "resource_field_code_taken"), (" --- ", 422, "resource_field_code_invalid")]:
        response = client.put(target, headers=version, json={"name": "End date", "data_type": "date", "code": value})
        assert response.status_code == status and response.json()["detail"]["code"] == reason
        assert headers() == version
    assert create("Duplicate", code=" date-end_of service ").status_code == 409
    field = ok(client.put(target, headers=version, json={"name": "End date", "data_type": "date", "code": "نهاية / الخدمة"}))
    assert field["code"] == "نهاية_الخدمة"
    assert {row["id"]: row["code"] for row in ok(client.get(fields, params={"sort": "code"}))} == {
        field["id"]: field["code"], second["id"]: second["code"],
    }
    options = path.replace("-types/", "-types/options/") + "/fields"
    assert ok(client.get(options, params={"selected": field["id"]}))[0]["code"] == field["code"]
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        assert db.execute("""SELECT before_state->>'code',after_state->>'code' FROM event_history
            WHERE entity_type='resource_type_field' AND entity_id=%s ORDER BY id DESC LIMIT 1""",
            (field["id"],)).fetchone() == ("DATE_END_OF_SERVICE", field["code"])
    other = ok(client.post(root, json={"name": "Other"}), 201)
    response = client.post(f"{root}/{other['id']}/fields", headers={"If-Match": str(other["version"])},
                           json={"name": "Separate field", "code": field["code"], "data_type": "integer"})
    assert ok(response, 201)["code"] == field["code"]
    denied_headers = headers()
    _grant_principal(set())
    _login_as_phase7(client)
    assert client.put(target, headers=denied_headers, json={"name": "End date", "data_type": "date", "code": "NO"}).status_code == 403


@pytest.mark.skipif("128_resource_field_codes" not in os.getenv("ERMS_TEST_DEFERRED_MIGRATIONS", ""),
                    reason="requires populated 125-to-128 upgrade")
def test_populated_field_code_upgrade(client):
    migrations = [Path(p) for p in os.environ["ERMS_TEST_DEFERRED_MIGRATIONS"].split(os.pathsep)]
    assert [p.name[:3] for p in migrations] == ["126", "127", "128"]
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as db:
        owner = db.execute("INSERT INTO resource_types(kind,name) VALUES ('record','Code rehearsal') RETURNING id").fetchone()[0]
        names = ["Ref!", "Ref?", "Ref 2", "...", "رقم الموظف"]
        ids = [db.execute("""INSERT INTO resource_type_fields(kind,type_id,name,display_order,data_type,max_length)
               VALUES ('record',%s,%s,%s,'text',100) RETURNING id""", (owner, name, order)).fetchone()[0]
               for order, name in enumerate(names, 1)]
        for migration in migrations[:2]:
            db.execute(migration.read_text(), prepare=False)
        db.execute("SELECT set_config('app.event_source','seeding',false)")
        generator = db.execute("""INSERT INTO code_generators(name,kind,type_id,field_id,applies_to,pattern,start,increment,max_code_length)
               VALUES ('Reference','record',%s,%s,'type','REF-{SERIAL}',1,1,40) RETURNING id""", (owner, ids[0])).fetchone()[0]
        parent = ok(client.post('/api/v1/aggregations', json={'aggregation_number':'CODE-TEST','title':'Parent','classification_id':1}), 201)
        record = ok(client.post('/api/v1/records', json={'aggregation_id':parent['id'],'title':'Typed record',
                    'type_id':owner,'record_number':'CODE-R1'}), 201)
        def snapshot(table):
            return db.execute(f"SELECT to_jsonb(t) FROM {table} t ORDER BY to_jsonb(t)").fetchall()
        tables = ["code_generators", "code_generator_counters", "resource_type_values"]
        before = {table: snapshot(table) for table in tables}
        assert all(before.values())
        db.execute(migrations[-1].read_text(), prepare=False)
        expected = ["REF", "REF_3", "REF_2", f"FIELD_{ids[3]}", "رقم_الموظف"]
        assert db.execute("SELECT id,code FROM resource_type_fields WHERE type_id=%s ORDER BY id", (owner,)).fetchall() == list(zip(ids, expected))
        assert db.execute("SELECT count(*) FROM event_history WHERE source='migration' AND entity_type='resource_type_field' AND 'code'=ANY(changed_fields)").fetchone()[0] == len(ids)
        assert {table: snapshot(table) for table in tables} == before
        assert db.execute("SELECT field_id FROM code_generators WHERE id=%s", (generator,)).fetchone() == (ids[0],)
        assert ok(client.get(f"/api/v1/records/{record['id']}"))["field_values"][str(ids[0])] == "REF-1"
