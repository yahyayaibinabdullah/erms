"""Statement-local canonical view predicates for dashboard and search scopes.

Keep differential tests against current_user_can_view_* when those predicates
change. Nothing here persists authorization results or accepts a caller-supplied
identity: every set belongs to current_user_id() on this request's connection.
Disposed statuses 10/11/12 are excluded for every dashboard caller. Canonical
authorization elsewhere can still permit controlled retained-resource access.
"""

_VISIBILITY_CTES = """
org_tree AS (
    SELECT unit.id,unit.parent_org_unit_id,unit.date_deactivated IS NULL AS active,
           unit.file_administrator_role_id,unit.id AS file_administrator_unit_id
      FROM org_units unit
     WHERE unit.parent_org_unit_id IS NULL
    UNION ALL
    SELECT unit.id,unit.parent_org_unit_id,parent.active AND unit.date_deactivated IS NULL,
           coalesce(unit.file_administrator_role_id,parent.file_administrator_role_id),
           CASE WHEN unit.file_administrator_role_id IS NOT NULL THEN unit.id
                ELSE parent.file_administrator_unit_id END
      FROM org_units unit JOIN org_tree parent ON parent.id=unit.parent_org_unit_id
), assigned_roles AS MATERIALIZED (
    SELECT DISTINCT role.id,role.org_unit_id,role.profile_id,role.is_information_governance,
           role.is_system,role.account_type_restriction,level.level_number,
           assignment.valid_from,assignment.valid_until
      FROM user_role_assignments assignment JOIN roles role ON role.id=assignment.role_id
      JOIN security_levels level ON level.id=role.security_level_id
 LEFT JOIN org_tree unit ON unit.id=role.org_unit_id
     WHERE assignment.user_id=current_user_id() AND assignment.valid_from<=CURRENT_TIMESTAMP
       AND (assignment.valid_until IS NULL OR assignment.valid_until>=CURRENT_TIMESTAMP)
       AND role.date_deactivated IS NULL
       AND CASE WHEN role.is_system THEN role.account_type_restriction='service' AND role.org_unit_id IS NULL
                ELSE coalesce(unit.active,false) END
), effective_roles AS MATERIALIZED (
    SELECT DISTINCT id,org_unit_id,profile_id,is_information_governance,is_system,account_type_restriction,level_number
      FROM assigned_roles WHERE valid_until IS NULL OR valid_until>CURRENT_TIMESTAMP
), effective_privileges AS MATERIALIZED (
    SELECT DISTINCT privilege.code FROM effective_roles role
      JOIN profile_privileges membership ON membership.profile_id=role.profile_id
      JOIN privileges privilege ON privilege.id=membership.privilege_id
      JOIN users account ON account.id=current_user_id() AND account.status='active'
), authority AS MATERIALIZED (
    SELECT max(level_number) AS clearance,
           max(level_number) FILTER (WHERE is_information_governance) AS governance_clearance
      FROM effective_roles
), manager_units(id) AS (
    SELECT unit.id FROM org_units unit JOIN effective_roles role ON role.id=unit.managing_role_id
     WHERE role.org_unit_id=unit.id AND NOT role.is_system
       AND role.account_type_restriction IS DISTINCT FROM 'service'
    UNION
    SELECT child.id FROM org_units child JOIN manager_units parent ON parent.id=child.parent_org_unit_id
), contextual_units AS MATERIALIZED (
    SELECT unit.id,
           unit.id IN (SELECT org_unit_id FROM effective_roles) AS member,
           unit.id IN (SELECT id FROM manager_units) AS manager,
           administrator.id IS NOT NULL AS file_administrator
      FROM org_tree unit
 LEFT JOIN effective_roles administrator ON administrator.id=unit.file_administrator_role_id
       AND administrator.org_unit_id=unit.file_administrator_unit_id
       AND NOT administrator.is_system AND administrator.account_type_restriction IS DISTINCT FROM 'service'
), live_aggregations AS MATERIALIZED (
    SELECT id,owning_org_unit_id,security_level_id,parent_aggregation_id,disposition_status,
           {aggregation_details}
           inherit_acl_from_parent,default_child_aggregation_acl_mode
      FROM aggregations {aggregation_candidates} WHERE {aggregation_scope}
), live_records AS MATERIALIZED (
    SELECT id,owning_org_unit_id,security_level_id,{record_details}
           aggregation_id,disposition_status,inherit_acl_from_parent
      FROM records {record_candidates} WHERE {record_scope}
), required_aggregation_rows AS (
    SELECT id,parent_aggregation_id,inherit_acl_from_parent,default_child_aggregation_acl_mode
      FROM live_aggregations
    UNION
    -- Normally all containers are live. Preserve canonical record/hold access
    -- even when a live record refers to a retained container.
    SELECT resource.id,resource.parent_aggregation_id,resource.inherit_acl_from_parent,
           resource.default_child_aggregation_acl_mode
      FROM aggregations resource
     WHERE resource.id IN (
         SELECT aggregation_id FROM live_records
          WHERE aggregation_id NOT IN (SELECT id FROM live_aggregations)
     )
    UNION
    -- Fetch only missing ancestors, regardless of their status or match status.
    SELECT parent.id,parent.parent_aggregation_id,parent.inherit_acl_from_parent,
           parent.default_child_aggregation_acl_mode
      FROM required_aggregation_rows child JOIN aggregations parent ON parent.id=child.parent_aggregation_id
     WHERE child.parent_aggregation_id NOT IN (SELECT id FROM live_aggregations)
), aggregation_sources AS (
    SELECT resource.id,resource.id AS source_id,false AS is_child_default,
           resource.default_child_aggregation_acl_mode
      FROM required_aggregation_rows resource WHERE resource.parent_aggregation_id IS NULL
    UNION ALL
    SELECT child.id,
           CASE WHEN NOT child.inherit_acl_from_parent THEN child.id
                WHEN source.default_child_aggregation_acl_mode='custom' THEN source.id ELSE source.source_id END,
           CASE WHEN NOT child.inherit_acl_from_parent THEN false
                WHEN source.default_child_aggregation_acl_mode='custom' THEN true ELSE source.is_child_default END,
           child.default_child_aggregation_acl_mode
      FROM aggregation_sources source JOIN required_aggregation_rows child ON child.parent_aggregation_id=source.id
), resolved_aggregation_sources AS MATERIALIZED (
    -- The single-parent hierarchy has exactly one source per aggregation.
    -- State that uniqueness explicitly; recursive row-count extrapolation can
    -- otherwise size a hash join for billions of rows in a shallow hierarchy.
    SELECT DISTINCT ON (id) id,source_id,is_child_default FROM aggregation_sources
), aggregation_acl_targets AS MATERIALIZED (
    SELECT DISTINCT source.source_id,source.is_child_default,resource.owning_org_unit_id
      FROM resolved_aggregation_sources source JOIN live_aggregations resource ON resource.id=source.id
), record_acl_targets AS MATERIALIZED (
    SELECT DISTINCT CASE WHEN inherit_acl_from_parent THEN aggregation_id ELSE id END AS source_id,
           inherit_acl_from_parent AS is_child_default,owning_org_unit_id
      FROM live_records
-- Let the target/grant join below constrain these branches. A separate target
-- semijoin followed by that same join compounded selectivity estimates and
-- made broad searches look like single-row lookups.
), aggregation_view_grants AS NOT MATERIALIZED (
    SELECT grant_row.aggregation_id AS source_id,false AS is_child_default,
           grant_row.principal_type,grant_row.role_id
      FROM aggregation_acl_grants grant_row JOIN permissions permission ON permission.id=grant_row.permission_id
     WHERE permission.code='aggregation.view'
    UNION ALL
    SELECT grant_row.aggregation_id,true,grant_row.principal_type,grant_row.role_id
      FROM aggregation_child_aggregation_acl_defaults grant_row JOIN permissions permission ON permission.id=grant_row.permission_id
     WHERE permission.code='aggregation.view'
), record_view_grants AS NOT MATERIALIZED (
    SELECT grant_row.record_id AS source_id,false AS is_child_default,
           grant_row.principal_type,grant_row.role_id,
           permission.code='record.view' AS is_record,
           permission.code='record.component.view' AS is_component,
           permission.code='record.component.list' AS is_list
      FROM record_acl_grants grant_row JOIN permissions permission ON permission.id=grant_row.permission_id
     WHERE permission.code IN ({record_permissions})
    UNION ALL
    SELECT grant_row.aggregation_id,true,grant_row.principal_type,grant_row.role_id,
           permission.code='record.view',permission.code='record.component.view',permission.code='record.component.list'
      FROM aggregation_child_record_acl_defaults grant_row JOIN permissions permission ON permission.id=grant_row.permission_id
     WHERE permission.code IN ({record_permissions})
), matched_aggregation_acl AS MATERIALIZED (
    SELECT DISTINCT target.* FROM aggregation_acl_targets target
      JOIN aggregation_view_grants grant_row USING(source_id,is_child_default)
 LEFT JOIN contextual_units unit ON unit.id=target.owning_org_unit_id
     WHERE grant_row.principal_type='everyone'
        OR grant_row.principal_type='role' AND grant_row.role_id IN (SELECT id FROM effective_roles)
        OR grant_row.principal_type='org_unit_members' AND unit.member
        OR grant_row.principal_type='owning_and_higher_level_unit_managers' AND unit.manager
        OR grant_row.principal_type='effective_file_administrator' AND unit.file_administrator
), matched_record_acl AS MATERIALIZED (
    SELECT target.*,bool_or(grant_row.is_record) AS can_view_record,
           bool_or(grant_row.is_component) AS can_view_component,
           bool_or(grant_row.is_list) AS can_list_components
      FROM record_acl_targets target
      JOIN record_view_grants grant_row USING(source_id,is_child_default)
 LEFT JOIN contextual_units unit ON unit.id=target.owning_org_unit_id
     WHERE grant_row.principal_type='everyone'
        OR grant_row.principal_type='role' AND grant_row.role_id IN (SELECT id FROM effective_roles)
        OR grant_row.principal_type='org_unit_members' AND unit.member
        OR grant_row.principal_type='owning_and_higher_level_unit_managers' AND unit.manager
        OR grant_row.principal_type='effective_file_administrator' AND unit.file_administrator
    GROUP BY target.source_id,target.is_child_default,target.owning_org_unit_id
), authorized_aggregations AS MATERIALIZED (
    SELECT resource.id,{authorized_aggregation_details}
           resource.owning_org_unit_id,resource.parent_aggregation_id,resource.disposition_status
      FROM live_aggregations resource
      JOIN security_levels required ON required.id=resource.security_level_id CROSS JOIN authority
     WHERE current_user_id() IS NOT NULL
       AND 'aggregation.view' IN (SELECT code FROM effective_privileges)
       AND required.level_number<=authority.clearance
       AND EXISTS (
           SELECT 1 FROM resolved_aggregation_sources source
           WHERE source.id=resource.id
             AND (required.level_number<=authority.governance_clearance OR EXISTS (
                 SELECT 1 FROM matched_aggregation_acl acl
                 WHERE acl.source_id=source.source_id AND acl.is_child_default=source.is_child_default
                   AND acl.owning_org_unit_id=resource.owning_org_unit_id)))
), authorized_records AS MATERIALIZED (
    SELECT resource.id,{authorized_record_details}resource.owning_org_unit_id,resource.aggregation_id,
           resource.disposition_status {component_projection} FROM live_records resource
      JOIN security_levels required ON required.id=resource.security_level_id CROSS JOIN authority
     WHERE current_user_id() IS NOT NULL
       AND 'record.view' IN (SELECT code FROM effective_privileges)
       AND required.level_number<=authority.clearance
       AND (required.level_number<=authority.governance_clearance OR
            (CASE WHEN resource.inherit_acl_from_parent THEN resource.aggregation_id ELSE resource.id END,
             resource.inherit_acl_from_parent,resource.owning_org_unit_id) IN (
                SELECT source_id,is_child_default,owning_org_unit_id
                FROM matched_record_acl WHERE can_view_record))
)
"""


def visibility_ctes(
    *, candidate_resource: str | None = None, component_access: bool = False,
    match_flags: bool = False, page_access: bool = False,
) -> str:
    """Optionally authorize only the IDs in a search's candidate_ids CTE."""
    if page_access:
        # Page IDs also include parents whose labels need ordinary view access.
        # Search status restrictions are applied by the search views separately.
        aggregation_scope = record_scope = "disposition_status <> 10"
    elif candidate_resource is None:
        aggregation_scope = record_scope = "disposition_status NOT IN (10,11,12)"
    else:
        if candidate_resource not in ("records", "aggregations"):
            raise ValueError("invalid candidate resource")
        # The search views also allow non-destroyed terminal rows for governance.
        candidates = """disposition_status <> 10
            AND (disposition_status NOT IN (11,12) OR (SELECT disposition_private.can_manage()))"""
        aggregation_scope = candidates if candidate_resource == "aggregations" else "false"
        record_scope = candidates if candidate_resource == "records" else "false"
    component_projection = ""
    if component_access:
        component_projection = """,
            'record.component.view' IN (SELECT code FROM effective_privileges)
            AND (COALESCE(required.level_number <= authority.governance_clearance, false)
                 OR COALESCE(
                     (CASE WHEN resource.inherit_acl_from_parent THEN resource.aggregation_id ELSE resource.id END,
                      resource.inherit_acl_from_parent,resource.owning_org_unit_id) IN (
                         SELECT source_id,is_child_default,owning_org_unit_id
                         FROM matched_record_acl WHERE can_view_component), false)) AS can_view_component"""
    if page_access:
        component_projection += """,
            COALESCE(required.level_number <= authority.governance_clearance, false)
            OR COALESCE(
                (CASE WHEN resource.inherit_acl_from_parent THEN resource.aggregation_id ELSE resource.id END,
                 resource.inherit_acl_from_parent,resource.owning_org_unit_id) IN (
                    SELECT source_id,is_child_default,owning_org_unit_id
                    FROM matched_record_acl WHERE can_list_components), false) AS can_list_components"""
    return _VISIBILITY_CTES.format(
        aggregation_scope=aggregation_scope, record_scope=record_scope,
        aggregation_candidates="JOIN page_aggregation_ids USING (id)" if page_access else "JOIN candidate_ids USING (id)" if candidate_resource == "aggregations" else "",
        record_candidates="JOIN page_record_ids USING (id)" if page_access else "JOIN candidate_ids USING (id)" if candidate_resource == "records" else "",
        aggregation_details="aggregation_number,title,medium,is_vital,date_closed,date_of_next_review,classification_id," if candidate_resource is None and not page_access else "",
        record_details=("record_number,title,medium,is_vital,date_of_next_review," if candidate_resource is None and not page_access else "")
            + ("metadata_match,component_match," if match_flags else ""),
        authorized_aggregation_details="resource.aggregation_number,resource.title,resource.medium,resource.is_vital,resource.date_closed,resource.date_of_next_review,resource.classification_id," if candidate_resource is None and not page_access else "",
        authorized_record_details=("resource.record_number,resource.title,resource.medium,resource.is_vital,resource.date_of_next_review," if candidate_resource is None and not page_access else "")
            + ("resource.metadata_match,resource.component_match," if match_flags else ""),
        record_permissions="'record.view', 'record.component.view', 'record.component.list'" if page_access else "'record.view', 'record.component.view'" if component_access else "'record.view'",
        component_projection=component_projection,
    )


VISIBILITY_CTES = visibility_ctes()
