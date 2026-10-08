from contextlib import asynccontextmanager
from datetime import datetime
from io import BytesIO
import json
import secrets
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg import Connection
from psycopg_pool import PoolTimeout
from psycopg.types.json import Jsonb

from .audit_context import (
    decode_change_reason,
    actor_email_context,
    actor_name_context,
    actor_user_id_context,
    actor_type_context,
    change_reason_context,
    correlation_id_context,
    event_source_context,
    request_id_context,
)
from .authentication import CSRF_COOKIE, SESSION_COOKIE, hash_secret, resolve_principal, router as authentication_router
from .service_authentication import (
    TEXT_INDEXING_ROUTE_PREFIX, resolve_text_indexer_principal, service_request_allowed,
)
from .crud import create_row, delete_row, get_or_404, list_rows, update_row
from .concurrency import expected_version
from .continuity_lock import acquire_continuity_shared_lock
from .config import boolean_environment, choice_environment, default_working_timezone, integer_environment
from .content_storage import configured_storage, inspect_upload
from .database import close_pool, get_connection, open_pool, pool
from .document_conversion import ConversionUnavailable, UnsupportedPreview, pdf_rendition
from .number_suggestions import router as number_suggestions_router
from .entity_localization import localized_projection, preferred_language
from .schemas import (
    AggregationCreate,
    AggregationRead,
    AggregationUpdate,
    DigitalComponentCreate,
    DigitalComponentRead,
    DigitalComponentUpdate,
    ComponentReorderRequest,
    ComponentMoveRequest,
    EventHistoryRead,
    RecordCreate,
    RecordDraftComponentRead,
    RecordDraftCreate,
    RecordDraftRead,
    RecordDraftUpdate,
    RecordRead,
    RecordPlacementCorrection,
    VitalStatusChange,
    ReviewDateChange,
    AggregationLocationChange,
    AggregationLocationPreview,
    AggregationLocationPreviewRead,
    RecordUpdate,
    SearchRequest,
    GlobalSearchRequest,
    SearchResponse,
    ResourceCapabilitiesRead,
    OwnershipDashboardCount,
    CreationRoleOption,
)
from .search import global_search_rows, search_rows
from .security_level_events import append_security_level_event, validate_security_level_change
from .resource_authorization import (
    audit_governance_view_if_used, lock_visible_resource, operation_allowed, require_clearance_for_level,
    require_closed_placement_correction, require_component_operation,
    require_destination_record_permission, require_draft_owner, require_global,
    require_resource_operation,
)
from .user_management import router as user_management_router
from .classification_management import router as classification_management_router
from .scheme_transfer.routes import router as scheme_transfer_router
from .browse import router as browse_router
from .favourites import router as favourites_router
from .resource_relationships import router as resource_relationships_router
from .security_levels import router as security_levels_router
from .authorization_admin import router as authorization_admin_router
from .resource_acls import router as resource_acl_router
from .governance_authorization import router as governance_authorization_router
from .security_operations import router as security_operations_router
from .dashboard import router as dashboard_router
from .holds import router as holds_router
from .text_indexing import router as text_indexing_router
from .reindexing import router as reindexing_router
from .saved_searches import router as saved_searches_router
from .messaging.routes import router as messaging_router
from .messaging import capture as messaging_capture
from .localization import (
    localization_readiness, router as localization_router,
    synchronize_message_definitions,
)
from .entity_translations import router as entity_translations_router
from .authorization_policy import load_policy_context, require_audit_view


RESOURCE_MEDIA = {"digital", "physical", "mixed"}
DEFAULT_ROOT_AGGREGATION_MEDIUM = choice_environment(
    "DEFAULT_ROOT_AGGREGATION_MEDIUM", "mixed", RESOURCE_MEDIA,
)
REVIEW_WARNING_WINDOW_DAYS = integer_environment("REVIEW_WARNING_WINDOW_DAYS", 30)


def _medium_error(code: str, message: str, **details) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": code, "message": message, **details})


def _record_medium_allowed(parent_medium: str, record_medium: str) -> bool:
    return parent_medium == "mixed" or parent_medium == record_medium


def _resolved_record_medium(parent: dict, requested: str | None) -> str:
    medium = requested or parent["medium"]
    if not _record_medium_allowed(parent["medium"], medium):
        raise _medium_error(
            "record_medium_not_allowed_by_parent",
            f"A {parent['medium']} aggregation can only contain compatible records.",
            parent_medium=parent["medium"], requested_medium=medium,
        )
    return medium


def _require_record_accepts_components(connection: Connection, record_id: int) -> dict:
    record = connection.execute(
        "SELECT id,medium FROM records WHERE id=%s FOR KEY SHARE", (record_id,),
    ).fetchone()
    if record is not None and record["medium"] == "physical":
        raise HTTPException(status_code=409, detail={
            "code": "physical_record_disallows_digital_components",
            "message": "This is a physical record. Digital files cannot be added.",
        })
    return record


def _require_draft_accepts_components(draft: dict) -> None:
    if draft.get("medium") == "physical":
        raise HTTPException(status_code=409, detail={
            "code": "physical_record_disallows_digital_components",
            "message": "This draft is for a physical record. Digital files cannot be added.",
        })
    if not draft.get("medium"):
        raise HTTPException(status_code=409, detail={
            "code": "record_medium_required_before_components",
            "message": "Select the parent aggregation and record medium before adding digital files.",
        })


from .messaging.realtime import Gateway, router as messaging_realtime_router
from .messaging.notification_routes import router as notification_administration_router
from .messaging.notification_registry import initialize_registry
from .messaging.notification_configuration import readiness as notification_readiness


@asynccontextmanager
async def lifespan(application: FastAPI):
    default_working_timezone()
    integer_environment("AUDIT_TRAIL_SEARCH_RESULT_LIMIT", 1000, minimum=1)
    open_pool()
    synchronize_message_definitions()
    initialize_registry()
    with pool.connection() as connection:
        notification_readiness(connection)
    application.state.messaging_gateway = Gateway()
    application.state.messaging_gateway.start()
    from .messaging.operations import Worker
    application.state.messaging_worker = Worker(application.state.messaging_gateway)
    application.state.messaging_worker.start()
    try:
        yield
    finally:
        await application.state.messaging_worker.stop()
        await application.state.messaging_gateway.stop()
        close_pool()


app = FastAPI(
    title="ERMS API",
    version="0.1.0",
    description="REST API for the Electronic Records Management System.",
    lifespan=lifespan,
)
app.include_router(messaging_realtime_router)
app.include_router(notification_administration_router)
app.include_router(number_suggestions_router)
app.include_router(user_management_router)
app.include_router(authentication_router)
app.include_router(scheme_transfer_router)
app.include_router(classification_management_router)
app.include_router(browse_router)
app.include_router(favourites_router)
app.include_router(resource_relationships_router)
app.include_router(security_levels_router)
app.include_router(authorization_admin_router)
app.include_router(resource_acl_router)
app.include_router(governance_authorization_router)
app.include_router(security_operations_router)
app.include_router(dashboard_router)
app.include_router(holds_router)
app.include_router(text_indexing_router)
app.include_router(reindexing_router)
app.include_router(saved_searches_router)
from .messaging.monitor import router as messaging_monitor_router
app.include_router(messaging_monitor_router)
app.include_router(messaging_router)
app.include_router(localization_router)
app.include_router(entity_translations_router)


@app.post("/api/v1/full-text-search", response_model=None, tags=["search"])
def full_text_search(
    payload: GlobalSearchRequest,
    connection: Connection = Depends(get_connection, scope="function"),
):
    return global_search_rows(connection,payload)

EVENT_SOURCES = {
    "api", "web_ui", "bulk_import", "background_worker", "scheduled_job",
    "integration", "migration", "seeding", "administrative_tool", "cli", "oidc_sync",
    "directory_sync",
}


def _request_uuid(value: str | None, header_name: str) -> str:
    if value is None:
        return str(uuid4())
    try:
        return str(UUID(value))
    except ValueError as exception:
        raise ValueError(f"{header_name} must be a valid UUID") from exception


from .messaging.operations import request_metrics
app.middleware("http")(request_metrics)


@app.middleware("http")
async def audit_request_context(request: Request, call_next):
    try:
        request_id = _request_uuid(request.headers.get("X-Request-ID"), "X-Request-ID")
        correlation_header = request.headers.get("X-Correlation-ID")
        correlation_id = (
            _request_uuid(correlation_header, "X-Correlation-ID")
            if correlation_header
            else request_id
        )
    except ValueError as exception:
        return JSONResponse(status_code=400, content={"detail": str(exception)})

    change_reason = decode_change_reason(request.headers.get("X-Change-Reason", ""))
    if len(change_reason) > 2000:
        return JSONResponse(
            status_code=400,
            content={"detail": "X-Change-Reason cannot exceed 2000 characters"},
        )

    event_source = request.headers.get("X-Event-Source", "api").strip().lower()
    if event_source not in EVENT_SOURCES:
        return JSONResponse(
            status_code=400,
            content={"detail": "X-Event-Source is not an approved event source"},
        )

    request_token = request_id_context.set(request_id)
    correlation_token = correlation_id_context.set(correlation_id)
    principal = None
    service_principal = None
    cookie_token = request.cookies.get(SESSION_COOKIE)
    authorization = request.headers.get("authorization", "")
    bearer_token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
    internal_text_indexing_path = request.url.path.startswith(TEXT_INDEXING_ROUTE_PREFIX)
    service_key_present = bool(bearer_token and bearer_token.startswith("wti_"))
    if service_key_present and not internal_text_indexing_path:
        return JSONResponse(status_code=401, content={"detail": "invalid authentication credentials"})
    session_token = None if internal_text_indexing_path else (bearer_token or cookie_token)
    if internal_text_indexing_path or session_token:
        try:
            with pool.connection() as authentication_connection:
                if internal_text_indexing_path and bearer_token:
                    service_principal = resolve_text_indexer_principal(
                        authentication_connection, bearer_token,
                        worker_id=request.headers.get("X-Worker-ID"),
                    )
                elif session_token:
                    principal = resolve_principal(authentication_connection, session_token)
                    request.state.policy_context = (
                        load_policy_context(authentication_connection, principal)
                        if principal else None
                    )
        except PoolTimeout:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"detail": "database connection pool is busy; retry shortly"},
                headers={"Retry-After": "1", "X-Request-ID": request_id,
                         "X-Correlation-ID": correlation_id},
            )
    public_path = (
        request.url.path == "/health"
        or request.url.path == "/api/v1/auth/login"
        or request.url.path in {"/docs", "/openapi.json", "/redoc"}
    )
    authenticated = service_principal if internal_text_indexing_path else principal
    if request.url.path.startswith("/api/v1/") and not public_path and authenticated is None:
        return JSONResponse(status_code=401, content={"detail": "authentication required"})
    if service_principal and not service_request_allowed(
        service_principal.credential_id,
        integer_environment("TEXT_INDEXER_RATE_LIMIT_PER_MINUTE", 600, minimum=1),
    ):
        return JSONResponse(status_code=429, content={"detail": "request rate limit exceeded"},
                            headers={"Retry-After": "1"})
    if principal and request.method == "POST":
        is_reindex = request.url.path.endswith("/reindex")
        is_search = request.url.path.endswith("/search") or request.url.path == "/api/v1/full-text-search"
        if is_reindex and not service_request_allowed(
            -1_000_000_000-principal.user_id,
            integer_environment("MANUAL_REINDEX_RATE_LIMIT_PER_MINUTE",60,minimum=1),
        ):
            return JSONResponse(status_code=429,content={"detail":{"code":"reindex_rate_limit_exceeded"}},
                                headers={"Retry-After":"60"})
        if is_search and not service_request_allowed(
            -principal.user_id,
            integer_environment("SEARCH_RATE_LIMIT_PER_MINUTE",600,minimum=1),
        ):
            return JSONResponse(status_code=429,content={"detail":{"code":"search_rate_limit_exceeded"}},
                                headers={"Retry-After":"1"})
    if principal and principal.must_change_password and request.url.path not in {
        "/api/v1/auth/me", "/api/v1/auth/change-password", "/api/v1/auth/logout"
    }:
        return JSONResponse(status_code=403, content={"detail": "password change required"})
    if principal and cookie_token and not bearer_token and request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("x-csrf-token", "")
        if not csrf or not secrets.compare_digest(hash_secret(csrf), hash_secret(request.cookies.get(CSRF_COOKIE, ""))):
            return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    request.state.principal = principal
    request.state.service_principal = service_principal
    if not hasattr(request.state, "policy_context"):
        request.state.policy_context = None
    actor = principal or service_principal
    actor_token = actor_type_context.set(
        "automated_process" if service_principal else ("user" if principal else "anonymous")
    )
    actor_user_token = actor_user_id_context.set(str(actor.user_id) if actor else "")
    actor_name_token = actor_name_context.set(actor.name if actor else "")
    actor_email_token = actor_email_context.set(principal.email if principal else "")
    source_token = event_source_context.set(event_source)
    reason_token = change_reason_context.set(change_reason)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id
        return response
    finally:
        change_reason_context.reset(reason_token)
        event_source_context.reset(source_token)
        actor_email_context.reset(actor_email_token)
        actor_name_context.reset(actor_name_token)
        actor_user_id_context.reset(actor_user_token)
        actor_type_context.reset(actor_token)
        correlation_id_context.reset(correlation_token)
        request_id_context.reset(request_token)


@app.exception_handler(psycopg.Error)
async def database_error_handler(_, exception: psycopg.Error):
    sqlstate = exception.sqlstate
    constraint_messages = {
        "aggregations_dates_in_order": (
            "aggregation_dates_out_of_order",
            "The aggregation's closing date cannot be earlier than its opening date.",
        ),
        "org_units_dates_in_order": (
            "organization_unit_dates_out_of_order",
            "The organization unit's deactivation date cannot be earlier than its creation date.",
        ),
        "users_dates_in_order": (
            "user_dates_out_of_order",
            "The account's deactivation date cannot be earlier than its creation date.",
        ),
        "roles_dates_in_order": (
            "role_dates_out_of_order",
            "The role's deactivation date cannot be earlier than its creation date.",
        ),
        "user_role_assignments_dates_in_order": (
            "assignment_dates_out_of_order",
            "The assignment's end date cannot be earlier than its start date.",
        ),
        "classification_schemes_dates_in_order": (
            "classification_scheme_dates_out_of_order",
            "The classification scheme's dates are not in a valid chronological order.",
        ),
        "classifications_dates_in_order": (
            "classification_dates_out_of_order",
            "The classification's deactivation date cannot be earlier than its creation date.",
        ),
    }
    constraint_name = exception.diag.constraint_name
    primary = exception.diag.message_primary or "database constraint violated"
    hold_failure_codes = {
        "effective_hold_prevents_deletion", "effective_hold_prevents_component_addition",
        "effective_hold_prevents_component_deletion", "effective_hold_prevents_component_reordering",
        "effective_hold_prevents_component_replacement", "effective_hold_prevents_metadata_change",
        "hold_not_empty", "hold_held_item_management_required_for_held_move",
    }
    if primary in hold_failure_codes:
        # The failed write transaction is rolled back, so record the rejected
        # operation in an independent transaction instead of losing the audit.
        try:
            with pool.connection() as audit_connection:
                audit_connection.execute(
                    """SELECT set_config('app.user_id',%s,true),set_config('app.actor_name',%s,true),
                              set_config('app.actor_email',%s,true),set_config('app.actor_type',%s,true),
                              set_config('app.event_source',%s,true),set_config('app.request_id',%s,true),
                              set_config('app.correlation_id',%s,true),set_config('app.change_reason',%s,true)""",
                    (actor_user_id_context.get(),actor_name_context.get(),actor_email_context.get(),actor_type_context.get(),
                     event_source_context.get(),request_id_context.get(),correlation_id_context.get(),change_reason_context.get()),
                )
                audit_connection.execute(
                    "SELECT append_domain_event('hold_operation',0,'HOLD_OPERATION_BLOCKED',%s::jsonb)",
                    (json.dumps({"failure_code": primary}),),
                )
        except psycopg.Error:
            pass
    if sqlstate == "23505" and constraint_name in {
        "aggregations_aggregation_number_key", "records_record_number_key",
    }:
        return JSONResponse(status_code=409, content={"detail": {
            "code": "duplicate_resource_number",
            "resource": "aggregations" if constraint_name.startswith("aggregations_") else "records",
        }})
    friendly_constraint = constraint_messages.get(constraint_name or "")
    if isinstance(exception, PoolTimeout):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        detail = "database connection pool is busy; retry shortly"
    elif sqlstate in {"23001", "23503", "23505", "P0001"}:
        status_code = status.HTTP_409_CONFLICT
        detail = (
            {
                "code": "security_hierarchy_violation",
                "message": "The security level conflicts with the containing aggregation",
                "context": exception.diag.message_detail,
            }
            if primary == "security_hierarchy_violation"
            else primary
        )
    elif friendly_constraint:
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        code, message = friendly_constraint
        detail = {
            "code": code,
            "message": message,
            "technical_detail": exception.diag.message_primary
            or f"database constraint {constraint_name} was violated",
            "constraint": constraint_name,
        }
    elif isinstance(exception, (psycopg.IntegrityError, psycopg.DataError)):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = exception.diag.message_primary or "database constraint violated"
    else:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        detail = "database operation failed"
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail},
    )


@app.get("/health", tags=["system"])
def health(connection: Connection = Depends(get_connection, scope="function")) -> dict[str, Any]:
    connection.execute("SELECT 1")
    notifications = notification_readiness(connection)
    if not notifications["ready"]:
        raise HTTPException(status_code=503, detail={"code": "notification_readiness_failed", "notifications": notifications})
    return {
        "status": "ok",
        "notifications": notifications,
        "messaging_realtime": app.state.messaging_gateway.health(),
        "full_text_search_enabled": boolean_environment("FULL_TEXT_SEARCH_ENABLED", True),
        "content_indexing_scheduling_enabled": boolean_environment(
            "CONTENT_INDEXING_SCHEDULING_ENABLED", True,
        ),
        "localization": localization_readiness(connection),
    }


def _creation_role_options(
    connection: Connection, parent_aggregation_id: int | None = None,
    *, language_tag: str | None = None,
) -> list[dict]:
    parameters: list[int] = []
    owner_clause = ""
    if parent_aggregation_id is not None:
        parent = connection.execute(
            "SELECT owning_org_unit_id FROM aggregations WHERE id=%s",
            (parent_aggregation_id,),
        ).fetchone()
        if parent is None:
            raise HTTPException(status_code=409, detail="referenced aggregation does not exist")
        owner_clause = " AND role.org_unit_id=%s"
        parameters.append(parent["owning_org_unit_id"])
    rows = connection.execute(
        """SELECT DISTINCT role.id AS role_id,role.code AS role_code,
                  role.name AS role_name,unit.id AS org_unit_id,
                  unit.code AS org_unit_code,unit.name AS org_unit_name,
                  role.translations AS role_translations,
                  unit.translations AS org_unit_translations
             FROM user_role_assignments assignment
             JOIN roles role ON role.id=assignment.role_id
             JOIN org_units unit ON unit.id=role.org_unit_id
            WHERE assignment.user_id=current_user_id()
              AND CURRENT_TIMESTAMP>=assignment.valid_from
              AND (assignment.valid_until IS NULL OR CURRENT_TIMESTAMP<assignment.valid_until)
              AND role_effectively_active(role.id)""" + owner_clause +
        " ORDER BY org_unit_name,role_name,role_id",
        parameters,
    ).fetchall()
    for row in rows:
        for entity in ("role", "org_unit"):
            translations = row.pop(f"{entity}_translations")
            if language_tag is not None:
                row[f"{entity}_name"] = localized_projection(
                    {"name": row[f"{entity}_name"], "translations": translations},
                    language_tag, "name",
                )["name"]
        row["label"] = f"{row['org_unit_name']} — {row['role_name']}"
    return rows


def _select_creator_role(
    connection: Connection, requested_role_id: int | None,
    parent_aggregation_id: int | None = None,
) -> dict:
    options = _creation_role_options(connection, parent_aggregation_id)
    if not options:
        raise HTTPException(status_code=403, detail={
            "code": "creator_acl_role_not_eligible",
            "message": "You do not have a current role in the owning organizational unit.",
        })
    if requested_role_id is None:
        if len(options) != 1:
            raise HTTPException(status_code=422, detail={
                "code": "creator_acl_role_selection_required",
                "message": "Select the organizational role to create this resource for.",
            })
        return options[0]
    selected = next((row for row in options if row["role_id"] == requested_role_id), None)
    if selected is None:
        raise HTTPException(status_code=403, detail={
            "code": "creator_acl_role_not_eligible",
            "message": "The selected role is not currently eligible for this owner.",
        })
    return selected


@app.get(
    "/api/v1/creation-role-options",
    response_model=list[CreationRoleOption], tags=["authorization"],
)
def creation_role_options(
    request: Request,
    parent_aggregation_id: int | None = None,
    connection: Connection = Depends(get_connection, scope="function"),
):
    return _creation_role_options(
        connection, parent_aggregation_id,
        language_tag=preferred_language(connection, request),
    )


@app.get(
    "/api/v1/dashboard/ownership-counts",
    response_model=list[OwnershipDashboardCount],
    tags=["dashboard"],
)
def dashboard_ownership_counts(
    request: Request,
    connection: Connection = Depends(get_connection, scope="function"),
):
    rows = list(connection.execute(
        """WITH eligible_units AS (
               SELECT DISTINCT unit.id,unit.code,unit.name,unit.translations
               FROM user_role_assignments assignment
               JOIN roles role ON role.id=assignment.role_id
               JOIN org_units unit ON unit.id=role.org_unit_id
               WHERE assignment.user_id=current_user_id()
                 AND CURRENT_TIMESTAMP>=assignment.valid_from
                 AND (assignment.valid_until IS NULL OR CURRENT_TIMESTAMP<=assignment.valid_until)
                 AND role_effectively_active(role.id)
           )
           SELECT unit.id AS org_unit_id,unit.code AS org_unit_code,
                  unit.name AS org_unit_name,unit.translations,
                  (SELECT count(*) FROM aggregations aggregation
                    WHERE aggregation.owning_org_unit_id=unit.id
                      AND current_user_can_view_aggregation(aggregation.id)) AS aggregation_count,
                  (SELECT count(*) FROM records record
                    WHERE record.owning_org_unit_id=unit.id
                      AND current_user_can_view_record(record.id)) AS record_count
           FROM eligible_units unit
           ORDER BY unit.name COLLATE "C",unit.id"""
    ).fetchall())
    language_tag = preferred_language(connection, request)
    for row in rows:
        row["name"] = row["org_unit_name"]
        row["org_unit_name"] = localized_projection(row, language_tag, "name")["name"]
        row.pop("name", None)
        row.pop("translations", None)
    return sorted(rows, key=lambda row: (
        str(row["org_unit_name"] or "").casefold(), row["org_unit_id"]
    ))


@app.post(
    "/api/v1/aggregations",
    response_model=AggregationRead,
    status_code=status.HTTP_201_CREATED,
    tags=["aggregations"],
)
def create_aggregation(
    payload: AggregationCreate,
    connection: Connection = Depends(get_connection, scope="function"),
):
    acquire_continuity_shared_lock(connection)
    values = payload.model_dump(exclude={"creator_acl_role_id"})
    selected_role = _select_creator_role(
        connection, payload.creator_acl_role_id, payload.parent_aggregation_id,
    )
    if payload.parent_aggregation_id is None:
        values["medium"] = payload.medium or DEFAULT_ROOT_AGGREGATION_MEDIUM
        level_id = payload.security_level_id or connection.execute(
            "SELECT lowest_security_level_id() AS id"
        ).fetchone()["id"]
        require_global(connection, "aggregation.create_root")
        require_clearance_for_level(connection, level_id)
        values["owning_org_unit_id"] = selected_role["org_unit_id"]
    else:
        parent = require_resource_operation(
            connection, "aggregation", payload.parent_aggregation_id,
            "aggregation.create_child", "aggregation.add_child",
        )
        if payload.medium is not None and payload.medium != parent["medium"]:
            raise _medium_error(
                "aggregation_medium_mismatch",
                "A child aggregation must use the same medium as its parent.",
                parent_medium=parent["medium"], requested_medium=payload.medium,
            )
        values["medium"] = parent["medium"]
        level_id = payload.security_level_id or parent["security_level_id"]
        require_clearance_for_level(connection, level_id)
    connection.execute(
        "SELECT set_config('app.creator_acl_role_id',%s,true),set_config('app.event_metadata',%s,true)",
        (str(selected_role["role_id"]), json.dumps({
            "creator_acl_role_id": selected_role["role_id"],
            "creator_acl_role_code": selected_role["role_code"],
            "creator_org_unit_id": selected_role["org_unit_id"],
        })),
    )
    return create_row(connection, "aggregations", values)


@app.get("/api/v1/aggregations", response_model=list[AggregationRead], tags=["aggregations"])
def list_aggregations(
    parent_aggregation_id: int | None = None,
    owning_org_unit_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    if parent_aggregation_id is not None and connection.execute(
        "SELECT 1 FROM aggregations WHERE id=%s AND current_user_can_view_aggregation(id)",
        (parent_aggregation_id,),
    ).fetchone() is None:
        return []
    return list_rows(
        connection,
        "aggregations",
        limit=limit,
        offset=offset,
        filters={"parent_aggregation_id": parent_aggregation_id,
                 "owning_org_unit_id": owning_org_unit_id},
    )


@app.post(
    "/api/v1/aggregations/search",
    response_model=None,
    tags=["aggregations"],
)
def search_aggregations(
    payload: SearchRequest,
    record_creation: bool = False,
    digital_only: bool = False,
    connection: Connection = Depends(get_connection, scope="function"),
):
    return search_rows(connection, "aggregations", payload, endpoint="/api/v1/aggregations/search", record_creation=record_creation, digital_only=digital_only)


@app.get("/api/v1/aggregations/{aggregation_id}", response_model=AggregationRead, tags=["aggregations"])
def get_aggregation(aggregation_id: int, connection: Connection = Depends(get_connection, scope="function")):
    aggregation = get_or_404(connection, "aggregations", aggregation_id)
    audit_governance_view_if_used(connection, "aggregation", aggregation)
    return aggregation


@app.get("/api/v1/aggregations/{aggregation_id}/capabilities", response_model=ResourceCapabilitiesRead, tags=["authorization"])
def get_aggregation_capabilities(
    aggregation_id: int,
    connection: Connection = Depends(get_connection, scope="function"),
):
    resource = get_or_404(connection, "aggregations", aggregation_id)
    mappings = {
        "modify_metadata": ("aggregation.modify", "aggregation.modify_metadata"),
        "delete": ("aggregation.delete", "aggregation.delete"),
        "close": ("aggregation.close", "aggregation.close"),
        "reopen": ("aggregation.reopen", "aggregation.reopen"),
        "move": ("aggregation.move", "aggregation.move"),
        "reclassify": ("aggregation.reclassify", "aggregation.reclassify"),
        "change_security_level": ("aggregation.security_level.change", "aggregation.security_level.change"),
        "manage_acl": ("aggregation.acl.manage", "aggregation.acl.manage"),
        "change_vital_status": ("aggregation.vital_status.change", "aggregation.vital_status.change"),
        "change_location": ("aggregation.location.change", "aggregation.location.change"),
        "change_review_date": ("aggregation.review_date.change", "aggregation.review_date.change"),
        "add_child": ("aggregation.create_child", "aggregation.add_child"),
        "add_record": ("record.create", "aggregation.add_record"),
    }
    capabilities = {name: operation_allowed(connection, "aggregation", aggregation_id, *policy)
                    for name, policy in mappings.items()}
    capabilities["view"] = True
    capabilities["close"] = capabilities["close"] and resource["date_closed"] is None
    capabilities["reopen"] = capabilities["reopen"] and resource["date_closed"] is not None
    vital_descendants = connection.execute("SELECT aggregation_has_vital_descendants(%s) AS value", (aggregation_id,)).fetchone()["value"]
    capabilities["delete"] = capabilities["delete"] and not resource["is_vital"] and not vital_descendants
    capability_reasons = {}
    hold_status = connection.execute(
        """SELECT count(*) effective_hold_count,
                  COALESCE(bool_or(preserve_resource_state),false) state_blocked
             FROM effective_holds_for_aggregation(%s)""", (aggregation_id,),
    ).fetchone()
    direct_holds = connection.execute(
        "SELECT count(*) count,COALESCE(bool_or(current_hold_actor_is_manager(hold_id)),false) any_manageable,COALESCE(bool_and(current_hold_actor_is_manager(hold_id)),true) all_manageable FROM hold_aggregation_assignments WHERE aggregation_id=%s",
        (aggregation_id,),
    ).fetchone()
    capabilities.update({
        "is_on_effective_hold": hold_status["effective_hold_count"] > 0,
        "resource_state_changes_blocked": hold_status["state_blocked"],
        "add_to_hold": bool(connection.execute("SELECT EXISTS(SELECT 1 FROM holds WHERE current_hold_actor_is_manager(id)) value").fetchone()["value"]),
        "remove_from_hold": direct_holds["count"] > 0 and direct_holds["any_manageable"],
        "remove_all_direct_hold_assignments": direct_holds["count"] > 0 and direct_holds["all_manageable"],
    })
    capabilities["effective_hold_count"] = hold_status["effective_hold_count"]
    if not capabilities["add_to_hold"]: capability_reasons["add_to_hold"]="hold_held_item_manager_required"
    if direct_holds["count"] and not capabilities["remove_from_hold"]: capability_reasons["remove_from_hold"]="hold_held_item_manager_required"
    if direct_holds["count"] and not capabilities["remove_all_direct_hold_assignments"]: capability_reasons["remove_all_direct_hold_assignments"]="not_all_direct_holds_manageable"
    if hold_status["effective_hold_count"]:
        capabilities["delete"] = False; capability_reasons["delete"] = "effective_hold_prevents_deletion"
    if hold_status["state_blocked"]:
        for name in ("modify_metadata","close","reopen","move","reclassify","change_vital_status","change_review_date"):
            capabilities[name] = False; capability_reasons[name] = "effective_hold_prevents_metadata_change"
    if resource["is_vital"]:
        capability_reasons["delete"] = "vital_resource_deletion_blocked"
    elif vital_descendants:
        capability_reasons["delete"] = "vital_descendant_deletion_blocked"
    capabilities["correct_ownership"] = bool(
        resource["parent_aggregation_id"] is None
        and connection.execute(
            """SELECT user_has_global_privilege(current_user_id(),'organization.ownership.correct')
                      AND EXISTS (
                        SELECT 1 FROM user_role_assignments assignment
                        JOIN roles role ON role.id=assignment.role_id
                        JOIN security_levels role_level ON role_level.id=role.security_level_id
                        JOIN security_levels resource_level ON resource_level.id=%s
                        WHERE assignment.user_id=current_user_id() AND role.is_information_governance
                          AND assignment.valid_from<=CURRENT_TIMESTAMP
                          AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
                          AND role_effectively_active(role.id)
                          AND role_level.level_number>=resource_level.level_number) AS allowed""",
            (resource["security_level_id"],),
        ).fetchone()["allowed"]
    )
    return {"resource_type": "aggregation", "resource_id": aggregation_id,
            "capabilities": capabilities, "capability_reasons": capability_reasons}


@app.patch("/api/v1/aggregations/{aggregation_id}", response_model=AggregationRead, tags=["aggregations"])
def update_aggregation(
    aggregation_id: int,
    payload: AggregationUpdate,
    request: Request,
    version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    existing = lock_visible_resource(connection, "aggregation", aggregation_id)
    fields = payload.model_fields_set
    metadata_fields = {"aggregation_number", "title", "description", "date_opened"}
    if fields & metadata_fields:
        require_resource_operation(
            connection, "aggregation", aggregation_id,
            "aggregation.modify", "aggregation.modify_metadata",
        )
    if "parent_aggregation_id" in fields and payload.parent_aggregation_id != existing["parent_aggregation_id"]:
        require_resource_operation(connection, "aggregation", aggregation_id, "aggregation.move", "aggregation.move")
        if payload.parent_aggregation_id is None:
            require_global(connection, "aggregation.create_root")
        else:
            destination = require_resource_operation(connection, "aggregation", payload.parent_aggregation_id,
                                       "aggregation.move", "aggregation.receive_child")
            if destination["medium"] != existing["medium"]:
                raise _medium_error(
                    "aggregation_medium_mismatch",
                    "This aggregation and all its descendants must be compatible with the destination medium.",
                    source_medium=existing["medium"], destination_medium=destination["medium"],
                )
            if destination["owning_org_unit_id"] != existing["owning_org_unit_id"]:
                raise HTTPException(status_code=422, detail={
                    "code": "ownership_change_requires_confirmation",
                    "message": "Use the move command and confirm the organizational ownership change.",
                })
    if "medium" in fields and payload.medium != existing["medium"]:
        require_resource_operation(
            connection, "aggregation", aggregation_id,
            "aggregation.modify", "aggregation.modify_metadata",
        )
        has_contents = connection.execute(
            """SELECT EXISTS (SELECT 1 FROM aggregations WHERE parent_aggregation_id=%s)
                      OR EXISTS (SELECT 1 FROM records WHERE aggregation_id=%s) AS value""",
            (aggregation_id, aggregation_id),
        ).fetchone()["value"]
        if has_contents:
            raise _medium_error(
                "medium_change_requires_empty_aggregation",
                "An aggregation's medium can only be changed while it is empty.",
            )
        if existing["parent_aggregation_id"] is not None:
            parent = connection.execute(
                "SELECT medium FROM aggregations WHERE id=%s FOR KEY SHARE",
                (existing["parent_aggregation_id"],),
            ).fetchone()
            if parent and payload.medium != parent["medium"]:
                raise _medium_error(
                    "aggregation_medium_mismatch",
                    "A child aggregation must use the same medium as its parent.",
                    parent_medium=parent["medium"], requested_medium=payload.medium,
                )
        medium_change_reason = decode_change_reason(request.headers.get("X-Change-Reason", "")).strip()
        if not medium_change_reason:
            raise _medium_error(
                "medium_change_reason_required",
                "Enter a reason for changing this aggregation's medium.",
            )
        connection.execute("SELECT set_config('app.change_reason',%s,true)", (medium_change_reason,))
    if "classification_id" in fields and payload.classification_id != existing["classification_id"]:
        require_resource_operation(connection, "aggregation", aggregation_id,
                                   "aggregation.reclassify", "aggregation.reclassify")
    if "date_closed" in fields and payload.date_closed != existing["date_closed"]:
        privilege = "aggregation.close" if payload.date_closed is not None else "aggregation.reopen"
        require_resource_operation(connection, "aggregation", aggregation_id, privilege, privilege)
        if payload.date_closed is None and existing["date_closed"] is not None:
            reopen_reason = decode_change_reason(request.headers.get("X-Change-Reason", "")).strip()
            if not reopen_reason:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "reopen_reason_required",
                        "message": "Enter a reason for reopening this aggregation.",
                    },
                )
        if (
            payload.date_closed is not None
            and existing["date_closed"] is None
            and payload.date_closed < existing["date_opened"]
        ):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "closure_before_opening",
                    "message": (
                        "This aggregation cannot be closed before its opening date. "
                        "Choose a closing date that is the same as or later than the opening date."
                    ),
                    "date_opened": existing["date_opened"].isoformat(),
                    "requested_date_closed": payload.date_closed.isoformat(),
                },
            )
    if "security_level_id" in fields and payload.security_level_id != existing["security_level_id"]:
        require_resource_operation(connection, "aggregation", aggregation_id,
                                   "aggregation.security_level.change", "aggregation.security_level.change")
        require_clearance_for_level(connection, payload.security_level_id)
        if not decode_change_reason(request.headers.get("X-Change-Reason", "")).strip():
            raise HTTPException(status_code=422, detail="X-Change-Reason is required when changing a security level")
    new_level_id = payload.security_level_id if "security_level_id" in payload.model_fields_set else None
    reason, old_number, new_number = validate_security_level_change(
        connection, request, existing["security_level_id"], new_level_id
    )
    if new_level_id is not None and new_number < old_number:
        require_global(connection, "security.resource.downgrade")
    updated = update_row(
        connection, "aggregations", aggregation_id, payload.model_dump(exclude_unset=True), version
    )
    if "medium" in fields and payload.medium != existing["medium"]:
        connection.execute(
            "SELECT append_domain_event('aggregation',%s,'MEDIUM_CHANGED',%s::jsonb,%s)",
            (aggregation_id, Jsonb({"old_medium": existing["medium"], "new_medium": payload.medium}), medium_change_reason),
        )
    append_security_level_event(
        connection, entity_type="aggregation", entity_id=aggregation_id,
        old_security_level_id=existing["security_level_id"], new_security_level_id=new_level_id,
        old_level_number=old_number, new_level_number=new_number, reason=reason,
    )
    return updated


@app.delete("/api/v1/aggregations/{aggregation_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["aggregations"])
def delete_aggregation(aggregation_id: int, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    require_resource_operation(connection, "aggregation", aggregation_id,
                               "aggregation.delete", "aggregation.delete")
    delete_row(connection, "aggregations", aggregation_id, version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/v1/aggregations/{aggregation_id}/vital-status", response_model=AggregationRead, tags=["aggregations"])
def change_aggregation_vital_status(aggregation_id: int, payload: VitalStatusChange, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    existing = require_resource_operation(connection, "aggregation", aggregation_id, "aggregation.vital_status.change", "aggregation.vital_status.change")
    if existing["is_vital"] == payload.is_vital:
        return get_or_404(connection, "aggregations", aggregation_id)
    connection.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true),set_config('app.suppress_ordinary_history','authorized',true),set_config('app.change_reason',%s,true)", (payload.reason,))
    updated = update_row(connection, "aggregations", aggregation_id, {"is_vital": payload.is_vital}, version)
    connection.execute("SELECT append_domain_event('aggregation',%s,'VITAL_STATUS_CHANGED',%s::jsonb,%s)", (aggregation_id, Jsonb({"old_is_vital": existing["is_vital"], "new_is_vital": payload.is_vital, "authorization_basis": "governed"}), payload.reason))
    return updated


@app.post("/api/v1/aggregations/{aggregation_id}/location", response_model=AggregationRead, tags=["aggregations"])
def change_aggregation_location(aggregation_id: int, payload: AggregationLocationChange, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    existing = require_resource_operation(connection, "aggregation", aggregation_id, "aggregation.location.change", "aggregation.location.change")
    values = payload.model_dump(exclude={"reason"}, exclude_unset=True)
    connection.execute("SELECT set_config('app.location_change_authorized','authorized',true),set_config('app.suppress_ordinary_history','authorized',true),set_config('app.change_reason',%s,true)", (payload.reason,))
    updated = update_row(connection, "aggregations", aggregation_id, values, version)
    connection.execute("SELECT append_domain_event('aggregation',%s,'RESOURCE_LOCATION_CHANGED',%s::jsonb,%s)", (aggregation_id, Jsonb({"old": {key: existing.get(key) for key in values}, "new": values, "authorization_basis": "governed"}), payload.reason))
    return updated


@app.post("/api/v1/aggregations/{aggregation_id}/location-preview", response_model=AggregationLocationPreviewRead, tags=["aggregations"])
def preview_aggregation_location_change(aggregation_id: int, payload: AggregationLocationPreview, connection: Connection = Depends(get_connection, scope="function")):
    require_resource_operation(connection, "aggregation", aggregation_id, "aggregation.location.change", "aggregation.location.change")
    proposed = payload.model_dump(exclude_unset=True)
    assigned_supplied = "assigned_location" in proposed
    current_supplied = "current_location" in proposed
    rows = list(connection.execute(
        """WITH RECURSIVE descendants AS (
               SELECT root.id,root.parent_aggregation_id,root.aggregation_number,root.title,
                      root.assigned_location,root.current_location,0 depth,
                      coalesce(CASE WHEN %s THEN %s ELSE root.assigned_location END,
                               aggregation_effective_assigned_location(root.parent_aggregation_id)) proposed_assigned,
                      coalesce(CASE WHEN %s THEN %s ELSE root.current_location END,
                               aggregation_effective_current_location(root.parent_aggregation_id)) proposed_current
                 FROM aggregations root WHERE root.id=%s
               UNION ALL
               SELECT child.id,child.parent_aggregation_id,child.aggregation_number,child.title,
                      child.assigned_location,child.current_location,parent.depth+1,
                      coalesce(child.assigned_location,parent.proposed_assigned),
                      coalesce(child.current_location,parent.proposed_current)
                 FROM aggregations child JOIN descendants parent ON child.parent_aggregation_id=parent.id
             ), aggregation_impact AS (
               SELECT 'aggregation'::text entity_type,item.id entity_id,item.aggregation_number number,item.title,item.depth,
                      aggregation_effective_assigned_location(item.id) old_assigned,
                      aggregation_effective_current_location(item.id) old_current,
                      item.proposed_assigned new_assigned,item.proposed_current new_current
                 FROM descendants item WHERE item.depth>0
             ), record_impact AS (
               SELECT 'record'::text entity_type,record.id entity_id,record.record_number number,record.title,parent.depth,
                      aggregation_effective_assigned_location(record.aggregation_id) old_assigned,
                      aggregation_effective_current_location(record.aggregation_id) old_current,
                      parent.proposed_assigned new_assigned,parent.proposed_current new_current
                 FROM records record JOIN descendants parent ON parent.id=record.aggregation_id
             ), impact AS (SELECT * FROM aggregation_impact UNION ALL SELECT * FROM record_impact)
             SELECT entity_type,entity_id,number,title
                 FROM impact
                WHERE old_assigned IS DISTINCT FROM new_assigned OR old_current IS DISTINCT FROM new_current
                  AND CASE WHEN entity_type='aggregation' THEN current_user_can_view_aggregation(entity_id) ELSE current_user_can_view_record(entity_id) END
                ORDER BY depth,entity_type,entity_id""",
        (assigned_supplied, proposed.get("assigned_location"), current_supplied,
         proposed.get("current_location"), aggregation_id),
    ).fetchall())
    return {"affected_descendant_count": len(rows), "affected_descendants": rows[:50], "preview_truncated": len(rows) > 50}


@app.post("/api/v1/aggregations/{aggregation_id}/review-date", response_model=AggregationRead, tags=["aggregations"])
def change_aggregation_review_date(aggregation_id: int, payload: ReviewDateChange, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    existing = require_resource_operation(connection, "aggregation", aggregation_id, "aggregation.review_date.change", "aggregation.review_date.change")
    if existing["date_of_next_review"] == payload.date_of_next_review:
        return get_or_404(connection, "aggregations", aggregation_id)
    connection.execute("SELECT set_config('app.review_date_change_authorized','authorized',true),set_config('app.suppress_ordinary_history','authorized',true),set_config('app.change_reason',%s,true)", (payload.reason,))
    updated = update_row(connection, "aggregations", aggregation_id, {"date_of_next_review": payload.date_of_next_review}, version)
    connection.execute("SELECT append_domain_event('aggregation',%s,'REVIEW_DATE_CHANGED',%s::jsonb,%s)", (aggregation_id, Jsonb({"old_date_of_next_review": existing["date_of_next_review"].isoformat() if existing["date_of_next_review"] else None, "new_date_of_next_review": payload.date_of_next_review.isoformat() if payload.date_of_next_review else None, "authorization_basis": "governed"}), payload.reason))
    return updated


@app.post("/api/v1/records", response_model=RecordRead, status_code=status.HTTP_201_CREATED, tags=["records"])
def create_record(payload: RecordCreate, connection: Connection = Depends(get_connection, scope="function")):
    acquire_continuity_shared_lock(connection)
    parent = connection.execute(
        "SELECT id,medium FROM aggregations WHERE id=%s FOR KEY SHARE", (payload.aggregation_id,),
    ).fetchone()
    if parent is None:
        raise HTTPException(status_code=409, detail="referenced aggregation does not exist")
    require_resource_operation(connection, "aggregation", payload.aggregation_id,
                               "record.create", "aggregation.add_record")
    selected_role = _select_creator_role(
        connection, payload.creator_acl_role_id, payload.aggregation_id,
    )
    level_id = payload.security_level_id or connection.execute(
        "SELECT lowest_security_level_id() AS id"
    ).fetchone()["id"]
    require_clearance_for_level(connection, level_id)
    connection.execute(
        "SELECT set_config('app.creator_acl_role_id',%s,true),set_config('app.event_metadata',%s,true)",
        (str(selected_role["role_id"]), json.dumps({
            "creator_acl_role_id": selected_role["role_id"],
            "creator_acl_role_code": selected_role["role_code"],
            "creator_org_unit_id": selected_role["org_unit_id"],
        })),
    )
    values = payload.model_dump(exclude={"creator_acl_role_id"})
    values["medium"] = _resolved_record_medium(parent, payload.medium)
    return create_row(connection, "records", values)


@app.get("/api/v1/records", response_model=list[RecordRead], tags=["records"])
def list_records(
    aggregation_id: int | None = None,
    owning_org_unit_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    if aggregation_id is not None and connection.execute(
        "SELECT 1 FROM aggregations WHERE id=%s AND current_user_can_view_aggregation(id)",
        (aggregation_id,),
    ).fetchone() is None:
        return []
    return list_rows(
        connection,
        "records",
        limit=limit,
        offset=offset,
        filters={"aggregation_id": aggregation_id,
                 "owning_org_unit_id": owning_org_unit_id},
    )


@app.post(
    "/api/v1/records/search",
    response_model=None,
    tags=["records"],
)
def search_records(
    payload: SearchRequest,
    connection: Connection = Depends(get_connection, scope="function"),
):
    return search_rows(connection, "records", payload, endpoint="/api/v1/records/search")


@app.get("/api/v1/records/{record_id}", response_model=RecordRead, tags=["records"])
def get_record(record_id: int, connection: Connection = Depends(get_connection, scope="function")):
    record = get_or_404(connection, "records", record_id)
    audit_governance_view_if_used(connection, "record", record)
    return record


@app.get("/api/v1/records/{record_id}/capabilities", response_model=ResourceCapabilitiesRead, tags=["authorization"])
def get_record_capabilities(
    record_id: int,
    connection: Connection = Depends(get_connection, scope="function"),
):
    record = get_or_404(connection, "records", record_id)
    component_metadata = connection.execute(
        "SELECT current_user_can_list_record_components(%s) AS allowed", (record_id,),
    ).fetchone()["allowed"]
    mappings = {
        "modify_metadata": ("record.modify", "record.modify_metadata"),
        "delete": ("record.delete", "record.delete"),
        "move": ("record.move", "record.move"),
        "change_security_level": ("record.security_level.change", "record.security_level.change"),
        "manage_acl": ("record.acl.manage", "record.acl.manage"),
        "change_vital_status": ("record.vital_status.change", "record.vital_status.change"),
        "change_review_date": ("record.review_date.change", "record.review_date.change"),
        "view_component": ("record.component.view", "record.component.view"),
        "download_component": ("record.component.download", "record.component.download"),
        "add_component": ("record.component.add", "record.component.add"),
        "replace_component": ("record.component.replace", "record.component.replace"),
        "remove_component": ("record.component.remove", "record.component.remove"),
        "reorder_components": ("record.component.reorder", "record.component.reorder"),
        "share_component": ("record.component.share", "record.component.share"),
        "print_component": ("record.component.print", "record.component.print"),
        "reindex_components": ("record.component.reindex", "record.component.view"),
    }
    capabilities = {name: operation_allowed(connection, "record", record_id, *policy)
                    for name, policy in mappings.items()}
    capabilities.update({"view": True, "list_components": component_metadata})
    capability_reasons = {}
    hold_status = connection.execute(
        """SELECT count(*) effective_hold_count,
                  COALESCE(bool_or(preserve_resource_state),false) state_blocked
             FROM effective_holds_for_record(%s)""", (record_id,),
    ).fetchone()
    direct_holds = connection.execute(
        "SELECT count(*) count,COALESCE(bool_or(current_hold_actor_is_manager(hold_id)),false) any_manageable,COALESCE(bool_and(current_hold_actor_is_manager(hold_id)),true) all_manageable FROM hold_record_assignments WHERE record_id=%s",
        (record_id,),
    ).fetchone()
    capabilities.update({
        "is_on_effective_hold": hold_status["effective_hold_count"] > 0,
        "resource_state_changes_blocked": hold_status["state_blocked"],
        "add_to_hold": bool(connection.execute("SELECT EXISTS(SELECT 1 FROM holds WHERE current_hold_actor_is_manager(id)) value").fetchone()["value"]),
        "remove_from_hold": direct_holds["count"] > 0 and direct_holds["any_manageable"],
        "remove_all_direct_hold_assignments": direct_holds["count"] > 0 and direct_holds["all_manageable"],
    })
    capabilities["effective_hold_count"] = hold_status["effective_hold_count"]
    if not capabilities["add_to_hold"]: capability_reasons["add_to_hold"]="hold_held_item_manager_required"
    if direct_holds["count"] and not capabilities["remove_from_hold"]: capability_reasons["remove_from_hold"]="hold_held_item_manager_required"
    if direct_holds["count"] and not capabilities["remove_all_direct_hold_assignments"]: capability_reasons["remove_all_direct_hold_assignments"]="not_all_direct_holds_manageable"
    if hold_status["effective_hold_count"]:
        capabilities["delete"] = False; capability_reasons["delete"] = "effective_hold_prevents_deletion"
        for name in ("add_component","replace_component","remove_component","reorder_components"):
            capabilities[name] = False; capability_reasons[name] = "effective_hold_prevents_component_" + ({"add_component":"addition","replace_component":"replacement","remove_component":"deletion","reorder_components":"reordering"}[name])
    if hold_status["state_blocked"]:
        for name in ("modify_metadata","move","change_vital_status","change_review_date"):
            capabilities[name] = False; capability_reasons[name] = "effective_hold_prevents_metadata_change"
    if record["medium"] == "physical":
        capabilities["add_component"] = False
        capabilities["replace_component"] = False
        capability_reasons["add_component"] = "physical_record_disallows_digital_components"
        capability_reasons["replace_component"] = "physical_record_disallows_digital_components"
    if record["is_vital"]:
        capabilities["delete"] = False
        capability_reasons["delete"] = "vital_resource_deletion_blocked"
    return {"resource_type": "record", "resource_id": record_id,
            "capabilities": capabilities, "capability_reasons": capability_reasons}


@app.patch("/api/v1/records/{record_id}", response_model=RecordRead, tags=["records"])
def update_record(
    record_id: int,
    payload: RecordUpdate,
    request: Request,
    version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    existing = lock_visible_resource(connection, "record", record_id)
    fields = payload.model_fields_set
    metadata_fields = {"record_number", "title", "description", "date_originated"}
    if fields & metadata_fields:
        require_resource_operation(
            connection, "record", record_id, "record.modify", "record.modify_metadata",
        )
    destination = None
    if "aggregation_id" in fields and payload.aggregation_id != existing["aggregation_id"]:
        require_resource_operation(connection, "record", record_id, "record.move", "record.move")
        destination = require_resource_operation(connection, "aggregation", payload.aggregation_id,
                                   "record.move", "aggregation.receive_record")
        if destination["owning_org_unit_id"] != existing["owning_org_unit_id"]:
            raise HTTPException(status_code=422, detail={
                "code": "ownership_change_requires_confirmation",
                "message": "Use the move command and confirm the organizational ownership change.",
            })
    if "medium" in fields and payload.medium != existing["medium"]:
        require_resource_operation(
            connection, "record", record_id, "record.modify", "record.modify_metadata",
        )
        if payload.medium == "physical" and connection.execute(
            "SELECT 1 FROM digital_components WHERE record_id=%s LIMIT 1", (record_id,),
        ).fetchone():
            raise _medium_error(
                "physical_record_has_digital_components",
                "Remove all digital components before changing this record to physical.",
            )
        medium_change_reason = decode_change_reason(request.headers.get("X-Change-Reason", "")).strip()
        if not medium_change_reason:
            raise _medium_error(
                "medium_change_reason_required",
                "Enter a reason for changing this record's medium.",
            )
        connection.execute(
            "SELECT set_config('app.change_reason',%s,true)", (medium_change_reason,),
        )
    if destination is None:
        parent_id = payload.aggregation_id if "aggregation_id" in fields else existing["aggregation_id"]
        destination = connection.execute(
            "SELECT id,medium FROM aggregations WHERE id=%s FOR KEY SHARE", (parent_id,),
        ).fetchone()
    resulting_medium = payload.medium if "medium" in fields else existing["medium"]
    _resolved_record_medium(destination, resulting_medium)
    if "security_level_id" in fields and payload.security_level_id != existing["security_level_id"]:
        require_resource_operation(connection, "record", record_id,
                                   "record.security_level.change", "record.security_level.change")
        require_clearance_for_level(connection, payload.security_level_id)
        if not decode_change_reason(request.headers.get("X-Change-Reason", "")).strip():
            raise HTTPException(status_code=422, detail="X-Change-Reason is required when changing a security level")
    new_level_id = payload.security_level_id if "security_level_id" in payload.model_fields_set else None
    reason, old_number, new_number = validate_security_level_change(
        connection, request, existing["security_level_id"], new_level_id
    )
    if new_level_id is not None and new_number < old_number:
        require_global(connection, "security.resource.downgrade")
    updated = update_row(connection, "records", record_id, payload.model_dump(exclude_unset=True), version)
    if "medium" in fields and payload.medium != existing["medium"]:
        connection.execute(
            "SELECT append_domain_event('record',%s,'MEDIUM_CHANGED',%s::jsonb,%s)",
            (record_id, Jsonb({"old_medium": existing["medium"], "new_medium": payload.medium}),
             medium_change_reason),
        )
    append_security_level_event(
        connection, entity_type="record", entity_id=record_id,
        old_security_level_id=existing["security_level_id"], new_security_level_id=new_level_id,
        old_level_number=old_number, new_level_number=new_number, reason=reason,
    )
    return updated


@app.delete("/api/v1/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["records"])
def delete_record(record_id: int, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    require_resource_operation(connection, "record", record_id, "record.delete", "record.delete")
    delete_row(connection, "records", record_id, version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/v1/records/{record_id}/vital-status", response_model=RecordRead, tags=["records"])
def change_record_vital_status(record_id: int, payload: VitalStatusChange, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    existing = require_resource_operation(connection, "record", record_id, "record.vital_status.change", "record.vital_status.change")
    if existing["is_vital"] == payload.is_vital:
        return get_or_404(connection, "records", record_id)
    connection.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true),set_config('app.suppress_ordinary_history','authorized',true),set_config('app.change_reason',%s,true)", (payload.reason,))
    updated = update_row(connection, "records", record_id, {"is_vital": payload.is_vital}, version)
    connection.execute("SELECT append_domain_event('record',%s,'VITAL_STATUS_CHANGED',%s::jsonb,%s)", (record_id, Jsonb({"old_is_vital": existing["is_vital"], "new_is_vital": payload.is_vital, "authorization_basis": "governed"}), payload.reason))
    return updated


@app.post("/api/v1/records/{record_id}/review-date", response_model=RecordRead, tags=["records"])
def change_record_review_date(record_id: int, payload: ReviewDateChange, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    existing = require_resource_operation(connection, "record", record_id, "record.review_date.change", "record.review_date.change")
    if existing["date_of_next_review"] == payload.date_of_next_review:
        return get_or_404(connection, "records", record_id)
    connection.execute("SELECT set_config('app.review_date_change_authorized','authorized',true),set_config('app.suppress_ordinary_history','authorized',true),set_config('app.change_reason',%s,true)", (payload.reason,))
    updated = update_row(connection, "records", record_id, {"date_of_next_review": payload.date_of_next_review}, version)
    connection.execute("SELECT append_domain_event('record',%s,'REVIEW_DATE_CHANGED',%s::jsonb,%s)", (record_id, Jsonb({"old_date_of_next_review": existing["date_of_next_review"].isoformat() if existing["date_of_next_review"] else None, "new_date_of_next_review": payload.date_of_next_review.isoformat() if payload.date_of_next_review else None, "authorization_basis": "governed"}), payload.reason))
    return updated


def _effective_closure(connection: Connection, aggregation_id: int) -> dict | None:
    return connection.execute(
        """WITH RECURSIVE ancestry AS (
             SELECT id,parent_aggregation_id,date_closed,0 AS depth FROM aggregations WHERE id=%s
             UNION ALL SELECT parent.id,parent.parent_aggregation_id,parent.date_closed,child.depth+1
             FROM aggregations parent JOIN ancestry child ON child.parent_aggregation_id=parent.id)
           SELECT id,date_closed FROM ancestry WHERE date_closed IS NOT NULL ORDER BY depth LIMIT 1""",
        (aggregation_id,),
    ).fetchone()


@app.get("/api/v1/aggregations/{aggregation_id}/effective-closure", tags=["aggregations"])
def get_effective_aggregation_closure(
    aggregation_id: int,
    connection: Connection = Depends(get_connection, scope="function"),
):
    """Return only the nearest closure needed by collection and component UIs.

    This deliberately avoids requiring clients to download the aggregation
    hierarchy merely to determine whether one resource is effectively closed.
    """
    require_resource_operation(
        connection, "aggregation", aggregation_id,
        "aggregation.view", "aggregation.view",
        lock=False,
    )
    closure = _effective_closure(connection, aggregation_id)
    if closure is not None:
        closure = connection.execute(
            "SELECT id, aggregation_number, title, date_closed FROM aggregations WHERE id=%s",
            (closure["id"],),
        ).fetchone()
    return {"closure": closure}


def _governance_basis(connection: Connection, security_level_ids: list[int]) -> list[dict]:
    return list(connection.execute(
        """SELECT DISTINCT role.id,role.code,role.name,level.level_number
           FROM user_role_assignments assignment JOIN roles role ON role.id=assignment.role_id
           JOIN security_levels level ON level.id=role.security_level_id
           JOIN security_levels required ON required.id=ANY(%s)
           WHERE assignment.user_id=current_user_id() AND role.is_information_governance
             AND assignment.valid_from<=CURRENT_TIMESTAMP
             AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
             AND role_effectively_active(role.id) AND level.level_number>=required.level_number
           ORDER BY role.id""", (security_level_ids,),
    ).fetchall())


@app.post("/api/v1/records/{record_id}/correct-placement", response_model=RecordRead, tags=["records"])
def correct_record_placement(
    record_id: int, payload: RecordPlacementCorrection, request: Request,
    version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    source = require_resource_operation(connection, "record", record_id, "record.move", "record.move")
    reason = decode_change_reason(request.headers.get("X-Change-Reason", "")).strip()
    if not reason:
        raise HTTPException(status_code=422, detail="X-Change-Reason is required")
    destination = require_closed_placement_correction(
        connection, payload.destination_aggregation_id, source["security_level_id"], "record.move",
    )
    closure = _effective_closure(connection, destination["id"])
    if closure is None:
        raise HTTPException(status_code=409, detail="destination is not effectively closed; use the ordinary move operation")
    if source["aggregation_id"] == destination["id"]:
        raise HTTPException(status_code=409, detail="record is already in the destination aggregation")
    basis = _governance_basis(connection, [source["security_level_id"], destination["security_level_id"]])
    connection.execute(
        "SELECT set_config('app.closed_record_placement_correction','authorized',true), set_config('app.change_reason',%s,true)",
        (reason,),
    )
    moved = update_row(connection, "records", record_id, {"aggregation_id": destination["id"]}, version)
    connection.execute(
        "SELECT append_domain_event('record',%s,'CLOSED_AGGREGATION_RECORD_CORRECTED',%s::jsonb,%s)",
        (record_id, Jsonb({"source_aggregation_id": source["aggregation_id"],
                          "destination_aggregation_id": destination["id"],
                          "effective_closure_aggregation_id": closure["id"],
                          "effective_closure_date": closure["date_closed"].isoformat(),
                          "closure_date_unchanged": True,
                          "authorization_basis": "information_governance",
                          "governance_roles": basis}), reason),
    )
    return moved


def _open_draft(connection: Connection, draft_id: int, *, lock: bool = False) -> dict:
    # A draft, including its staged components, is the in-progress record
    # creation package. Re-evaluate record.create on every operation so a
    # privilege removed after the draft was opened takes effect immediately.
    require_global(connection, "record.create")
    require_draft_owner(connection, draft_id)
    suffix = " FOR UPDATE" if lock else ""
    draft = connection.execute(
        f"SELECT * FROM record_drafts WHERE id = %s{suffix}", (draft_id,)
    ).fetchone()
    if draft is None:
        raise HTTPException(status_code=404, detail="record draft not found")
    if draft["expires_at"] <= datetime.now(draft["expires_at"].tzinfo):
        raise HTTPException(status_code=410, detail="record draft has expired")
    return draft


@app.post("/api/v1/record-drafts", response_model=RecordDraftRead, status_code=201, tags=["record drafts"])
def create_record_draft(payload: RecordDraftCreate, connection: Connection = Depends(get_connection, scope="function")):
    require_global(connection, "record.create")
    values = payload.model_dump(exclude_none=True)
    if payload.aggregation_id is not None:
        parent = connection.execute(
            "SELECT id,medium FROM aggregations WHERE id=%s FOR KEY SHARE",
            (payload.aggregation_id,),
        ).fetchone()
        if parent is None:
            raise HTTPException(status_code=409, detail="referenced aggregation does not exist")
        values["medium"] = _resolved_record_medium(parent, payload.medium)
    values["owner_user_id"] = connection.execute("SELECT current_user_id() AS id").fetchone()["id"]
    if not values:
        return connection.execute("INSERT INTO record_drafts DEFAULT VALUES RETURNING *").fetchone()
    return create_row(connection, "record_drafts", values)


@app.get("/api/v1/record-drafts/{draft_id}", response_model=RecordDraftRead, tags=["record drafts"])
def get_record_draft(draft_id: int, connection: Connection = Depends(get_connection, scope="function")):
    return _open_draft(connection, draft_id)


@app.patch("/api/v1/record-drafts/{draft_id}", response_model=RecordDraftRead, tags=["record drafts"])
def update_record_draft(draft_id: int, payload: RecordDraftUpdate, connection: Connection = Depends(get_connection, scope="function")):
    draft = _open_draft(connection, draft_id)
    values = payload.model_dump(exclude_unset=True)
    messaging_capture.validate_medium(connection, draft_id, values.get("medium", draft["medium"]))
    aggregation_id = values.get("aggregation_id", draft["aggregation_id"])
    if aggregation_id is not None:
        parent = connection.execute(
            "SELECT id,medium FROM aggregations WHERE id=%s FOR KEY SHARE", (aggregation_id,),
        ).fetchone()
        if parent is None:
            raise HTTPException(status_code=409, detail="referenced aggregation does not exist")
        values["medium"] = _resolved_record_medium(
            parent, values.get("medium", draft.get("medium")),
        )
    if values.get("medium") == "physical" and draft.get("medium") != "physical" and connection.execute(
        "SELECT 1 FROM record_draft_components WHERE draft_id=%s LIMIT 1", (draft_id,),
    ).fetchone():
        raise _medium_error(
            "physical_record_has_staged_components",
            "Remove all staged digital files before changing this draft to physical.",
        )
    if not values:
        return _open_draft(connection, draft_id)
    assignments = ", ".join(f"{key} = %s" for key in values)
    return connection.execute(
        f"UPDATE record_drafts SET {assignments} WHERE id = %s RETURNING *",
        (*values.values(), draft_id),
    ).fetchone()


@app.delete("/api/v1/record-drafts/{draft_id}", status_code=204, tags=["record drafts"])
def discard_record_draft(draft_id: int, connection: Connection = Depends(get_connection, scope="function")):
    _open_draft(connection, draft_id, lock=True)
    connection.execute("DELETE FROM record_drafts WHERE id = %s", (draft_id,))
    return Response(status_code=204)


@app.get("/api/v1/record-drafts/{draft_id}/components", response_model=list[RecordDraftComponentRead], tags=["record drafts"])
def list_record_draft_components(draft_id: int, connection: Connection = Depends(get_connection, scope="function")):
    _open_draft(connection, draft_id)
    return list(connection.execute(
        """SELECT id, draft_id, component_order, file_name, date_created,
                  date_originated, mime_type, size_in_bytes, checksum_algo,
                  checksum_value, 'staged' AS content_status,
                  'temporary' AS storage_backend
           FROM record_draft_components WHERE draft_id = %s ORDER BY component_order""",
        (draft_id,),
    ).fetchall())


@app.post("/api/v1/record-drafts/{draft_id}/components", response_model=RecordDraftComponentRead, status_code=201, tags=["record drafts"])
def upload_record_draft_component(
    draft_id: int,
    file: UploadFile = File(...),
    component_order: int = Form(..., gt=0),
    date_originated: datetime | None = Form(default=None),
    connection: Connection = Depends(get_connection, scope="function"),
):
    draft = _open_draft(connection, draft_id, lock=True)
    messaging_capture.protect_components(connection, draft_id)
    _require_draft_accepts_components(draft)
    inspected = inspect_upload(file)
    component = connection.execute(
        """INSERT INTO record_draft_components
               (draft_id, component_order, file_name, date_originated, mime_type,
                size_in_bytes, checksum_algo, checksum_value, content_status)
           VALUES (%s, %s, %s, COALESCE(%s, CURRENT_TIMESTAMP), %s, %s, 'sha256', %s, 'uploading')
           RETURNING id""",
        (draft_id, component_order, file.filename or "unnamed", date_originated,
         file.content_type or "application/octet-stream", inspected.size_in_bytes,
         inspected.checksum_value),
    ).fetchone()
    configured_storage().store_draft_upload(connection, component["id"], file)
    component = connection.execute(
        """SELECT id, draft_id, component_order, file_name, date_created,
                  date_originated, mime_type, size_in_bytes, checksum_algo,
                  checksum_value, 'staged' AS content_status,
                  'temporary' AS storage_backend
           FROM record_draft_components WHERE id = %s""",
        (component["id"],),
    ).fetchone()
    connection.execute("UPDATE record_drafts SET date_updated = CURRENT_TIMESTAMP WHERE id = %s", (draft_id,))
    return component


def _reorder_components(connection: Connection, table: str, parent_column: str, parent_id: int, payload: ComponentReorderRequest) -> None:
    requested = {item.id: item.component_order for item in payload.components}
    if len(requested) != len(payload.components) or set(requested.values()) != set(range(1, len(requested) + 1)):
        raise HTTPException(status_code=422, detail="component order must contain each position from 1 through the component count")
    existing = {
        row["id"] for row in connection.execute(
            f"SELECT id FROM {table} WHERE {parent_column} = %s FOR UPDATE", (parent_id,)
        ).fetchall()
    }
    if existing != set(requested):
        raise HTTPException(status_code=422, detail="component list must contain every component exactly once")
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    for component_id, position in requested.items():
        connection.execute(
            f"UPDATE {table} SET component_order = %s WHERE id = %s", (position, component_id)
        )


@app.put("/api/v1/record-drafts/{draft_id}/components/order", status_code=204, tags=["record drafts"])
def reorder_record_draft_components(draft_id: int, payload: ComponentReorderRequest, connection: Connection = Depends(get_connection, scope="function")):
    _open_draft(connection, draft_id, lock=True)
    messaging_capture.protect_components(connection, draft_id)
    _reorder_components(connection, "record_draft_components", "draft_id", draft_id, payload)
    connection.execute("UPDATE record_drafts SET date_updated = CURRENT_TIMESTAMP WHERE id = %s", (draft_id,))
    return Response(status_code=204)


@app.delete("/api/v1/record-drafts/{draft_id}/components/{component_id}", status_code=204, tags=["record drafts"])
def delete_record_draft_component(draft_id: int, component_id: int, connection: Connection = Depends(get_connection, scope="function")):
    _open_draft(connection, draft_id, lock=True)
    messaging_capture.protect_components(connection, draft_id)
    deleted = connection.execute(
        "DELETE FROM record_draft_components WHERE id = %s AND draft_id = %s RETURNING id",
        (component_id, draft_id),
    ).fetchone()
    if deleted is None:
        raise HTTPException(status_code=404, detail="record draft component not found")
    rows = connection.execute(
        "SELECT id FROM record_draft_components WHERE draft_id = %s ORDER BY component_order", (draft_id,)
    ).fetchall()
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    for position, row in enumerate(rows, 1):
        connection.execute("UPDATE record_draft_components SET component_order = %s WHERE id = %s", (position, row["id"]))
    connection.execute("UPDATE record_drafts SET date_updated = CURRENT_TIMESTAMP WHERE id = %s", (draft_id,))
    return Response(status_code=204)


@app.post("/api/v1/record-drafts/{draft_id}/commit", response_model=RecordRead, status_code=201, tags=["record drafts"])
def commit_record_draft(
    draft_id: int, request: Request, creator_acl_role_id: int | None = None,
    connection: Connection = Depends(get_connection, scope="function"),
):
    draft = _open_draft(connection, draft_id, lock=True)
    request.state.message_capture = messaging_capture.capture_draft(connection, draft_id) is not None
    capture = messaging_capture.prepare(connection, draft)
    missing = [name for name in ("aggregation_id", "medium", "record_number", "title") if not draft.get(name)]
    if missing:
        raise HTTPException(status_code=422, detail=f"draft is missing required fields: {', '.join(missing)}")
    security_level_id = draft["security_level_id"]
    if security_level_id is None:
        security_level_id = connection.execute(
            "SELECT id FROM security_levels ORDER BY level_number,id LIMIT 1"
        ).fetchone()["id"]
    require_resource_operation(
        connection, "aggregation", draft["aggregation_id"],
        "record.create", "aggregation.add_record",
    )
    parent = connection.execute(
        "SELECT id,medium FROM aggregations WHERE id=%s FOR KEY SHARE", (draft["aggregation_id"],),
    ).fetchone()
    medium = _resolved_record_medium(parent, draft.get("medium"))
    selected_role = _select_creator_role(
        connection, creator_acl_role_id, draft["aggregation_id"],
    )
    require_clearance_for_level(connection, security_level_id)
    connection.execute(
        "SELECT set_config('app.creator_acl_role_id',%s,true),set_config('app.event_metadata',%s,true)",
        (str(selected_role["role_id"]), json.dumps({
            "workflow": "message_capture" if capture else "record_creation",
            "creator_acl_role_id": selected_role["role_id"],
            "creator_acl_role_code": selected_role["role_code"],
            "creator_org_unit_id": selected_role["org_unit_id"],
        })),
    )
    components = connection.execute(
        "SELECT * FROM record_draft_components WHERE draft_id = %s ORDER BY component_order FOR UPDATE", (draft_id,)
    ).fetchall()
    if medium == "physical" and components:
        raise HTTPException(status_code=409, detail={
            "code": "physical_record_disallows_digital_components",
            "message": "This is a physical record. Digital files cannot be added.",
        })
    record = create_row(connection, "records", {
        "aggregation_id": draft["aggregation_id"], "record_number": draft["record_number"],
        "title": draft["title"], "description": draft["description"],
        "date_originated": draft["date_originated"],
        "security_level_id": security_level_id,
        "medium": medium,
        "is_vital": draft["is_vital"],
        "date_of_next_review": draft["date_of_next_review"],
    })
    if capture:
        messaging_capture.finalize_staging(connection, draft, record, capture)
        components = connection.execute("SELECT * FROM record_draft_components WHERE draft_id=%s ORDER BY component_order FOR UPDATE", (draft_id,)).fetchall()
    committed_components = []
    incomplete = [item["file_name"] for item in components if item["content_status"] != "available"]
    if incomplete:
        raise HTTPException(status_code=409, detail="all draft component uploads must be complete")
    for staged in components:
        component = create_row(connection, "digital_components", {
            "record_id": record["id"], "component_order": staged["component_order"],
            "file_name": staged["file_name"], "date_originated": staged["date_originated"],
            "mime_type": staged["mime_type"], "size_in_bytes": staged["size_in_bytes"],
            "checksum_algo": staged["checksum_algo"], "checksum_value": staged["checksum_value"],
            "storage_backend": "postgresql", "content_status": "available",
        })
        committed_components.append(component["id"])
        configured_storage().promote_draft(connection, staged["id"], component["id"])
        _append_content_event(connection, component["id"], "CONTENT_UPLOADED", {
            "file_name": component["file_name"], "mime_type": component["mime_type"],
            "size_in_bytes": component["size_in_bytes"], "checksum_algo": component["checksum_algo"],
            "checksum_value": component["checksum_value"], "record_creation": True,
            "workflow": "message_capture" if capture else "record_creation",
        })
    if capture:
        messaging_capture.persist(connection, draft, record, capture, committed_components)
    connection.execute("DELETE FROM record_drafts WHERE id = %s", (draft_id,))
    return record


@app.post("/api/v1/record-drafts/{draft_id}/commit-placement-correction", response_model=RecordRead, status_code=201, tags=["record drafts"])
def commit_record_draft_placement_correction(
    draft_id: int,
    request: Request,
    creator_acl_role_id: int | None = None,
    connection: Connection = Depends(get_connection, scope="function"),
):
    draft = _open_draft(connection, draft_id, lock=True)
    messaging_capture.protect_components(connection, draft_id)
    if not draft.get("aggregation_id"):
        raise HTTPException(status_code=422, detail="draft destination is required")
    security_level_id = draft["security_level_id"]
    if security_level_id is None:
        security_level_id = connection.execute(
            "SELECT id FROM security_levels ORDER BY level_number,id LIMIT 1"
        ).fetchone()["id"]
    reason = decode_change_reason(request.headers.get("X-Change-Reason", "")).strip()
    if not reason:
        raise HTTPException(status_code=422, detail="X-Change-Reason is required")
    destination = require_closed_placement_correction(
        connection, draft["aggregation_id"], security_level_id, "record.create",
    )
    closure = _effective_closure(connection, destination["id"])
    if closure is None:
        raise HTTPException(status_code=409, detail="destination is not effectively closed; use the ordinary commit operation")
    basis = _governance_basis(connection, [security_level_id, destination["security_level_id"]])
    connection.execute(
        "SELECT set_config('app.closed_record_placement_correction','authorized',true), set_config('app.change_reason',%s,true)",
        (reason,),
    )
    record = commit_record_draft(draft_id, creator_acl_role_id, connection)
    connection.execute(
        "SELECT append_domain_event('record',%s,'CLOSED_AGGREGATION_RECORD_CORRECTED',%s::jsonb,%s)",
        (record["id"], Jsonb({
            "source_aggregation_id": None,
            "destination_aggregation_id": destination["id"],
            "effective_closure_aggregation_id": closure["id"],
            "effective_closure_date": closure["date_closed"].isoformat(),
            "closure_date_unchanged": True,
            "authorization_basis": "information_governance",
            "governance_roles": basis,
        }), reason),
    )
    return record


@app.post(
    "/api/v1/digital-components",
    response_model=DigitalComponentRead,
    status_code=status.HTTP_201_CREATED,
    tags=["digital components"],
    deprecated=True,
    summary="Create digital-component metadata (deprecated)",
    description=(
        "Deprecated: this operation creates metadata only and does not upload or "
        "verify file content. Use `POST "
        "/api/v1/records/{record_id}/digital-components/upload` to create a usable "
        "digital component with its metadata and stored content."
    ),
)
def create_digital_component(
    payload: DigitalComponentCreate,
    connection: Connection = Depends(get_connection, scope="function"),
):
    require_resource_operation(connection, "record", payload.record_id,
                               "record.component.add", "record.component.add")
    _require_record_accepts_components(connection, payload.record_id)
    return create_row(connection, "digital_components", payload.model_dump())


@app.get(
    "/api/v1/digital-components",
    response_model=list[DigitalComponentRead],
    tags=["digital components"],
)
def list_digital_components(
    record_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    return list_rows(
        connection,
        "digital_components",
        limit=limit,
        offset=offset,
        filters={"record_id": record_id},
        order_by=("record_id", "component_order"),
    )


@app.post(
    "/api/v1/digital-components/search",
    response_model=None,
    tags=["digital components"],
)
def search_digital_components(
    payload: SearchRequest,
    connection: Connection = Depends(get_connection, scope="function"),
):
    return search_rows(connection, "digital_components", payload, endpoint="/api/v1/digital-components/search")


@app.get(
    "/api/v1/digital-components/{component_id}",
    response_model=DigitalComponentRead,
    tags=["digital components"],
)
def get_digital_component(component_id: int, connection: Connection = Depends(get_connection, scope="function")):
    return get_or_404(connection, "digital_components", component_id)


@app.patch(
    "/api/v1/digital-components/{component_id}",
    response_model=DigitalComponentRead,
    tags=["digital components"],
)
def update_digital_component(
    component_id: int,
    payload: DigitalComponentUpdate,
    version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    component, _ = require_component_operation(
        connection, component_id, "record.component.replace", "record.component.replace")
    if "record_id" in payload.model_fields_set and payload.record_id != component["record_id"]:
        raise HTTPException(status_code=422, detail="moving digital components between records is not supported")
    return update_row(
        connection,
        "digital_components",
        component_id,
        payload.model_dump(exclude_unset=True),
        version,
    )


@app.delete(
    "/api/v1/digital-components/{component_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["digital components"],
)
def delete_digital_component(
    component_id: int,
    version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    component, _ = require_component_operation(
        connection, component_id, "record.component.remove", "record.component.remove")
    delete_row(connection, "digital_components", component_id, version)
    remaining = connection.execute(
        "SELECT id FROM digital_components WHERE record_id = %s ORDER BY component_order",
        (component["record_id"],),
    ).fetchall()
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    for position, row in enumerate(remaining, 1):
        connection.execute(
            "UPDATE digital_components SET component_order = %s WHERE id = %s",
            (position, row["id"]),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.put(
    "/api/v1/records/{record_id}/digital-components/order",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["digital components"],
)
def reorder_digital_components(
    record_id: int,
    payload: ComponentReorderRequest,
    connection: Connection = Depends(get_connection, scope="function"),
):
    require_resource_operation(connection, "record", record_id,
                               "record.component.reorder", "record.component.reorder")
    _reorder_components(connection, "digital_components", "record_id", record_id, payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post(
    "/api/v1/records/{record_id}/digital-components/{component_id}/move",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["digital components"],
)
def move_digital_component(
    record_id: int,
    component_id: int,
    payload: ComponentMoveRequest,
    connection: Connection = Depends(get_connection, scope="function"),
):
    """Move one component by one position without downloading the full list."""
    require_resource_operation(
        connection, "record", record_id,
        "record.component.reorder", "record.component.reorder",
    )
    rows = list(connection.execute(
        """SELECT id,component_order FROM digital_components
            WHERE record_id=%s ORDER BY component_order,id FOR UPDATE""",
        (record_id,),
    ).fetchall())
    index = next((position for position, row in enumerate(rows) if row["id"] == component_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="digital component not found")
    target_index = index + payload.direction
    if target_index < 0 or target_index >= len(rows):
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    current = rows[index]
    target = rows[target_index]
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    connection.execute(
        "UPDATE digital_components SET component_order=%s WHERE id=%s",
        (target["component_order"], current["id"]),
    )
    connection.execute(
        "UPDATE digital_components SET component_order=%s WHERE id=%s",
        (current["component_order"], target["id"]),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _append_content_event(
    connection: Connection,
    component_id: int,
    operation: str,
    metadata: dict,
) -> None:
    connection.execute(
        "SELECT append_domain_event(%s, %s, %s, %s)",
        ("digital_component", component_id, operation, Jsonb(metadata)),
    )


def _content_range(value: str | None, total: int) -> tuple[int, int, int]:
    """Return an inclusive-exclusive byte interval and HTTP response status."""
    if value is None:
        return 0, total, 200
    if not value.startswith("bytes=") or "," in value:
        raise HTTPException(
            status_code=416, detail="invalid or multiple byte ranges are not supported",
            headers={"Content-Range": f"bytes */{total}"},
        )
    specification = value[6:].strip()
    try:
        first, last = specification.split("-", 1)
        if not first:
            suffix = int(last)
            if suffix <= 0 or total == 0:
                raise ValueError
            start = max(0, total - suffix)
            end = total
        else:
            start = int(first)
            end = total if not last else min(total, int(last) + 1)
            if start < 0 or start >= total or end <= start:
                raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=416, detail="requested byte range is not satisfiable",
            headers={"Content-Range": f"bytes */{total}"},
        )
    return start, end, 206


@app.post(
    "/api/v1/records/{record_id}/digital-components/upload",
    response_model=DigitalComponentRead,
    status_code=status.HTTP_201_CREATED,
    tags=["digital component content"],
)
def upload_digital_component(
    record_id: int,
    file: UploadFile = File(...),
    component_order: int = Form(..., gt=0),
    date_originated: datetime | None = Form(default=None),
    connection: Connection = Depends(get_connection, scope="function"),
):
    require_resource_operation(connection, "record", record_id,
                               "record.component.add", "record.component.add")
    _require_record_accepts_components(connection, record_id)
    inspected = inspect_upload(file)
    mime_type = file.content_type or "application/octet-stream"
    component = create_row(
        connection,
        "digital_components",
        {
            "record_id": record_id,
            "component_order": component_order,
            "file_name": file.filename or "unnamed",
            "date_originated": date_originated,
            "mime_type": mime_type,
            "size_in_bytes": inspected.size_in_bytes,
            "checksum_algo": "sha256",
            "checksum_value": inspected.checksum_value,
            "storage_backend": "postgresql",
            "content_status": "available",
        },
    )
    uploaded = configured_storage().store_upload(connection, component["id"], file)
    component = get_or_404(connection, "digital_components", component["id"])
    _append_content_event(
        connection,
        component["id"],
        "CONTENT_UPLOADED",
        {"file_name": component["file_name"], "mime_type": mime_type,
         "size_in_bytes": uploaded.size_in_bytes, "checksum_algo": "sha256",
         "checksum_value": uploaded.checksum_value},
    )
    return component


@app.head(
    "/api/v1/digital-components/{component_id}/content",
    include_in_schema=False,
)
@app.get(
    "/api/v1/digital-components/{component_id}/content",
    tags=["digital component content"],
)
def download_digital_component_content(
    component_id: int,
    request: Request,
    connection: Connection = Depends(get_connection, scope="function"),
):
    component, _ = require_component_operation(
        connection, component_id, "record.component.download", "record.component.download")
    storage = configured_storage()
    location = storage.location(connection, component_id)
    if location is None:
        raise HTTPException(status_code=404, detail="digital component content not found")
    _append_content_event(connection, component_id, "CONTENT_DOWNLOADED", {
        "size_in_bytes": component["size_in_bytes"],
        "checksum_algo": component["checksum_algo"],
        "checksum_value": component["checksum_value"],
    })
    encoded_name = quote(component["file_name"], safe="")
    start, end, response_status = _content_range(request.headers.get("range"), location.size_in_bytes)
    length = end - start
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
        "Content-Length": str(length),
        "Accept-Ranges": "bytes",
        "ETag": f'"sha256-{component["checksum_value"]}"',
    }
    if response_status == 206:
        headers["Content-Range"] = f"bytes {start}-{end - 1}/{location.size_in_bytes}"
    if request.method == "HEAD":
        return Response(status_code=response_status, media_type=component["mime_type"], headers=headers)
    return StreamingResponse(
        storage.iter_content(location, start, end),
        status_code=response_status,
        media_type=component["mime_type"],
        headers=headers,
    )


def _component_rendition_response(
    component: dict, request: Request, connection: Connection,
):
    storage = configured_storage()
    component_id = component["id"]
    location = storage.location(connection, component_id)
    if location is None:
        raise HTTPException(status_code=404, detail="digital component content not found")
    mime_type = component["mime_type"].lower()
    native_preview = (
        mime_type in {
            "image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/avif",
        }
        or mime_type.startswith("audio/")
        or mime_type.startswith("video/")
    )
    if native_preview or mime_type == "application/pdf":
        rendered_mime = mime_type if native_preview else "application/pdf"
        _append_content_event(connection, component_id, "CONTENT_VIEWED", {
            "rendition_mime_type": rendered_mime,
            "rendering_method": "browser-native" if native_preview else "original",
            "original_checksum": component["checksum_value"],
        })
        encoded_name = quote(component["file_name"], safe="")
        start, end, response_status = _content_range(request.headers.get("range"), location.size_in_bytes)
        headers = {
            "Content-Disposition": f"inline; filename*=UTF-8''{encoded_name}",
            "Content-Length": str(end - start),
            "Accept-Ranges": "bytes",
            "ETag": f'"sha256-{component["checksum_value"]}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        }
        if response_status == 206:
            headers["Content-Range"] = f"bytes {start}-{end - 1}/{location.size_in_bytes}"
        if request.method == "HEAD":
            return Response(status_code=response_status, media_type=rendered_mime, headers=headers)
        # The web viewer buffers renditions before passing them to PDF.js or a
        # native media control. Finish the database read before the response is
        # sent so an interrupted browser request cannot strand a server-side
        # cursor, poison its pooled connection, or terminate a fixed-length
        # response early.
        content = storage.read(connection, component_id)
        if content is None:
            raise HTTPException(status_code=404, detail="digital component content not found")
        if len(content) != location.size_in_bytes:
            raise HTTPException(status_code=500, detail="digital component content size mismatch")
        return Response(
            content=content[start:end], status_code=response_status,
            media_type=rendered_mime, headers=headers,
        )
    maximum_source = integer_environment("MAX_RENDITION_SIZE_BYTES", 100 * 1024 * 1024, minimum=1)
    if location.size_in_bytes > maximum_source:
        raise HTTPException(status_code=413, detail="source document exceeds the configured rendition size limit")
    content = storage.read(connection, component_id)
    if content is None:
        raise HTTPException(status_code=404, detail="digital component content not found")
    try:
        rendition, method = pdf_rendition(content, component["file_name"], mime_type)
    except UnsupportedPreview as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
    except ConversionUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    _append_content_event(connection, component_id, "CONTENT_VIEWED", {
        "rendition_mime_type": "application/pdf", "rendering_method": method,
        "original_checksum": component["checksum_value"],
    })
    encoded_name = quote(f"{component['file_name']}.pdf", safe="")
    return StreamingResponse(
        BytesIO(rendition),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{encoded_name}",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


@app.head(
    "/api/v1/digital-components/{component_id}/rendition",
    include_in_schema=False,
)
@app.get(
    "/api/v1/digital-components/{component_id}/rendition",
    tags=["digital component content"],
)
def view_digital_component_rendition(
    component_id: int,
    request: Request,
    connection: Connection = Depends(get_connection, scope="function"),
):
    component, _ = require_component_operation(
        connection, component_id, "record.component.view", "record.component.view")
    return _component_rendition_response(component, request, connection)


@app.head(
    "/api/v1/digital-components/{component_id}/print-rendition",
    include_in_schema=False,
)
@app.get(
    "/api/v1/digital-components/{component_id}/print-rendition",
    tags=["digital component content"],
)
def print_digital_component_rendition(
    component_id: int,
    request: Request,
    connection: Connection = Depends(get_connection, scope="function"),
):
    """Return a printable rendition only when the print operation is authorized."""
    component, _ = require_component_operation(
        connection, component_id, "record.component.print", "record.component.print")
    return _component_rendition_response(component, request, connection)


@app.put(
    "/api/v1/digital-components/{component_id}/content",
    response_model=DigitalComponentRead,
    tags=["digital component content"],
)
def replace_digital_component_content(
    component_id: int,
    file: UploadFile = File(...),
    version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    current, _ = require_component_operation(
        connection, component_id, "record.component.replace", "record.component.replace")
    if current["version"] != version:
        return update_row(connection, "digital_components", component_id, {}, version)
    mime_type = file.content_type or "application/octet-stream"
    inspected = inspect_upload(file)
    uploaded = configured_storage().store_upload(connection, component_id, file)
    component = update_row(connection, "digital_components", component_id, {
        "file_name": file.filename or "unnamed",
        "mime_type": mime_type,
        "size_in_bytes": inspected.size_in_bytes,
        "checksum_algo": "sha256",
        "checksum_value": inspected.checksum_value,
        "storage_backend": "postgresql",
        "storage_key": None,
        "content_status": "available",
    }, version)
    _append_content_event(connection, component_id, "CONTENT_REPLACED", {
        "file_name": component["file_name"], "mime_type": mime_type,
        "size_in_bytes": uploaded.size_in_bytes, "checksum_algo": "sha256",
        "checksum_value": uploaded.checksum_value,
    })
    return component


@app.delete(
    "/api/v1/digital-components/{component_id}/content",
    response_model=DigitalComponentRead,
    tags=["digital component content"],
)
def delete_digital_component_content(
    component_id: int,
    version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    require_component_operation(
        connection, component_id, "record.component.remove", "record.component.remove")
    configured_storage().delete(connection, component_id)
    component = update_row(connection, "digital_components", component_id, {
        "content_status": "deleted",
    }, version)
    _append_content_event(connection, component_id, "CONTENT_DELETED", {
        "size_in_bytes": component["size_in_bytes"],
        "checksum_algo": component["checksum_algo"],
        "checksum_value": component["checksum_value"],
    })
    return component


@app.get(
    "/api/v1/event-history",
    response_model=list[EventHistoryRead],
    tags=["event history"],
    dependencies=[Depends(require_audit_view)],
)
def list_event_history(
    entity_type: str | None = None,
    entity_id: int | None = None,
    operation: str | None = None,
    request_id: UUID | None = None,
    correlation_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    return list_rows(
        connection,
        "event_history",
        limit=limit,
        offset=offset,
        filters={
            "entity_type": entity_type,
            "entity_id": entity_id,
            "operation": operation,
            "request_id": request_id,
            "correlation_id": correlation_id,
        },
        order_by=("occurred_at", "id"),
        descending=True,
    )


@app.post(
    "/api/v1/event-history/search",
    response_model=None,
    tags=["event history"],
    dependencies=[Depends(require_audit_view)],
)
def search_event_history(
    payload: SearchRequest,
    connection: Connection = Depends(get_connection, scope="function"),
):
    return search_rows(connection, "event_history", payload, endpoint="/api/v1/event-history/search")


@app.get(
    "/api/v1/event-history/operations",
    response_model=list[str],
    tags=["event history"],
    dependencies=[Depends(require_audit_view)],
)
def list_event_history_operations(
    connection: Connection = Depends(get_connection, scope="function"),
):
    """Return every operation represented in the immutable audit history."""
    return _distinct_event_history_values(connection, "operation")


def _distinct_event_history_values(
    connection: Connection, column: str,
) -> list[str]:
    """Return sorted nonblank values for a trusted event-history column."""
    if column not in {"entity_type", "operation", "source", "actor_type"}:
        raise ValueError("unsupported event-history filter column")
    return [
        row[column]
        for row in connection.execute(
            f"""
            SELECT DISTINCT {column}
              FROM event_history
             WHERE {column} IS NOT NULL
               AND btrim({column}) <> ''
             ORDER BY {column}
            """
        ).fetchall()
    ]


@app.get(
    "/api/v1/event-history/filter-options",
    response_model=dict[str, list[str]],
    tags=["event history"],
    dependencies=[Depends(require_audit_view)],
)
def list_event_history_filter_options(
    connection: Connection = Depends(get_connection, scope="function"),
):
    """Return authoritative values for every categorical audit filter."""
    return {
        "entity_types": _distinct_event_history_values(connection, "entity_type"),
        "operations": _distinct_event_history_values(connection, "operation"),
        "sources": _distinct_event_history_values(connection, "source"),
        "actor_types": _distinct_event_history_values(connection, "actor_type"),
    }


@app.get(
    "/api/v1/event-history/actors",
    response_model=None,
    tags=["event history"],
    dependencies=[Depends(require_audit_view)],
)
def list_event_history_actors(
    q: str = Query(..., min_length=2, max_length=128),
    limit: int = Query(25, ge=1, le=25),
    entity_type: str | None = Query(None, max_length=100),
    actor_type: str | None = Query(None, max_length=40),
    connection: Connection = Depends(get_connection, scope="function"),
):
    from .audit_search import actor_suggestions

    return actor_suggestions(connection, q, limit=limit,
                             entity_type=entity_type, actor_type=actor_type)


@app.get(
    "/api/v1/event-history/{event_id}",
    response_model=EventHistoryRead,
    tags=["event history"],
    dependencies=[Depends(require_audit_view)],
)
def get_event_history(event_id: int, connection: Connection = Depends(get_connection, scope="function")):
    return get_or_404(connection, "event_history", event_id)


def _entity_history(
    connection: Connection,
    entity_type: str,
    entity_id: int,
    limit: int,
    offset: int,
):
    return list_rows(
        connection,
        "event_history",
        limit=limit,
        offset=offset,
        filters={"entity_type": entity_type, "entity_id": entity_id},
        order_by=("occurred_at", "id"),
        descending=True,
    )


@app.get(
    "/api/v1/aggregations/{aggregation_id}/history",
    response_model=list[EventHistoryRead],
    tags=["event history"],
)
def get_aggregation_history(
    aggregation_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    live = connection.execute(
        "SELECT 1 FROM aggregations WHERE id=%s AND current_user_can_view_aggregation(id)",
        (aggregation_id,),
    ).fetchone()
    deleted = connection.execute(
        "SELECT 1 FROM authorized_event_history WHERE entity_type='aggregation' AND entity_id=%s "
        "AND operation='DELETE' AND user_has_global_privilege(current_user_id(),'audit.view')",
        (aggregation_id,),
    ).fetchone()
    if live is None and deleted is None:
        raise HTTPException(status_code=404, detail="aggregation not found")
    return _entity_history(connection, "aggregation", aggregation_id, limit, offset)


@app.get(
    "/api/v1/records/{record_id}/history",
    response_model=list[EventHistoryRead],
    tags=["event history"],
)
def get_record_history(
    record_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    live = connection.execute(
        "SELECT 1 FROM records WHERE id=%s AND current_user_can_view_record(id)", (record_id,),
    ).fetchone()
    deleted = connection.execute(
        "SELECT 1 FROM authorized_event_history WHERE entity_type='record' AND entity_id=%s "
        "AND operation='DELETE' AND user_has_global_privilege(current_user_id(),'audit.view')",
        (record_id,),
    ).fetchone()
    if live is None and deleted is None:
        raise HTTPException(status_code=404, detail="record not found")
    return _entity_history(connection, "record", record_id, limit, offset)


@app.get(
    "/api/v1/digital-components/{component_id}/history",
    response_model=list[EventHistoryRead],
    tags=["event history"],
)
def get_digital_component_history(
    component_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    get_or_404(connection, "digital_components", component_id)
    return _entity_history(connection, "digital_component", component_id, limit, offset)
