from __future__ import annotations

import hashlib
import ipaddress
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from psycopg import Connection

from .config import boolean_environment
from .application_settings import cache as settings_cache
from .database import get_connection
from .entity_localization import localized_projection, preferred_language_for_user
from .authorization_policy import (
    load_policy_context,
    require_identity_sessions_admin,
)
from .schemas import (
    ChangePasswordRequest, LoginRequest, LoginSessionRead, PrincipalRead,
    SelfRecentActivityRead,
)


SESSION_COOKIE = "erms_session"
CSRF_COOKIE = "erms_csrf"
# Provisioning identifier only; runtime authorization never grants by role name.
SYSTEM_ADMIN_ROLE = "system-administrator"
COOKIE_SECURE = boolean_environment("AUTH_COOKIE_SECURE", False)
password_hasher = PasswordHasher()


@dataclass(frozen=True)
class Principal:
    user_id: int
    session_id: int
    name: str
    email: str
    account_type: str
    must_change_password: bool
    roles: list[dict[str, Any]]

def hash_secret(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def hash_password(password: str) -> str:
    """Hash already validated application passwords or explicit seed fixtures."""
    return password_hasher.hash(password)


def validate_password(password: str, settings) -> None:
    minimum = settings["AUTH_PASSWORD_MIN_LENGTH"]
    if len(password) < minimum:
        raise ValueError(f"password must contain at least {minimum} characters")



def _deadline(instant: datetime, units: int, seconds_per_unit: int) -> datetime:
    """Represent valid large policy durations without datetime overflow."""
    maximum = datetime.max.replace(tzinfo=timezone.utc) - timedelta(days=1)
    seconds = units * seconds_per_unit
    if seconds >= (maximum - instant).total_seconds():
        return maximum
    return instant + timedelta(seconds=seconds)


def temporary_password(settings) -> str:
    password = secrets.token_urlsafe(max(15, (settings['AUTH_PASSWORD_MIN_LENGTH'] * 3 + 3) // 4))
    validate_password(password, settings)
    return password

def _roles(connection: Connection, user_id: int) -> list[dict[str, Any]]:
    return list(connection.execute(
        """
        SELECT r.id, r.code, r.name, r.translations,
               jsonb_build_object('id', ou.id, 'code', ou.code, 'name', ou.name,
                                  'translations', ou.translations) AS org_unit
        FROM user_role_assignments ura
        JOIN roles r ON r.id = ura.role_id AND r.status = 'active'
        JOIN org_units ou ON ou.id = r.org_unit_id
        WHERE ura.user_id = %s
          AND org_unit_effectively_active(ou.id)
          AND ura.valid_from <= CURRENT_TIMESTAMP
          AND (ura.valid_until IS NULL OR ura.valid_until > CURRENT_TIMESTAMP)
        ORDER BY r.name, r.id
        """, (user_id,)
    ).fetchall())


def resolve_principal(connection: Connection, token: str) -> Principal | None:
    row = connection.execute(
        """
        SELECT s.id AS session_id, s.user_id, u.name, u.email, u.account_type,
               c.must_change_password, s.date_created, s.last_seen_at,
               s.expires_at, s.absolute_expires_at, CURRENT_TIMESTAMP AS evaluated_at
        FROM login_sessions s
        JOIN users u ON u.id = s.user_id
        JOIN user_credentials c ON c.user_id = u.id
        WHERE s.session_token_hash = %s
          AND s.revoked_at IS NULL
          AND s.expires_at > CURRENT_TIMESTAMP
          AND s.absolute_expires_at > CURRENT_TIMESTAMP
          AND u.status = 'active'
          AND u.account_type = 'person'
        FOR UPDATE OF s
        """, (hash_secret(token),)
    ).fetchone()
    if not row:
        return None
    settings = settings_cache.for_connection(connection)
    now = row['evaluated_at']
    idle_deadline = _deadline(row['last_seen_at'], settings['AUTH_SESSION_IDLE_MINUTES'], 60)
    absolute_deadline = _deadline(row['date_created'], settings['AUTH_SESSION_ABSOLUTE_HOURS'], 3600)
    if min(idle_deadline, absolute_deadline) <= now:
        # Persist terminal expiry before a later policy increase can revive it.
        connection.execute(
            "UPDATE login_sessions SET expires_at=LEAST(expires_at,%s), absolute_expires_at=LEAST(absolute_expires_at,%s) WHERE id=%s",
            (min(idle_deadline,absolute_deadline), absolute_deadline, row['session_id']))
        return None
    last_seen = now if row['last_seen_at'] < now - timedelta(minutes=1) else row['last_seen_at']
    expires_at = min(_deadline(last_seen, settings['AUTH_SESSION_IDLE_MINUTES'], 60), absolute_deadline)
    connection.execute(
        """UPDATE login_sessions SET last_seen_at=%s, expires_at=%s, absolute_expires_at=%s
           WHERE id=%s AND (last_seen_at,expires_at,absolute_expires_at) IS DISTINCT FROM (%s,%s,%s)""",
        (last_seen, expires_at, absolute_deadline, row['session_id'],last_seen,expires_at,absolute_deadline))
    return Principal(
        user_id=row["user_id"], session_id=row["session_id"], name=row["name"],
        email=row["email"], account_type=row["account_type"],
        must_change_password=row["must_change_password"], roles=_roles(connection, row["user_id"]),
    )


def principal_from_request(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return principal


def _append_event(connection: Connection, user_id: int, operation: str, metadata: dict[str, Any]) -> None:
    connection.execute(
        "SELECT append_domain_event('user', %s, %s, %s::jsonb)",
        (user_id, operation, __import__("json").dumps(metadata)),
    )


def _client_context(request: Request) -> tuple[str | None, str | None]:
    client_ip = request.client.host if request.client else None
    try:
        client_ip = str(ipaddress.ip_address(client_ip)) if client_ip else None
    except ValueError:
        client_ip = None
    user_agent = request.headers.get("user-agent")
    return client_ip, user_agent[:1000] if user_agent else None


def _timestamp(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _session_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": row["id"],
        "client_ip": str(row["client_ip"]) if row.get("client_ip") else None,
        "user_agent": row.get("user_agent"),
        "session_created_at": _timestamp(row.get("date_created")),
        "last_seen_at": _timestamp(row.get("last_seen_at")),
        "expires_at": _timestamp(row.get("expires_at")),
        "absolute_expires_at": _timestamp(row.get("absolute_expires_at")),
        "revoked_at": _timestamp(row.get("revoked_at")),
    }


def revoke_sessions_for_user(
    connection: Connection,
    user_id: int,
    *,
    revoked_by: int | None,
    reason: str,
) -> int:
    sessions = connection.execute(
        """
        UPDATE login_sessions
           SET revoked_at = CURRENT_TIMESTAMP,
               revoked_by = %s
         WHERE user_id = %s AND revoked_at IS NULL
        RETURNING id, client_ip, user_agent, date_created, last_seen_at,
                  expires_at, absolute_expires_at, revoked_at
        """,
        (revoked_by, user_id),
    ).fetchall()
    if sessions:
        _append_event(
            connection,
            user_id,
            "SESSION_REVOKED",
            {
                "revocation_scope": "all",
                "revocation_reason": reason,
                "sessions_revoked": len(sessions),
                "sessions": [_session_snapshot(session) for session in sessions],
            },
        )
    return len(sessions)


router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


@router.post("/login", response_model=PrincipalRead)
def login(payload: LoginRequest, request: Request, response: Response, connection: Connection = Depends(get_connection, scope="function")):
    settings = settings_cache.for_connection(connection)
    generic = HTTPException(status_code=401, detail="invalid email or password")
    row = connection.execute(
        """
        SELECT u.id, u.name, u.email, u.account_type, u.status,
               c.password_hash, c.must_change_password, c.temporary_expires_at,
               c.failed_attempt_count, c.locked_until
        FROM users u JOIN user_credentials c ON c.user_id = u.id
        WHERE lower(u.email) = lower(%s)
        FOR UPDATE OF c
        """, (payload.email,)
    ).fetchone()
    now = datetime.now(timezone.utc)
    if not row or row["status"] != "active" or row["account_type"] != "person":
        raise generic
    if row["locked_until"] and row["locked_until"] > now:
        raise generic
    try:
        valid = password_hasher.verify(row["password_hash"], payload.password)
    except (VerifyMismatchError, InvalidHashError):
        valid = False
    if not valid:
        attempts = row["failed_attempt_count"] + 1
        locked_until = _deadline(now, settings['AUTH_LOCKOUT_MINUTES'], 60) if attempts >= settings['AUTH_LOCKOUT_ATTEMPTS'] else None
        connection.execute(
            "UPDATE user_credentials SET failed_attempt_count=%s, last_failed_at=%s, locked_until=%s, date_updated=%s WHERE user_id=%s",
            (attempts, now, locked_until, now, row["id"]),
        )
        client_ip, user_agent = _client_context(request)
        _append_event(connection, row["id"], "AUTHENTICATION_FAILED", {
            "client_ip": client_ip,
            "user_agent": user_agent,
            "failed_attempt_count": attempts,
            "lock_applied": bool(locked_until),
            "locked_until": _timestamp(locked_until),
        })
        # The request intentionally ends with an HTTP error. Persist the failure
        # before raising so the dependency cleanup cannot roll back lockout state.
        connection.commit()
        raise generic
    if row["temporary_expires_at"] and row["temporary_expires_at"] <= now:
        raise HTTPException(status_code=401, detail="temporary password has expired")
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    expires_at = _deadline(now, settings['AUTH_SESSION_IDLE_MINUTES'], 60)
    absolute_at = _deadline(now, settings['AUTH_SESSION_ABSOLUTE_HOURS'], 3600)
    expires_at = min(expires_at, absolute_at)
    client_ip, user_agent = _client_context(request)
    session = connection.execute(
        """
        INSERT INTO login_sessions
            (user_id, session_token_hash, csrf_token_hash, expires_at, absolute_expires_at, client_ip, user_agent)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """,
        (row["id"], hash_secret(token), hash_secret(csrf), expires_at, absolute_at,
         client_ip, user_agent),
    ).fetchone()
    connection.execute(
        "UPDATE user_credentials SET failed_attempt_count=0, locked_until=NULL, last_authenticated_at=%s, date_updated=%s WHERE user_id=%s",
        (now, now, row["id"]),
    )
    connection.execute(
        "SELECT set_config('app.user_id', %s, true), set_config('app.actor_type', 'user', true)",
        (str(row["id"]),),
    )
    _append_event(connection, row["id"], "AUTHENTICATION_SUCCEEDED", {
        "session_id": session["id"],
        "client_ip": client_ip,
        "user_agent": user_agent,
        "expires_at": expires_at.isoformat(),
        "absolute_expires_at": absolute_at.isoformat(),
    })
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=COOKIE_SECURE, samesite="lax", path="/")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=COOKIE_SECURE, samesite="lax", path="/")
    principal = Principal(row["id"], session["id"], row["name"], row["email"], row["account_type"], row["must_change_password"], _roles(connection, row["id"]))
    return principal_response(principal, connection)


def _previous_login_at(connection: Connection, principal: Principal) -> datetime | None:
    row = connection.execute(
        """
        SELECT occurred_at
          FROM event_history
         WHERE entity_type = 'user'
           AND entity_id = %s
           AND operation = 'AUTHENTICATION_SUCCEEDED'
           AND COALESCE(metadata->>'session_id', '') <> %s
         ORDER BY occurred_at DESC, id DESC
         LIMIT 1
        """,
        (principal.user_id, str(principal.session_id)),
    ).fetchone()
    return row["occurred_at"] if row else None


def principal_response(principal: Principal, connection: Connection) -> dict[str, Any]:
    policy = load_policy_context(connection, principal)
    language = preferred_language_for_user(connection, principal.user_id)
    user = dict(connection.execute(
        "SELECT id,name,email,account_type,translations FROM users WHERE id=%s",
        (principal.user_id,),
    ).fetchone())
    user["localized"] = localized_projection(user, language, "name")
    user.pop("translations", None)
    roles = []
    for source in principal.roles:
        role = {key: value for key, value in source.items() if key != "translations"}
        role["localized"] = localized_projection(source, language, "name")
        unit = source["org_unit"]
        role["org_unit"] = {key: value for key, value in unit.items() if key != "translations"}
        role["org_unit"]["localized"] = localized_projection(unit, language, "name")
        roles.append(role)
    return {
        "user": user,
        "roles": roles,
        "session": {"id": principal.session_id},
        "must_change_password": principal.must_change_password,
        "previous_login_at": _previous_login_at(connection, principal),
        "can_manage_disposition": principal.account_type == 'person' and any(
            role.is_information_governance and 'disposition.jobs.manage' in role.privileges
            for role in policy.effective_roles
        ),
        "global_privileges": sorted({
            privilege
            for role in policy.effective_roles
            for privilege in role.privileges
        }),
    }


@router.get("/me", response_model=PrincipalRead)
def me(
    principal: Principal = Depends(principal_from_request),
    connection: Connection = Depends(get_connection, scope="function"),
):
    return principal_response(principal, connection)


@router.get("/me/recent-activity", response_model=list[SelfRecentActivityRead])
def my_recent_activity(
    limit: int = Query(6, ge=1, le=50),
    since: datetime | None = None,
    principal: Principal = Depends(principal_from_request),
    connection: Connection = Depends(get_connection, scope="function"),
):
    """Return only the caller's own recent governed-resource work.

    This is not an audit-trail endpoint: it contains no audit snapshots,
    reasons, other actors, or resources the caller can no longer view.
    """
    from .application_configuration import recent_since_default
    from .application_settings import cache
    if since is None:
        since = recent_since_default(cache.for_connection(connection)["DASHBOARD_RECENT_DAYS"])
    return list(connection.execute(
        """WITH governed_resource_events AS (
               SELECT DISTINCT ON (event.entity_type,event.entity_id,event.operation)
                      event.id,event.entity_type,event.entity_id,event.operation,
                      event.occurred_at
                 FROM event_history AS event
                WHERE event.actor_user_id=%s
                  AND event.entity_type IN ('aggregation','record')
                  AND event.operation IN ('CREATE','UPDATE')
                  AND (%s::timestamptz IS NULL OR event.occurred_at >= %s)
                ORDER BY event.entity_type,event.entity_id,event.operation,
                         event.occurred_at DESC,event.id DESC
           ), content_view_targets AS (
               SELECT event.id,'record'::text AS entity_type,
                      component.record_id AS entity_id,event.operation,event.occurred_at
                 FROM event_history event
                 JOIN digital_components component ON component.id=event.entity_id
                WHERE event.actor_user_id=%s
                  AND event.entity_type='digital_component'
                  AND event.operation='CONTENT_VIEWED'
                  AND (%s::timestamptz IS NULL OR event.occurred_at >= %s)
               UNION ALL
               SELECT event.id,'aggregation'::text AS entity_type,
                      record.aggregation_id AS entity_id,event.operation,event.occurred_at
                 FROM event_history event
                 JOIN digital_components component ON component.id=event.entity_id
                 JOIN records record ON record.id=component.record_id
                WHERE event.actor_user_id=%s
                  AND event.entity_type='digital_component'
                  AND event.operation='CONTENT_VIEWED'
                  AND (%s::timestamptz IS NULL OR event.occurred_at >= %s)
           ), content_view_events AS (
               SELECT DISTINCT ON (entity_type,entity_id)
                      id,entity_type,entity_id,operation,occurred_at
                 FROM content_view_targets
                ORDER BY entity_type,entity_id,occurred_at DESC,id DESC
           ), latest_resource_events AS (
               SELECT * FROM governed_resource_events
               UNION ALL
               SELECT * FROM content_view_events
           ), matching_events AS (
               SELECT event.entity_type,event.entity_id,event.operation,event.occurred_at,
                      row_number() OVER (
                          PARTITION BY event.entity_type, event.operation
                          ORDER BY event.occurred_at DESC, event.id DESC
                      ) AS position
                 FROM latest_resource_events AS event
                WHERE (
                      (event.entity_type='aggregation' AND EXISTS (
                          SELECT 1 FROM aggregations resource
                           WHERE resource.id=event.entity_id
                             AND current_user_can_view_aggregation(resource.id)
                      ))
                      OR
                      (event.entity_type='record' AND EXISTS (
                          SELECT 1 FROM records resource
                           WHERE resource.id=event.entity_id
                             AND current_user_can_view_record(resource.id)
                      ))
                  )
           )
           SELECT entity_type, entity_id, operation, occurred_at
             FROM matching_events
            WHERE position <= %s
            ORDER BY occurred_at DESC, entity_type, entity_id""",
        (
            principal.user_id, since, since,
            principal.user_id, since, since,
            principal.user_id, since, since,
            limit,
        ),
    ).fetchall())


@router.post("/logout", status_code=204)
def logout(response: Response, principal: Principal = Depends(principal_from_request), connection: Connection = Depends(get_connection, scope="function")):
    session = connection.execute(
        """UPDATE login_sessions SET revoked_at=CURRENT_TIMESTAMP, revoked_by=%s
             WHERE id=%s
         RETURNING id, client_ip, user_agent, date_created, last_seen_at,
                   expires_at, absolute_expires_at, revoked_at""",
        (principal.user_id, principal.session_id),
    ).fetchone()
    _append_event(connection, principal.user_id, "SESSION_REVOKED", {
        **_session_snapshot(session),
        "revocation_scope": "current",
        "revocation_reason": "logout",
        "sessions_revoked": 1,
    })
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/change-password", status_code=204)
def change_password(payload: ChangePasswordRequest, principal: Principal = Depends(principal_from_request), connection: Connection = Depends(get_connection, scope="function")):
    credential = connection.execute("SELECT password_hash FROM user_credentials WHERE user_id=%s", (principal.user_id,)).fetchone()
    try:
        valid = password_hasher.verify(credential["password_hash"], payload.current_password)
    except (VerifyMismatchError, InvalidHashError):
        valid = False
    if not valid:
        raise HTTPException(status_code=400, detail="current password is incorrect")
    try:
        validate_password(payload.new_password, settings_cache.for_connection(connection))
        new_hash = hash_password(payload.new_password)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    connection.execute(
        "UPDATE user_credentials SET password_hash=%s, must_change_password=false, temporary_expires_at=NULL, password_changed_at=CURRENT_TIMESTAMP, date_updated=CURRENT_TIMESTAMP WHERE user_id=%s",
        (new_hash, principal.user_id),
    )
    other_sessions = connection.execute(
        """UPDATE login_sessions SET revoked_at=CURRENT_TIMESTAMP, revoked_by=%s
             WHERE user_id=%s AND id<>%s AND revoked_at IS NULL
         RETURNING id, client_ip, user_agent, date_created, last_seen_at,
                   expires_at, absolute_expires_at, revoked_at""",
        (principal.user_id, principal.user_id, principal.session_id),
    ).fetchall()
    _append_event(connection, principal.user_id, "PASSWORD_CHANGED", {
        "revocation_reason": "password_changed",
        "sessions_revoked": len(other_sessions),
        "sessions": [_session_snapshot(session) for session in other_sessions],
    })
    return Response(status_code=204)


@router.get(
    "/sessions", response_model=list[LoginSessionRead],
    dependencies=[Depends(require_identity_sessions_admin)],
)
def list_sessions(
    user_id: int | None = None,
    limit: int | None = Query(None, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(principal_from_request),
    connection: Connection = Depends(get_connection, scope="function"),
):
    target_user_id = user_id
    pagination_sql = "" if limit is None else " LIMIT %s OFFSET %s"
    parameters: list[Any] = [principal.session_id, target_user_id, target_user_id]
    if limit is not None:
        parameters.extend((limit, offset))
    return list(connection.execute(
        """
        SELECT s.id, s.user_id, u.name AS user_name, u.email AS user_email, u.account_type,
               s.date_created, s.last_seen_at, s.expires_at, s.absolute_expires_at,
               s.revoked_at, host(s.client_ip) AS client_ip, s.user_agent,
               (s.id=%s) AS is_current,
               CASE WHEN s.revoked_at IS NOT NULL THEN 'revoked'
                    WHEN s.expires_at <= CURRENT_TIMESTAMP OR s.absolute_expires_at <= CURRENT_TIMESTAMP THEN 'expired'
                    ELSE 'active' END AS status
        FROM login_sessions s JOIN users u ON u.id=s.user_id
        WHERE (%s::bigint IS NULL OR s.user_id=%s) ORDER BY s.date_created DESC
        """ + pagination_sql, parameters
    ).fetchall())


@router.get("/sessions/page", dependencies=[Depends(require_identity_sessions_admin)])
def page_sessions(
    user_id: int | None = None,
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
    query: str = Query("", max_length=200),
    session_status: str = Query("all", pattern="^(all|active|expired|revoked)$"),
    sort_by: str = Query("date_created", pattern="^(date_created|last_seen_at|expires_at|status|client_ip)$"),
    descending: bool = True,
    date_field: str = Query("date_created", pattern="^(date_created|last_seen_at)$"),
    from_timestamp: datetime | None = None,
    until_timestamp: datetime | None = None,
    principal: Principal = Depends(principal_from_request),
    connection: Connection = Depends(get_connection, scope="function"),
):
    if limit is None:
        from .application_settings import cache
        limit = min(cache.for_connection(connection)["USER_DETAILS_SESSION_LIMIT"],50) if user_id is not None else 20
    sort_columns = {
        "date_created": "date_created", "last_seen_at": "last_seen_at",
        "expires_at": "expires_at", "status": "status", "client_ip": "client_ip",
    }
    normalized_query = query.strip()
    filters: list[str] = []
    parameters: list[Any] = []
    if user_id is not None:
        filters.append("user_id=%s")
        parameters.append(user_id)
    if normalized_query:
        filters.append(
            "(COALESCE(user_name,'') ILIKE %s OR COALESCE(user_email,'') ILIKE %s "
            "OR COALESCE(client_ip,'') ILIKE %s OR COALESCE(user_agent,'') ILIKE %s)"
        )
        parameters.extend((f"%{normalized_query}%",) * 4)
    if session_status != "all":
        filters.append("status=%s")
        parameters.append(session_status)
    if from_timestamp is not None:
        filters.append(f"{date_field}>=%s")
        parameters.append(from_timestamp)
    if until_timestamp is not None:
        filters.append(f"{date_field}<=%s")
        parameters.append(until_timestamp)
    source = """
        SELECT s.id, s.user_id, u.name AS user_name, u.email AS user_email, u.account_type,
               s.date_created, s.last_seen_at, s.expires_at, s.absolute_expires_at,
               s.revoked_at, host(s.client_ip) AS client_ip, s.user_agent,
               (s.id=%s) AS is_current,
               CASE WHEN s.revoked_at IS NOT NULL THEN 'revoked'
                    WHEN s.expires_at <= CURRENT_TIMESTAMP OR s.absolute_expires_at <= CURRENT_TIMESTAMP THEN 'expired'
                    ELSE 'active' END AS status
          FROM login_sessions s JOIN users u ON u.id=s.user_id
    """
    where_sql = " AND ".join(filters) if filters else "TRUE"
    base_parameters = [principal.session_id, *parameters]
    total = connection.execute(
        f"SELECT count(*) AS total FROM ({source}) session_source WHERE {where_sql}",
        base_parameters,
    ).fetchone()["total"]
    direction = "DESC" if descending else "ASC"
    items = list(connection.execute(
        f"SELECT * FROM ({source}) session_source WHERE {where_sql} "
        f"ORDER BY {sort_columns[sort_by]} {direction}, id {direction} LIMIT %s OFFSET %s",
        [*base_parameters, limit, offset],
    ).fetchall())
    active = connection.execute(
        f"SELECT count(*) AS total FROM ({source}) session_source WHERE {where_sql} AND status='active'",
        base_parameters,
    ).fetchone()["total"]
    return {
        "items": items, "total": int(total), "active": int(active),
        "limit": limit, "offset": offset,
    }


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(session_id: int, request: Request, principal: Principal = Depends(principal_from_request), connection: Connection = Depends(get_connection, scope="function")):
    target = connection.execute("SELECT user_id FROM login_sessions WHERE id=%s", (session_id,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="session not found")
    if target["user_id"] != principal.user_id:
        require_identity_sessions_admin(request)
    session = connection.execute(
        """UPDATE login_sessions
              SET revoked_at=COALESCE(revoked_at,CURRENT_TIMESTAMP), revoked_by=%s
            WHERE id=%s
        RETURNING id, client_ip, user_agent, date_created, last_seen_at,
                  expires_at, absolute_expires_at, revoked_at""",
        (principal.user_id, session_id),
    ).fetchone()
    _append_event(connection, target["user_id"], "SESSION_REVOKED", {
        **_session_snapshot(session),
        "revocation_scope": "individual",
        "revocation_reason": "administrator_revocation" if target["user_id"] != principal.user_id else "user_revocation",
        "sessions_revoked": 1,
    })
    return Response(status_code=204)


@router.delete("/users/{user_id}/sessions", status_code=204, dependencies=[Depends(require_identity_sessions_admin)])
def revoke_user_sessions(user_id: int, principal: Principal = Depends(principal_from_request), connection: Connection = Depends(get_connection, scope="function")):
    revoke_sessions_for_user(
        connection, user_id, revoked_by=principal.user_id,
        reason="administrator_revocation",
    )
    return Response(status_code=204)


@router.post("/users/{user_id}/temporary-password", dependencies=[Depends(require_identity_sessions_admin)])
def issue_temporary_password(user_id: int, principal: Principal = Depends(principal_from_request), connection: Connection = Depends(get_connection, scope="function")):
    user = connection.execute("SELECT id, email, account_type FROM users WHERE id=%s", (user_id,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    if user["account_type"] != "person" or not user["email"]:
        raise HTTPException(status_code=422, detail="local passwords require a person account with an email address")
    password = temporary_password(settings_cache.for_connection(connection))
    password_hash = hash_password(password)
    temporary_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    connection.execute(
        """
        INSERT INTO user_credentials (user_id,password_hash,must_change_password,temporary_expires_at)
        VALUES (%s,%s,true,%s)
        ON CONFLICT (user_id) DO UPDATE SET
          password_hash=EXCLUDED.password_hash, must_change_password=true,
          temporary_expires_at=EXCLUDED.temporary_expires_at,
          password_changed_at=CURRENT_TIMESTAMP, failed_attempt_count=0,
          locked_until=NULL, date_updated=CURRENT_TIMESTAMP
        """, (user_id, password_hash, temporary_expires_at)
    )
    revoked = revoke_sessions_for_user(
        connection, user_id, revoked_by=principal.user_id, reason="password_reset",
    )
    _append_event(connection, user_id, "PASSWORD_RESET", {
        "temporary": True,
        "expires_at": temporary_expires_at.isoformat(),
        "sessions_revoked": revoked,
    })
    return {"temporary_password": password, "expires_at": temporary_expires_at}
