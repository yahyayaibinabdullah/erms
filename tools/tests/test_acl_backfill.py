"""Rehearse the approved bulk correction on a disposable copy, never live data."""
import os
import json
import psycopg
import pytest
from tools.backfill_hierarchical_oversight_acls import SCOPES, build_plan, apply_plan


@pytest.fixture
def connection():
    with psycopg.connect(os.environ["ACL_BACKFILL_TEST_URL"]) as connection:
        assert connection.execute("SELECT current_database()").fetchone()[0].startswith("erms_acl_backfill_test_")
        try:
            yield connection
        finally:
            connection.rollback()


def test_rehearsal_preserves_every_unrelated_row_and_setting(connection):
    plan = build_plan(connection)
    assert not plan["conflicts"]
    before_grants = {s[0]: dict(connection.execute(f"SELECT id,to_jsonb(t) FROM {s[0]} t").fetchall()) for s in SCOPES}
    before_resources = {table: dict(connection.execute(f"SELECT id,to_jsonb(t) FROM {table} t").fetchall()) for table in ("aggregations", "records")}
    first_history = connection.execute("SELECT COALESCE(max(id),0) FROM event_history").fetchone()[0]
    report = apply_plan(connection, plan, "User-approved upgrade of existing default ACLs")
    assert connection.execute("SELECT count(*) FROM pg_trigger WHERE tgname IN ('aggregations_protect_closed_hierarchy','records_protect_closed_aggregation') AND tgenabled='O'").fetchone()[0] == 2
    for scope, definition in zip(plan["scopes"], SCOPES):
        table = scope["table"]
        after = dict(connection.execute(f"SELECT id,to_jsonb(t) FROM {table} t").fetchall())
        original = before_grants[table]
        assert set(original) - set(after) == set(scope["remove"])
        assert all(after[id] == row for id, row in original.items() if id not in scope["remove"])
        assert len(set(after) - set(original)) == len(scope["add"])
        changes = connection.execute("SELECT count(*) FROM event_history WHERE id>%s AND entity_type=%s AND operation IN ('CREATE','DELETE')", (first_history, definition[5])).fetchone()[0]
        assert changes == len(scope["add"]) + len(scope["remove"])
    for table, original in before_resources.items():
        after = dict(connection.execute(f"SELECT id,to_jsonb(t) FROM {table} t").fetchall())
        assert set(after) == set(original)
        for id, old in original.items():
            new = after[id]
            relevant = [(scope, definition) for scope, definition in zip(plan["scopes"], SCOPES) if definition[3] == table and id in scope["changed"]]
            counters = {definition[4] for _, definition in relevant}
            for key in old:
                if key in counters:
                    assert new[key] == old[key] + 1
                elif key == "version":
                    assert new[key] == old[key] + len(relevant)
                elif key != "date_updated":
                    assert new[key] == old[key], (table, id, key)
    second = build_plan(connection)
    assert not second["conflicts"]
    assert all(not s["add"] and not s["remove"] for s in second["scopes"])
    before_noop = second["before"]
    apply_plan(connection, second, "Idempotence verification")
    assert build_plan(connection)["before"] == before_noop
    print(json.dumps(report))


def test_stale_preview_is_rejected(connection):
    plan = build_plan(connection)
    connection.execute("UPDATE aggregations SET resource_acl_version=resource_acl_version+1 WHERE id=(SELECT min(id) FROM aggregations)")
    with pytest.raises(ValueError, match="changed since preview"):
        apply_plan(connection, plan, "Stale preview test")


def test_custom_synthetic_grants_are_not_overwritten(connection):
    plan = build_plan(connection)
    if not plan["scopes"][0]["add"]:
        pytest.skip("Pre-upgrade rehearsal required")
    owner, principal, permission = plan["scopes"][0]["add"][0]
    connection.execute("INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,permission_id) VALUES (%s,%s,%s)", (owner, principal, permission))
    custom = build_plan(connection)
    assert any(c.get("reason") == "custom_synthetic_permissions" for c in custom["conflicts"])
    with pytest.raises(ValueError, match="conflicts"):
        apply_plan(connection, custom, "Do not overwrite custom grants")
