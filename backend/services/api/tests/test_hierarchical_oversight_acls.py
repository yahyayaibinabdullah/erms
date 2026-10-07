"""Approved HACL-01–12 contract, using the disposable database test harness."""
import os
from pathlib import Path
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
import pytest

from .test_organizational_acl_defaults_phase6 import (
    AGGREGATION_CREATOR, AGGREGATION_MEMBERS, RECORD_CREATOR, RECORD_MEMBERS,
    _permission_codes,
)
from .test_phase7_mutation_authorization import _grant_principal, _login_as_phase7
from .test_phase9_governance_authorization import _login_admin

MANAGERS = "owning_and_higher_level_unit_managers"
FILE_ADMIN = "effective_file_administrator"
SCOPES = [
    ("aggregation_acl_grants", "aggregation_id", "aggregation"),
    ("aggregation_child_aggregation_acl_defaults", "aggregation_id", "aggregation"),
    ("aggregation_child_record_acl_defaults", "aggregation_id", "record"),
    ("record_acl_grants", "record_id", "record"),
]


def db():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def _only_contextual(aggregation_id, record_id=None):
    with db() as c:
        c.execute("DELETE FROM aggregation_acl_grants WHERE aggregation_id=%s AND principal_type NOT IN (%s,%s)", (aggregation_id, MANAGERS, FILE_ADMIN))
        if record_id is not None:
            c.execute("UPDATE records SET inherit_acl_from_parent=false WHERE id=%s", (record_id,))
            c.execute("DELETE FROM record_acl_grants WHERE record_id=%s AND principal_type NOT IN (%s,%s)", (record_id, MANAGERS, FILE_ADMIN))


def _ancestor(c, code, parent=None):
    return c.execute("INSERT INTO org_units(code,name,parent_org_unit_id) VALUES (%s,%s,%s) RETURNING id", (code, code, parent)).fetchone()["id"]


def _role(c, unit, code):
    return c.execute("INSERT INTO roles(org_unit_id,code,name) VALUES (%s,%s,%s) RETURNING id", (unit, code, code)).fetchone()["id"]


def _matches(c, user_id, owner, principal):
    return c.execute("SELECT user_matches_contextual_acl(%s,%s,%s) AS result", (user_id, owner, principal)).fetchone()["result"]


@pytest.mark.parametrize("table,column,kind", SCOPES)
def test_exact_prospective_defaults_and_null_role_ids(client, aggregation, record, table, column, kind):
    owner_id = record["id"] if kind == "record" and table == "record_acl_grants" else aggregation["id"]
    creator = AGGREGATION_CREATOR if kind == "aggregation" else RECORD_CREATOR
    members = AGGREGATION_MEMBERS if kind == "aggregation" else RECORD_MEMBERS
    assert _permission_codes(table, column, owner_id, "role") == creator
    assert _permission_codes(table, column, owner_id, MANAGERS) == members
    assert _permission_codes(table, column, owner_id, FILE_ADMIN) == creator | {f"{kind}.acl.manage"}
    with db() as c:
        assert not c.execute(f"SELECT 1 FROM {table} WHERE {column}=%s AND principal_type IN (%s,%s) AND role_id IS NOT NULL", (owner_id, MANAGERS, FILE_ADMIN)).fetchone()
        assert c.execute("SELECT 1 FROM event_history WHERE after_state->>'principal_type'=%s", (MANAGERS,)).fetchone()


def test_dormant_defaults_do_not_override_live_parent_policy(client, aggregation):
    acl = client.get(f"/api/v1/aggregations/{aggregation['id']}/permissions").json()
    saved = client.put(f"/api/v1/aggregations/{aggregation['id']}/permissions", json={
        "version": acl["resource_acl_version"], "grants": [{"principal_type": "everyone", "permission_codes": ["aggregation.view"]}], "reason": "Parent policy controls children",
    })
    assert saved.status_code == 200, saved.text
    child = client.post("/api/v1/aggregations", json={"aggregation_number": "OVERSIGHT-CHILD", "title": "Child", "parent_aggregation_id": aggregation["id"]})
    assert child.status_code == 201, child.text
    result = client.get(f"/api/v1/aggregations/{child.json()['id']}/permissions").json()
    assert result["effective_acl"][0]["principal_type"] == "everyone"
    assert {MANAGERS, FILE_ADMIN} <= {row["principal_type"] for row in result["override_acl"]}
    assert result["override_acl_is_dormant"]


def test_manager_matches_owning_unit_and_ancestors_with_current_assignments(client, aggregation):
    user, role = _grant_principal({"aggregation.view"})
    _only_contextual(aggregation["id"])
    with db() as c:
        upper = _ancestor(c, "upper")
        middle = _ancestor(c, "middle", upper)
        c.execute("UPDATE org_units SET parent_org_unit_id=%s,managing_role_id=%s WHERE id=1", (middle, role))
        assert _matches(c, user, 1, MANAGERS)
        c.execute("UPDATE org_units SET managing_role_id=NULL WHERE id=1")
        c.execute("UPDATE roles SET org_unit_id=%s WHERE id=%s", (upper, role))
        c.execute("UPDATE org_units SET managing_role_id=%s WHERE id=%s", (role, upper))
        inactive = _role(c, middle, "inactive-middle-manager")
        c.execute("UPDATE org_units SET managing_role_id=%s WHERE id=%s", (inactive, middle))
        c.execute("UPDATE roles SET date_deactivated=clock_timestamp() WHERE id=%s", (inactive,))
        assert _matches(c, user, 1, MANAGERS), "Inactive intermediate manager must not stop traversal"
        c.execute("UPDATE user_role_assignments SET valid_from=NOW()+interval '1 day' WHERE user_id=%s", (user,))
        assert not _matches(c, user, 1, MANAGERS)
        c.execute("UPDATE user_role_assignments SET valid_from=NOW()-interval '2 days',valid_until=NOW()-interval '1 day' WHERE user_id=%s", (user,))
        assert not _matches(c, user, 1, MANAGERS)
        c.execute("UPDATE user_role_assignments SET valid_until=NULL WHERE user_id=%s", (user,))
    _login_as_phase7(client)
    assert client.get(f"/api/v1/aggregations/{aggregation['id']}").status_code == 200
    with db() as c:
        c.execute("UPDATE org_units SET parent_org_unit_id=NULL WHERE id=1")
    assert client.get(f"/api/v1/aggregations/{aggregation['id']}").status_code == 404


def test_file_administrator_nearest_configured_role_without_inactive_fallback(client, aggregation):
    user, role = _grant_principal({"aggregation.view", "aggregation.acl.manage"})
    _only_contextual(aggregation["id"])
    with db() as c:
        upper = _ancestor(c, "upper")
        middle = _ancestor(c, "middle", upper)
        c.execute("UPDATE org_units SET parent_org_unit_id=%s WHERE id=1", (middle,))
        assert not _matches(c, user, 1, FILE_ADMIN)
        c.execute("UPDATE roles SET org_unit_id=%s WHERE id=%s", (upper, role))
        c.execute("UPDATE org_units SET file_administrator_role_id=%s WHERE id=%s", (role, upper))
        assert _matches(c, user, 1, FILE_ADMIN)
        nearer = _role(c, middle, "nearer-file-admin")
        c.execute("UPDATE org_units SET file_administrator_role_id=%s WHERE id=%s", (nearer, middle))
        assert not _matches(c, user, 1, FILE_ADMIN), "Unassigned configured role prevents ancestor fallback"
        c.execute("UPDATE roles SET date_deactivated=clock_timestamp() WHERE id=%s", (nearer,))
        assert not _matches(c, user, 1, FILE_ADMIN), "Inactive configured role prevents ancestor fallback"
        c.execute("UPDATE org_units SET file_administrator_role_id=NULL WHERE id=%s", (middle,))
    _login_as_phase7(client)
    assert client.get(f"/api/v1/aggregations/{aggregation['id']}/permissions").status_code == 200
    with db() as c:
        c.execute("UPDATE org_units SET file_administrator_role_id=NULL WHERE id=%s", (upper,))
    assert client.get(f"/api/v1/aggregations/{aggregation['id']}/permissions").status_code == 404


@pytest.mark.parametrize("principal", [MANAGERS, FILE_ADMIN])
@pytest.mark.parametrize("gate", ["privilege", "clearance", "closed", "hold"])
def test_contextual_grants_do_not_bypass_other_gates(client, aggregation, record, principal, gate):
    privileges = {"aggregation.view", "record.view", "aggregation.modify", "record.component.download"}
    if gate == "privilege":
        privileges.remove("aggregation.modify")
        privileges.remove("record.component.download")
    user, role = _grant_principal(privileges, clearance_code="G" if gate == "clearance" else "TS")
    _only_contextual(aggregation["id"], record["id"])
    field = "managing_role_id" if principal == MANAGERS else "file_administrator_role_id"
    with db() as c:
        c.execute(f"UPDATE org_units SET {field}=%s WHERE id=1", (role,))
        if gate == "clearance":
            level = c.execute("SELECT id FROM security_levels WHERE code='S'").fetchone()["id"]
            c.execute("UPDATE aggregations SET security_level_id=%s WHERE id=%s", (level, aggregation["id"]))
            c.execute("UPDATE records SET security_level_id=%s WHERE id=%s", (level, record["id"]))
        elif gate == "closed":
            c.execute("UPDATE aggregations SET date_closed=NOW() WHERE id=%s", (aggregation["id"],))
        elif gate == "hold":
            hold = c.execute("INSERT INTO holds(code,name,valid_from,preserve_resource_state,owner_user_id) VALUES ('preserve','Preserve',NOW(),true,1) RETURNING id").fetchone()["id"]
            c.execute("SELECT set_config('app.change_reason','Preserve test resource',true)")
            c.execute("SELECT set_config('app.user_id','1',true)")
            c.execute("INSERT INTO hold_aggregation_assignments(aggregation_id,hold_id) VALUES (%s,%s)", (aggregation["id"], hold))
    _login_as_phase7(client)
    if gate == "clearance":
        assert client.get(f"/api/v1/aggregations/{aggregation['id']}").status_code == 404
        assert client.get(f"/api/v1/records/{record['id']}").status_code == 404
    else:
        current = client.get(f"/api/v1/aggregations/{aggregation['id']}")
        assert current.status_code == 200, current.text
        changed = client.patch(f"/api/v1/aggregations/{aggregation['id']}", headers={"If-Match": str(current.json()["version"])}, json={"title": "Forbidden change"})
        assert changed.status_code in (403, 409), changed.text


@pytest.mark.parametrize("field", ["managing_role_id", "file_administrator_role_id"])
def test_designations_same_unit_governed_versioned_and_audited(client, field):
    with db() as c:
        other = _ancestor(c, "other")
        invalid = _role(c, other, "foreign-role")
    current = client.get("/api/v1/org-units/1").json()
    invalid_result = client.patch("/api/v1/org-units/1", json={field: invalid}, headers={"If-Match": str(current["version"])})
    assert invalid_result.status_code == 422, invalid_result.text
    changed = client.patch("/api/v1/org-units/1", json={field: 1}, headers={"If-Match": str(current["version"])})
    assert changed.status_code == 200, changed.text
    stale = client.patch("/api/v1/org-units/1", json={field: None}, headers={"If-Match": str(current["version"])})
    assert stale.status_code == 412
    cleared = client.patch("/api/v1/org-units/1", json={field: None}, headers={"If-Match": str(changed.json()["version"])})
    assert cleared.status_code == 200, cleared.text
    with db() as c:
        assert c.execute("SELECT 1 FROM event_history WHERE entity_type='org_unit' AND entity_id=1 AND after_state ? %s", (field,)).fetchone()
    _grant_principal({"aggregation.view"})
    _login_as_phase7(client)
    denied = client.patch("/api/v1/org-units/1", json={field: 1}, headers={"If-Match": str(cleared.json()["version"])})
    assert denied.status_code == 403


def test_both_designations_survive_save_readback_summary_tree_and_unrelated_edit(client):
    from types import SimpleNamespace
    from frontend.webui.app import form_payload
    from frontend.webui.entities import ENTITIES

    with db() as c:
        administrator = _role(c, 1, "FILE-ADMIN")
    url = '/api/v1/org-units/1'
    existing = client.get(url).json()
    controls = {field.name: SimpleNamespace(value=existing.get(field.name)) for field in ENTITIES['org-units'].fields}
    controls['managing_role_id'].value = '1'
    controls['file_administrator_role_id'].value = str(administrator)
    payload = form_payload(ENTITIES['org-units'], controls, creating=False)
    saved = client.patch(url, json=payload, headers={'If-Match': str(existing['version'])})
    assert saved.status_code == 200, saved.text
    for endpoint in (url, '/api/v1/browse/organization/org-units/1/summary'):
        result = client.get(endpoint)
        assert result.status_code == 200, result.text
        assert result.json()['managing_role_id'] == 1
        assert result.json()['file_administrator_role_id'] == administrator
    roots = client.get('/api/v1/browse/organization/roots')
    assert roots.status_code == 200, roots.text
    root = next(row for row in roots.json() if row['id'] == 1)
    assert (root['managing_role_id'], root['file_administrator_role_id']) == (1, administrator)
    reopened = client.get(url).json()
    controls = {field.name: SimpleNamespace(value=reopened.get(field.name)) for field in ENTITIES['org-units'].fields}
    controls['description'].value = 'Unrelated metadata edit after reopening'
    updated = client.patch(url, json=form_payload(ENTITIES['org-units'], controls, creating=False), headers={'If-Match': str(reopened['version'])})
    assert updated.status_code == 200, updated.text
    with db() as c:
        persisted = c.execute('SELECT managing_role_id,file_administrator_role_id FROM org_units WHERE id=1').fetchone()
        assert persisted == {'managing_role_id': 1, 'file_administrator_role_id': administrator}
    final = client.get(url).json()
    cleared = client.patch(url, json={'managing_role_id': None, 'file_administrator_role_id': None}, headers={'If-Match': str(final['version'])})
    assert cleared.status_code == 200, cleared.text
    assert client.get(url).json()['managing_role_id'] is None
    assert client.get(url).json()['file_administrator_role_id'] is None


def test_designated_role_integrity_and_protected_delete(client):
    with db() as c:
        c.execute("UPDATE org_units SET managing_role_id=1,file_administrator_role_id=1 WHERE id=1")
        other = _ancestor(c, "other")
        for statement, params in [
            ("UPDATE org_units SET managing_role_id=999999 WHERE id=1", ()),
            ("UPDATE org_units SET managing_role_id=2 WHERE id=1", ()),
            ("UPDATE roles SET org_unit_id=%s WHERE id=1", (other,)),
            ("UPDATE roles SET account_type_restriction='service' WHERE id=1", ()),
        ]:
            with pytest.raises(psycopg.Error), c.transaction():
                c.execute(statement, params)
        c.execute("UPDATE roles SET date_deactivated=clock_timestamp() WHERE id=1")
        assert c.execute("SELECT managing_role_id FROM org_units WHERE id=1").fetchone()["managing_role_id"] == 1
        assert not c.execute("SELECT * FROM contextual_acl_roles(1,%s)", (MANAGERS,)).fetchall()


def test_designated_role_delete_preflight_requires_configuration_removal(client):
    with db() as c:
        role = _role(c, 1, "designated-only")
        c.execute("UPDATE org_units SET managing_role_id=%s WHERE id=1", (role,))
    report = client.get(f"/api/v1/roles/{role}/deletion-preflight")
    assert report.status_code == 200, report.text
    assert "role_designated_by_unit" in {item["code"] for item in report.json()["blockers"]}
    with db() as c:
        with pytest.raises(psycopg.errors.RestrictViolation), c.transaction():
            c.execute("DELETE FROM roles WHERE id=%s", (role,))


@pytest.mark.parametrize("principal", [MANAGERS, FILE_ADMIN])
def test_record_contextual_permissions_follow_exact_sets_and_current_assignment(client, aggregation, record, principal):
    user, role = _grant_principal(set(RECORD_CREATOR) | {"record.acl.manage"})
    _only_contextual(aggregation["id"], record["id"])
    field = "managing_role_id" if principal == MANAGERS else "file_administrator_role_id"
    expected = RECORD_MEMBERS if principal == MANAGERS else RECORD_CREATOR | {"record.acl.manage"}
    with db() as c:
        c.execute(f"UPDATE org_units SET {field}=%s WHERE id=1", (role,))
        for permission in set(RECORD_CREATOR) | {"record.acl.manage"}:
            actual = c.execute("SELECT user_has_record_permission(%s,%s,%s) AS allowed", (user, record["id"], permission)).fetchone()["allowed"]
            assert actual == (permission in expected), permission
        c.execute("UPDATE user_role_assignments SET valid_from=NOW()-interval '1 day',valid_until=NOW()-interval '1 minute' WHERE user_id=%s", (user,))
        assert not c.execute("SELECT user_has_record_permission(%s,%s,'record.view') AS allowed", (user, record["id"])).fetchone()["allowed"]


@pytest.mark.parametrize("principal", [MANAGERS, FILE_ADMIN])
def test_api_removal_version_history_and_no_automatic_recreation(client, aggregation, principal):
    endpoint = f"/api/v1/aggregations/{aggregation['id']}/permissions"
    acl = client.get(endpoint).json()
    grants = [{key: row[key] for key in ("principal_type", "role_id", "permission_codes")} for row in acl["effective_acl"] if row["principal_type"] != principal]
    saved = client.put(endpoint, json={"version": acl["resource_acl_version"], "grants": grants, "reason": "Remove contextual access deliberately"})
    assert saved.status_code == 200, saved.text
    stale = client.put(endpoint, json={"version": acl["resource_acl_version"], "grants": grants, "reason": "Stale save"})
    assert stale.status_code == 409
    with db() as c:
        c.execute("UPDATE org_units SET managing_role_id=1,file_administrator_role_id=1 WHERE id=1")
        assert not c.execute("SELECT 1 FROM aggregation_acl_grants WHERE aggregation_id=%s AND principal_type=%s", (aggregation["id"], principal)).fetchone()
        assert c.execute("SELECT 1 FROM event_history WHERE reason='Remove contextual access deliberately'").fetchone()
    for malformed in [dict(principal_type=principal, role_id=1, permission_codes=["aggregation.view"]), dict(principal_type="invented", permission_codes=["aggregation.view"])]:
        invalid = client.put(endpoint, json={"version": saved.json()["resource_acl_version"], "grants": [malformed], "reason": "Invalid principal"})
        assert invalid.status_code == 422


def test_explanations_identify_contextual_role_and_bounded_disclosure(client, aggregation):
    user, role = _grant_principal({"aggregation.view", "aggregation.acl.manage"})
    _only_contextual(aggregation["id"])
    with db() as c:
        c.execute("UPDATE org_units SET managing_role_id=%s,file_administrator_role_id=%s WHERE id=1", (role, role))
    _login_as_phase7(client)
    result = client.post("/api/v1/authorization/explain", json={"resource_type": "aggregation", "resource_id": aggregation["id"], "operation": "aggregation.view"})
    assert result.status_code == 200, result.text
    assert result.json()["allowed"]
    matches = result.json()["acl"]["contextual_matches"]
    assert {m["principal_type"] for m in matches} == {MANAGERS, FILE_ADMIN}
    assert {m["role_id"] for m in matches} == {role}
    endpoint = f"/api/v1/aggregations/{aggregation['id']}/acl-contextual-principals"
    assert client.get(endpoint, params={"principal_type": MANAGERS}).status_code == 403, "ACL scope must not imply permission to inspect the organization"
    _login_admin(client)
    with db() as c:
        parent = _ancestor(c, "top")
        c.execute("UPDATE org_units SET parent_org_unit_id=%s WHERE id=1", (parent,))
    first = client.get(endpoint, params={"principal_type": MANAGERS, "limit": 1, "offset": 0}).json()
    assert len(first["items"]) == 1 and first["has_more"]
    second = client.get(endpoint, params={"principal_type": MANAGERS, "limit": 1, "offset": 1}).json()
    assert second["items"][0]["org_unit_id"] == parent
    assert second["items"][0]["role_id"] is None
    assert not second["has_more"]
    assert client.get(endpoint, params={"principal_type": MANAGERS, "limit": 101}).status_code == 422


def test_ownership_move_previews_and_resolves_contextual_access_without_copying_roles(client, aggregation):
    user, source_role = _grant_principal({"aggregation.view", "record.view"})
    with db() as c:
        destination_unit = _ancestor(c, "destination-unit")
        destination_role = _role(c, destination_unit, "destination-role")
        c.execute("INSERT INTO user_role_assignments(user_id,role_id) VALUES (1,%s)", (destination_role,))
        c.execute("UPDATE org_units SET managing_role_id=%s,file_administrator_role_id=%s WHERE id=1", (source_role, source_role))
    destination = client.post("/api/v1/aggregations", json={"aggregation_number": "DEST", "title": "Destination", "classification_id": 1, "creator_acl_role_id": destination_role})
    assert destination.status_code == 201, destination.text
    child = client.post("/api/v1/aggregations", json={"aggregation_number": "MOVING", "title": "Moving", "parent_aggregation_id": aggregation["id"], "creator_acl_role_id": 1}).json()
    _only_contextual(aggregation["id"])
    endpoint = f"/api/v1/aggregations/{child['id']}"
    preview = client.get(endpoint + "/acl-move-preview", params={"destination_aggregation_id": destination.json()["id"], "keep_current_access_as_override": True})
    assert preview.status_code == 200, preview.text
    assert preview.json()["contextual_access_may_change"]
    moved = client.post(endpoint + "/acl-move", json={"destination_aggregation_id": destination.json()["id"], "resource_version": child["version"], "keep_current_access_as_override": True, "confirm_ownership_change": True, "reason": "Change organizational ownership"})
    assert moved.status_code == 200, moved.text
    with db() as c:
        assert c.execute("SELECT owning_org_unit_id FROM aggregations WHERE id=%s", (child["id"],)).fetchone()["owning_org_unit_id"] == destination_unit
        assert {row["principal_type"] for row in c.execute("SELECT principal_type FROM aggregation_acl_grants WHERE aggregation_id=%s", (child["id"],)).fetchall()} == {MANAGERS, FILE_ADMIN}
        assert not _matches(c, user, destination_unit, MANAGERS)
        assert not _matches(c, user, destination_unit, FILE_ADMIN)
    _login_as_phase7(client)
    assert client.get(endpoint).status_code == 404
    with db() as c:
        c.execute("UPDATE org_units SET managing_role_id=%s,file_administrator_role_id=%s WHERE id=%s", (destination_role, destination_role, destination_unit))
        c.execute("INSERT INTO user_role_assignments(user_id,role_id) VALUES (%s,%s)", (user, destination_role))
    assert client.get(endpoint).status_code == 200


@pytest.mark.parametrize("table,column,kind", SCOPES)
def test_database_rejects_duplicate_or_anchored_contextual_grants(client, aggregation, record, table, column, kind):
    owner_id = record["id"] if table == "record_acl_grants" else aggregation["id"]
    with db() as c:
        for principal in (MANAGERS, FILE_ADMIN):
            with pytest.raises(psycopg.errors.UniqueViolation), c.transaction():
                c.execute(f"INSERT INTO {table}({column},principal_type,permission_id) SELECT %s,%s,id FROM permissions WHERE code=%s", (owner_id, principal, f"{kind}.view"))
            with pytest.raises(psycopg.errors.CheckViolation), c.transaction():
                c.execute(f"INSERT INTO {table}({column},principal_type,role_id,permission_id) SELECT %s,%s,1,id FROM permissions WHERE code=%s", (owner_id, principal, f"{kind}.view"))


def test_upgrade_preserves_every_existing_acl_grant_and_changes_only_future_defaults():
    """HACL-12: a separate disposable database follows the real upgrade path."""
    root = Path(__file__).resolve().parents[4]
    database_name = "erms_acl_upgrade_" + uuid.uuid4().hex
    admin_url = make_conninfo(os.environ["DATABASE_URL"], dbname="postgres")
    upgrade_url = make_conninfo(os.environ["DATABASE_URL"], dbname=database_name)
    created = False
    try:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created = True
        with psycopg.connect(upgrade_url) as c:
            previous = (root / "database/schema.sql").read_text().split("-- Hierarchical oversight authorization")[0]
            c.execute(previous, prepare=False)
            unit = c.execute("INSERT INTO org_units(code,name) VALUES ('upgrade-unit','Upgrade unit') RETURNING id").fetchone()[0]
            role = c.execute("INSERT INTO roles(org_unit_id,code,name) VALUES (%s,'upgrade-role','Upgrade role') RETURNING id", (unit,)).fetchone()[0]
            scheme = c.execute("INSERT INTO classification_schemes(code,title,date_published) VALUES ('UPGRADE','Upgrade',NOW()) RETURNING id").fetchone()[0]
            classification = c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES (%s,'UPGRADE-01','Upgrade class',true) RETURNING id", (scheme,)).fetchone()[0]
            c.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES (%s,5,0,'destruction')", (classification,))
            c.execute("SELECT set_config('app.creator_acl_role_id',%s,true)", (str(role),))
            agg = c.execute("INSERT INTO aggregations(aggregation_number,title,owning_org_unit_id,classification_id,medium) VALUES ('LEGACY','Legacy',%s,%s,'physical') RETURNING id", (unit, classification)).fetchone()[0]
            c.execute("INSERT INTO records(record_number,title,aggregation_id,owning_org_unit_id,medium) VALUES ('LEGACY-R','Legacy record',%s,%s,'physical')", (agg, unit))
            before = {table: c.execute(f"SELECT * FROM {table} ORDER BY id").fetchall() for table, _, _ in SCOPES}
            assert all(before.values())
            c.commit()
            c.execute((root / "database/migrations/048_hierarchical_oversight_acls.sql").read_text(), prepare=False)
            after = {table: c.execute(f"SELECT * FROM {table} ORDER BY id").fetchall() for table, _, _ in SCOPES}
            assert before == after
            c.execute("SELECT set_config('app.creator_acl_role_id',%s,true)", (str(role),))
            new = c.execute("INSERT INTO aggregations(aggregation_number,title,owning_org_unit_id,classification_id) VALUES ('NEW','New',%s,%s) RETURNING id", (unit, classification)).fetchone()[0]
            assert c.execute("SELECT count(*) FROM aggregation_acl_grants WHERE aggregation_id=%s AND principal_type=%s", (new, FILE_ADMIN)).fetchone()[0] == 7
            assert not c.execute("SELECT 1 FROM aggregation_acl_grants g JOIN permissions p ON p.id=g.permission_id WHERE g.aggregation_id=%s AND g.principal_type='role' AND p.code='aggregation.acl.manage'", (new,)).fetchone()
    finally:
        if created:
            with psycopg.connect(admin_url, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name)))
