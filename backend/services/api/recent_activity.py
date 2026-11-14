"""Personal activity candidates and ordinary resource visibility in one statement."""
from datetime import datetime
from typing import Literal

from psycopg import Connection
from psycopg.types.json import Jsonb

from .dashboard_visibility import visibility_ctes
from .resource_authorization import governance_role_snapshot
from .search_execution import interactive_search


# Keep the same ordinary view scope as the detail routes, including retained
# status 11/12 when the caller can view it. Dashboard metrics have a different
# live-only scope. Only the card path needs ACL attribution for audit events.
ACTIVITY_SCOPES = {
    None: (None, "", "JOIN records record ON record.id=component.record_id",
           "VALUES ('record'::text,component.record_id),('aggregation'::text,record.aggregation_id)"),
    "record": ("records", "AND event.entity_type='record'", "",
               "VALUES ('record'::text,component.record_id)"),
    "aggregation": ("aggregations", "AND event.entity_type='aggregation'",
                    "JOIN records record ON record.id=component.record_id",
                    "VALUES ('aggregation'::text,record.aggregation_id)"),
}


def _activity_statement(entity_type: str | None) -> str:
    resource_table, resource_filter, parent_join, targets = ACTIVITY_SCOPES[entity_type]
    card_fields = "" if entity_type is None else f"""
        ,resource.title,resource.{entity_type}_number AS number,
         CASE WHEN NOT event.has_view_acl THEN resource.security_level_id END AS bypass_level_id,
         level.level_number
    """
    resource_join = "" if entity_type is None else f"""
        JOIN {resource_table} resource ON resource.id=event.entity_id
        JOIN security_levels level ON level.id=resource.security_level_id
    """
    attribution = ",has_view_acl" if entity_type is not None else ""
    event_attribution = ",target.has_view_acl" if entity_type is not None else ""
    return f"""WITH RECURSIVE governed_resource_events AS (
        SELECT DISTINCT ON (event.entity_type,event.entity_id,event.operation)
               event.id,event.entity_type,event.entity_id,event.operation,event.occurred_at
          FROM event_history event
         WHERE event.actor_user_id=%s AND event.occurred_at >= %s
           AND event.entity_type IN ('aggregation','record')
           AND event.operation IN ('CREATE','UPDATE') {resource_filter}
         ORDER BY event.entity_type,event.entity_id,event.operation,event.occurred_at DESC,event.id DESC
    ), content_view_events AS (
        SELECT DISTINCT ON (target.entity_type,target.entity_id)
               event.id,target.entity_type,target.entity_id,event.operation,event.occurred_at
          FROM event_history event
          JOIN digital_components component ON component.id=event.entity_id
          {parent_join}
          CROSS JOIN LATERAL ({targets}) target(entity_type,entity_id)
         WHERE event.actor_user_id=%s AND event.occurred_at >= %s
           AND event.entity_type='digital_component' AND event.operation='CONTENT_VIEWED'
         ORDER BY target.entity_type,target.entity_id,event.occurred_at DESC,event.id DESC
    ), latest_resource_events AS MATERIALIZED (
        SELECT * FROM governed_resource_events UNION ALL SELECT * FROM content_view_events
    ), page_aggregation_ids AS (
        SELECT DISTINCT entity_id AS id FROM latest_resource_events WHERE entity_type='aggregation'
    ), page_record_ids AS (
        SELECT DISTINCT entity_id AS id FROM latest_resource_events WHERE entity_type='record'
    ), {visibility_ctes(page_access=True, acl_attribution=entity_type is not None)},
    authorized_targets AS (
        SELECT 'aggregation'::text AS entity_type,id{attribution} FROM authorized_aggregations
        UNION ALL
        SELECT 'record'::text,id{attribution} FROM authorized_records
    ), ranked_events AS (
        SELECT event.*{event_attribution},
               row_number() OVER (
                   PARTITION BY event.entity_type,event.operation ORDER BY event.occurred_at DESC,event.id DESC
               ) AS position
          FROM latest_resource_events event JOIN authorized_targets target
            ON target.entity_type=event.entity_type AND target.id=event.entity_id
    ), bounded_events AS MATERIALIZED (
        SELECT * FROM ranked_events WHERE position<=%s
    )
    SELECT event.entity_type,event.entity_id,event.operation,event.occurred_at{card_fields}
      FROM bounded_events event {resource_join}
     ORDER BY event.occurred_at DESC,event.entity_type,event.entity_id,event.id DESC
    """


ACTIVITY_STATEMENTS = {scope: _activity_statement(scope) for scope in ACTIVITY_SCOPES}


@interactive_search
def recent_activity(
    connection: Connection, user_id: int, since: datetime, limit: int,
    entity_type: Literal["record", "aggregation"] | None,
) -> list[dict]:
    rows = connection.execute(
        ACTIVITY_STATEMENTS[entity_type], (user_id, since, user_id, since, limit),
    ).fetchall()
    if entity_type is None:
        return rows

    # The old card loader opened each distinct resource through the detail
    # route, which audited governance bypass when ordinary ACL access was absent.
    # Preserve that audit once per returned resource. Read qualifying roles
    # once, then write all events together through the existing audit function.
    bypassed = {}
    for row in rows:
        level_id = row.pop("bypass_level_id")
        level_number = row.pop("level_number")
        if level_id is not None:
            bypassed[row["entity_id"]] = (level_number, level_id)
    if bypassed:
        _, lowest_level_id = min(bypassed.values())
        roles = governance_role_snapshot(connection, [lowest_level_id])
        permission = f"{entity_type}.view"
        events = [
            {"id": resource_id, "metadata": {
                "authorization_basis": "information_governance",
                "required_privilege": permission,
                "required_permission": permission,
                "qualifying_roles": [role for role in roles if role["level_number"] >= level],
            }}
            for resource_id, (level, _) in bypassed.items()
        ]
        connection.execute("""
            SELECT append_domain_event(%s,event.id,'INFORMATION_GOVERNANCE_BYPASS_USED',event.metadata)
              FROM jsonb_to_recordset(%s) AS event(id bigint,metadata jsonb)
        """, (entity_type, Jsonb(events)))
    return rows
