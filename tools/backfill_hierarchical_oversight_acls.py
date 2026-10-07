"""Preview and transactionally upgrade existing ACLs; never infer creator roles.

This explicit maintenance operation is separate from schema migration 048.
Call build_plan on a read-only connection, then apply_plan inside a transaction.
The caller owns backup, database selection, commit and report persistence.
"""
import hashlib
import json

MANAGERS = "owning_and_higher_level_unit_managers"
FILE_ADMIN = "effective_file_administrator"
PERMISSIONS = {
    "aggregation": {
        MANAGERS: {"aggregation.view", "aggregation.history.view"},
        FILE_ADMIN: {"aggregation.view", "aggregation.modify_metadata", "aggregation.add_child",
                     "aggregation.add_record", "aggregation.close", "aggregation.acl.manage",
                     "aggregation.history.view"},
    },
    "record": {
        MANAGERS: {"record.view", "record.component.list", "record.component.view", "record.component.download"},
        FILE_ADMIN: {"record.view", "record.acl.manage", "record.history.view", "record.component.list",
                     "record.component.view", "record.component.download", "record.component.share", "record.component.print"},
    },
}
SCOPES = (
    ("aggregation_acl_grants", "aggregation_id", "aggregation", "aggregations", "resource_acl_version", "aggregation_acl_grant", "ACL_REPLACED"),
    ("aggregation_child_aggregation_acl_defaults", "aggregation_id", "aggregation", "aggregations", "child_aggregation_acl_version", "aggregation_child_aggregation_acl_default", "DEFAULT_CHILD_AGGREGATION_ACL_REPLACED"),
    ("aggregation_child_record_acl_defaults", "aggregation_id", "record", "aggregations", "child_record_acl_version", "aggregation_child_record_acl_default", "DEFAULT_CHILD_RECORD_ACL_REPLACED"),
    ("record_acl_grants", "record_id", "record", "records", "resource_acl_version", "record_acl_grant", "ACL_REPLACED"),
)


def snapshot(connection):
    """Full rows protect unrelated grants, settings and preview freshness."""
    return {table: connection.execute(
        f"SELECT count(*),md5(string_agg(row_to_json(t)::text,E'\\n' ORDER BY id)) FROM {table} t"
    ).fetchone() for table in [scope[0] for scope in SCOPES] + ["aggregations", "records"]}


def build_plan(connection):
    permission_ids = dict(connection.execute("SELECT code,id FROM permissions").fetchall())
    required = set().union(*(codes for groups in PERMISSIONS.values() for codes in groups.values()))
    if required - permission_ids.keys():
        raise ValueError("Required permissions are missing")
    creators = {(kind, entity_id): str(metadata.get("creator_acl_role_id", ""))
                for kind, entity_id, metadata in connection.execute(
                    "SELECT DISTINCT ON(entity_type,entity_id) entity_type,entity_id,metadata "
                    "FROM event_history WHERE entity_type IN ('aggregation','record') AND operation='CREATE' "
                    "ORDER BY entity_type,entity_id,id").fetchall()}
    plan = {"before": snapshot(connection), "scopes": [], "conflicts": []}
    # Deleted contextual grants may represent deliberate customization. Do not
    # silently restore them, even if the present-day ACL is empty.
    deleted = connection.execute(
        "SELECT id,entity_type FROM event_history WHERE operation='DELETE' "
        "AND entity_type=ANY(%s) AND before_state->>'principal_type'=ANY(%s)",
        ([s[5] for s in SCOPES], [MANAGERS, FILE_ADMIN]),
    ).fetchall()
    if deleted:
        plan["conflicts"].append({"previously_removed_synthetic_grants": deleted})
    for table, owner, kind, resource_table, counter, history_type, event in SCOPES:
        resource_kind = "aggregation" if resource_table == "aggregations" else "record"
        owners = [r[0] for r in connection.execute(f"SELECT id FROM {resource_table} ORDER BY id")]
        grants = connection.execute(
            f"SELECT g.id,g.{owner},g.principal_type,g.role_id,p.code FROM {table} g "
            "JOIN permissions p ON p.id=g.permission_id ORDER BY g.id").fetchall()
        existing = {}
        remove = []
        for grant_id, resource_id, principal, role_id, code in grants:
            existing.setdefault((resource_id, principal), set()).add(code)
            if principal == "role" and code == kind + ".acl.manage":
                creator = creators.get((resource_kind, resource_id))
                if not creator or not creator.isdigit():
                    plan["conflicts"].append({"table": table, "grant_id": grant_id, "reason": "creator_not_identifiable"})
                elif str(role_id) == creator:
                    remove.append(grant_id)
                # Explicit grants to other roles are not creator defaults.
        add = []
        changed = {row[1] for row in grants if row[0] in set(remove)}
        for resource_id in owners:
            for principal, codes in PERMISSIONS[kind].items():
                present = existing.get((resource_id, principal), set())
                if present and present != codes:
                    plan["conflicts"].append({"table": table, "resource_id": resource_id,
                                              "principal": principal, "reason": "custom_synthetic_permissions"})
                elif not present:
                    add.extend((resource_id, principal, permission_ids[code]) for code in sorted(codes))
                    changed.add(resource_id)
        plan["scopes"].append({"table": table, "add": add, "remove": remove, "changed": sorted(changed)})
    plan["hash"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return plan


def apply_plan(connection, plan, reason):
    if not reason.strip():
        raise ValueError("A reason is required")
    connection.execute("SET LOCAL lock_timeout='10s'")
    connection.execute("LOCK TABLE permissions,event_history,aggregations,records," +
                       ",".join(s[0] for s in SCOPES) + " IN ACCESS EXCLUSIVE MODE")
    current = build_plan(connection)
    if current["hash"] != plan["hash"]:
        raise ValueError("Database changed since preview; generate a new preview")
    if plan["conflicts"]:
        raise ValueError("Review conflicts before applying this plan")
    metadata = json.dumps({"maintenance_operation": "hierarchical_oversight_acl_backfill", "plan_hash": plan["hash"]})
    connection.execute("SELECT set_config('app.event_source','migration',true),"
                       "set_config('app.actor_type','automated_process',true),"
                       "set_config('app.change_reason',%s,true),set_config('app.event_metadata',%s,true)", (reason, metadata))
    # Closed-resource guards currently reject even ACL-version-only updates.
    # Suspend only those guards, under exclusive locks, for this explicitly
    # approved maintenance transaction. Audit and ACL validation stay enabled.
    guards = (("aggregations", "aggregations_protect_closed_hierarchy"),
              ("records", "records_protect_closed_aggregation"))
    for table, trigger in guards:
        enabled = connection.execute("SELECT tgenabled FROM pg_trigger WHERE tgrelid=%s::regclass AND tgname=%s", (table, trigger)).fetchone()
        if enabled != ('O',):
            raise ValueError("Unexpected closed-resource guard configuration")
        connection.execute(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")
    for scope, definition in zip(plan["scopes"], SCOPES):
        table, owner, kind, resource_table, counter, _, event = definition
        connection.execute(f"DELETE FROM {table} WHERE id=ANY(%s)", (scope["remove"],))
        with connection.cursor() as cursor:
            cursor.executemany(f"INSERT INTO {table} ({owner},principal_type,permission_id) VALUES (%s,%s,%s)", scope["add"])
        connection.execute(f"UPDATE {resource_table} SET {counter}={counter}+1,version=version+1 WHERE id=ANY(%s)", (scope["changed"],))
        resource_kind = "aggregation" if resource_table == "aggregations" else "record"
        with connection.cursor() as cursor:
            cursor.executemany("SELECT append_domain_event(%s,%s,%s,%s::jsonb,%s)",
                               [(resource_kind, resource_id, event, metadata, reason) for resource_id in scope["changed"]])
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    for table, trigger in guards:
        connection.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")
    after = build_plan(connection)
    if after["conflicts"] or any(s["add"] or s["remove"] for s in after["scopes"]):
        raise AssertionError("Postconditions failed")
    return {"plan_hash": plan["hash"], "scopes": [
        {"table": s["table"], "added": len(s["add"]), "removed": len(s["remove"]),
         "changed_resources": len(s["changed"])} for s in plan["scopes"]]}
