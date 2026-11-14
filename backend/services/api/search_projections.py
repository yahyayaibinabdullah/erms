"""Set-based inherited values needed by search criteria, not page decoration."""
from psycopg import sql

HOLD_FIELDS = {'on_effective_hold', 'resource_state_changes_blocked', 'effective_hold_id'}
LOCATION_FIELDS = {'effective_assigned_location', 'effective_current_location'}


def requested_fields(request):
    def fields(node):
        if node is None:
            return set()
        return ({node.field} if node.field else set()) | set().union(
            *(fields(child) for child in (node.and_ or node.or_ or []))) | fields(node.not_)
    return fields(request.where) | {s.field for s in request.sort}


def projection_ctes(resource, request):
    """Mirror the search views' values without walking ancestors per candidate.

    Propagate each active hold down the hierarchy once, preserving both direct
    record holds and inherited holds. Locations propagate the nearest non-null
    value, including empty strings, exactly as the canonical SQL functions do.
    These values do not authorize a resource: the caller must still join the
    canonical batch ACL before selecting/ranking any hit. Never return hold IDs
    through the resource response; they are internal filter inputs only.
    """
    fields = requested_fields(request)
    retention = resource == 'aggregations' and any(field.startswith('effective_retention.') for field in fields)
    if not retention and not fields & (HOLD_FIELDS | LOCATION_FIELDS):
        return []
    ctes, columns, joins = [], [], []
    if retention:
        # The canonical resolver depends on the governing root and that root's
        # classification. Resolve each distinct classification once, then join
        # root overrides and propagate their values to descendants.
        ctes.append(sql.SQL('''search_root_map(id,root_id) AS (
            SELECT id,id FROM aggregations WHERE parent_aggregation_id IS NULL
            UNION ALL SELECT child.id,parent.root_id FROM aggregations child
                JOIN search_root_map parent ON child.parent_aggregation_id=parent.id
        ), unique_search_roots AS MATERIALIZED (SELECT DISTINCT ON(id) * FROM search_root_map),
        search_classification_rules AS MATERIALIZED (
            SELECT classes.classification_id,rule.* FROM (
                SELECT DISTINCT classification_id FROM aggregations WHERE parent_aggregation_id IS NULL
            ) classes LEFT JOIN LATERAL effective_classification_retention_rule(classes.classification_id) rule ON true
        ), search_retention_values AS NOT MATERIALIZED (
            SELECT mapping.id,coalesce(local.current_period_years,rule.current_period_years) AS current_period_years,
                   coalesce(local.intermediate_period_years,rule.intermediate_period_years) AS intermediate_period_years,
                   coalesce(local.final_disposition,rule.final_disposition) AS final_disposition
            FROM unique_search_roots mapping JOIN aggregations root ON root.id=mapping.root_id
            LEFT JOIN aggregation_retention_rules local ON local.aggregation_id=root.id
            LEFT JOIN search_classification_rules rule ON rule.classification_id=root.classification_id
        )'''))
    if fields & HOLD_FIELDS:
        ctes.append(sql.SQL('''active_search_holds AS MATERIALIZED (
            SELECT id,preserve_resource_state FROM holds
            WHERE valid_from<=statement_timestamp() AND (valid_to IS NULL OR statement_timestamp()<valid_to)
        ), search_aggregation_holds(aggregation_id,hold_id,preserve_resource_state) AS (
            SELECT assignment.aggregation_id,hold.id,hold.preserve_resource_state
            FROM hold_aggregation_assignments assignment JOIN active_search_holds hold ON hold.id=assignment.hold_id
            UNION
            SELECT child.id,parent.hold_id,parent.preserve_resource_state
            FROM search_aggregation_holds parent JOIN aggregations child ON child.parent_aggregation_id=parent.aggregation_id
        )'''))
        held = sql.SQL('SELECT aggregation_id AS id,hold_id,preserve_resource_state FROM search_aggregation_holds')
        if resource == 'records':
            held = sql.SQL('''SELECT record.id,hold.hold_id,hold.preserve_resource_state
                FROM records record JOIN search_aggregation_holds hold ON hold.aggregation_id=record.aggregation_id
                UNION SELECT assignment.record_id,hold.id,hold.preserve_resource_state
                FROM hold_record_assignments assignment JOIN active_search_holds hold ON hold.id=assignment.hold_id''')
        ctes.append(sql.SQL('''search_hold_values AS MATERIALIZED (
            SELECT id,array_agg(hold_id ORDER BY hold_id) AS hold_ids,bool_or(preserve_resource_state) AS blocked
            FROM ({}) held GROUP BY id
        )''').format(held))
        columns.extend([sql.SQL('hold.id IS NOT NULL AS on_effective_hold'),
                        sql.SQL('coalesce(hold.blocked,false) AS resource_state_changes_blocked'),
                        sql.SQL("coalesce(hold.hold_ids,'{}'::bigint[]) AS effective_hold_ids")])
        joins.append(sql.SQL('LEFT JOIN search_hold_values hold ON hold.id=base.id'))
    if fields & LOCATION_FIELDS:
        ctes.append(sql.SQL('''search_locations(id,assigned,current) AS (
            SELECT id,assigned_location,current_location FROM aggregations WHERE parent_aggregation_id IS NULL
            UNION ALL
            SELECT child.id,coalesce(child.assigned_location,parent.assigned),coalesce(child.current_location,parent.current)
            FROM aggregations child JOIN search_locations parent ON child.parent_aggregation_id=parent.id
        ), unique_search_locations AS MATERIALIZED (SELECT DISTINCT ON(id) * FROM search_locations)'''))
        for name, column in [('assigned', 'assigned'), ('current', 'current')]:
            value = sql.SQL('location.{}').format(sql.Identifier(column))
            if resource == 'aggregations':
                value = sql.SQL('CASE WHEN base.disposition_status<>10 THEN {} END').format(value)
            columns.append(sql.SQL('{} AS {}').format(value, sql.Identifier(f'effective_{name}_location')))
        joins.append(sql.SQL('LEFT JOIN unique_search_locations location ON location.id=base.{}').format(
            sql.Identifier('aggregation_id' if resource == 'records' else 'id')))
    if not columns:
        return ctes
    ctes.append(sql.SQL('search_resources AS NOT MATERIALIZED (SELECT base.*,{} FROM {} base {})').format(
        sql.SQL(',').join(columns), sql.Identifier(resource), sql.SQL(' ').join(joins)))
    return ctes
