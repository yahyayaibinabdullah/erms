"""Type metadata participates in the resource owner's write transaction."""

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from .continuity_lock import acquire_continuity_shared_lock
from .resource_types import check_custodian
from .resource_authorization import _audit_governance_bypass


def current_fields(c, kind, resource_id):
    return c.execute(
        """SELECT coalesce(jsonb_object_agg(field_id,resource_field_json(value)),'{}') AS fields
                        FROM resource_type_values WHERE kind=%s AND resource_id=%s""",
        (kind, resource_id),
    ).fetchone()["fields"]


def prepare_metadata(c, kind, old, destination, level_id, raw, confirmed):
    resource_id = old["id"] if old else None
    source = old["type_id"] if old else None
    acquire_continuity_shared_lock(c)
    checks = [(destination, level_id)]
    if old:
        checks.append((source, old["security_level_id"]))
    for target, required_level in dict.fromkeys(checks):
        if target is None:
            continue
        if (
            c.execute(
                """SELECT id FROM resource_types WHERE kind=%s AND id=%s
                            AND user_passes_type_gate(current_user_id(),kind,id,%s,true) FOR SHARE""",
                (kind, target, required_level),
            ).fetchone()
            is None
        ):
            raise HTTPException(403, detail={"code": "insufficient_type_access"})
    previous = current_fields(c, kind, resource_id) if source is not None else {}
    if source != destination:
        check_custodian(c, level_id)
        if previous and not confirmed:
            raise HTTPException(
                409, detail={"code": "type_change_requires_confirmation"}
            )
    proposed = c.execute(
        """SELECT coalesce(jsonb_object_agg(field_id,resource_field_json(value)),'{}') AS fields
            FROM resolve_resource_type_values(%s,%s,%s,coalesce(%s::jsonb->'field_values','{}'::jsonb))""",
        (kind, resource_id, destination, raw),
    ).fetchone()["fields"]
    if old and (source != destination or previous != proposed):
        c.execute(f"SELECT assert_{kind}_effectively_open(%s)", (resource_id,))
        c.execute("SELECT lock_hold_policy_shared()")
        if c.execute(
            "SELECT resource_state_changes_blocked(%s,%s) AS blocked",
            (kind, resource_id),
        ).fetchone()["blocked"]:
            raise HTTPException(
                409, detail={"code": "effective_hold_prevents_metadata_change"}
            )
        # Lifecycle triggers on the owner-row update still run. Remove old
        # references first so that changing type_id satisfies its composite FK.
        c.execute(
            "DELETE FROM resource_type_values WHERE kind=%s AND resource_id=%s",
            (kind, resource_id),
        )
    return source, previous, proposed, old["security_level_id"] if old else None


def prepare_update(c, kind, existing, payload, raw, metadata_fields):
    fields = payload.model_fields_set
    changes = payload.model_dump(
        exclude_unset=True, exclude={"field_values", "confirm_type_change"}
    )
    destination = payload.type_id if "type_id" in fields else existing["type_id"]
    if not fields.intersection(metadata_fields) or (
        destination is None and existing["type_id"] is None and not payload.field_values
    ):
        return changes, None
    prepared = prepare_metadata(
        c,
        kind,
        existing,
        destination,
        payload.security_level_id or existing["security_level_id"],
        raw,
        payload.confirm_type_change,
    )
    # A field-only update still advances the resource's optimistic version.
    changes["type_id"] = destination
    return changes, prepared


def finish_metadata(c, kind, row, prepared):
    source, previous, proposed, previous_level = prepared
    create_privilege = (
        "record.create"
        if kind == "record"
        else (
            "aggregation.create_child"
            if row.get("parent_aggregation_id")
            else "aggregation.create_root"
        )
    )
    destination = row["type_id"]
    if previous != proposed or source != destination:
        c.execute(
            """INSERT INTO resource_type_values(kind,resource_id,type_id,field_id,data_type,text_capacity,value)
            SELECT %s,%s,%s,f.id,f.data_type,f.text_capacity,resource_field_decode(f.data_type,input.value)
            FROM jsonb_each(%s::jsonb) input JOIN resource_type_fields f ON f.id=input.key::bigint
            WHERE f.kind=%s AND f.type_id=%s""",
            (kind, row["id"], destination, Jsonb(proposed), kind, destination),
        )
        c.execute(
            "SELECT append_domain_event(%s,%s,'TYPE_METADATA_CHANGED',%s)",
            (
                kind,
                row["id"],
                Jsonb(
                    {
                        "before": {
                            "type_id": source,
                            "security_level_id": previous_level,
                            "field_values": previous,
                        },
                        "after": {
                            "type_id": destination,
                            "security_level_id": row["security_level_id"],
                            "field_values": proposed,
                        },
                    }
                ),
            ),
        )
        if (
            destination is not None
            and not c.execute(
                "SELECT user_has_type_grant(current_user_id(),%s,%s,true) AS allowed",
                (kind, destination),
            ).fetchone()["allowed"]
        ):
            _audit_governance_bypass(
                c,
                kind,
                row["id"],
                f"{kind}.modify" if previous_level is not None else create_privilege,
                "type.use",
                row["security_level_id"],
                type_bypass=True,
            )
    row["field_values"] = proposed
    return row
