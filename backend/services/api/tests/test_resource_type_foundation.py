"""PostgreSQL contracts for the resource type foundation."""
from datetime import date, datetime, timezone
from decimal import Decimal
import os

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from backend.services.api.entity_localization import localized_projection


@pytest.fixture
def db():
    # Roll back local catalogue definitions as well as metadata on fixture resources.
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        try:
            yield connection
        finally:
            connection.rollback()


def create_type(db, kind="record", name="Inspection"):
    return db.execute("INSERT INTO resource_types(kind,name) VALUES (%s,%s) RETURNING id",
                      (kind, name)).fetchone()["id"]


def add_field(db, type_id, data_type, name=None, *, kind="record", required=False, limit=None, default=None):
    return db.execute("""
        INSERT INTO resource_type_fields(kind,type_id,name,data_type,required,display_order,max_length,default_value)
        VALUES (%s,%s,%s,%s,%s,1,%s,resource_field_decode(%s,%s)) RETURNING id
        """, (kind, type_id, name or data_type, data_type, required, limit, data_type, Jsonb(default))).fetchone()["id"]


def choice(db, field_id, name, order=1):
    return db.execute("INSERT INTO resource_field_choices(field_id,name,display_order) VALUES (%s,%s,%s) RETURNING id",
                      (field_id, name, order)).fetchone()["id"]


def resolve(db, type_id, submitted, resource_id=None, kind="record"):
    return db.execute("""
        SELECT field_id, (value).* FROM resolve_resource_type_values(%s,%s,%s,%s)
        """, (kind, resource_id, type_id, Jsonb({str(k): v for k, v in submitted.items()}))).fetchall()


def rejects(db, statement, params, error=psycopg.IntegrityError):
    with pytest.raises(error), db.transaction():
        db.execute(statement, params)


def test_native_literals_and_input_shapes(db):
    t = create_type(db)
    values = [
        ("text", "أ🙂", "text_value", "أ🙂"),
        ("integer", 0, "integer_value", 0),
        ("decimal", "12345678901234567890.000000000000003", "decimal_value", Decimal("12345678901234567890.000000000000003")),
        ("boolean", False, "boolean_value", False),
        ("date", "2024-02-29", "date_value", date(2024, 2, 29)),
        ("datetime", "2026-11-19T07:00:01.321+04:00", "datetime_value",
         datetime(2026, 11, 19, 3, 0, 1, 321000, tzinfo=timezone.utc)),
    ]
    for dtype, given, column, expected in values:
        fid = add_field(db, t, dtype, required=True, limit=2 if dtype == "text" else None, default=given)
        result = {row["field_id"]: row for row in resolve(db, t, {})}
        assert result[fid][column] == expected
        assert sum(v is not None for k, v in result[fid].items() if k != "field_id") == 1
    f = add_field(db, t, "single_choice", required=True)
    selected = choice(db, f, "Other")
    assert resolve(db, t, {f: selected})[-1]["choice_id"] == selected
    for dtype, invalid in [("text", {"ar": "أ"}), ("text", ["value"]), ("boolean", 0), ("integer", True),
                           ("integer", 1.5), ("decimal", "NaN"), ("date", "2025-02-29"),
                           ("datetime", "2026-11-19T07:00:01"), ("single_choice", "Other")]:
        rejects(db, "SELECT resource_field_decode(%s,%s)", (dtype, Jsonb(invalid)), psycopg.DataError)


def test_assignment_defaults_clearing_and_next_metadata_update(db, record):
    t = create_type(db)
    text = add_field(db, t, "text", limit=3, default="old")
    zero = add_field(db, t, "integer", required=True, default=0)
    flag = add_field(db, t, "boolean", required=True, default=False)
    r = record["id"]
    result = resolve(db, t, {text: None}, r)
    assert [(row["field_id"], row["integer_value"], row["boolean_value"]) for row in result] == [
        (zero, 0, None), (flag, None, False)]
    assert resolve(db, t, {text: "أ🙂", flag: True}, r)[0]["text_value"] == "أ🙂"
    assert resolve(db, t, {}, r)[0]["text_value"] == "old"
    # Materialize a verified assignment. Phase 2 owns the authorized write path.
    db.execute("""CREATE TEMP TABLE proposed ON COMMIT DROP AS
                  SELECT * FROM resolve_resource_type_values('record',%s,%s,%s)""", (r, t, Jsonb({str(text): None})))
    db.execute("UPDATE records SET type_id=%s WHERE id=%s", (t, r))
    db.execute("""INSERT INTO resource_type_values(kind,resource_id,type_id,field_id,data_type,text_capacity,value)
                  SELECT 'record',%s,%s,field_id,data_type,text_capacity,value FROM proposed""", (r, t))
    db.execute("UPDATE resource_type_fields SET default_value=resource_field_decode('integer','8') WHERE id=%s", (zero,))
    assert [row["field_id"] for row in resolve(db, t, {}, r)] == [zero, flag]
    assert resolve(db, t, {}, r)[0]["integer_value"] == 0
    assert resolve(db, t, {})[1]["integer_value"] == 8
    extra = add_field(db, t, "decimal", required=True, default="1.2")
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        resolve(db, t, {}, r)
    db.execute("UPDATE resource_type_fields SET required=true WHERE id=%s", (text,))
    for empty in (None, "", " \t", "\u00a0", "1234"):
        with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
            resolve(db, t, {text: empty, extra: 0}, r)
    assert resolve(db, t, {text: "أ🙂", extra: 0}, r)[0]["text_value"] == "أ🙂"
    assert db.execute("SELECT count(*) AS n FROM resource_type_values WHERE resource_id=%s", (r,)).fetchone()["n"] == 2
    destination = create_type(db, name="Review")
    new = add_field(db, destination, "integer", name="integer", default=9)
    assert resolve(db, destination, {}, r)[0]["field_id"] == new
    assert resolve(db, destination, {}, r)[0]["integer_value"] == 9
    assert resolve(db, None, {}, r) == []
    with pytest.raises(psycopg.DataError), db.transaction():
        resolve(db, None, {text: "old"}, r)


def test_value_membership_and_safe_definition_edits(db, record):
    t = create_type(db)
    other = create_type(db, name="Review")
    a = create_type(db, "aggregation")
    r = record["id"]
    field = add_field(db, t, "text", limit=4)
    pick = add_field(db, t, "single_choice")
    yes = choice(db, pick, "Yes")
    alternate = choice(db, pick, "No", 2)
    foreign = choice(db, add_field(db, other, "single_choice"), "Yes")
    for invalid in (foreign, -1, "Yes"):
        with pytest.raises(psycopg.Error), db.transaction():
            resolve(db, t, {pick: invalid})
    rejects(db, "UPDATE records SET type_id=%s WHERE id=%s", (a, r))
    rejects(db, "UPDATE aggregations SET type_id=%s WHERE id=%s", (t, record["aggregation_id"]))
    db.execute("UPDATE records SET type_id=%s WHERE id=%s", (t, r))
    insert = """INSERT INTO resource_type_values(kind,resource_id,type_id,field_id,data_type,text_capacity,value)
                VALUES ('record',%s,%s,%s,%s,%s,resource_field_decode(%s,%s))"""
    db.execute(insert, (r, t, field, "text", 4, "text", Jsonb("🙂أب")))
    db.execute(insert, (r, t, pick, "single_choice", 0, "single_choice", Jsonb(yes)))
    db.execute("UPDATE resource_type_fields SET max_length=3 WHERE id=%s", (field,))
    assert db.execute("SELECT text_capacity FROM resource_type_values WHERE field_id=%s", (field,)).fetchone()["text_capacity"] == 3
    for statement, params in [
        ("UPDATE resource_type_fields SET max_length=2 WHERE id=%s", (field,)),
        ("UPDATE resource_type_fields SET data_type='date', max_length=NULL WHERE id=%s", (field,)),
        ("DELETE FROM resource_type_fields WHERE id=%s", (field,)),
        ("DELETE FROM resource_types WHERE id=%s", (t,)),
        ("UPDATE records SET type_id=NULL WHERE id=%s", (r,)),
        ("DELETE FROM resource_field_choices WHERE id=%s", (yes,)),
        ("UPDATE resource_type_fields SET default_value=resource_field_decode('single_choice',%s) WHERE id=%s", (Jsonb(foreign), pick)),
        ("UPDATE resource_type_fields SET default_value=resource_field_decode('text',%s) WHERE id=%s", (Jsonb("long"), field)),
        (insert, (r, other, foreign, "single_choice", 0, "single_choice", Jsonb(foreign))),
        (insert, (r + 100000, t, field, "text", 3, "text", Jsonb("أ"))),
        ("UPDATE resource_type_values SET value=resource_field_decode('single_choice',%s) WHERE field_id=%s", (Jsonb(foreign), pick)),
        ("UPDATE resource_type_values SET value=resource_field_decode('integer','0') WHERE field_id=%s", (field,)),
    ]:
        rejects(db, statement, params)
    db.execute("UPDATE resource_type_fields SET default_value=resource_field_decode('single_choice',%s) WHERE id=%s",
               (Jsonb(alternate), pick))
    rejects(db, "DELETE FROM resource_field_choices WHERE id=%s", (alternate,))
    db.execute("UPDATE resource_field_choices SET name='Approved',display_order=5 WHERE id=%s", (yes,))
    assert resolve(db, t, {}, r)[1]["choice_id"] == yes
    assert resolve(db, t, {})[0]["choice_id"] == alternate
    db.execute("UPDATE resource_type_fields SET default_value=NULL WHERE id=%s", (pick,))
    db.execute("DELETE FROM resource_field_choices WHERE id=%s", (alternate,))
    db.execute("DELETE FROM resource_type_values WHERE resource_id=%s", (r,))
    db.execute("UPDATE resource_type_fields SET data_type='date', max_length=NULL WHERE id=%s", (field,))
    db.execute("UPDATE records SET type_id=NULL WHERE id=%s", (r,))
    db.execute("DELETE FROM resource_types WHERE id=%s", (t,))


def test_catalogue_translations_grants_and_stable_ids(db, record):
    t = create_type(db)
    a = create_type(db, "aggregation")
    f = add_field(db, a, "single_choice", kind="aggregation")
    c = choice(db, f, "Approved")
    db.execute("SELECT set_config('app.change_reason','Test multilingual type definitions',true)")
    db.execute("""INSERT INTO supported_languages(language_tag,english_name,native_name,direction,is_enabled)
                  VALUES ('fr','French','Français','ltr',true)""")
    for table, key, label in [("aggregation_types", a, "تفتيش"), ("resource_type_fields", f, "حالة"),
                              ("resource_field_choices", c, "مقبول")]:
        stmt = sql.SQL("UPDATE {} SET translations=%s WHERE id=%s RETURNING *").format(sql.Identifier(table))
        french = {"name": "Libellé"}
        if table == "aggregation_types":
            french["description"] = "Une inspection"
        row = db.execute(stmt, (Jsonb({"ar": {"name": label}, "fr": french}), key)).fetchone()
        assert localized_projection(row, "fr-CA", "name")["name"] == "Libellé"
        if table == "aggregation_types":
            assert localized_projection(row, "fr", "name")["description"] == "Une inspection"
        assert row["id"] == key
        assert localized_projection(row, "ar-AE", "name")["name"] == label
        assert localized_projection(row, "de", "name")["name"] == row["name"]
        with pytest.raises(psycopg.IntegrityError), db.transaction():
            db.execute(stmt, (Jsonb({"zz": {"name": "Unconfigured"}}), key))
    rejects(db, "INSERT INTO resource_types(kind,name) VALUES ('record','Inspection')", ())
    rejects(db, "INSERT INTO resource_types(kind,name) VALUES ('aggregation',%s)", ("\u00a0",))
    with pytest.raises(psycopg.IntegrityError), db.transaction():
        add_field(db, a, "single_choice", kind="aggregation")
    assert not db.execute("SELECT FROM resource_type_role_grants WHERE type_id=%s", (t,)).fetchall()
    for use in (False, True):
        grant = db.execute("""INSERT INTO resource_type_role_grants(kind,type_id,role_id,can_use)
            VALUES ('record',%s,1,%s) ON CONFLICT(kind,type_id,role_id) DO UPDATE SET can_use=excluded.can_use
            RETURNING role_id,can_use""", (t, use)).fetchone()
        assert grant == {"role_id": 1, "can_use": use}
    rejects(db, "INSERT INTO resource_type_role_grants VALUES ('aggregation',%s,1,true)", (t,))
    rejects(db, "INSERT INTO resource_type_role_grants VALUES ('record',%s,-1,true)", (t,))
    db.execute("UPDATE aggregations SET type_id=%s WHERE id=%s", (a, record["aggregation_id"]))
    assert resolve(db, a, {f: c}, record["aggregation_id"], "aggregation")[0]["choice_id"] == c
    db.execute("""INSERT INTO resource_type_values(kind,resource_id,type_id,field_id,data_type,text_capacity,value)
                  SELECT 'aggregation',%s,%s, proposed.*
                  FROM resolve_resource_type_values('aggregation',%s,%s,%s) proposed""",
               (record["aggregation_id"], a, record["aggregation_id"], a, Jsonb({str(f): c})))
    assert resolve(db, a, {}, record["aggregation_id"], "aggregation")[0]["choice_id"] == c
    assert db.execute("SELECT type_id FROM records WHERE id=%s", (record["id"],)).fetchone()["type_id"] is None


def test_public_resource_models_reject_unknown_type(client, record, aggregation):
    for path, resource, required in [("records", record, {"aggregation_id": aggregation["id"], "record_number": "R2"}),
                                     ("aggregations", aggregation, {"classification_id": 1, "aggregation_number": "A2"})]:
        response = client.post(f"/api/v1/{path}", json={**required, "title": "Test", "type_id": 9223372036854775807})
        assert response.status_code == 403, response.text
        response = client.patch(f"/api/v1/{path}/{resource['id']}", json={"type_id": 9223372036854775807, "field_values": {}},
                                headers={"If-Match": str(resource["version"]), "X-Change-Reason": "Verify type isolation"})
        assert response.status_code == 403, response.text


def test_invalid_definitions_and_reference_ownership(db, record):
    t = create_type(db)
    other = create_type(db, name="Other")
    r = record["id"]
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        add_field(db, t, "text", limit=None)
    for dtype, length, literal in [("integer", 2, 0), ("text", 0, ""), ("text", 2, "long"), ("text", 2, "\u2003")]:
        with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
            add_field(db, t, dtype, limit=length, required=True, default=literal)
    f = add_field(db, t, "integer", default=0)
    rejects(db, "UPDATE resource_type_fields SET data_type='boolean' WHERE id=%s", (f,))
    with pytest.raises(psycopg.errors.ForeignKeyViolation), db.transaction():
        choice(db, f, "Invalid")
    wrong_field = add_field(db, other, "integer")
    with pytest.raises(psycopg.errors.InvalidParameterValue), db.transaction():
        resolve(db, t, {wrong_field: 2})
    db.execute("UPDATE records SET type_id=%s WHERE id=%s", (t, r))
    insert = """INSERT INTO resource_type_values(kind,resource_id,type_id,field_id,data_type,text_capacity,value)
        VALUES ('record',%s,%s,%s,'integer',0,resource_field_decode('integer','0'))"""
    rejects(db, insert, (r, other, wrong_field))
    rejects(db, insert, (r, t, wrong_field))
    db.execute(insert, (r, t, f))
    rejects(db, insert, (r, t, f))
    rejects(db, "UPDATE resource_type_values SET value=ROW('two',3,NULL,NULL,NULL,NULL,NULL)::resource_field_literal WHERE field_id=%s", (f,))
    for translations in ({"ar": {"name": "\u2003"}}, {"ar": {"description": "Unused attribute"}}):
        rejects(db, "UPDATE resource_type_fields SET translations=%s WHERE id=%s", (Jsonb(translations), f))
    db.execute("UPDATE resource_type_fields SET name='Count',display_order=10 WHERE id=%s", (f,))
    assert resolve(db, t, {}, r)[0]["field_id"] == f


def test_concurrent_length_reduction_cannot_invalidate_a_new_value(db, record):
    t = create_type(db, name="Concurrent limit")
    field = add_field(db, t, "text", limit=4)
    r = record["id"]
    db.execute("UPDATE records SET type_id=%s WHERE id=%s", (t, r))
    db.commit()
    try:
        with psycopg.connect(os.environ["DATABASE_URL"]) as editor:
            db.execute("""INSERT INTO resource_type_values(kind,resource_id,type_id,field_id,data_type,text_capacity,value)
                VALUES ('record',%s,%s,%s,'text',4,resource_field_decode('text',%s))""", (r, t, field, Jsonb("abcd")))
            shrink = "UPDATE resource_type_fields SET max_length=2 WHERE id=%s"
            with pytest.raises(psycopg.errors.LockNotAvailable), editor.transaction():
                editor.execute("SET LOCAL lock_timeout='200ms'")
                editor.execute(shrink, (field,))
            db.commit()
            with pytest.raises(psycopg.errors.CheckViolation), editor.transaction():
                editor.execute(shrink, (field,))
        assert resolve(db, t, {}, r)[0]["text_value"] == "abcd"
    finally:
        db.rollback()
        db.execute("DELETE FROM resource_type_values WHERE kind='record' AND resource_id=%s", (r,))
        db.execute("UPDATE records SET type_id=NULL WHERE id=%s", (r,))
        db.execute("DELETE FROM resource_types WHERE kind='record' AND id=%s", (t,))
        db.commit()
