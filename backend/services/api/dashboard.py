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
from .dashboard_visibility import VISIBILITY_CTES


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
        f"""WITH RECURSIVE {VISIBILITY_CTES}, reviewable AS (
          SELECT 'aggregation'::text entity_type,id entity_id,date_of_next_review,title,aggregation_number,NULL::text record_number
          FROM authorized_aggregations WHERE date_of_next_review IS NOT NULL
           AND owning_org_unit_id IN (SELECT org_unit_id FROM effective_roles)
          UNION ALL
          SELECT 'record',id,date_of_next_review,title,NULL::text,record_number
          FROM authorized_records WHERE date_of_next_review IS NOT NULL
           AND owning_org_unit_id IN (SELECT org_unit_id FROM effective_roles)
        ) SELECT * FROM reviewable WHERE {comparison} ORDER BY date_of_next_review ASC,entity_type,entity_id LIMIT %s OFFSET %s""",
        parameters,
    ).fetchall())


def _resource_metrics(connection: Connection, review_window_days: int, review_preview_limit: int,
                      recent_limit: int = 4, recent_since: datetime | None = None) -> dict:
    """Authorize each resource once for this request, then aggregate by owner.

    These CTEs live only for this SQL statement: no identity-dependent data is
    cached across requests. Overview totals retain the search views' lifecycle
    filter; ownership/storage retain their existing live-resource semantics.
    Visibility is a set-based equivalent of the canonical predicates, checked by
    differential tests. Active holds
    propagate down the hierarchy once instead of walking ancestry per row;
    their half-open validity window matches the canonical effective-hold functions.
    """
    return connection.execute(
        f"""WITH RECURSIVE {VISIBILITY_CTES}, review_cutoff AS MATERIALIZED (
               SELECT ({REVIEW_WINDOW_END_SQL}) AS ends_at
           ), held_aggregations(aggregation_id) AS (
               SELECT assignment.aggregation_id
                 FROM hold_aggregation_assignments assignment JOIN holds hold ON hold.id=assignment.hold_id
                WHERE hold.valid_from<=statement_timestamp()
                  AND (hold.valid_to IS NULL OR statement_timestamp()<hold.valid_to)
               UNION
               SELECT child.id FROM aggregations child
                 JOIN held_aggregations parent ON child.parent_aggregation_id=parent.aggregation_id
           ), directly_held_records AS MATERIALIZED (
               SELECT DISTINCT assignment.record_id
                 FROM hold_record_assignments assignment JOIN holds hold ON hold.id=assignment.hold_id
                WHERE hold.valid_from<=statement_timestamp()
                  AND (hold.valid_to IS NULL OR statement_timestamp()<hold.valid_to)
           ), visible_aggregations AS MATERIALIZED (
               SELECT resource.id,resource.owning_org_unit_id,resource.medium,
                      resource.is_vital,resource.date_closed,resource.date_of_next_review,
                      resource.title,resource.aggregation_number,
                      resource.parent_aggregation_id,resource.classification_id,
                      (resource.disposition_status NOT IN (10,11,12) OR authority.manages_disposition) AS overview_visible,
                      CASE WHEN resource.disposition_status NOT IN (10,11,12) OR authority.manages_disposition
                           THEN resource.id IN (SELECT aggregation_id FROM held_aggregations)
                           ELSE false END AS on_effective_hold
                 FROM authorized_aggregations resource CROSS JOIN authority
           ), visible_records AS MATERIALIZED (
               SELECT resource.id,resource.owning_org_unit_id,resource.medium,
                      resource.is_vital,resource.date_of_next_review,resource.title,resource.record_number,
                      (resource.disposition_status NOT IN (10,11,12) OR authority.manages_disposition) AS overview_visible,
                      CASE WHEN resource.disposition_status NOT IN (10,11,12) OR authority.manages_disposition
                           THEN (resource.aggregation_id IN (SELECT aggregation_id FROM held_aggregations)
                                 OR resource.id IN (SELECT record_id FROM directly_held_records))
                           ELSE false END AS on_effective_hold
                 FROM authorized_records resource CROSS JOIN authority
           ), component_metrics AS (
               SELECT component.record_id,count(*) AS component_count,
                      coalesce(sum(component.size_in_bytes),0) AS storage_size_in_bytes
                 FROM digital_components component
                 JOIN visible_records record ON record.id=component.record_id
                GROUP BY component.record_id
           ), aggregation_metrics AS (
               SELECT owning_org_unit_id AS org_unit_id,
                      count(*) FILTER (WHERE overview_visible) AS total,
                      count(*) FILTER (WHERE overview_visible AND medium='physical') AS physical,
                      count(*) FILTER (WHERE overview_visible AND medium='digital') AS digital,
                      count(*) FILTER (WHERE overview_visible AND medium='mixed') AS mixed,
                      count(*) FILTER (WHERE overview_visible AND is_vital) AS vital,
                      count(*) FILTER (WHERE overview_visible AND on_effective_hold) AS held,
                      count(*) FILTER (WHERE overview_visible AND date_closed IS NULL) AS open,
                      count(*) FILTER (WHERE overview_visible AND date_closed IS NOT NULL) AS closed,
                      count(*) AS owned_total,
                      count(*) FILTER (WHERE date_closed IS NULL) AS owned_open,
                      count(*) FILTER (WHERE date_closed IS NOT NULL) AS owned_closed
                 FROM visible_aggregations GROUP BY owning_org_unit_id
           ), record_metrics AS (
               SELECT record.owning_org_unit_id AS org_unit_id,
                      count(*) FILTER (WHERE record.overview_visible) AS total,
                      count(*) FILTER (WHERE record.overview_visible AND record.medium='physical') AS physical,
                      count(*) FILTER (WHERE record.overview_visible AND record.medium='digital') AS digital,
                      count(*) FILTER (WHERE record.overview_visible AND record.medium='mixed') AS mixed,
                      count(*) FILTER (WHERE record.overview_visible AND record.is_vital) AS vital,
                      count(*) FILTER (WHERE record.overview_visible AND record.on_effective_hold) AS held,
                      count(*) AS owned_total,
                      count(*) FILTER (WHERE record.medium='physical') AS owned_physical,
                      count(*) FILTER (WHERE record.medium='digital') AS owned_digital,
                      count(*) FILTER (WHERE record.medium='mixed') AS owned_mixed,
                      count(*) FILTER (WHERE record.is_vital) AS owned_vital,
                      coalesce(sum(component.component_count),0) AS component_count,
                      coalesce(sum(component.storage_size_in_bytes),0) AS storage_size_in_bytes
                 FROM visible_records record
            LEFT JOIN component_metrics component ON component.record_id=record.id
                GROUP BY record.owning_org_unit_id
           ), eligible_units AS (
               SELECT DISTINCT unit.id AS org_unit_id,unit.code AS org_unit_code,
                      unit.name AS org_unit_name,unit.translations
                 FROM assigned_roles role JOIN org_units unit ON unit.id=role.org_unit_id
           ), review_units AS (
               SELECT DISTINCT org_unit_id FROM effective_roles
           ), reviewable AS MATERIALIZED (
               SELECT 'aggregation'::text AS entity_type,id AS entity_id,date_of_next_review,
                      title,aggregation_number,NULL::text AS record_number
                 FROM visible_aggregations
                WHERE date_of_next_review IS NOT NULL AND owning_org_unit_id IN (SELECT org_unit_id FROM review_units)
               UNION ALL
               SELECT 'record',id,date_of_next_review,title,NULL::text,record_number
                 FROM visible_records
                WHERE date_of_next_review IS NOT NULL AND owning_org_unit_id IN (SELECT org_unit_id FROM review_units)
           ), governed_resource_events AS (
               SELECT DISTINCT ON (event.entity_type,event.entity_id,event.operation)
                      event.id,event.entity_type,event.entity_id,event.operation,event.occurred_at
                 FROM event_history event
                WHERE event.actor_user_id=current_user_id()
                  AND event.entity_type IN ('aggregation','record')
                  AND event.operation IN ('CREATE','UPDATE')
                  AND event.occurred_at >= coalesce(%s::timestamptz,'-infinity'::timestamptz)
                ORDER BY event.entity_type,event.entity_id,event.operation,
                         event.occurred_at DESC,event.id DESC
           ), content_view_events AS (
               SELECT DISTINCT ON (component.record_id)
                      event.id,'record'::text AS entity_type,
                      component.record_id AS entity_id,
                      event.operation,event.occurred_at
                 FROM event_history event
                 JOIN digital_components component ON component.id=event.entity_id
                WHERE event.actor_user_id=current_user_id()
                  AND event.entity_type='digital_component'
                  AND event.operation='CONTENT_VIEWED'
                  AND event.occurred_at >= coalesce(%s::timestamptz,'-infinity'::timestamptz)
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
           , bounded_events AS MATERIALIZED (
               SELECT * FROM ranked_events WHERE position<=%s
           ), visible_recent_records AS MATERIALIZED (
               SELECT id,title,record_number FROM authorized_records
                WHERE id IN (SELECT entity_id FROM bounded_events WHERE entity_type='record')
           ), visible_recent_aggregations AS MATERIALIZED (
               SELECT id,title,aggregation_number FROM authorized_aggregations
                WHERE id IN (SELECT entity_id FROM bounded_events WHERE entity_type='aggregation')
           )
           , personal_activity AS (
           SELECT event.entity_type,event.entity_id,event.operation,event.occurred_at,
                  coalesce(aggregation.title,record.title) AS title,
                  aggregation.aggregation_number,record.record_number
             FROM bounded_events event
        LEFT JOIN visible_recent_aggregations aggregation
               ON event.entity_type='aggregation' AND aggregation.id=event.entity_id
        LEFT JOIN visible_recent_records record
               ON event.entity_type='record' AND record.id=event.entity_id
            WHERE (aggregation.id IS NOT NULL OR record.id IS NOT NULL)
            ORDER BY event.occurred_at DESC,event.entity_type,event.entity_id
           ), favourite_aggregations AS (
               SELECT aggregation.id,aggregation.aggregation_number,aggregation.title,
                      parent.id AS parent_aggregation_id,favourite.date_created AS date_favourited
                 FROM user_favourite_aggregations favourite
                 JOIN authorized_aggregations aggregation ON aggregation.id=favourite.aggregation_id
            LEFT JOIN authorized_aggregations parent ON parent.id=aggregation.parent_aggregation_id
                WHERE favourite.user_id=current_user_id()
                ORDER BY favourite.date_created DESC,aggregation.id DESC
           ), favourite_records AS (
               SELECT record.id,record.record_number,record.title,
                      aggregation.id AS aggregation_id,aggregation.aggregation_number,
                      aggregation.title AS aggregation_title,favourite.date_created AS date_favourited
                 FROM user_favourite_records favourite
                 JOIN authorized_records record ON record.id=favourite.record_id
            LEFT JOIN authorized_aggregations aggregation ON aggregation.id=record.aggregation_id
                WHERE favourite.user_id=current_user_id()
                ORDER BY favourite.date_created DESC,record.id DESC
           ) SELECT
               (SELECT coalesce(jsonb_agg(code),'[]'::jsonb) FROM effective_privileges) AS privileges,
               (SELECT coalesce(jsonb_agg(item ORDER BY item.date_favourited DESC,item.id DESC),'[]'::jsonb) FROM favourite_aggregations item) AS favourite_aggregations,
               (SELECT coalesce(jsonb_agg(item ORDER BY item.date_favourited DESC,item.id DESC),'[]'::jsonb) FROM favourite_records item) AS favourite_records,
               (SELECT coalesce(jsonb_agg(item ORDER BY item.occurred_at DESC,item.entity_type,item.entity_id),'[]'::jsonb) FROM personal_activity item) AS recent_activity,
               (SELECT coalesce(jsonb_agg(metric),'[]'::jsonb) FROM aggregation_metrics metric) AS aggregations,
               (SELECT coalesce(jsonb_agg(metric),'[]'::jsonb) FROM record_metrics metric) AS records,
               (SELECT coalesce(jsonb_agg(unit),'[]'::jsonb) FROM eligible_units unit) AS units,
               (SELECT count(*) FROM visible_aggregations
                 WHERE parent_aggregation_id IS NULL AND classification_id IS NULL) AS unclassified_root_count,
               (SELECT count(*) FROM reviewable WHERE date_of_next_review<=CURRENT_TIMESTAMP) AS overdue_review_count,
               (SELECT count(*) FROM reviewable WHERE date_of_next_review>CURRENT_TIMESTAMP
                   AND date_of_next_review<=(SELECT ends_at FROM review_cutoff)) AS upcoming_review_count,
               (SELECT coalesce(jsonb_agg(item),'[]'::jsonb) FROM (
                   SELECT * FROM reviewable WHERE date_of_next_review<=CURRENT_TIMESTAMP
                   ORDER BY date_of_next_review ASC,entity_id ASC LIMIT %s
               ) item) AS overdue_reviews,
               (SELECT coalesce(jsonb_agg(item),'[]'::jsonb) FROM (
                   SELECT * FROM reviewable WHERE date_of_next_review>CURRENT_TIMESTAMP
                     AND date_of_next_review<=(SELECT ends_at FROM review_cutoff)
                   ORDER BY date_of_next_review ASC,entity_id ASC LIMIT %s
               ) item) AS upcoming_reviews""",
        (review_window_days, review_window_days, recent_since, recent_since, recent_limit, review_preview_limit, review_preview_limit),
    ).fetchone()


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
    resource_metrics = _resource_metrics(connection, REVIEW_WARNING_WINDOW_DAYS, DASHBOARD_REVIEW_PREVIEW_LIMIT,
                                         recent_limit, recent_since)
    privileges = set(resource_metrics["privileges"])
    overview_counts = {
        resource: sum(row["total"] for row in resource_metrics[resource])
        for resource in ("aggregations", "records")
    }
    overview_medium_counts = {
        resource: {medium: sum(row[medium] for row in resource_metrics[resource])
                   for medium in ("physical", "digital", "mixed")}
        for resource in ("aggregations", "records")
    }
    overview_resource_attention_counts = {
        resource: {metric: sum(row[metric] for row in resource_metrics[resource])
                   for metric in ("vital", "held")}
        for resource in ("aggregations", "records")
    }
    overview_aggregation_status_counts = {
        status: sum(row[status] for row in resource_metrics["aggregations"])
        for status in ("open", "closed")
    }
    overview_digital_component_metrics = {
        metric: sum(row[metric] for row in resource_metrics["records"])
        for metric in ("component_count", "storage_size_in_bytes")
    }
    administrative_counts = []
    for resource, table, privilege in (
        ("holds", "holds", "holds.administer"),
        ("classification-schemes", "classification_schemes", "classifications.administer"),
        ("classifications", "classifications", "classifications.administer"),
        ("org-units", "org_units", "organization.administer"),
        ("roles", "roles", "organization.administer"),
        ("users", "users", "identity.users.administer"),
    ):
        if privilege in privileges:
            # Identifiers and labels come only from the fixed table above.
            administrative_counts.append(f"SELECT '{resource}' AS resource,count(*) AS total FROM {table}")
    if administrative_counts:
        overview_counts.update({row["resource"]: row["total"] for row in connection.execute(
            " UNION ALL ".join(administrative_counts)).fetchall()})

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
            """WITH RECURSIVE classification_tree AS (
                   SELECT classification.id,classification.date_deactivated IS NULL AS active,
                          classification.id IN (SELECT classification_id FROM classification_retention_rules) AS has_rule
                     FROM classifications classification WHERE parent_classification_id IS NULL
                   UNION ALL
                   SELECT child.id,parent.active AND child.date_deactivated IS NULL,
                          parent.has_rule OR child.id IN (SELECT classification_id FROM classification_retention_rules)
                     FROM classification_tree parent JOIN classifications child ON child.parent_classification_id=parent.id
               ), scheme_metrics AS (
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
                                AND scheme.date_deactivated IS NULL AND scheme.date_published<=CURRENT_TIMESTAMP
                                AND tree.active AND tree.has_rule
                          ) AS assignable_terminals
                     FROM classification_schemes scheme
                LEFT JOIN classifications classification
                       ON classification.classification_scheme_id=scheme.id
                LEFT JOIN classification_tree tree ON tree.id=classification.id
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

    # Count true stored roots in the same authorized snapshot, never from
    # relationship IDs that may have been redacted in an API response.
    unclassified_root_count = resource_metrics["unclassified_root_count"]

    aggregation_by_unit = {row["org_unit_id"]: row for row in resource_metrics["aggregations"]}
    records_by_unit = {row["org_unit_id"]: row for row in resource_metrics["records"]}
    ownership_counts = []
    for unit in resource_metrics["units"]:
        aggregation = aggregation_by_unit.get(unit["org_unit_id"], {})
        record = records_by_unit.get(unit["org_unit_id"], {})
        ownership_counts.append({
            **unit,
            "aggregation_count": aggregation.get("owned_total", 0),
            "open_aggregation_count": aggregation.get("owned_open", 0),
            "closed_aggregation_count": aggregation.get("owned_closed", 0),
            "record_count": record.get("owned_total", 0),
            "physical_record_count": record.get("owned_physical", 0),
            "digital_record_count": record.get("owned_digital", 0),
            "mixed_record_count": record.get("owned_mixed", 0),
            "vital_record_count": record.get("owned_vital", 0),
            "storage_size_in_bytes": record.get("storage_size_in_bytes", 0),
        })
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
            "aggregations": resource_metrics["favourite_aggregations"],
            "records": resource_metrics["favourite_records"],
        },
        "recent_activity": resource_metrics["recent_activity"],
        "review_warning_window_days": REVIEW_WARNING_WINDOW_DAYS,
        "overdue_review_count": int(resource_metrics["overdue_review_count"]),
        "upcoming_review_count": int(resource_metrics["upcoming_review_count"]),
        "overdue_reviews": resource_metrics["overdue_reviews"],
        "upcoming_reviews": resource_metrics["upcoming_reviews"],
    }
