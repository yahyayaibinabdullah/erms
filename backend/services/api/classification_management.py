from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from psycopg import Connection

from .concurrency import expected_version
from .disposition.acceleration import current_accelerations
from .crud import create_row, delete_row, get_or_404, list_rows, update_row
from .database import get_connection
from .entity_localization import (
    localize_rows,
    localize_search_result,
    preferred_language,
    sort_localized_rows,
)
from .schemas import (
    AggregationRetentionRuleCreate,
    AggregationRetentionRuleRead,
    ClassificationCreate,
    ClassificationRead,
    ClassificationRetentionRuleRead,
    ClassificationSchemeCreate,
    ClassificationSchemeClassificationCounts,
    ClassificationSchemeRead,
    ClassificationSchemeUpdate,
    ClassificationUpdate,
    EventHistoryRead,
    EffectiveRetentionRuleRead,
    RetentionRuleInput,
    SearchRequest,
    SearchResponse,
)
from .search import search_rows
from .http_cache import apply_collection_etag
from .authorization_policy import require_audit_view, require_classifications_admin


router = APIRouter(prefix="/api/v1")


def _history(connection: Connection, entity_type: str, entity_id: int):
    return list_rows(
        connection, "event_history", limit=500, offset=0,
        filters={"entity_type": entity_type, "entity_id": entity_id},
        order_by=("occurred_at", "id"), descending=True,
    )


def _required_reason(value: str | None) -> str:
    if value is None or not value.strip():
        raise HTTPException(status_code=422, detail="X-Change-Reason is required")
    return value.strip()


@router.post("/classification-schemes", response_model=ClassificationSchemeRead, status_code=201, tags=["classification schemes"], dependencies=[Depends(require_classifications_admin)])
def create_scheme(payload: ClassificationSchemeCreate, connection: Connection = Depends(get_connection, scope="function")):
    return create_row(connection, "classification_schemes", payload.model_dump(exclude_none=True))


@router.get("/classification-schemes", response_model=list[ClassificationSchemeRead], tags=["classification schemes"])
def list_schemes(
    request: Request,
    response: Response,
    eligible: bool | None = None,
    sort: Literal["created", "title", "code", "published_status"] = "created",
    direction: Literal["asc", "desc"] = "asc",
    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    predicates: list[str] = []
    if eligible is not None:
        eligible_predicate = (
            "date_deactivated IS NULL AND date_published IS NOT NULL "
            "AND date_published <= CURRENT_TIMESTAMP"
        )
        predicates.append(eligible_predicate if eligible else f"NOT ({eligible_predicate})")

    order_expressions = {
        "created": "id",
        "title": "LOWER(title)",
        "code": "LOWER(code)",
        "published_status": """CASE
            WHEN date_deactivated IS NOT NULL THEN 3
            WHEN date_published IS NULL THEN 2
            WHEN date_published > CURRENT_TIMESTAMP THEN 1
            ELSE 0 END""",
    }
    order_direction = direction.upper()
    query = "SELECT * FROM classification_schemes"
    if predicates:
        query += " WHERE " + " AND ".join(predicates)
    query += (
        f" ORDER BY {order_expressions[sort]} {order_direction}, "
        f"LOWER(title) {order_direction}, id {order_direction} LIMIT %s OFFSET %s"
    )
    rows = list(connection.execute(
        query,
        (limit, offset),
    ).fetchall())
    localized = localize_rows(rows, preferred_language(connection, request), "title")
    result = sort_localized_rows(localized, "title") if sort == "title" else localized
    return apply_collection_etag(request, response, result) or result


@router.post("/classification-schemes/search", response_model=None, tags=["classification schemes"])
def search_schemes(
    request: Request, payload: SearchRequest,
    connection: Connection = Depends(get_connection, scope="function"),
):
    return localize_search_result(
        search_rows(
            connection, "classification_schemes", payload,
            endpoint="/api/v1/classification-schemes/search",
        ),
        preferred_language(connection, request), "title",
    )


@router.get(
    "/classification-schemes/classification-counts",
    response_model=list[ClassificationSchemeClassificationCounts],
    tags=["classification schemes"],
    dependencies=[Depends(require_classifications_admin)],
)
def classification_counts_by_scheme(
    connection: Connection = Depends(get_connection, scope="function"),
):
    return list(connection.execute(
        """SELECT scheme.id AS classification_scheme_id,
                  count(classification.id) FILTER (
                      WHERE classification.id IS NOT NULL AND NOT classification.is_terminal
                  ) AS branch_count,
                  count(classification.id) FILTER (
                      WHERE classification.is_terminal
                  ) AS terminal_count,
                  count(classification.id) FILTER (
                      WHERE classification.is_terminal
                        AND classification_scheme_is_eligible(scheme.id)
                        AND classification_is_effectively_active(classification.id)
                        AND EXISTS (
                            SELECT 1
                              FROM effective_classification_retention_rule(classification.id)
                        )
                  ) AS eligible_terminal_count
             FROM classification_schemes AS scheme
        LEFT JOIN classifications AS classification
               ON classification.classification_scheme_id = scheme.id
         GROUP BY scheme.id
         ORDER BY scheme.id"""
    ).fetchall())


@router.get("/classification-schemes/{scheme_id}", response_model=ClassificationSchemeRead, tags=["classification schemes"])
def get_scheme(scheme_id: int, request: Request, connection: Connection = Depends(get_connection, scope="function")):
    return localize_rows([get_or_404(connection, "classification_schemes", scheme_id)], preferred_language(connection, request), "title")[0]


@router.patch("/classification-schemes/{scheme_id}", response_model=ClassificationSchemeRead, tags=["classification schemes"], dependencies=[Depends(require_classifications_admin)])
def update_scheme(
    scheme_id: int, payload: ClassificationSchemeUpdate,
    version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    return update_row(connection, "classification_schemes", scheme_id, payload.model_dump(exclude_unset=True), version)


@router.post("/classification-schemes/{scheme_id}/publish", response_model=ClassificationSchemeRead, tags=["classification schemes"], dependencies=[Depends(require_classifications_admin)])
def publish_scheme(
    scheme_id: int, version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    row = connection.execute(
        "UPDATE classification_schemes SET date_published=CURRENT_TIMESTAMP WHERE id=%s AND version=%s RETURNING *",
        (scheme_id, version),
    ).fetchone()
    if row is None:
        current = get_or_404(connection, "classification_schemes", scheme_id)
        raise HTTPException(status_code=412, detail={"message": "entity has changed", "current_version": current["version"]})
    return row


@router.post("/classification-schemes/{scheme_id}/unpublish", response_model=ClassificationSchemeRead, tags=["classification schemes"], dependencies=[Depends(require_classifications_admin)])
def unpublish_scheme(
    scheme_id: int, version: int = Depends(expected_version),
    reason: str | None = Header(None, alias="X-Change-Reason"),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _required_reason(reason)
    row = connection.execute(
        """UPDATE classification_schemes
              SET date_published=NULL
            WHERE id=%s AND version=%s
              AND date_published IS NOT NULL
              AND date_first_used IS NULL
        RETURNING *""",
        (scheme_id, version),
    ).fetchone()
    if row is not None:
        return row
    current = get_or_404(connection, "classification_schemes", scheme_id)
    if current["version"] != version:
        raise HTTPException(status_code=412, detail={
            "message": "entity has changed", "current_version": current["version"],
        })
    if current["date_first_used"] is not None:
        raise HTTPException(
            status_code=409,
            detail="a classification scheme that has governed an aggregation cannot be unpublished",
        )
    raise HTTPException(status_code=409, detail="classification scheme is already unpublished")


@router.post("/classification-schemes/{scheme_id}/deactivate", response_model=ClassificationSchemeRead, tags=["classification schemes"], dependencies=[Depends(require_classifications_admin)])
def deactivate_scheme(
    scheme_id: int, version: int = Depends(expected_version),
    reason: str | None = Header(None, alias="X-Change-Reason"),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _required_reason(reason)
    row = connection.execute(
        "UPDATE classification_schemes SET date_deactivated=CURRENT_TIMESTAMP WHERE id=%s AND version=%s RETURNING *",
        (scheme_id, version),
    ).fetchone()
    if row is None:
        current = get_or_404(connection, "classification_schemes", scheme_id)
        raise HTTPException(status_code=412, detail={"message": "entity has changed", "current_version": current["version"]})
    return row


@router.post("/classification-schemes/{scheme_id}/reactivate", response_model=ClassificationSchemeRead, tags=["classification schemes"], dependencies=[Depends(require_classifications_admin)])
def reactivate_scheme(
    scheme_id: int, version: int = Depends(expected_version),
    reason: str | None = Header(None, alias="X-Change-Reason"),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _required_reason(reason)
    return update_row(connection, "classification_schemes", scheme_id, {"date_deactivated": None}, version)


@router.delete("/classification-schemes/{scheme_id}", status_code=204, tags=["classification schemes"], dependencies=[Depends(require_classifications_admin)])
def delete_scheme(
    scheme_id: int, version: int = Depends(expected_version),
    reason: str | None = Header(None, alias="X-Change-Reason"),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _required_reason(reason)
    delete_row(connection, "classification_schemes", scheme_id, version)
    return Response(status_code=204)


@router.get("/classification-schemes/{scheme_id}/history", response_model=list[EventHistoryRead], tags=["event history"], dependencies=[Depends(require_audit_view)])
def scheme_history(scheme_id: int, connection: Connection = Depends(get_connection, scope="function")):
    return _history(connection, "classification_scheme", scheme_id)


@router.post("/classifications", response_model=ClassificationRead, status_code=201, tags=["classifications"], dependencies=[Depends(require_classifications_admin)])
def create_classification(payload: ClassificationCreate, connection: Connection = Depends(get_connection, scope="function")):
    values = payload.model_dump(exclude={"retention_rule"}, exclude_none=True)
    classification = create_row(connection, "classifications", values)
    if payload.retention_rule is not None:
        create_row(connection, "classification_retention_rules", {
            "classification_id": classification["id"], **payload.retention_rule.model_dump()
        })
    return classification


@router.get("/classifications", response_model=list[ClassificationRead], tags=["classifications"])
def list_classifications(
    request: Request,
    classification_scheme_id: int | None = None,
    parent_classification_id: int | None = None,
    roots_only: bool = False,
    eligible: bool = False,
    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    clauses, parameters = [], []
    if classification_scheme_id is not None:
        clauses.append("c.classification_scheme_id = %s"); parameters.append(classification_scheme_id)
    if roots_only:
        clauses.append("c.parent_classification_id IS NULL")
    elif parent_classification_id is not None:
        clauses.append("c.parent_classification_id = %s"); parameters.append(parent_classification_id)
    if eligible:
        clauses.extend(("c.is_terminal", "classification_scheme_is_eligible(c.classification_scheme_id)",
                        "classification_is_effectively_active(c.id)",
                        "EXISTS (SELECT 1 FROM effective_classification_retention_rule(c.id))"))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    parameters.extend((limit, offset))
    rows = list(connection.execute(
        f'SELECT c.* FROM classifications c{where} '
        'ORDER BY c.code COLLATE "C" ASC, c.id ASC LIMIT %s OFFSET %s',
        parameters,
    ).fetchall())
    # Classification trees are navigated by their stable classification codes.
    # Preserve that ordering after localization; translated titles must not
    # reshuffle either root classifications or children.
    return localize_rows(rows, preferred_language(connection, request), "title")


@router.post("/classifications/search", response_model=None, tags=["classifications"])
def search_classifications(
    request: Request, payload: SearchRequest,
    eligible: bool = False,
    connection: Connection = Depends(get_connection, scope="function"),
):
    return localize_search_result(
        search_rows(
            connection, "classifications", payload,
            endpoint="/api/v1/classifications/search",
            eligible_classifications=eligible,
        ),
        preferred_language(connection, request), "title",
    )


@router.get("/classifications/recent", response_model=list[ClassificationRead], tags=["classifications"])
def recent_classifications(
    request: Request, limit: int | None = Query(None, ge=1, le=20),
    offset: int = Query(0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    principal = request.state.principal
    from .application_settings import cache
    configured_limit = cache.for_connection(connection)["CLASSIFICATION_RECENT_SELECTION_LIMIT"]
    limit = min(limit if limit is not None else 20, max(0, configured_limit-offset))
    return list(connection.execute(
        """SELECT c.* FROM user_classification_selections recent
           JOIN classifications c ON c.id=recent.classification_id
           WHERE recent.user_id=%s AND c.is_terminal
             AND classification_scheme_is_eligible(c.classification_scheme_id)
             AND classification_is_effectively_active(c.id)
             AND EXISTS (SELECT 1 FROM effective_classification_retention_rule(c.id))
           ORDER BY recent.last_selected_at DESC,c.id DESC LIMIT %s OFFSET %s""",
        (principal.user_id, limit, offset),
    ).fetchall())


@router.get("/classifications/{classification_id}", response_model=ClassificationRead, tags=["classifications"])
def get_classification(classification_id: int, request: Request, connection: Connection = Depends(get_connection, scope="function")):
    return localize_rows([get_or_404(connection, "classifications", classification_id)], preferred_language(connection, request), "title")[0]


@router.get("/classifications/{classification_id}/path", response_model=list[ClassificationRead], tags=["classifications"])
def classification_path(classification_id: int, request: Request, connection: Connection = Depends(get_connection, scope="function")):
    rows = connection.execute(
        """WITH RECURSIVE lineage AS (
               SELECT c.*, 0 depth FROM classifications c WHERE id=%s
               UNION ALL SELECT p.*, child.depth+1 FROM classifications p
               JOIN lineage child ON p.id=child.parent_classification_id
           ) SELECT id, classification_scheme_id, parent_classification_id, code, title,
                    description, authority, scope_note, keywords, is_terminal,
                    date_created, date_updated, date_deactivated, date_first_used, version, translations
             FROM lineage ORDER BY depth DESC""", (classification_id,)
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="classification not found")
    return localize_rows(list(rows), preferred_language(connection, request), "title")


@router.patch("/classifications/{classification_id}", response_model=ClassificationRead, tags=["classifications"], dependencies=[Depends(require_classifications_admin)])
def update_classification(
    classification_id: int, payload: ClassificationUpdate,
    version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    connection.execute("SELECT pg_advisory_xact_lock(7357,1)")
    return update_row(connection, "classifications", classification_id, payload.model_dump(exclude_unset=True), version)


@router.delete("/classifications/{classification_id}", status_code=204, tags=["classifications"], dependencies=[Depends(require_classifications_admin)])
def delete_classification(
    classification_id: int, version: int = Depends(expected_version),
    reason: str | None = Header(None, alias="X-Change-Reason"),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _required_reason(reason)
    delete_row(connection, "classifications", classification_id, version)
    return Response(status_code=204)


@router.post("/classifications/{classification_id}/deactivate", response_model=ClassificationRead, tags=["classifications"], dependencies=[Depends(require_classifications_admin)])
def deactivate_classification(
    classification_id: int, version: int = Depends(expected_version),
    reason: str | None = Header(None, alias="X-Change-Reason"),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _required_reason(reason)
    current = get_or_404(connection, "classifications", classification_id)
    if current["date_deactivated"] is not None:
        raise HTTPException(status_code=409, detail="classification is already deactivated")
    row = connection.execute(
        "UPDATE classifications SET date_deactivated=CURRENT_TIMESTAMP "
        "WHERE id=%s AND version=%s RETURNING *",
        (classification_id, version),
    ).fetchone()
    if row is None:
        current = get_or_404(connection, "classifications", classification_id)
        raise HTTPException(status_code=412, detail={
            "message": "entity has changed", "current_version": current["version"],
        })
    return row


@router.post("/classifications/{classification_id}/reactivate", response_model=ClassificationRead, tags=["classifications"], dependencies=[Depends(require_classifications_admin)])
def reactivate_classification(
    classification_id: int, version: int = Depends(expected_version),
    reason: str | None = Header(None, alias="X-Change-Reason"),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _required_reason(reason)
    current = get_or_404(connection, "classifications", classification_id)
    if current["date_deactivated"] is None:
        raise HTTPException(status_code=409, detail="classification is already active")
    return update_row(connection, "classifications", classification_id, {"date_deactivated": None}, version)


@router.get("/classifications/{classification_id}/history", response_model=list[EventHistoryRead], tags=["event history"], dependencies=[Depends(require_audit_view)])
def classification_history(classification_id: int, connection: Connection = Depends(get_connection, scope="function")):
    return _history(connection, "classification", classification_id)


@router.get("/classifications/{classification_id}/retention-rule", response_model=ClassificationRetentionRuleRead | None, tags=["retention rules"])
def get_classification_rule(classification_id: int, connection: Connection = Depends(get_connection, scope="function")):
    get_or_404(connection, "classifications", classification_id)
    return connection.execute("SELECT * FROM classification_retention_rules WHERE classification_id=%s", (classification_id,)).fetchone()


@router.put("/classifications/{classification_id}/retention-rule", response_model=ClassificationRetentionRuleRead, tags=["retention rules"], dependencies=[Depends(require_classifications_admin)])
def put_classification_rule(
    classification_id: int, payload: RetentionRuleInput,
    version: int | None = Query(None, ge=1),
    connection: Connection = Depends(get_connection, scope="function"),
):
    connection.execute("SELECT pg_advisory_xact_lock(7357,1)")
    get_or_404(connection, "classifications", classification_id)
    current = connection.execute("SELECT * FROM classification_retention_rules WHERE classification_id=%s", (classification_id,)).fetchone()
    if current is None:
        return create_row(connection, "classification_retention_rules", {"classification_id": classification_id, **payload.model_dump()})
    if version is None:
        raise HTTPException(status_code=428, detail="If-Match/version is required for an existing rule")
    return update_row(connection, "classification_retention_rules", current["id"], payload.model_dump(), version)


@router.delete("/classifications/{classification_id}/retention-rule", status_code=204, tags=["retention rules"], dependencies=[Depends(require_classifications_admin)])
def delete_classification_rule(
    classification_id: int, version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    connection.execute("SELECT pg_advisory_xact_lock(7357,1)")
    row = connection.execute("SELECT id FROM classification_retention_rules WHERE classification_id=%s", (classification_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="classification retention rule not found")
    delete_row(connection, "classification_retention_rules", row["id"], version)
    return Response(status_code=204)


@router.get("/classifications/{classification_id}/effective-retention-rule", tags=["retention rules"])
def effective_classification_rule(classification_id: int, connection: Connection = Depends(get_connection, scope="function")):
    get_or_404(connection, "classifications", classification_id)
    row = connection.execute("SELECT * FROM effective_classification_retention_rule(%s)", (classification_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no effective retention rule")
    return row


@router.get("/aggregations/{aggregation_id}/retention-rule", response_model=AggregationRetentionRuleRead | None, tags=["retention rules"])
def get_aggregation_rule(aggregation_id: int, connection: Connection = Depends(get_connection, scope="function")):
    get_or_404(connection, "aggregations", aggregation_id)
    return connection.execute("SELECT * FROM aggregation_retention_rules WHERE aggregation_id=%s", (aggregation_id,)).fetchone()


@router.put("/aggregations/{aggregation_id}/retention-rule", response_model=AggregationRetentionRuleRead, tags=["retention rules"])
def put_aggregation_rule(
    aggregation_id: int, payload: AggregationRetentionRuleCreate,
    version: int | None = Query(None, ge=1),
    reason: str | None = Header(None, alias="X-Change-Reason"),
    connection: Connection = Depends(get_connection, scope="function"),
):
    connection.execute("SELECT pg_advisory_xact_lock(7357,1)")
    _required_reason(reason)
    aggregation = get_or_404(connection, "aggregations", aggregation_id)
    if aggregation["parent_aggregation_id"] is not None:
        raise HTTPException(status_code=409, detail="child aggregations cannot have a local retention rule")
    current = connection.execute("SELECT * FROM aggregation_retention_rules WHERE aggregation_id=%s", (aggregation_id,)).fetchone()
    if current is None:
        return create_row(connection, "aggregation_retention_rules", {"aggregation_id": aggregation_id, **payload.model_dump()})
    if version is None:
        raise HTTPException(status_code=428, detail="version is required for an existing rule")
    return update_row(connection, "aggregation_retention_rules", current["id"], payload.model_dump(), version)


@router.delete("/aggregations/{aggregation_id}/retention-rule", status_code=204, tags=["retention rules"])
def delete_aggregation_rule(
    aggregation_id: int, version: int = Depends(expected_version),
    reason: str | None = Header(None, alias="X-Change-Reason"),
    connection: Connection = Depends(get_connection, scope="function"),
):
    connection.execute("SELECT pg_advisory_xact_lock(7357,1)")
    _required_reason(reason)
    row = connection.execute("SELECT id FROM aggregation_retention_rules WHERE aggregation_id=%s", (aggregation_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="aggregation retention rule not found")
    delete_row(connection, "aggregation_retention_rules", row["id"], version)
    return Response(status_code=204)


@router.get("/aggregations/{aggregation_id}/effective-retention-rule", response_model=EffectiveRetentionRuleRead, tags=["retention rules"])
def effective_aggregation_rule(aggregation_id: int, request: Request, connection: Connection = Depends(get_connection, scope="function")):
    get_or_404(connection, "aggregations", aggregation_id)
    row = connection.execute("SELECT * FROM aggregation_effective_retention_rule(%s)", (aggregation_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no effective retention rule")
    acceleration = current_accelerations(connection, [row["governing_root_aggregation_id"]], preferred_language(connection, request))
    return {**row, "acceleration": acceleration.get(row["governing_root_aggregation_id"])}
