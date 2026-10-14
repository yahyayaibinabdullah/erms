from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from psycopg import Connection

from .authentication import Principal, principal_from_request
from .database import get_connection
from .schemas import DashboardReviewItem, DashboardSummaryRead
from .application_settings import cache
from .application_configuration import ui_configuration, recent_since_default
from .entity_localization import localized_projection, preferred_language


router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])

# Saturate only beyond PostgreSQL's timestamp domain, so every valid registry
# integer works without interval overflow or a new product-level upper limit.
REVIEW_WINDOW_END_SQL = """CASE WHEN %s::bigint > (DATE '294276-12-31'-CURRENT_DATE)
 THEN 'infinity'::timestamptz ELSE CURRENT_TIMESTAMP +
 (LEAST(%s::bigint,DATE '294276-12-31'-CURRENT_DATE)*INTERVAL '1 day') END"""


@router.get("/reviews", response_model=list[DashboardReviewItem])
def dashboard_reviews(
    state: Literal["overdue", "upcoming"] = Query(...),
    limit: int = Query(500, ge=1, le=500),
    offset: int = Query(0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    comparison = (
        "date_of_next_review<=CURRENT_TIMESTAMP" if state == "overdue" else
        f"date_of_next_review>CURRENT_TIMESTAMP AND date_of_next_review<=({REVIEW_WINDOW_END_SQL})"
    )
    settings = cache.for_connection(connection)
    parameters = (settings["REVIEW_WARNING_WINDOW_DAYS"], settings["REVIEW_WARNING_WINDOW_DAYS"], limit, offset) if state == "upcoming" else (limit, offset)
    return list(connection.execute(
        f"""WITH reviewable AS (
          SELECT 'aggregation'::text entity_type,id entity_id,date_of_next_review,title,aggregation_number,NULL::text record_number
          FROM aggregations WHERE date_of_next_review IS NOT NULL AND current_user_can_view_aggregation(id)
           AND owning_org_unit_id IN (SELECT DISTINCT role.org_unit_id FROM user_role_assignments assignment JOIN roles role ON role.id=assignment.role_id WHERE assignment.user_id=current_user_id() AND assignment.valid_from<=CURRENT_TIMESTAMP AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(role.id))
          UNION ALL
          SELECT 'record',id,date_of_next_review,title,NULL::text,record_number
          FROM records WHERE date_of_next_review IS NOT NULL AND current_user_can_view_record(id)
           AND owning_org_unit_id IN (SELECT DISTINCT role.org_unit_id FROM user_role_assignments assignment JOIN roles role ON role.id=assignment.role_id WHERE assignment.user_id=current_user_id() AND assignment.valid_from<=CURRENT_TIMESTAMP AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(role.id))
        ) SELECT * FROM reviewable WHERE {comparison} ORDER BY date_of_next_review ASC,entity_type,entity_id LIMIT %s OFFSET %s""",
        parameters,
    ).fetchall())


@router.get("/summary", response_model=DashboardSummaryRead)
def dashboard_summary(
    request: Request,
    recent_limit: int | None = Query(None, ge=1, le=50),
    recent_since: datetime | None = None,
    principal: Principal = Depends(principal_from_request),
    connection: Connection = Depends(get_connection, scope="function"),
):
    """Return the authenticated user's complete dashboard summary.

    Dashboard clients should use this endpoint instead of issuing separate
    search, count, favourites, recent-activity, classification, and ownership
    requests for individual cards. The response applies the same authorization
    and resource-visibility rules as the underlying features while using one
    database-pool checkout.
    """
    settings = cache.for_connection(connection)
    recent_limit = recent_limit if recent_limit is not None else min(settings["DASHBOARD_RECENT_ITEM_LIMIT"], 50)
    recent_since = recent_since if recent_since is not None else recent_since_default(settings["DASHBOARD_RECENT_DAYS"])
    REVIEW_WARNING_WINDOW_DAYS = settings["REVIEW_WARNING_WINDOW_DAYS"]
    DASHBOARD_REVIEW_PREVIEW_LIMIT = min(settings["DASHBOARD_REVIEW_PREVIEW_LIMIT"], 50)
    privilege_rows = connection.execute(
        """SELECT code FROM privileges
            WHERE user_has_global_privilege(current_user_id(), code)"""
    ).fetchall()
    privileges = {row["code"] for row in privilege_rows}

    overview_counts = {}
    overview_medium_counts = {}
    overview_resource_attention_counts = {}
    overview_aggregation_status_counts = {"open": 0, "closed": 0}
    for resource in ("aggregations", "records"):
        status_columns = (
            ", count(*) FILTER (WHERE date_closed IS NULL) AS open,"
            " count(*) FILTER (WHERE date_closed IS NOT NULL) AS closed"
            if resource == "aggregations" else ""
        )
        row = connection.execute(
            f"""SELECT count(*) AS total,
                       count(*) FILTER (WHERE medium='physical') AS physical,
                       count(*) FILTER (WHERE medium='digital') AS digital,
                       count(*) FILTER (WHERE medium='mixed') AS mixed,
                       count(*) FILTER (WHERE is_vital) AS vital,
                       count(*) FILTER (WHERE on_effective_hold) AS held
                       {status_columns}
                  FROM authorized_{resource}_for_search"""
        ).fetchone()
        overview_counts[resource] = row["total"]
        overview_medium_counts[resource] = {
            medium: row[medium] for medium in ("physical", "digital", "mixed")
        }
        overview_resource_attention_counts[resource] = {
            metric: row[metric] for metric in ("vital", "held")
        }
        if resource == "aggregations":
            overview_aggregation_status_counts = {
                status: row[status] for status in ("open", "closed")
            }
    overview_digital_component_metrics = dict(connection.execute(
        """SELECT count(component.id) AS component_count,
                  coalesce(sum(component.size_in_bytes),0) AS storage_size_in_bytes
             FROM records record
        LEFT JOIN digital_components component ON component.record_id=record.id
            WHERE current_user_can_view_record(record.id)"""
    ).fetchone())
    if "holds.administer" in privileges:
        overview_counts["holds"] = connection.execute(
            "SELECT count(*) AS total FROM holds"
        ).fetchone()["total"]
    for resource, privilege in (
        ("classification-schemes", "classifications.administer"),
        ("classifications", "classifications.administer"),
        ("org-units", "organization.administer"),
        ("roles", "organization.administer"),
        ("users", "identity.users.administer"),
    ):
        if privilege in privileges:
            table = resource.replace("-", "_")
            overview_counts[resource] = connection.execute(
                f'SELECT count(*) AS total FROM "{table}"'
            ).fetchone()["total"]

    classification_metrics = {
        "published_scheme_count": 0,
        "draft_scheme_count": 0,
        "inactive_scheme_count": 0,
        "branch_count": 0,
        "terminal_count": 0,
        "assignable_terminal_count": 0,
        "draft_terminal_count": 0,
        "inactive_classification_count": 0,
    }
    if "classifications.administer" in privileges:
        classification_metrics = dict(connection.execute(
            """WITH scheme_metrics AS (
                   SELECT scheme.id,
                          scheme.date_deactivated IS NOT NULL AS inactive,
                          scheme.date_deactivated IS NULL
                            AND (scheme.date_published IS NULL
                                 OR scheme.date_published > CURRENT_TIMESTAMP) AS draft,
                          scheme.date_deactivated IS NULL
                            AND scheme.date_published IS NOT NULL
                            AND scheme.date_published <= CURRENT_TIMESTAMP AS published,
                          count(classification.id) FILTER (
                              WHERE classification.id IS NOT NULL
                                AND NOT classification.is_terminal
                          ) AS branches,
                          count(classification.id) FILTER (
                              WHERE classification.is_terminal
                          ) AS terminals,
                          count(classification.id) FILTER (
                              WHERE classification.is_terminal
                                AND classification_scheme_is_eligible(scheme.id)
                                AND classification_is_effectively_active(classification.id)
                                AND EXISTS (
                                    SELECT 1 FROM effective_classification_retention_rule(classification.id)
                                )
                          ) AS assignable_terminals
                     FROM classification_schemes scheme
                LEFT JOIN classifications classification
                       ON classification.classification_scheme_id=scheme.id
                 GROUP BY scheme.id
               )
               SELECT count(*) FILTER (WHERE published) AS published_scheme_count,
                      count(*) FILTER (WHERE draft) AS draft_scheme_count,
                      count(*) FILTER (WHERE inactive) AS inactive_scheme_count,
                      coalesce(sum(branches),0) AS branch_count,
                      coalesce(sum(terminals),0) AS terminal_count,
                      coalesce(sum(assignable_terminals),0) AS assignable_terminal_count,
                      coalesce(sum(terminals) FILTER (WHERE draft),0) AS draft_terminal_count,
                      (SELECT count(*) FROM classifications
                        WHERE date_deactivated IS NOT NULL) AS inactive_classification_count
                 FROM scheme_metrics"""
        ).fetchone())

    # Root status and visibility are security-sensitive facts. Count from the
    # real hierarchy and authorize each resource; never infer roots from a
    # response-redacted parent identifier.
    unclassified_root_count = connection.execute(
        """SELECT count(*) AS total FROM aggregations
            WHERE parent_aggregation_id IS NULL
              AND classification_id IS NULL
              AND current_user_can_view_aggregation(id)"""
    ).fetchone()["total"]

    ownership_counts = list(connection.execute(
        """WITH eligible_units AS (
               SELECT DISTINCT unit.id,unit.code,unit.name,unit.translations
               FROM user_role_assignments assignment
               JOIN roles role ON role.id=assignment.role_id
               JOIN org_units unit ON unit.id=role.org_unit_id
               WHERE assignment.user_id=current_user_id()
                 AND CURRENT_TIMESTAMP>=assignment.valid_from
                 AND (assignment.valid_until IS NULL OR CURRENT_TIMESTAMP<=assignment.valid_until)
                 AND role_effectively_active(role.id)
           ), aggregation_metrics AS (
               SELECT aggregation.owning_org_unit_id AS org_unit_id,
                      count(*) AS aggregation_count,
                      count(*) FILTER (WHERE aggregation.date_closed IS NULL) AS open_aggregation_count,
                      count(*) FILTER (WHERE aggregation.date_closed IS NOT NULL) AS closed_aggregation_count
                 FROM aggregations aggregation
                WHERE current_user_can_view_aggregation(aggregation.id)
                GROUP BY aggregation.owning_org_unit_id
           ), record_metrics AS (
               SELECT record.owning_org_unit_id AS org_unit_id,
                      count(*) AS record_count,
                      count(*) FILTER (WHERE record.medium='physical') AS physical_record_count,
                      count(*) FILTER (WHERE record.medium='digital') AS digital_record_count,
                      count(*) FILTER (WHERE record.medium='mixed') AS mixed_record_count,
                      count(*) FILTER (WHERE record.is_vital) AS vital_record_count
                 FROM records record
                WHERE current_user_can_view_record(record.id)
                GROUP BY record.owning_org_unit_id
           ), component_metrics AS (
               SELECT record.owning_org_unit_id AS org_unit_id,
                      coalesce(sum(component.size_in_bytes),0) AS storage_size_in_bytes
                 FROM records record
                 JOIN digital_components component ON component.record_id=record.id
                WHERE current_user_can_view_record(record.id)
                GROUP BY record.owning_org_unit_id
           )
           SELECT unit.id AS org_unit_id,unit.code AS org_unit_code,
                  unit.name AS org_unit_name,unit.translations,
                  coalesce(aggregation_metrics.aggregation_count,0) AS aggregation_count,
                  coalesce(aggregation_metrics.open_aggregation_count,0) AS open_aggregation_count,
                  coalesce(aggregation_metrics.closed_aggregation_count,0) AS closed_aggregation_count,
                  coalesce(record_metrics.record_count,0) AS record_count,
                  coalesce(record_metrics.physical_record_count,0) AS physical_record_count,
                  coalesce(record_metrics.digital_record_count,0) AS digital_record_count,
                  coalesce(record_metrics.mixed_record_count,0) AS mixed_record_count,
                  coalesce(record_metrics.vital_record_count,0) AS vital_record_count,
                  coalesce(component_metrics.storage_size_in_bytes,0) AS storage_size_in_bytes
             FROM eligible_units unit
        LEFT JOIN aggregation_metrics ON aggregation_metrics.org_unit_id=unit.id
        LEFT JOIN record_metrics ON record_metrics.org_unit_id=unit.id
        LEFT JOIN component_metrics ON component_metrics.org_unit_id=unit.id
            ORDER BY unit.name COLLATE "C",unit.id"""
    ).fetchall())
    dashboard_language = preferred_language(connection, request)
    for owner_count in ownership_counts:
        owner_count["name"] = owner_count["org_unit_name"]
        localized = localized_projection(owner_count, dashboard_language, "name")
        owner_count["org_unit_name"] = localized["name"]
        owner_count.pop("name", None)
        owner_count.pop("translations", None)
    ownership_counts.sort(key=lambda item: (
        str(item["org_unit_name"] or "").casefold(), item["org_unit_id"]
    ))

    favourite_aggregations = list(connection.execute(
        """SELECT aggregation.id,aggregation.aggregation_number,aggregation.title,
                  CASE WHEN aggregation.parent_aggregation_id IS NULL
                            OR current_user_can_view_aggregation(aggregation.parent_aggregation_id)
                       THEN aggregation.parent_aggregation_id END AS parent_aggregation_id,
                  favourite.date_created AS date_favourited
             FROM user_favourite_aggregations favourite
             JOIN aggregations aggregation ON aggregation.id=favourite.aggregation_id
            WHERE favourite.user_id=%s
              AND current_user_can_view_aggregation(aggregation.id)
            ORDER BY favourite.date_created DESC,aggregation.id DESC""",
        (principal.user_id,),
    ).fetchall())
    favourite_records = list(connection.execute(
        """SELECT record.id,record.record_number,record.title,
                  CASE WHEN current_user_can_view_aggregation(record.aggregation_id)
                       THEN record.aggregation_id END AS aggregation_id,
                  CASE WHEN current_user_can_view_aggregation(record.aggregation_id)
                       THEN aggregation.aggregation_number END AS aggregation_number,
                  CASE WHEN current_user_can_view_aggregation(record.aggregation_id)
                       THEN aggregation.title END AS aggregation_title,
                  favourite.date_created AS date_favourited
             FROM user_favourite_records favourite
             JOIN records record ON record.id=favourite.record_id
             JOIN aggregations aggregation ON aggregation.id=record.aggregation_id
            WHERE favourite.user_id=%s AND current_user_can_view_record(record.id)
            ORDER BY favourite.date_created DESC,record.id DESC""",
        (principal.user_id,),
    ).fetchall())

    recent_activity = list(connection.execute(
        """WITH governed_resource_events AS (
               SELECT DISTINCT ON (event.entity_type,event.entity_id,event.operation)
                      event.id,event.entity_type,event.entity_id,event.operation,event.occurred_at
                 FROM event_history event
                WHERE event.actor_user_id=%s
                  AND event.entity_type IN ('aggregation','record')
                  AND event.operation IN ('CREATE','UPDATE')
                  AND (%s::timestamptz IS NULL OR event.occurred_at >= %s)
                ORDER BY event.entity_type,event.entity_id,event.operation,
                         event.occurred_at DESC,event.id DESC
           ), content_view_events AS (
               SELECT DISTINCT ON (component.record_id)
                      event.id,'record'::text AS entity_type,
                      component.record_id AS entity_id,
                      event.operation,event.occurred_at
                 FROM event_history event
                 JOIN digital_components component ON component.id=event.entity_id
                WHERE event.actor_user_id=%s
                  AND event.entity_type='digital_component'
                  AND event.operation='CONTENT_VIEWED'
                  AND (%s::timestamptz IS NULL OR event.occurred_at >= %s)
                ORDER BY component.record_id,event.occurred_at DESC,event.id DESC
           ), latest_resource_events AS (
               SELECT * FROM governed_resource_events
               UNION ALL
               SELECT * FROM content_view_events
           ), ranked_events AS (
               SELECT event.entity_type,event.entity_id,event.operation,event.occurred_at,
                      row_number() OVER (
                          PARTITION BY event.entity_type,event.operation
                          ORDER BY event.occurred_at DESC,event.id DESC
                      ) AS position
                 FROM latest_resource_events event
           )
           SELECT event.entity_type,event.entity_id,event.operation,event.occurred_at,
                  coalesce(aggregation.title,record.title) AS title,
                  aggregation.aggregation_number,record.record_number
             FROM ranked_events event
        LEFT JOIN aggregations aggregation
               ON event.entity_type='aggregation' AND aggregation.id=event.entity_id
              AND current_user_can_view_aggregation(aggregation.id)
        LEFT JOIN records record
               ON event.entity_type='record' AND record.id=event.entity_id
              AND current_user_can_view_record(record.id)
            WHERE event.position<=%s
              AND (aggregation.id IS NOT NULL OR record.id IS NOT NULL)
            ORDER BY event.occurred_at DESC,event.entity_type,event.entity_id""",
        (
            principal.user_id, recent_since, recent_since,
            principal.user_id, recent_since, recent_since,
            recent_limit,
        ),
    ).fetchall())
    review_counts = connection.execute(
        f"""SELECT
             count(*) FILTER (WHERE date_of_next_review<=CURRENT_TIMESTAMP) AS overdue,
             count(*) FILTER (WHERE date_of_next_review>CURRENT_TIMESTAMP
                                AND date_of_next_review<=({REVIEW_WINDOW_END_SQL})) AS upcoming
           FROM (
             SELECT date_of_next_review FROM aggregations
              WHERE date_of_next_review IS NOT NULL
                AND current_user_can_view_aggregation(id)
                AND owning_org_unit_id IN (SELECT DISTINCT role.org_unit_id FROM user_role_assignments assignment JOIN roles role ON role.id=assignment.role_id WHERE assignment.user_id=current_user_id() AND assignment.valid_from<=CURRENT_TIMESTAMP AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(role.id))
             UNION ALL
             SELECT date_of_next_review FROM records
              WHERE date_of_next_review IS NOT NULL
                AND current_user_can_view_record(id)
                AND owning_org_unit_id IN (SELECT DISTINCT role.org_unit_id FROM user_role_assignments assignment JOIN roles role ON role.id=assignment.role_id WHERE assignment.user_id=current_user_id() AND assignment.valid_from<=CURRENT_TIMESTAMP AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(role.id))
           ) reviewable""",
        (REVIEW_WARNING_WINDOW_DAYS, REVIEW_WARNING_WINDOW_DAYS),
    ).fetchone()
    review_rows = list(connection.execute(
        """WITH reviewable AS (
               SELECT 'aggregation'::text AS entity_type,id AS entity_id,date_of_next_review,title,aggregation_number,NULL::text AS record_number
                 FROM aggregations WHERE date_of_next_review IS NOT NULL AND current_user_can_view_aggregation(id)
                  AND owning_org_unit_id IN (SELECT DISTINCT role.org_unit_id FROM user_role_assignments assignment JOIN roles role ON role.id=assignment.role_id WHERE assignment.user_id=current_user_id() AND assignment.valid_from<=CURRENT_TIMESTAMP AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(role.id))
               UNION ALL
               SELECT 'record',id,date_of_next_review,title,NULL::text,record_number
                 FROM records WHERE date_of_next_review IS NOT NULL AND current_user_can_view_record(id)
                  AND owning_org_unit_id IN (SELECT DISTINCT role.org_unit_id FROM user_role_assignments assignment JOIN roles role ON role.id=assignment.role_id WHERE assignment.user_id=current_user_id() AND assignment.valid_from<=CURRENT_TIMESTAMP AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(role.id))
           ) SELECT * FROM reviewable
           WHERE date_of_next_review <= CURRENT_TIMESTAMP
           ORDER BY date_of_next_review ASC,entity_id ASC LIMIT %s""",
        (DASHBOARD_REVIEW_PREVIEW_LIMIT,),
    ).fetchall())
    upcoming_rows = list(connection.execute(
        f"""WITH reviewable AS (
               SELECT 'aggregation'::text AS entity_type,id AS entity_id,date_of_next_review,title,aggregation_number,NULL::text AS record_number
                 FROM aggregations WHERE date_of_next_review IS NOT NULL AND current_user_can_view_aggregation(id)
                  AND owning_org_unit_id IN (SELECT DISTINCT role.org_unit_id FROM user_role_assignments assignment JOIN roles role ON role.id=assignment.role_id WHERE assignment.user_id=current_user_id() AND assignment.valid_from<=CURRENT_TIMESTAMP AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(role.id))
               UNION ALL
               SELECT 'record',id,date_of_next_review,title,NULL::text,record_number
                 FROM records WHERE date_of_next_review IS NOT NULL AND current_user_can_view_record(id)
                  AND owning_org_unit_id IN (SELECT DISTINCT role.org_unit_id FROM user_role_assignments assignment JOIN roles role ON role.id=assignment.role_id WHERE assignment.user_id=current_user_id() AND assignment.valid_from<=CURRENT_TIMESTAMP AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(role.id))
           ) SELECT * FROM reviewable
           WHERE date_of_next_review > CURRENT_TIMESTAMP
             AND date_of_next_review <= ({REVIEW_WINDOW_END_SQL})
           ORDER BY date_of_next_review ASC,entity_id ASC LIMIT %s""",
        (REVIEW_WARNING_WINDOW_DAYS, REVIEW_WARNING_WINDOW_DAYS, DASHBOARD_REVIEW_PREVIEW_LIMIT,),
    ).fetchall())

    return {
        "application_configuration": ui_configuration(connection, snapshot=settings),
        "overview_counts": overview_counts,
        "overview_medium_counts": overview_medium_counts,
        "overview_resource_attention_counts": overview_resource_attention_counts,
        "overview_aggregation_status_counts": overview_aggregation_status_counts,
        "overview_digital_component_metrics": overview_digital_component_metrics,
        "classification_metrics": classification_metrics,
        "unclassified_root_count": unclassified_root_count,
        "ownership_counts": ownership_counts,
        "favourites": {
            "aggregations": favourite_aggregations,
            "records": favourite_records,
        },
        "recent_activity": recent_activity,
        "review_warning_window_days": REVIEW_WARNING_WINDOW_DAYS,
        "overdue_review_count": int(review_counts["overdue"]),
        "upcoming_review_count": int(review_counts["upcoming"]),
        "overdue_reviews": review_rows,
        "upcoming_reviews": upcoming_rows,
    }
