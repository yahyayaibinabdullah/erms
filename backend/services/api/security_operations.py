from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import Connection

from .authorization_admin import CUSTODY_PRIVILEGE_CODES
from .authorization_policy import require_authorization_admin, require_audit_view
from .database import get_connection
from .schemas import (
    SecurityDenialGroupRead,
    SecurityEventDetailRead,
    SecurityOperationsSummaryRead,
    SecurityReconciliationRead,
)


router = APIRouter(prefix="/api/v1/security-operations", tags=["security operations"])


SECURITY_OPERATIONS = (
    "NOTIFICATION_CONFIGURATION_SAVED", "NOTIFICATION_CONFIGURATION_ACTIVATED",
    "NOTIFICATION_TEST_SENT", "NOTIFICATION_TEST_FAILED",
    "AUTHORIZATION_DENIED", "AUTHENTICATION_FAILED", "ACCOUNT_LOCKED",
    "INFORMATION_GOVERNANCE_BYPASS_USED", "ACCESS_EXPLANATION_VIEWED",
    "SECURITY_LEVEL_CHANGED", "SECURITY_LEVEL_UPGRADED", "SECURITY_LEVEL_DOWNGRADED",
    "ACL_REPLACED", "DEFAULT_CHILD_AGGREGATION_ACL_REPLACED",
    "DEFAULT_CHILD_RECORD_ACL_REPLACED", "PROFILE_PRIVILEGES_REPLACED",
    "PROFILE_ASSIGNED", "GOVERNANCE_ROLE_CHANGED",
)


def _validate_window(since: datetime, end: datetime) -> None:
    if (since.tzinfo is None) != (end.tzinfo is None) or end <= since or end - since > timedelta(days=366):
        raise HTTPException(status_code=422, detail="invalid security-operations date range")


def _recent_security_events(
    connection: Connection, since: datetime, end: datetime, *, limit: int, offset: int = 0,
) -> list[dict]:
    return list(connection.execute(
        """SELECT event.id,event.occurred_at,event.operation,event.actor_user_id,
                  event.actor_name,event.actor_email,event.actor_type,event.entity_type,event.entity_id,
                  CASE
                    WHEN coalesce((event.metadata->>'redacted')::boolean,false)
                      THEN 'Protected item — details hidden'
                    WHEN event.entity_type='aggregation' AND aggregation.id IS NOT NULL
                      THEN aggregation.aggregation_number || ' — ' || aggregation.title
                    WHEN event.entity_type='record' AND record.id IS NOT NULL
                      THEN record.record_number || ' — ' || record.title
                    WHEN event.entity_type='user' AND account.id IS NOT NULL
                      THEN account.name || coalesce(' — ' || account.email,'')
                    WHEN event.entity_type='profile' AND profile.id IS NOT NULL
                      THEN profile.code || ' — ' || profile.name
                    WHEN event.entity_type='role' AND role.id IS NOT NULL
                      THEN role.code || ' — ' || role.name
                    WHEN event.entity_type='org_unit' AND org_unit.id IS NOT NULL
                      THEN org_unit.code || ' — ' || org_unit.name
                    WHEN event.entity_type='classification' AND classification.id IS NOT NULL
                      THEN classification.code || ' — ' || classification.title
                    WHEN event.entity_type='classification_scheme' AND scheme.id IS NOT NULL
                      THEN scheme.code || ' — ' || scheme.title
                    WHEN event.entity_type='security_level' AND security_level.id IS NOT NULL
                      THEN security_level.code || ' — ' || security_level.name
                    ELSE initcap(replace(event.entity_type,'_',' ')) || ' #' || event.entity_id::text
                  END AS entity_label,
                  nullif(event.metadata->>'decision_code','') AS decision_code,
                  nullif(event.metadata->>'required_privilege','') AS required_privilege,
                  coalesce((event.metadata->>'redacted')::boolean,false) AS redacted
             FROM (
                 SELECT * FROM authorized_event_history
                  WHERE occurred_at >= %s AND occurred_at <= %s AND operation=ANY(%s)
                  ORDER BY occurred_at DESC,id DESC LIMIT %s OFFSET %s
             ) event
             LEFT JOIN aggregations aggregation ON event.entity_type='aggregation'
                  AND aggregation.id=event.entity_id AND current_user_can_view_aggregation(aggregation.id)
             LEFT JOIN records record ON event.entity_type='record'
                  AND record.id=event.entity_id AND current_user_can_view_record(record.id)
             LEFT JOIN users account ON event.entity_type='user' AND account.id=event.entity_id
             LEFT JOIN profiles profile ON event.entity_type='profile' AND profile.id=event.entity_id
             LEFT JOIN roles role ON event.entity_type='role' AND role.id=event.entity_id
             LEFT JOIN org_units org_unit ON event.entity_type='org_unit' AND org_unit.id=event.entity_id
             LEFT JOIN classifications classification ON event.entity_type='classification'
                  AND classification.id=event.entity_id
             LEFT JOIN classification_schemes scheme ON event.entity_type='classification_scheme'
                  AND scheme.id=event.entity_id
             LEFT JOIN security_levels security_level ON event.entity_type='security_level'
                  AND security_level.id=event.entity_id
            ORDER BY event.occurred_at DESC,event.id DESC""",
        (since, end, list(SECURITY_OPERATIONS), limit, offset),
    ).fetchall())


@router.get("/events", response_model=list[SecurityEventDetailRead], dependencies=[Depends(require_audit_view)])
def security_events(
    start_at: datetime = Query(...),
    end_at: datetime = Query(...),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    """Page through the security events in an already selected window."""
    _validate_window(start_at, end_at)
    return _recent_security_events(connection, start_at, end_at, limit=limit, offset=offset)


def _denial_groups(
    connection: Connection, since: datetime, end: datetime, *, limit: int, offset: int = 0,
) -> list[dict]:
    return list(connection.execute(
        """SELECT coalesce(metadata->>'decision_code','unspecified') AS decision_code,
                  coalesce(metadata->>'required_privilege','unspecified') AS required_privilege,
                  count(*)::int AS count,max(occurred_at) AS last_seen_at
             FROM event_history
            WHERE occurred_at >= %s AND occurred_at <= %s AND operation='AUTHORIZATION_DENIED'
            GROUP BY 1,2 ORDER BY count(*) DESC,1,2 LIMIT %s OFFSET %s""",
        (since, end, limit, offset),
    ).fetchall())


@router.get("/denial-groups", response_model=list[SecurityDenialGroupRead], dependencies=[Depends(require_audit_view)])
def security_denial_groups(
    start_at: datetime = Query(...),
    end_at: datetime = Query(...),
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    """Page through sanitized denial groups in the selected security window."""
    _validate_window(start_at, end_at)
    return _denial_groups(connection, start_at, end_at, limit=limit, offset=offset)


@router.get("/summary", response_model=SecurityOperationsSummaryRead, dependencies=[Depends(require_audit_view)])
def security_summary(
    hours: int = Query(24, ge=1, le=24 * 90),
    start_at: datetime | None = Query(None),
    end_at: datetime | None = Query(None),
    recent_event_limit: int = Query(100, ge=1, le=100),
    denial_group_limit: int = Query(50, ge=1, le=50),
    connection: Connection = Depends(get_connection, scope="function"),
):
    """Return aggregate security signals without protected snapshots or request content."""
    generated_at = datetime.now(timezone.utc)
    end = end_at or generated_at
    since = start_at or (end - timedelta(hours=hours))
    _validate_window(since, end)
    rows = list(connection.execute(
        """SELECT operation,count(*)::int AS count,max(occurred_at) AS last_seen_at
           FROM event_history WHERE occurred_at >= %s AND occurred_at <= %s AND operation=ANY(%s)
           GROUP BY operation ORDER BY count(*) DESC,operation""",
        (since, end, list(SECURITY_OPERATIONS)),
    ).fetchall())
    denials = _denial_groups(connection, since, end, limit=denial_group_limit)
    recent_events = _recent_security_events(connection, since, end, limit=recent_event_limit)
    full_privilege_roles = list(connection.execute(
        """SELECT role.id,role.code,role.name,role.status,
                  profile.code AS profile_code,profile.name AS profile_name,
                  (profile.code='ALL_PRIVS') AS is_builtin_bootstrap_profile
             FROM roles role
             JOIN profiles profile ON profile.id=role.profile_id
            WHERE (SELECT count(*) FROM profile_privileges membership
                    WHERE membership.profile_id=profile.id)
                  = (SELECT count(*) FROM privileges)
              AND (SELECT count(*) FROM privileges)>0
            ORDER BY role.name,role.code,role.id"""
    ).fetchall())
    return {
        "window_start": since, "window_end": end,
        "window_hours": max(1, int((end - since).total_seconds() // 3600)),
        "generated_at": generated_at, "event_counts": rows, "denial_groups": denials,
        "recent_events": recent_events, "full_privilege_roles": full_privilege_roles,
        "total_security_events": sum(row["count"] for row in rows),
        "total_denials": next((row["count"] for row in rows if row["operation"] == "AUTHORIZATION_DENIED"), 0),
    }


def _continuity(connection: Connection) -> dict:
    highest = connection.execute(
        "SELECT coalesce(max(level_number),0) AS value FROM security_levels"
    ).fetchone()["value"]
    administrators = list(connection.execute(
        """SELECT DISTINCT account.id,account.name,account.email
           FROM users account JOIN user_role_assignments assignment ON assignment.user_id=account.id
           JOIN roles role ON role.id=assignment.role_id
           JOIN profile_privileges membership ON membership.profile_id=role.profile_id
           JOIN privileges privilege ON privilege.id=membership.privilege_id
           WHERE account.status='active' AND role_effectively_active(role.id)
             AND assignment.valid_from<=CURRENT_TIMESTAMP
             AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
             AND privilege.code='authorization.administer' ORDER BY account.name"""
    ).fetchall())
    custodians = list(connection.execute(
        """SELECT DISTINCT account.id,account.name,account.email,role.id AS role_id,
                  role.code AS role_code,level.code AS security_level_code
           FROM users account JOIN user_role_assignments assignment ON assignment.user_id=account.id
           JOIN roles role ON role.id=assignment.role_id
           JOIN security_levels level ON level.id=role.security_level_id
           WHERE account.status='active' AND role.is_information_governance
             AND level.level_number >= %s AND role_effectively_active(role.id)
             AND assignment.valid_from<=CURRENT_TIMESTAMP
             AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
             AND (SELECT count(DISTINCT privilege.code)
                  FROM profile_privileges membership JOIN privileges privilege ON privilege.id=membership.privilege_id
                  WHERE membership.profile_id=role.profile_id AND privilege.code=ANY(%s))=%s
           ORDER BY account.name""",
        (highest, list(CUSTODY_PRIVILEGE_CODES), len(CUSTODY_PRIVILEGE_CODES)),
    ).fetchall())
    return {"active_authorization_administrators": administrators,
            "highest_clearance_governance_custodians": custodians}


@router.get("/reconciliation", response_model=SecurityReconciliationRead, dependencies=[Depends(require_authorization_admin)])
def reconciliation(connection: Connection = Depends(get_connection, scope="function")):
    continuity = _continuity(connection)
    problems: list[dict] = []
    admin_count = len(continuity["active_authorization_administrators"])
    custodian_count = len({item["id"] for item in continuity["highest_clearance_governance_custodians"]})
    if admin_count == 0:
        problems.append({"code": "zero_authorization_administrators", "severity": "critical"})
    elif admin_count == 1:
        problems.append({"code": "single_authorization_administrator", "severity": "advisory"})
    if custodian_count == 0:
        problems.append({"code": "zero_universal_governance_custodians", "severity": "critical"})
    elif custodian_count == 1:
        problems.append({"code": "single_universal_governance_custodian", "severity": "advisory"})
    hierarchy_violations = connection.execute(
        """SELECT count(*)::int AS value FROM aggregations child
           JOIN aggregations parent ON parent.id=child.parent_aggregation_id
           JOIN security_levels child_level ON child_level.id=child.security_level_id
           JOIN security_levels parent_level ON parent_level.id=parent.security_level_id
           WHERE child_level.level_number>parent_level.level_number"""
    ).fetchone()["value"] + connection.execute(
        """SELECT count(*)::int AS value FROM records child
           JOIN aggregations parent ON parent.id=child.aggregation_id
           JOIN security_levels child_level ON child_level.id=child.security_level_id
           JOIN security_levels parent_level ON parent_level.id=parent.security_level_id
           WHERE child_level.level_number>parent_level.level_number"""
    ).fetchone()["value"]
    if hierarchy_violations:
        problems.append({"code": "security_hierarchy_violation", "severity": "critical",
                         "count": hierarchy_violations})
    ownership_rows = connection.execute(
        """SELECT resource_type,count(*)::int AS count
             FROM organizational_ownership_diagnostics
            GROUP BY resource_type ORDER BY resource_type"""
    ).fetchall()
    ownership_by_type = {row["resource_type"]: row["count"] for row in ownership_rows}
    ownership_violations = sum(ownership_by_type.values())
    if ownership_violations:
        problems.append({
            "code": "organizational_ownership_invariant_violation",
            "severity": "critical", "count": ownership_violations,
        })
    return {"generated_at": datetime.now(timezone.utc), **continuity,
            "hierarchy_violation_count": hierarchy_violations,
            "ownership_invariant_violation_count": ownership_violations,
            "ownership_invariant_violations_by_type": ownership_by_type,
            "findings": problems}
