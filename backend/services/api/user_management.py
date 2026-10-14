import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from psycopg import Connection, sql

from .crud import create_row, delete_row, get_or_404, list_rows, update_row
from .concurrency import expected_version
from .application_settings import cache as settings_cache
from .database import get_connection
from .entity_localization import (
    localize_rows,
    localize_search_result,
    preferred_language,
    sort_localized_rows,
)
from .schemas import (
    EventHistoryRead,
    DeletionPreflightRead,
    OrgUnitCreate,
    OrgUnitRead,
    OrgUnitUpdate,
    RoleCreate,
    RoleRead,
    RoleUpdate,
    ProfileRead,
    ProfileReferenceRead,
    SearchRequest,
    SearchResponse,
    ServiceCredentialCreate,
    ServiceCredentialCreated,
    ServiceCredentialPage,
    ServiceCredentialRead,
    ServiceCredentialRotate,
    TextIndexerCreate,
    TextIndexerBackfillRequest,
    TextIndexerCreated,
    TextIndexerDetail,
    TextIndexerRead,
    UserCreate,
    UserRead,
    UserRoleAssignmentCreate,
    UserRoleAssignmentRead,
    UserRoleAssignmentUpdate,
    UserUpdate,
)
from .search import search_rows
from .authentication import revoke_sessions_for_user
from .security_level_events import append_security_level_event, validate_security_level_change
from .authorization_admin import (
    _effective_people_for_privilege, _reason, _universal_custodian_count,
    assert_continuity,
)
from .authorization_policy import (
    require_audit_view,
    require_identity_users_admin,
    require_identity_text_indexers_admin,
    require_organization_admin,
)
from .permanent_deletion import analyze_deletion, permanently_delete
from .continuity_lock import acquire_continuity_lock
from .text_indexing_maintenance import (
    failure_diagnostics as text_indexing_failure_diagnostics,
    readiness as text_indexing_readiness,
    reconcile as reconcile_text_indexing,
    retry_failed as retry_failed_text_indexing,
)
from .http_cache import apply_collection_etag


router = APIRouter(prefix="/api/v1")

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _service_account(connection: Connection, user_id: int, *, active: bool = False):
    account = get_or_404(connection, "users", user_id)
    if account["account_type"] != "service":
        raise HTTPException(status_code=422, detail="API credentials require a service account")
    if active and account["status"] != "active":
        raise HTTPException(status_code=409, detail="service account must be active")
    return account


def _is_text_indexer_account(connection: Connection, user_id: int) -> bool:
    return bool(connection.execute(
        """SELECT EXISTS(
                 SELECT 1 FROM user_role_assignments assignment
                 JOIN roles role ON role.id=assignment.role_id
                WHERE assignment.user_id=%s
                  AND role.code='text-indexer-service' AND role.is_system
             ) AS value""",
        (user_id,),
    ).fetchone()["value"])


def _text_indexer_account(connection: Connection, user_id: int, *, active: bool = False):
    account = _service_account(connection, user_id, active=active)
    if not _is_text_indexer_account(connection, user_id):
        raise HTTPException(status_code=404, detail="text indexer not found")
    return account


def _reject_text_indexer_account(connection: Connection, user_id: int) -> None:
    if _is_text_indexer_account(connection, user_id):
        raise HTTPException(
            status_code=409,
            detail="text-indexer identities must be managed through the dedicated Text Indexers workflow",
        )


def _reject_text_indexer_assignment(connection: Connection, assignment_id: int) -> None:
    row = connection.execute(
        """SELECT assignment.user_id,role.code,role.is_system
             FROM user_role_assignments assignment
             JOIN roles role ON role.id=assignment.role_id
            WHERE assignment.id=%s""",
        (assignment_id,),
    ).fetchone()
    if row and row["code"] == "text-indexer-service" and row["is_system"]:
        raise HTTPException(
            status_code=409,
            detail="the protected text-indexer role assignment is managed by the dedicated Text Indexers workflow",
        )


def _text_indexer_rows(connection: Connection, *, user_id: int | None = None):
    parameters: tuple[int, ...] = (user_id,) if user_id is not None else ()
    user_filter = "AND account.id=%s" if user_id is not None else ""
    return connection.execute(
        f"""SELECT account.*,
                   count(DISTINCT credential.id)::integer AS credential_count,
                   count(DISTINCT credential.id) FILTER (
                       WHERE credential.status='active' AND credential.expires_at>CURRENT_TIMESTAMP
                   )::integer AS active_credential_count,
                   max(credential.last_used_at) AS last_used_at
              FROM users account
              JOIN user_role_assignments assignment ON assignment.user_id=account.id
              JOIN roles role ON role.id=assignment.role_id
              LEFT JOIN service_account_credentials credential
                     ON credential.service_user_id=account.id
             WHERE account.account_type='service'
               AND role.code='text-indexer-service' AND role.is_system
               {user_filter}
             GROUP BY account.id
             ORDER BY account.name,account.id""",
        parameters,
    ).fetchall()


def _list_service_credentials(connection: Connection, user_id: int) -> list[dict]:
    rows = connection.execute(
        """SELECT credential.*, creator.name AS created_by_name
             FROM service_account_credentials credential
             LEFT JOIN users creator ON creator.id=credential.created_by_user_id
            WHERE credential.service_user_id=%s
            ORDER BY credential.date_created DESC,credential.id DESC""",
        (user_id,),
    ).fetchall()
    return [_credential_result(row) for row in rows]


def _list_service_credentials_page(
    connection: Connection, user_id: int, *, history: str, limit: int, offset: int,
) -> dict:
    predicates = {
        "all": "TRUE",
        "usable": "credential.status='active' AND credential.expires_at>CURRENT_TIMESTAMP",
        "history": "credential.status='revoked' OR credential.expires_at<=CURRENT_TIMESTAMP",
    }
    predicate = predicates[history]
    total = connection.execute(
        f"""SELECT count(*) AS value FROM service_account_credentials credential
             WHERE credential.service_user_id=%s AND ({predicate})""",
        (user_id,),
    ).fetchone()["value"]
    rows = connection.execute(
        f"""SELECT credential.*, creator.name AS created_by_name
               FROM service_account_credentials credential
               LEFT JOIN users creator ON creator.id=credential.created_by_user_id
              WHERE credential.service_user_id=%s AND ({predicate})
              ORDER BY credential.date_created DESC,credential.id DESC
              LIMIT %s OFFSET %s""",
        (user_id, limit, offset),
    ).fetchall()
    return {
        "items": [_credential_result(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "retention_days": settings_cache.for_connection(connection)["TEXT_INDEXER_CREDENTIAL_HISTORY_RETENTION_DAYS"],
    }


def _credential_row(connection: Connection, user_id: int, credential_id: int):
    row = connection.execute(
        "SELECT * FROM service_account_credentials WHERE id=%s AND service_user_id=%s",
        (credential_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="API credential not found")
    return row


def _credential_result(row: dict) -> dict:
    allowed = {
        "id", "service_user_id", "name", "credential_identifier", "status",
        "date_created", "expires_at", "last_used_at", "last_worker_id",
        "date_revoked", "created_by_user_id", "created_by_name", "api_key",
    }
    value = {key: item for key, item in dict(row).items() if key in allowed}
    value.setdefault("created_by_name", None)
    if value["status"] == "active":
        now = datetime.now(value["expires_at"].tzinfo)
        if value["expires_at"] <= now:
            value["status"] = "expired"
        elif value["expires_at"] <= now + timedelta(days=7):
            value["status"] = "expiring"
    return value


def _issue_service_credential(connection: Connection, request: Request, user_id: int, payload: ServiceCredentialCreate) -> dict:
    _text_indexer_account(connection, user_id, active=True)
    identifier = "".join(secrets.choice(_CROCKFORD) for _ in range(26))
    secret = secrets.token_urlsafe(32)
    principal = request.state.principal
    row = connection.execute(
        """INSERT INTO service_account_credentials(
               service_user_id,name,credential_identifier,secret_hash,expires_at,created_by_user_id)
             VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
        (user_id, payload.name, identifier, hashlib.sha256(secret.encode("ascii")).hexdigest(),
         payload.expires_at, principal.user_id),
    ).fetchone()
    connection.execute(
        "SELECT append_domain_event('user',%s,'SERVICE_API_CREDENTIAL_CREATED',%s::jsonb,NULL)",
        (user_id, json.dumps({"credential_identifier": identifier, "expires_at": payload.expires_at.isoformat()})),
    )
    row = dict(row); row["created_by_name"] = principal.name; row["api_key"] = f"wti_{identifier}.{secret}"
    return _credential_result(row)


def _rotate_service_credential(
    connection: Connection, request: Request, user_id: int, credential_id: int,
    payload: ServiceCredentialRotate,
) -> dict:
    old = _credential_row(connection, user_id, credential_id)
    if old["status"] != "active" or old["expires_at"] <= datetime.now(old["expires_at"].tzinfo):
        raise HTTPException(status_code=409, detail="only an active credential can be rotated")
    if payload.overlap_until is None:
        connection.execute(
            """UPDATE service_account_credentials SET status='revoked',date_revoked=CURRENT_TIMESTAMP,
                      revoked_by_user_id=%s WHERE id=%s""",
            (request.state.principal.user_id, credential_id),
        )
    else:
        connection.execute(
            "UPDATE service_account_credentials SET expires_at=LEAST(expires_at,%s) WHERE id=%s",
            (payload.overlap_until, credential_id),
        )
    result = _issue_service_credential(connection, request, user_id, payload)
    connection.execute(
        "SELECT append_domain_event('user',%s,'SERVICE_API_CREDENTIAL_ROTATED',%s::jsonb,NULL)",
        (user_id, json.dumps({"old_credential_identifier": old["credential_identifier"],
                              "new_credential_identifier": result["credential_identifier"],
                              "overlap_until": payload.overlap_until.isoformat() if payload.overlap_until else None})),
    )
    return result


def _revoke_service_credential(
    connection: Connection, request: Request, user_id: int, credential_id: int,
) -> None:
    row = _credential_row(connection, user_id, credential_id)
    if row["status"] != "active":
        raise HTTPException(status_code=409, detail="credential is already revoked")
    connection.execute(
        """UPDATE service_account_credentials SET status='revoked',date_revoked=CURRENT_TIMESTAMP,
                  revoked_by_user_id=%s WHERE id=%s""",
        (request.state.principal.user_id, credential_id),
    )
    connection.execute(
        "SELECT append_domain_event('user',%s,'SERVICE_API_CREDENTIAL_REVOKED',%s::jsonb,NULL)",
        (user_id, json.dumps({"credential_identifier": row["credential_identifier"]})),
    )


def _change_lifecycle(
    connection: Connection, table: str, entity_id: int, version: int,
    *, active: bool,
):
    return _update_lifecycle_dates(
        connection, table, entity_id, version,
        {"date_deactivated": "NULL" if active else "clock_timestamp()"},
    )


def _update_lifecycle_dates(
    connection: Connection,
    table: str,
    entity_id: int,
    version: int,
    assignments: dict[str, str],
):
    if table not in {"org_units", "users", "roles"}:
        raise ValueError("unsupported lifecycle table")
    allowed_columns = {"date_deactivated", "date_suspended"}
    if not assignments or not set(assignments).issubset(allowed_columns):
        raise ValueError("unsupported lifecycle assignment")
    allowed_expressions = {"NULL", "clock_timestamp()"}
    if not set(assignments.values()).issubset(allowed_expressions):
        raise ValueError("unsupported lifecycle expression")
    updates = sql.SQL(", ").join(
        sql.Identifier(column) + sql.SQL(" = ") + sql.SQL(expression)
        for column, expression in assignments.items()
    )
    query = sql.SQL(
        "UPDATE {} SET {} WHERE id = %s AND version = %s RETURNING *"
    ).format(sql.Identifier(table), updates)
    changed = connection.execute(query, (entity_id, version)).fetchone()
    if changed is None:
        current = get_or_404(connection, table, entity_id)
        raise HTTPException(
            status_code=412,
            detail={"message": "entity has changed", "current_version": current["version"]},
        )
    return changed


def _continuity_snapshot(connection: Connection) -> tuple[int, int]:
    return (
        _effective_people_for_privilege(connection, "authorization.administer"),
        _universal_custodian_count(connection),
    )


def _assert_snapshot_continuity(connection: Connection, snapshot: tuple[int, int]) -> None:
    assert_continuity(connection, snapshot[0], snapshot[1])


def _history(connection: Connection, entity_type: str, entity_id: int):
    return list_rows(
        connection,
        "event_history",
        limit=500,
        offset=0,
        filters={"entity_type": entity_type, "entity_id": entity_id},
        order_by=("occurred_at", "id"),
        descending=True,
    )


@router.get("/profiles/reference", response_model=list[ProfileReferenceRead], tags=["profiles"])
def list_profile_references(
    request: Request,
    response: Response,
    limit: int = Query(default=500, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    """Profile identity and unrestricted-profile warning state for role selectors."""
    rows = list(connection.execute(
        """SELECT profile.*,
                  ((SELECT count(*) FROM profile_privileges membership
                     WHERE membership.profile_id=profile.id)
                   = (SELECT count(*) FROM privileges)
                   AND (SELECT count(*) FROM privileges)>0) AS grants_all_privileges
             FROM profiles profile
            ORDER BY profile.name,profile.id LIMIT %s OFFSET %s""",
        (limit, offset),
    ).fetchall())
    localized = sort_localized_rows(
        localize_rows(rows, preferred_language(connection, request), "name"), "name"
    )
    return apply_collection_etag(request, response, localized) or localized


@router.post("/org-units", response_model=OrgUnitRead, status_code=201, tags=["org units"], dependencies=[Depends(require_organization_admin)])
def create_org_unit(payload: OrgUnitCreate, connection: Connection = Depends(get_connection, scope="function")):
    return create_row(connection, "org_units", payload.model_dump())


@router.get("/org-units", response_model=list[OrgUnitRead], tags=["org units"])
def list_org_units(
    request: Request,
    response: Response,
    parent_org_unit_id: int | None = None,
    unit_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    rows = list_rows(
        connection,
        "org_units",
        limit=limit,
        offset=offset,
        filters={"parent_org_unit_id": parent_org_unit_id, "status": unit_status},
    )
    localized = sort_localized_rows(localize_rows(rows, preferred_language(connection, request), "name"), "name")
    return apply_collection_etag(request, response, localized) or localized


@router.post("/org-units/search", response_model=None, tags=["org units"])
def search_org_units(
    request: Request, payload: SearchRequest,
    connection: Connection = Depends(get_connection, scope="function"),
):
    language_tag = preferred_language(connection, request)
    return localize_search_result(
        search_rows(
            connection, "org_units", payload,
            endpoint="/api/v1/org-units/search",
            localized_sort_language=language_tag,
        ),
        language_tag, "name",
    )


@router.get("/org-units/{org_unit_id}", response_model=OrgUnitRead, tags=["org units"])
def get_org_unit(org_unit_id: int, request: Request, connection: Connection = Depends(get_connection, scope="function")):
    return localize_rows([get_or_404(connection, "org_units", org_unit_id)], preferred_language(connection, request), "name")[0]


@router.get("/org-units/{org_unit_id}/deletion-preflight", response_model=DeletionPreflightRead, tags=["org units"], dependencies=[Depends(require_organization_admin)])
def preflight_org_unit_deletion(request: Request, org_unit_id: int, connection: Connection = Depends(get_connection, scope="function")):
    principal = getattr(request.state, "principal", None)
    return analyze_deletion(connection, "org_unit", org_unit_id, actor_user_id=principal.user_id if principal else None)


@router.delete("/org-units/{org_unit_id}", status_code=204, tags=["org units"], dependencies=[Depends(require_organization_admin)])
def permanently_delete_org_unit(request: Request, org_unit_id: int, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    permanently_delete(connection, request, "org_unit", org_unit_id, version)
    return Response(status_code=204)


@router.patch("/org-units/{org_unit_id}", response_model=OrgUnitRead, tags=["org units"], dependencies=[Depends(require_organization_admin)])
def update_org_unit(
    org_unit_id: int,
    payload: OrgUnitUpdate,
    version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    acquire_continuity_lock(connection)
    snapshot = _continuity_snapshot(connection)
    changed = update_row(
        connection, "org_units", org_unit_id, payload.model_dump(exclude_unset=True), version
    )
    _assert_snapshot_continuity(connection, snapshot)
    return changed


@router.post("/org-units/{org_unit_id}/deactivate", response_model=OrgUnitRead, tags=["org units"], dependencies=[Depends(require_organization_admin)])
def explicitly_deactivate_org_unit(org_unit_id: int, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    acquire_continuity_lock(connection)
    snapshot = _continuity_snapshot(connection)
    changed = _change_lifecycle(connection, "org_units", org_unit_id, version, active=False)
    _assert_snapshot_continuity(connection, snapshot)
    return changed


@router.post("/org-units/{org_unit_id}/activate", response_model=OrgUnitRead, tags=["org units"], dependencies=[Depends(require_organization_admin)])
def activate_org_unit(org_unit_id: int, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    return _change_lifecycle(connection, "org_units", org_unit_id, version, active=True)


@router.get(
    "/org-units/{org_unit_id}/history",
    response_model=list[EventHistoryRead],
    tags=["event history"],
    dependencies=[Depends(require_audit_view)],
)
def get_org_unit_history(org_unit_id: int, connection: Connection = Depends(get_connection, scope="function")):
    return _history(connection, "org_unit", org_unit_id)


@router.get(
    "/text-indexers", response_model=list[TextIndexerRead], tags=["text indexers"],
    dependencies=[Depends(require_identity_text_indexers_admin)],
)
def list_text_indexers(connection: Connection = Depends(get_connection, scope="function")):
    return _text_indexer_rows(connection)


@router.post(
    "/text-indexers", response_model=TextIndexerCreated, status_code=201,
    tags=["text indexers"], dependencies=[Depends(require_identity_text_indexers_admin)],
)
def create_text_indexer(
    request: Request, payload: TextIndexerCreate,
    connection: Connection = Depends(get_connection, scope="function"),
):
    account = create_row(connection, "users", {
        "name": payload.name,
        "external_id": payload.external_id,
        "account_type": "service",
    })
    role = connection.execute(
        "SELECT id FROM roles WHERE code='text-indexer-service' AND is_system FOR SHARE"
    ).fetchone()
    if role is None:
        raise HTTPException(status_code=503, detail="protected text-indexer service role is unavailable")
    create_row(connection, "user_role_assignments", {
        "user_id": account["id"], "role_id": role["id"],
    })
    credential = _issue_service_credential(
        connection, request, account["id"],
        ServiceCredentialCreate(name=payload.credential_name, expires_at=payload.expires_at),
    )
    created = _text_indexer_rows(connection, user_id=account["id"])[0]
    return {"text_indexer": created, "credential": credential}


@router.get(
    "/text-indexers/health", response_model=None, tags=["text indexers"],
    dependencies=[Depends(require_identity_text_indexers_admin)],
)
def get_text_indexers_health(
    connection: Connection = Depends(get_connection, scope="function"),
):
    snapshot = text_indexing_readiness(connection)
    return {
        "status": "ready" if snapshot["ready_for_search"] else "attention_required",
        "observed_at": datetime.now().astimezone(),
        **snapshot,
    }


@router.get(
    "/text-indexers/diagnostics", response_model=None, tags=["text indexers"],
    dependencies=[Depends(require_identity_text_indexers_admin)],
)
def get_text_indexer_diagnostics(
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    return text_indexing_failure_diagnostics(connection, limit, offset)


@router.post(
    "/text-indexers/backfill", response_model=None, tags=["text indexers"],
    dependencies=[Depends(require_identity_text_indexers_admin)],
)
def queue_text_indexers_backfill(
    payload: TextIndexerBackfillRequest,
    connection: Connection = Depends(get_connection, scope="function"),
):
    result = reconcile_text_indexing(connection, payload.batch_size, False)
    return {"batch_size": payload.batch_size, **result}


@router.post(
    "/text-indexers/retry-failed", response_model=None, tags=["text indexers"],
    dependencies=[Depends(require_identity_text_indexers_admin)],
)
def retry_failed_text_indexer_documents(
    payload: TextIndexerBackfillRequest,
    connection: Connection = Depends(get_connection, scope="function"),
):
    result = retry_failed_text_indexing(connection, payload.batch_size, False)
    return {"batch_size": payload.batch_size, **result}


@router.get(
    "/text-indexers/{user_id}", response_model=TextIndexerDetail,
    tags=["text indexers"], dependencies=[Depends(require_identity_text_indexers_admin)],
)
def get_text_indexer(user_id: int, connection: Connection = Depends(get_connection, scope="function")):
    rows = _text_indexer_rows(connection, user_id=user_id)
    if not rows:
        raise HTTPException(status_code=404, detail="text indexer not found")
    return dict(rows[0])


@router.get(
    "/text-indexers/{user_id}/credentials", response_model=ServiceCredentialPage,
    tags=["text indexers"], dependencies=[Depends(require_identity_text_indexers_admin)],
)
def list_text_indexer_credentials(
    user_id: int,
    history: str = Query(default="all", pattern="^(all|usable|history)$"),
    limit: int = Query(default=5, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _text_indexer_account(connection, user_id)
    return _list_service_credentials_page(
        connection, user_id, history=history, limit=limit, offset=offset,
    )


@router.post(
    "/text-indexers/{user_id}/credentials", response_model=ServiceCredentialCreated,
    status_code=201, tags=["text indexers"],
    dependencies=[Depends(require_identity_text_indexers_admin)],
)
def create_text_indexer_credential(
    request: Request, user_id: int, payload: ServiceCredentialCreate,
    connection: Connection = Depends(get_connection, scope="function"),
):
    return _issue_service_credential(connection, request, user_id, payload)


@router.post(
    "/text-indexers/{user_id}/credentials/{credential_id}/rotate",
    response_model=ServiceCredentialCreated, status_code=201, tags=["text indexers"],
    dependencies=[Depends(require_identity_text_indexers_admin)],
)
def rotate_text_indexer_credential(
    request: Request, user_id: int, credential_id: int, payload: ServiceCredentialRotate,
    connection: Connection = Depends(get_connection, scope="function"),
):
    _text_indexer_account(connection, user_id, active=True)
    return _rotate_service_credential(connection, request, user_id, credential_id, payload)


@router.post(
    "/text-indexers/{user_id}/credentials/{credential_id}/revoke", status_code=204,
    tags=["text indexers"], dependencies=[Depends(require_identity_text_indexers_admin)],
)
def revoke_text_indexer_credential(
    request: Request, user_id: int, credential_id: int,
    connection: Connection = Depends(get_connection, scope="function"),
):
    _text_indexer_account(connection, user_id)
    _revoke_service_credential(connection, request, user_id, credential_id)
    return Response(status_code=204)


@router.post(
    "/text-indexers/{user_id}/{action}", response_model=TextIndexerRead,
    tags=["text indexers"], dependencies=[Depends(require_identity_text_indexers_admin)],
)
def change_text_indexer_status(
    request: Request, user_id: int, action: str,
    version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _text_indexer_account(connection, user_id)
    if action not in {"activate", "suspend", "unsuspend"}:
        raise HTTPException(status_code=404, detail="text-indexer action not found")
    changed = _set_user_lifecycle(connection, request, user_id, version, action=action)
    return _text_indexer_rows(connection, user_id=changed["id"])[0]


@router.post("/users", response_model=UserRead, status_code=201, tags=["users"], dependencies=[Depends(require_identity_users_admin)])
def create_user(payload: UserCreate, connection: Connection = Depends(get_connection, scope="function")):
    return create_row(connection, "users", payload.model_dump())


@router.get("/users", response_model=list[UserRead], tags=["users"])
def list_users(
    request: Request,
    user_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    rows = list_rows(
        connection,
        "users",
        limit=limit,
        offset=offset,
        filters={"status": user_status},
    )
    return sort_localized_rows(localize_rows(rows, preferred_language(connection, request), "name"), "name")


@router.post("/users/search", response_model=None, tags=["users"])
def search_users(
    request: Request, payload: SearchRequest,
    connection: Connection = Depends(get_connection, scope="function"),
):
    language_tag = preferred_language(connection, request)
    return localize_search_result(
        search_rows(
            connection, "users", payload, endpoint="/api/v1/users/search",
            localized_sort_language=language_tag,
        ),
        language_tag, "name",
    )


@router.get("/users/{user_id}", response_model=UserRead, tags=["users"])
def get_user(user_id: int, request: Request, connection: Connection = Depends(get_connection, scope="function")):
    return localize_rows([get_or_404(connection, "users", user_id)], preferred_language(connection, request), "name")[0]


@router.get(
    "/users/{user_id}/api-credentials", response_model=list[ServiceCredentialRead],
    tags=["users"], dependencies=[Depends(require_identity_text_indexers_admin)],
)
def list_service_credentials(user_id: int, connection: Connection = Depends(get_connection, scope="function")):
    _text_indexer_account(connection, user_id)
    return _list_service_credentials(connection, user_id)


@router.post(
    "/users/{user_id}/api-credentials", response_model=ServiceCredentialCreated,
    status_code=201, tags=["users"], dependencies=[Depends(require_identity_text_indexers_admin)],
)
def create_service_credential(
    request: Request, user_id: int, payload: ServiceCredentialCreate,
    connection: Connection = Depends(get_connection, scope="function"),
):
    return _issue_service_credential(connection, request, user_id, payload)


@router.post(
    "/users/{user_id}/api-credentials/{credential_id}/rotate",
    response_model=ServiceCredentialCreated, status_code=201, tags=["users"],
    dependencies=[Depends(require_identity_text_indexers_admin)],
)
def rotate_service_credential(
    request: Request, user_id: int, credential_id: int, payload: ServiceCredentialRotate,
    connection: Connection = Depends(get_connection, scope="function"),
):
    return _rotate_service_credential(connection, request, user_id, credential_id, payload)


@router.post(
    "/users/{user_id}/api-credentials/{credential_id}/revoke", status_code=204,
    tags=["users"], dependencies=[Depends(require_identity_text_indexers_admin)],
)
def revoke_service_credential(
    request: Request, user_id: int, credential_id: int,
    connection: Connection = Depends(get_connection, scope="function"),
):
    _text_indexer_account(connection, user_id)
    _revoke_service_credential(connection, request, user_id, credential_id)
    return Response(status_code=204)


@router.get("/users/{user_id}/deletion-preflight", response_model=DeletionPreflightRead, tags=["users"], dependencies=[Depends(require_identity_users_admin)])
def preflight_user_deletion(request: Request, user_id: int, connection: Connection = Depends(get_connection, scope="function")):
    principal = getattr(request.state, "principal", None)
    return analyze_deletion(connection, "user", user_id, actor_user_id=principal.user_id if principal else None)


@router.delete("/users/{user_id}", status_code=204, tags=["users"], dependencies=[Depends(require_identity_users_admin)])
def permanently_delete_user(request: Request, user_id: int, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    _reject_text_indexer_account(connection, user_id)
    permanently_delete(connection, request, "user", user_id, version)
    return Response(status_code=204)


@router.patch("/users/{user_id}", response_model=UserRead, tags=["users"], dependencies=[Depends(require_identity_users_admin)])
def update_user(
    user_id: int,
    payload: UserUpdate,
    version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _reject_text_indexer_account(connection, user_id)
    acquire_continuity_lock(connection)
    snapshot = _continuity_snapshot(connection)
    changed = update_row(connection, "users", user_id, payload.model_dump(exclude_unset=True), version)
    _assert_snapshot_continuity(connection, snapshot)
    return changed


def _set_user_lifecycle(
    connection: Connection,
    request: Request,
    user_id: int,
    version: int,
    *,
    action: str,
):
    acquire_continuity_lock(connection)
    current = get_or_404(connection, "users", user_id)
    continuity_snapshot = _continuity_snapshot(connection)
    transitions = {
        "activate": ({"inactive"}, "active", None),
        "deactivate": ({"active", "suspended"}, "inactive", "user_deactivated"),
        "suspend": ({"active"}, "suspended", "user_suspended"),
        "unsuspend": ({"suspended"}, "active", None),
    }
    allowed, target_status, revocation_reason = transitions[action]
    if current["status"] not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"cannot {action} a user whose status is {current['status']}",
        )
    if target_status == "inactive":
        values = {
            "date_deactivated": "clock_timestamp()",
            "date_suspended": "NULL",
        }
    elif target_status == "suspended":
        values = {
            "date_deactivated": "NULL",
            "date_suspended": "clock_timestamp()",
        }
    else:
        values = {"date_deactivated": "NULL", "date_suspended": "NULL"}
    changed = _update_lifecycle_dates(
        connection, "users", user_id, version, values,
    )
    if revocation_reason:
        principal = getattr(request.state, "principal", None)
        revoke_sessions_for_user(
            connection,
            user_id,
            revoked_by=principal.user_id if principal else None,
            reason=revocation_reason,
        )
    _assert_snapshot_continuity(connection, continuity_snapshot)
    return changed


@router.post("/users/{user_id}/deactivate", response_model=UserRead, tags=["users"], dependencies=[Depends(require_identity_users_admin)])
def explicitly_deactivate_user(request: Request, user_id: int, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    _reject_text_indexer_account(connection, user_id)
    return _set_user_lifecycle(connection, request, user_id, version, action="deactivate")


@router.post("/users/{user_id}/activate", response_model=UserRead, tags=["users"], dependencies=[Depends(require_identity_users_admin)])
def activate_user(request: Request, user_id: int, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    _reject_text_indexer_account(connection, user_id)
    return _set_user_lifecycle(connection, request, user_id, version, action="activate")


@router.post("/users/{user_id}/suspend", response_model=UserRead, tags=["users"], dependencies=[Depends(require_identity_users_admin)])
def suspend_user(request: Request, user_id: int, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    _reject_text_indexer_account(connection, user_id)
    return _set_user_lifecycle(connection, request, user_id, version, action="suspend")


@router.post("/users/{user_id}/unsuspend", response_model=UserRead, tags=["users"], dependencies=[Depends(require_identity_users_admin)])
def unsuspend_user(request: Request, user_id: int, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    _reject_text_indexer_account(connection, user_id)
    return _set_user_lifecycle(connection, request, user_id, version, action="unsuspend")


@router.get(
    "/users/{user_id}/history",
    response_model=list[EventHistoryRead],
    tags=["event history"],
    dependencies=[Depends(require_audit_view)],
)
def get_user_history(user_id: int, connection: Connection = Depends(get_connection, scope="function")):
    return _history(connection, "user", user_id)


@router.post("/roles", response_model=RoleRead, status_code=201, tags=["roles"], dependencies=[Depends(require_organization_admin)])
def create_role(payload: RoleCreate, connection: Connection = Depends(get_connection, scope="function")):
    return create_row(connection, "roles", payload.model_dump())


@router.get("/roles", response_model=list[RoleRead], tags=["roles"])
def list_roles(
    request: Request,
    response: Response,
    org_unit_id: int | None = None,
    supervisor_role_id: int | None = None,
    role_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    include_system: bool = False,
    connection: Connection = Depends(get_connection, scope="function"),
):
    filters = {
        "org_unit_id": org_unit_id,
        "supervisor_role_id": supervisor_role_id,
        "status": role_status,
    }
    if not include_system:
        filters["is_system"] = False
    rows = list_rows(
        connection,
        "roles",
        limit=limit,
        offset=offset,
        filters=filters,
    )
    localized = sort_localized_rows(localize_rows(rows, preferred_language(connection, request), "name"), "name")
    return apply_collection_etag(request, response, localized) or localized


@router.post("/roles/search", response_model=None, tags=["roles"])
def search_roles(
    request: Request, payload: SearchRequest, include_system: bool = False,
    connection: Connection = Depends(get_connection, scope="function"),
):
    language_tag = preferred_language(connection, request)
    return localize_search_result(
        search_rows(
            connection, "roles", payload, endpoint="/api/v1/roles/search",
            include_system_roles=include_system,
            localized_sort_language=language_tag,
        ),
        language_tag, "name",
    )


@router.get("/roles/{role_id}", response_model=RoleRead, tags=["roles"])
def get_role(role_id: int, request: Request, connection: Connection = Depends(get_connection, scope="function")):
    return localize_rows([get_or_404(connection, "roles", role_id)], preferred_language(connection, request), "name")[0]


@router.get("/roles/{role_id}/deletion-preflight", response_model=DeletionPreflightRead, tags=["roles"], dependencies=[Depends(require_organization_admin)])
def preflight_role_deletion(request: Request, role_id: int, connection: Connection = Depends(get_connection, scope="function")):
    role = get_or_404(connection, "roles", role_id)
    if role["is_system"]:
        raise HTTPException(status_code=409, detail="built-in roles are read-only")
    principal = getattr(request.state, "principal", None)
    return analyze_deletion(connection, "role", role_id, actor_user_id=principal.user_id if principal else None)


@router.delete("/roles/{role_id}", status_code=204, tags=["roles"], dependencies=[Depends(require_organization_admin)])
def permanently_delete_role(request: Request, role_id: int, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    role = get_or_404(connection, "roles", role_id)
    if role["is_system"]:
        raise HTTPException(status_code=409, detail="built-in roles are read-only")
    permanently_delete(connection, request, "role", role_id, version)
    return Response(status_code=204)


@router.patch("/roles/{role_id}", response_model=RoleRead, tags=["roles"], dependencies=[Depends(require_organization_admin)])
def update_role(
    role_id: int,
    payload: RoleUpdate,
    request: Request,
    version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    acquire_continuity_lock(connection)
    existing = get_or_404(connection, "roles", role_id)
    if existing["is_system"]:
        raise HTTPException(status_code=409, detail="built-in roles are read-only")
    sensitive_authorization_change = (
        "profile_id" in payload.model_fields_set
        and payload.profile_id != existing["profile_id"]
    ) or (
        "is_information_governance" in payload.model_fields_set
        and payload.is_information_governance != existing["is_information_governance"]
    )
    clearance_change = (
        "security_level_id" in payload.model_fields_set
        and payload.security_level_id != existing["security_level_id"]
    )
    authorization_reason = _reason(request) if sensitive_authorization_change else None
    continuity_snapshot = (
        _continuity_snapshot(connection)
        if sensitive_authorization_change or clearance_change
        else None
    )
    new_level_id = payload.security_level_id if "security_level_id" in payload.model_fields_set else None
    reason, old_number, new_number = validate_security_level_change(
        connection, request, existing["security_level_id"], new_level_id
    )
    updated = update_row(connection, "roles", role_id, payload.model_dump(exclude_unset=True), version)
    append_security_level_event(
        connection, entity_type="role", entity_id=role_id,
        old_security_level_id=existing["security_level_id"], new_security_level_id=new_level_id,
        old_level_number=old_number, new_level_number=new_number, reason=reason,
    )
    if continuity_snapshot is not None:
        _assert_snapshot_continuity(connection, continuity_snapshot)
    if "profile_id" in payload.model_fields_set and payload.profile_id != existing["profile_id"]:
        connection.execute(
            "SELECT append_domain_event('role',%s,'PROFILE_ASSIGNED',%s::jsonb,%s)",
            (role_id, json.dumps({
                "old_profile_id": existing["profile_id"], "new_profile_id": payload.profile_id,
            }), authorization_reason),
        )
    if "is_information_governance" in payload.model_fields_set and payload.is_information_governance != existing["is_information_governance"]:
        connection.execute(
            "SELECT append_domain_event('role',%s,'GOVERNANCE_ROLE_CHANGED',%s::jsonb,%s)",
            (role_id, json.dumps({
                "old_value": existing["is_information_governance"],
                "new_value": payload.is_information_governance,
            }), authorization_reason),
        )
    return updated


@router.post("/roles/{role_id}/deactivate", response_model=RoleRead, tags=["roles"], dependencies=[Depends(require_organization_admin)])
def explicitly_deactivate_role(role_id: int, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    role = get_or_404(connection, "roles", role_id)
    if role["is_system"]:
        raise HTTPException(status_code=409, detail="built-in roles are read-only")
    acquire_continuity_lock(connection)
    snapshot = _continuity_snapshot(connection)
    changed = _change_lifecycle(connection, "roles", role_id, version, active=False)
    _assert_snapshot_continuity(connection, snapshot)
    return changed


@router.post("/roles/{role_id}/activate", response_model=RoleRead, tags=["roles"], dependencies=[Depends(require_organization_admin)])
def activate_role(role_id: int, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    role = get_or_404(connection, "roles", role_id)
    if role["is_system"]:
        raise HTTPException(status_code=409, detail="built-in roles are read-only")
    return _change_lifecycle(connection, "roles", role_id, version, active=True)


@router.get(
    "/roles/{role_id}/history",
    response_model=list[EventHistoryRead],
    tags=["event history"],
    dependencies=[Depends(require_audit_view)],
)
def get_role_history(role_id: int, connection: Connection = Depends(get_connection, scope="function")):
    return _history(connection, "role", role_id)


@router.post(
    "/user-role-assignments",
    response_model=UserRoleAssignmentRead,
    status_code=201,
    tags=["user role assignments"],
    dependencies=[Depends(require_organization_admin)],
)
def create_assignment(
    payload: UserRoleAssignmentCreate,
    connection: Connection = Depends(get_connection, scope="function"),
):
    role = get_or_404(connection, "roles", payload.role_id)
    if role["is_system"]:
        raise HTTPException(
            status_code=409,
            detail="built-in roles cannot be assigned through the ordinary role workflow",
        )
    return create_row(connection, "user_role_assignments", payload.model_dump())


@router.get(
    "/user-role-assignments",
    response_model=list[UserRoleAssignmentRead],
    tags=["user role assignments"],
    dependencies=[Depends(require_organization_admin)],
)
def list_assignments(
    user_id: int | None = None,
    role_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    return list_rows(
        connection,
        "user_role_assignments",
        limit=limit,
        offset=offset,
        filters={"user_id": user_id, "role_id": role_id},
    )


@router.post(
    "/user-role-assignments/search",
    response_model=None,
    tags=["user role assignments"],
    dependencies=[Depends(require_organization_admin)],
)
def search_assignments(
    payload: SearchRequest,
    connection: Connection = Depends(get_connection, scope="function"),
):
    return search_rows(connection, "user_role_assignments", payload, endpoint="/api/v1/user-role-assignments/search")


@router.get(
    "/user-role-assignments/{assignment_id}",
    response_model=UserRoleAssignmentRead,
    tags=["user role assignments"],
    dependencies=[Depends(require_organization_admin)],
)
def get_assignment(assignment_id: int, connection: Connection = Depends(get_connection, scope="function")):
    return get_or_404(connection, "user_role_assignments", assignment_id)


@router.patch(
    "/user-role-assignments/{assignment_id}",
    response_model=UserRoleAssignmentRead,
    tags=["user role assignments"],
    dependencies=[Depends(require_organization_admin)],
)
def update_assignment(
    assignment_id: int,
    payload: UserRoleAssignmentUpdate,
    version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _reject_text_indexer_assignment(connection, assignment_id)
    acquire_continuity_lock(connection)
    snapshot = _continuity_snapshot(connection)
    changed = update_row(
        connection,
        "user_role_assignments",
        assignment_id,
        payload.model_dump(exclude_unset=True),
        version,
    )
    _assert_snapshot_continuity(connection, snapshot)
    return changed


@router.delete(
    "/user-role-assignments/{assignment_id}",
    status_code=204,
    tags=["user role assignments"],
    dependencies=[Depends(require_organization_admin)],
)
def delete_assignment(assignment_id: int, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    _reject_text_indexer_assignment(connection, assignment_id)
    acquire_continuity_lock(connection)
    snapshot = _continuity_snapshot(connection)
    delete_row(connection, "user_role_assignments", assignment_id, version)
    _assert_snapshot_continuity(connection, snapshot)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/user-role-assignments/{assignment_id}/history",
    response_model=list[EventHistoryRead],
    tags=["event history"],
    dependencies=[Depends(require_audit_view)],
)
def get_assignment_history(
    assignment_id: int,
    connection: Connection = Depends(get_connection, scope="function"),
):
    return _history(connection, "user_role_assignment", assignment_id)


@router.get(
    "/users/{user_id}/roles",
    tags=["user role assignments"],
    dependencies=[Depends(require_identity_users_admin)],
)
def get_user_roles(
    user_id: int, request: Request, q: str = Query("", max_length=120),
    limit: int = Query(25, ge=1, le=50), offset: int = Query(0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    get_or_404(connection, "users", user_id)
    language = preferred_language(connection, request)
    term = q.strip()
    params = (user_id, term, term, term, language, term)
    where = """WHERE assignment.user_id=%s
      AND (%s='' OR role.code ILIKE '%%'||%s||'%%' OR role.name ILIKE '%%'||%s||'%%'
           OR COALESCE(role.translations->%s->>'name','') ILIKE '%%'||%s||'%%')"""
    total = connection.execute(
        f"SELECT count(*) AS value FROM user_role_assignments assignment JOIN roles role ON role.id=assignment.role_id {where}", params,
    ).fetchone()["value"]
    rows = list(connection.execute(
        f"""SELECT assignment.*, role.code AS counterpart_code, role.name AS counterpart_name,
                    role.description AS counterpart_description, role.status AS counterpart_status,
                    role.translations AS counterpart_translations
               FROM user_role_assignments assignment JOIN roles role ON role.id=assignment.role_id {where}
              ORDER BY lower(COALESCE(NULLIF(role.translations->%s->>'name',''),role.name)),assignment.id
              LIMIT %s OFFSET %s""", (*params, language, limit, offset),
    ).fetchall())
    for row in rows:
        localized = localize_rows([{
            "name": row["counterpart_name"], "description": row["counterpart_description"],
            "translations": row["counterpart_translations"],
        }], language, "name")[0]["localized"]
        row["counterpart"] = {
            "id": row["role_id"], "code": row["counterpart_code"],
            "name": localized["name"], "description": localized["description"],
            "status": row["counterpart_status"],
        }
    return {"items": rows, "total": total, "limit": limit, "offset": offset, "returned": len(rows)}


@router.get(
    "/roles/{role_id}/users",
    tags=["user role assignments"],
    dependencies=[Depends(require_organization_admin)],
)
def get_role_users(
    role_id: int, request: Request, q: str = Query("", max_length=120),
    limit: int = Query(25, ge=1, le=50), offset: int = Query(0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    get_or_404(connection, "roles", role_id)
    language = preferred_language(connection, request)
    term = q.strip()
    params = (role_id, term, term, term, term, language, term)
    where = """WHERE assignment.role_id=%s
      AND (%s='' OR user_row.name ILIKE '%%'||%s||'%%' OR user_row.email ILIKE '%%'||%s||'%%'
           OR user_row.external_id ILIKE '%%'||%s||'%%'
           OR COALESCE(user_row.translations->%s->>'name','') ILIKE '%%'||%s||'%%')"""
    total = connection.execute(
        f"SELECT count(*) AS value FROM user_role_assignments assignment JOIN users user_row ON user_row.id=assignment.user_id {where}", params,
    ).fetchone()["value"]
    rows = list(connection.execute(
        f"""SELECT assignment.*, user_row.name AS counterpart_name, user_row.email AS counterpart_email,
                    user_row.external_id AS counterpart_external_id, user_row.account_type AS counterpart_account_type,
                    user_row.status AS counterpart_status, user_row.translations AS counterpart_translations
               FROM user_role_assignments assignment JOIN users user_row ON user_row.id=assignment.user_id {where}
              ORDER BY lower(COALESCE(NULLIF(user_row.translations->%s->>'name',''),user_row.name)),assignment.id
              LIMIT %s OFFSET %s""", (*params, language, limit, offset),
    ).fetchall())
    for row in rows:
        localized = localize_rows([{
            "name": row["counterpart_name"], "translations": row["counterpart_translations"],
        }], language, "name")[0]["localized"]
        row["counterpart"] = {
            "id": row["user_id"], "name": localized["name"], "email": row["counterpart_email"],
            "external_id": row["counterpart_external_id"], "account_type": row["counterpart_account_type"],
            "status": row["counterpart_status"],
        }
    return {"items": rows, "total": total, "limit": limit, "offset": offset, "returned": len(rows)}
