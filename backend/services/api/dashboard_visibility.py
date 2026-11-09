"""Statement-local canonical view predicates within the dashboard live scope.

Keep differential tests against current_user_can_view_* when those predicates
change. Nothing here persists authorization results or accepts a caller-supplied
identity: every set belongs to current_user_id() on this request's connection.
Disposed statuses 10/11/12 are excluded for every dashboard caller. Canonical
authorization elsewhere can still permit controlled retained-resource access.
"""

VISIBILITY_CTES = """
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
    SELECT id,aggregation_number,title,owning_org_unit_id,security_level_id,medium,is_vital,
           date_closed,date_of_next_review,parent_aggregation_id,classification_id,disposition_status,
           inherit_acl_from_parent,default_child_aggregation_acl_mode
      FROM aggregations WHERE disposition_status NOT IN (10,11,12)
), live_records AS MATERIALIZED (
    SELECT id,record_number,title,owning_org_unit_id,security_level_id,medium,is_vital,
           date_of_next_review,aggregation_id,disposition_status,inherit_acl_from_parent
      FROM records WHERE disposition_status NOT IN (10,11,12)
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
    -- Fetch only missing ancestors. Unrelated disposed branches never enter
    -- the ACL/hold graph; a required ancestor is not filtered by its status.
    SELECT parent.id,parent.parent_aggregation_id,parent.inherit_acl_from_parent,
           parent.default_child_aggregation_acl_mode
      FROM required_aggregation_rows child JOIN aggregations parent ON parent.id=child.parent_aggregation_id
     WHERE child.parent_aggregation_id NOT IN (SELECT id FROM live_aggregations)
), aggregation_sources AS (
    SELECT resource.id,resource.id AS source_id,'resource'::text AS source_kind,
           resource.default_child_aggregation_acl_mode
      FROM required_aggregation_rows resource WHERE resource.parent_aggregation_id IS NULL
    UNION ALL
    SELECT child.id,
           CASE WHEN NOT child.inherit_acl_from_parent THEN child.id
                WHEN source.default_child_aggregation_acl_mode='custom' THEN source.id ELSE source.source_id END,
           CASE WHEN NOT child.inherit_acl_from_parent THEN 'resource'
                WHEN source.default_child_aggregation_acl_mode='custom' THEN 'child_default' ELSE source.source_kind END,
           child.default_child_aggregation_acl_mode
      FROM aggregation_sources source JOIN required_aggregation_rows child ON child.parent_aggregation_id=source.id
), aggregation_acl_targets AS MATERIALIZED (
    SELECT DISTINCT source.source_id,source.source_kind,resource.owning_org_unit_id
      FROM aggregation_sources source JOIN live_aggregations resource ON resource.id=source.id
), record_acl_targets AS MATERIALIZED (
    SELECT DISTINCT CASE WHEN inherit_acl_from_parent THEN aggregation_id ELSE id END AS source_id,
           CASE WHEN inherit_acl_from_parent THEN 'child_default' ELSE 'resource' END AS source_kind,owning_org_unit_id
      FROM live_records
), aggregation_view_grants AS MATERIALIZED (
    SELECT grant_row.aggregation_id AS source_id,'resource'::text AS source_kind,
           grant_row.principal_type,grant_row.role_id
      FROM aggregation_acl_grants grant_row JOIN permissions permission ON permission.id=grant_row.permission_id
     WHERE permission.code='aggregation.view'
       AND grant_row.aggregation_id IN (SELECT source_id FROM aggregation_acl_targets WHERE source_kind='resource')
    UNION ALL
    SELECT grant_row.aggregation_id,'child_default',grant_row.principal_type,grant_row.role_id
      FROM aggregation_child_aggregation_acl_defaults grant_row JOIN permissions permission ON permission.id=grant_row.permission_id
     WHERE permission.code='aggregation.view'
       AND grant_row.aggregation_id IN (SELECT source_id FROM aggregation_acl_targets WHERE source_kind='child_default')
), record_view_grants AS MATERIALIZED (
    SELECT grant_row.record_id AS source_id,'resource'::text AS source_kind,
           grant_row.principal_type,grant_row.role_id
      FROM record_acl_grants grant_row JOIN permissions permission ON permission.id=grant_row.permission_id
     WHERE permission.code='record.view'
       AND grant_row.record_id IN (SELECT source_id FROM record_acl_targets WHERE source_kind='resource')
    UNION ALL
    SELECT grant_row.aggregation_id,'child_default',grant_row.principal_type,grant_row.role_id
      FROM aggregation_child_record_acl_defaults grant_row JOIN permissions permission ON permission.id=grant_row.permission_id
     WHERE permission.code='record.view'
       AND grant_row.aggregation_id IN (SELECT source_id FROM record_acl_targets WHERE source_kind='child_default')
), matched_aggregation_acl AS MATERIALIZED (
    SELECT DISTINCT target.* FROM aggregation_acl_targets target
      JOIN aggregation_view_grants grant_row USING(source_id,source_kind)
 LEFT JOIN contextual_units unit ON unit.id=target.owning_org_unit_id
     WHERE grant_row.principal_type='everyone'
        OR grant_row.principal_type='role' AND grant_row.role_id IN (SELECT id FROM effective_roles)
        OR grant_row.principal_type='org_unit_members' AND unit.member
        OR grant_row.principal_type='owning_and_higher_level_unit_managers' AND unit.manager
        OR grant_row.principal_type='effective_file_administrator' AND unit.file_administrator
), matched_record_acl AS MATERIALIZED (
    SELECT DISTINCT target.* FROM record_acl_targets target
      JOIN record_view_grants grant_row USING(source_id,source_kind)
 LEFT JOIN contextual_units unit ON unit.id=target.owning_org_unit_id
     WHERE grant_row.principal_type='everyone'
        OR grant_row.principal_type='role' AND grant_row.role_id IN (SELECT id FROM effective_roles)
        OR grant_row.principal_type='org_unit_members' AND unit.member
        OR grant_row.principal_type='owning_and_higher_level_unit_managers' AND unit.manager
        OR grant_row.principal_type='effective_file_administrator' AND unit.file_administrator
), authorized_aggregations AS MATERIALIZED (
    SELECT resource.id,resource.aggregation_number,resource.title,resource.owning_org_unit_id,
           resource.medium,resource.is_vital,resource.date_closed,resource.date_of_next_review,
           resource.parent_aggregation_id,resource.classification_id,resource.disposition_status
      FROM live_aggregations resource
      JOIN aggregation_sources source ON source.id=resource.id
      JOIN security_levels required ON required.id=resource.security_level_id CROSS JOIN authority
 LEFT JOIN matched_aggregation_acl acl ON acl.source_id=source.source_id AND acl.source_kind=source.source_kind
           AND acl.owning_org_unit_id=resource.owning_org_unit_id
     WHERE current_user_id() IS NOT NULL
       AND 'aggregation.view' IN (SELECT code FROM effective_privileges)
       AND required.level_number<=authority.clearance
       AND (required.level_number<=authority.governance_clearance OR acl.source_id IS NOT NULL)
), authorized_records AS MATERIALIZED (
    SELECT resource.id,resource.record_number,resource.title,resource.owning_org_unit_id,
           resource.medium,resource.is_vital,resource.date_of_next_review,resource.aggregation_id,
           resource.disposition_status FROM live_records resource
      JOIN security_levels required ON required.id=resource.security_level_id CROSS JOIN authority
 LEFT JOIN matched_record_acl acl ON acl.source_kind=CASE WHEN resource.inherit_acl_from_parent THEN 'child_default' ELSE 'resource' END
           AND acl.source_id=CASE WHEN resource.inherit_acl_from_parent THEN resource.aggregation_id ELSE resource.id END
           AND acl.owning_org_unit_id=resource.owning_org_unit_id
     WHERE current_user_id() IS NOT NULL
       AND 'record.view' IN (SELECT code FROM effective_privileges)
       AND required.level_number<=authority.clearance
       AND (required.level_number<=authority.governance_clearance OR acl.source_id IS NOT NULL)
)
"""
