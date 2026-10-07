-- Prospective defaults only: this upgrade never changes existing ACL grants.
BEGIN;
CREATE OR REPLACE FUNCTION event_reference_identity(reference_field text, reference_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE snapshot jsonb;
DECLARE existing_snapshots jsonb;
BEGIN
    CASE reference_field
        WHEN 'profile_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM profiles WHERE id=reference_id;
        WHEN 'old_profile_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM profiles WHERE id=reference_id;
        WHEN 'new_profile_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM profiles WHERE id=reference_id;
        WHEN 'security_level_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name,'level_number',level_number) INTO snapshot FROM security_levels WHERE id=reference_id;
        WHEN 'classification_id' THEN SELECT jsonb_build_object('id',id,'code',code,'title',title) INTO snapshot FROM classifications WHERE id=reference_id;
        WHEN 'parent_classification_id' THEN SELECT jsonb_build_object('id',id,'code',code,'title',title) INTO snapshot FROM classifications WHERE id=reference_id;
        WHEN 'classification_scheme_id' THEN SELECT jsonb_build_object('id',id,'code',code,'title',title) INTO snapshot FROM classification_schemes WHERE id=reference_id;
        WHEN 'aggregation_id' THEN SELECT jsonb_build_object('id',id,'code',aggregation_number,'title',title) INTO snapshot FROM aggregations WHERE id=reference_id;
        WHEN 'parent_aggregation_id' THEN SELECT jsonb_build_object('id',id,'code',aggregation_number,'title',title) INTO snapshot FROM aggregations WHERE id=reference_id;
        WHEN 'destination_aggregation_id' THEN SELECT jsonb_build_object('id',id,'code',aggregation_number,'title',title) INTO snapshot FROM aggregations WHERE id=reference_id;
        WHEN 'record_id' THEN SELECT jsonb_build_object('id',id,'code',record_number,'title',title) INTO snapshot FROM records WHERE id=reference_id;
        WHEN 'role_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM roles WHERE id=reference_id;
        WHEN 'managing_role_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM roles WHERE id=reference_id;
        WHEN 'file_administrator_role_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM roles WHERE id=reference_id;
        WHEN 'supervisor_role_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM roles WHERE id=reference_id;
        WHEN 'user_id' THEN SELECT jsonb_build_object('id',id,'name',name,'email',email) INTO snapshot FROM users WHERE id=reference_id;
        WHEN 'owner_user_id' THEN SELECT jsonb_build_object('id',id,'name',name,'email',email) INTO snapshot FROM users WHERE id=reference_id;
        WHEN 'org_unit_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM org_units WHERE id=reference_id;
        WHEN 'parent_org_unit_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM org_units WHERE id=reference_id;
        WHEN 'owning_org_unit_id' THEN SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO snapshot FROM org_units WHERE id=reference_id;
        ELSE snapshot := NULL;
    END CASE;
    RETURN snapshot;
END;
$$;

ALTER TABLE org_units
 ADD COLUMN managing_role_id bigint REFERENCES roles(id) ON DELETE RESTRICT,
 ADD COLUMN file_administrator_role_id bigint REFERENCES roles(id) ON DELETE RESTRICT;
CREATE INDEX org_units_managing_role_idx ON org_units(managing_role_id);
CREATE INDEX org_units_file_administrator_role_idx ON org_units(file_administrator_role_id);

CREATE FUNCTION validate_org_unit_designated_roles() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE designated bigint;
BEGIN
 FOREACH designated IN ARRAY ARRAY[NEW.managing_role_id,NEW.file_administrator_role_id] LOOP
  IF designated IS NOT NULL AND NOT EXISTS (
   SELECT 1 FROM roles WHERE id=designated AND org_unit_id=NEW.id AND NOT is_system
    AND account_type_restriction IS DISTINCT FROM 'service'
  ) THEN RAISE EXCEPTION 'designated role must belong to the same unit and be a non-system person role' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF NEW.file_administrator_role_id IS DISTINCT FROM OLD.file_administrator_role_id
   AND NEW.file_administrator_role_id IS NOT NULL
   AND NOT role_effectively_active(NEW.file_administrator_role_id) THEN
  RAISE EXCEPTION 'File Administrator role must be active' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER org_units_validate_designated_roles BEFORE INSERT OR UPDATE ON org_units
 FOR EACH ROW EXECUTE FUNCTION validate_org_unit_designated_roles();

CREATE FUNCTION protect_designated_role_unit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM org_units WHERE
  (managing_role_id=NEW.id OR file_administrator_role_id=NEW.id)
  AND (id IS DISTINCT FROM NEW.org_unit_id OR NEW.is_system
    OR NEW.account_type_restriction='service')) THEN
  RAISE EXCEPTION 'role is designated by an organizational unit; clear or replace its designation first' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER roles_protect_designation BEFORE UPDATE ON roles
 FOR EACH ROW EXECUTE FUNCTION protect_designated_role_unit();

DO $$
DECLARE acl_table text; constraint_row record;
BEGIN
 FOREACH acl_table IN ARRAY ARRAY['aggregation_acl_grants','aggregation_child_aggregation_acl_defaults','aggregation_child_record_acl_defaults','record_acl_grants'] LOOP
  FOR constraint_row IN SELECT conname FROM pg_constraint WHERE conrelid=acl_table::regclass
    AND contype='c' AND pg_get_constraintdef(oid) LIKE '%principal_type%' LOOP
   EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I',acl_table,constraint_row.conname);
  END LOOP;
  EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I CHECK (
    (principal_type=''role'' AND role_id IS NOT NULL) OR
    (principal_type IN (''everyone'',''org_unit_members'',''owning_and_higher_level_unit_managers'',''effective_file_administrator'') AND role_id IS NULL))',acl_table,acl_table||'_principal_valid');
  EXECUTE format('CREATE UNIQUE INDEX %I ON %I(%I,principal_type,permission_id)
   WHERE principal_type IN (''owning_and_higher_level_unit_managers'',''effective_file_administrator'')',
   acl_table||'_oversight_unique',acl_table,CASE WHEN acl_table='record_acl_grants' THEN 'record_id' ELSE 'aggregation_id' END);
 END LOOP;
END $$;

-- Resolves roles from current data, with no authorization cache.
CREATE FUNCTION contextual_acl_roles(p_owner bigint,p_principal text)
 RETURNS TABLE(role_id bigint,org_unit_id bigint) LANGUAGE sql STABLE AS $$
 WITH RECURSIVE chain AS (
  SELECT id,parent_org_unit_id,managing_role_id,file_administrator_role_id,0 AS depth
   FROM org_units WHERE id=p_owner
  UNION ALL
  SELECT parent.id,parent.parent_org_unit_id,parent.managing_role_id,parent.file_administrator_role_id,child.depth+1
   FROM org_units parent JOIN chain child ON parent.id=child.parent_org_unit_id
 ), selected AS (
  SELECT managing_role_id AS role_id,id AS org_unit_id FROM chain
   WHERE p_principal='owning_and_higher_level_unit_managers'
  UNION ALL
  SELECT file_administrator_role_id,id FROM
   (SELECT * FROM chain WHERE file_administrator_role_id IS NOT NULL ORDER BY depth LIMIT 1) nearest
   WHERE p_principal='effective_file_administrator'
 )
 SELECT selected.role_id,selected.org_unit_id FROM selected JOIN roles role ON role.id=selected.role_id
 WHERE role.org_unit_id=selected.org_unit_id AND NOT role.is_system
   AND role.account_type_restriction IS DISTINCT FROM 'service' AND role_effectively_active(role.id)
$$;
CREATE FUNCTION user_matches_contextual_acl(p_user bigint,p_owner bigint,p_principal text)
 RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM contextual_acl_roles(p_owner,p_principal) match
  JOIN user_role_assignments assignment ON assignment.role_id=match.role_id
  WHERE assignment.user_id=p_user AND assignment.valid_from<=CURRENT_TIMESTAMP
   AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP))
$$;

CREATE OR REPLACE FUNCTION user_has_aggregation_permission(
  p_user_id bigint, p_aggregation_id bigint, p_permission text
) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE
  cursor_row aggregations%ROWTYPE;
  parent_row aggregations%ROWTYPE;
  source_id bigint;
  source_kind text;
  target_owner_id bigint;
BEGIN
  SELECT * INTO cursor_row FROM aggregations WHERE id=p_aggregation_id;
  IF NOT FOUND THEN RETURN false; END IF;
  target_owner_id := cursor_row.owning_org_unit_id;
  IF NOT cursor_row.inherit_acl_from_parent OR cursor_row.parent_aggregation_id IS NULL THEN
    source_id := cursor_row.id; source_kind := 'resource';
  ELSE
    LOOP
      SELECT * INTO parent_row FROM aggregations WHERE id=cursor_row.parent_aggregation_id;
      IF NOT FOUND THEN RETURN false; END IF;
      IF parent_row.default_child_aggregation_acl_mode='custom' THEN
        source_id := parent_row.id; source_kind := 'child_default'; EXIT;
      ELSIF NOT parent_row.inherit_acl_from_parent OR parent_row.parent_aggregation_id IS NULL THEN
        source_id := parent_row.id; source_kind := 'resource'; EXIT;
      END IF;
      cursor_row := parent_row;
    END LOOP;
  END IF;

  IF source_kind='resource' THEN
    RETURN EXISTS (
      SELECT 1 FROM aggregation_acl_grants grant_row
      JOIN permissions permission ON permission.id=grant_row.permission_id
      WHERE grant_row.aggregation_id=source_id AND permission.code=p_permission
        AND (grant_row.principal_type='everyone'
          OR (grant_row.principal_type='role' AND EXISTS (
            SELECT 1 FROM user_role_assignments assignment
            WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
              AND assignment.valid_from<=CURRENT_TIMESTAMP
              AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
              AND role_effectively_active(assignment.role_id)))
          OR user_matches_contextual_acl(p_user_id,target_owner_id,grant_row.principal_type)
          OR (grant_row.principal_type='org_unit_members' AND EXISTS (
            SELECT 1 FROM user_role_assignments assignment
            JOIN roles role ON role.id=assignment.role_id
            WHERE assignment.user_id=p_user_id AND role.org_unit_id=target_owner_id
              AND assignment.valid_from<=CURRENT_TIMESTAMP
              AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
              AND role_effectively_active(role.id))))
    );
  END IF;
  RETURN EXISTS (
    SELECT 1 FROM aggregation_child_aggregation_acl_defaults grant_row
    JOIN permissions permission ON permission.id=grant_row.permission_id
    WHERE grant_row.aggregation_id=source_id AND permission.code=p_permission
      AND (grant_row.principal_type='everyone'
        OR (grant_row.principal_type='role' AND EXISTS (
          SELECT 1 FROM user_role_assignments assignment
          WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
            AND assignment.valid_from<=CURRENT_TIMESTAMP
            AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
            AND role_effectively_active(assignment.role_id)))
        OR user_matches_contextual_acl(p_user_id,target_owner_id,grant_row.principal_type)
          OR (grant_row.principal_type='org_unit_members' AND EXISTS (
          SELECT 1 FROM user_role_assignments assignment
          JOIN roles role ON role.id=assignment.role_id
          WHERE assignment.user_id=p_user_id AND role.org_unit_id=target_owner_id
            AND assignment.valid_from<=CURRENT_TIMESTAMP
            AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
            AND role_effectively_active(role.id))))
  );
END $$;

CREATE OR REPLACE FUNCTION user_has_record_permission(
  p_user_id bigint, p_record_id bigint, p_permission text
) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS (
    SELECT 1 FROM records resource
    JOIN permissions permission ON permission.code=p_permission
    JOIN record_acl_grants grant_row ON NOT resource.inherit_acl_from_parent
      AND grant_row.record_id=resource.id AND grant_row.permission_id=permission.id
    WHERE resource.id=p_record_id AND
      (grant_row.principal_type='everyone'
       OR (grant_row.principal_type='role' AND EXISTS (
         SELECT 1 FROM user_role_assignments assignment
         WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(assignment.role_id)))
       OR user_matches_contextual_acl(p_user_id,resource.owning_org_unit_id,grant_row.principal_type)
          OR (grant_row.principal_type='org_unit_members' AND EXISTS (
         SELECT 1 FROM user_role_assignments assignment
         JOIN roles role ON role.id=assignment.role_id
         WHERE assignment.user_id=p_user_id AND role.org_unit_id=resource.owning_org_unit_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(role.id))))
  ) OR EXISTS (
    SELECT 1 FROM records resource
    JOIN permissions permission ON permission.code=p_permission
    JOIN aggregation_child_record_acl_defaults grant_row
      ON resource.inherit_acl_from_parent AND grant_row.aggregation_id=resource.aggregation_id
      AND grant_row.permission_id=permission.id
    WHERE resource.id=p_record_id AND
      (grant_row.principal_type='everyone'
       OR (grant_row.principal_type='role' AND EXISTS (
         SELECT 1 FROM user_role_assignments assignment
         WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(assignment.role_id)))
       OR user_matches_contextual_acl(p_user_id,resource.owning_org_unit_id,grant_row.principal_type)
          OR (grant_row.principal_type='org_unit_members' AND EXISTS (
         SELECT 1 FROM user_role_assignments assignment
         JOIN roles role ON role.id=assignment.role_id
         WHERE assignment.user_id=p_user_id AND role.org_unit_id=resource.owning_org_unit_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(role.id))))
  )
$$;

CREATE OR REPLACE FUNCTION user_has_destination_record_permission(
  p_user_id bigint,p_aggregation_id bigint,p_permission text
) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS(
    SELECT 1 FROM aggregations resource
    JOIN aggregation_child_record_acl_defaults grant_row
      ON grant_row.aggregation_id=resource.id
    JOIN permissions permission ON permission.id=grant_row.permission_id
    WHERE resource.id=p_aggregation_id AND permission.code=p_permission
      AND (grant_row.principal_type='everyone'
       OR (grant_row.principal_type='role' AND EXISTS(
         SELECT 1 FROM user_role_assignments assignment
         WHERE assignment.user_id=p_user_id AND assignment.role_id=grant_row.role_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(assignment.role_id)))
       OR user_matches_contextual_acl(p_user_id,resource.owning_org_unit_id,grant_row.principal_type)
          OR (grant_row.principal_type='org_unit_members' AND EXISTS(
         SELECT 1 FROM user_role_assignments assignment
         JOIN roles role ON role.id=assignment.role_id
         WHERE assignment.user_id=p_user_id AND role.org_unit_id=resource.owning_org_unit_id
           AND assignment.valid_from<=CURRENT_TIMESTAMP
           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(role.id))))
  )
$$;




CREATE OR REPLACE FUNCTION initialize_resource_acls() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE creator_role_id bigint := NULLIF(current_setting('app.creator_acl_role_id',true),'')::bigint;
  acl_scope record;
BEGIN
  IF creator_role_id IS NULL THEN RETURN NEW; END IF;
  IF TG_TABLE_NAME='aggregations' THEN
    INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,role_id,permission_id)
      SELECT NEW.id,'role',creator_role_id,id FROM permissions WHERE code=ANY(ARRAY['aggregation.view','aggregation.modify_metadata','aggregation.add_child','aggregation.add_record','aggregation.close','aggregation.history.view']);
    INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,permission_id)
      SELECT NEW.id,'org_unit_members',id FROM permissions WHERE code=ANY(ARRAY['aggregation.view','aggregation.history.view']);
    INSERT INTO aggregation_child_aggregation_acl_defaults(aggregation_id,principal_type,role_id,permission_id)
      SELECT NEW.id,'role',creator_role_id,id FROM permissions WHERE code=ANY(ARRAY['aggregation.view','aggregation.modify_metadata','aggregation.add_child','aggregation.add_record','aggregation.close','aggregation.history.view']);
    INSERT INTO aggregation_child_aggregation_acl_defaults(aggregation_id,principal_type,permission_id)
      SELECT NEW.id,'org_unit_members',id FROM permissions WHERE code=ANY(ARRAY['aggregation.view','aggregation.history.view']);
    INSERT INTO aggregation_child_record_acl_defaults(aggregation_id,principal_type,role_id,permission_id)
      SELECT NEW.id,'role',creator_role_id,id FROM permissions WHERE code=ANY(ARRAY['record.view','record.history.view','record.component.list','record.component.view','record.component.download','record.component.share','record.component.print']);
    INSERT INTO aggregation_child_record_acl_defaults(aggregation_id,principal_type,permission_id)
      SELECT NEW.id,'org_unit_members',id FROM permissions WHERE code=ANY(ARRAY['record.view','record.component.list','record.component.view','record.component.download']);
  ELSE
    INSERT INTO record_acl_grants(record_id,principal_type,role_id,permission_id)
      SELECT NEW.id,'role',creator_role_id,id FROM permissions WHERE code=ANY(ARRAY['record.view','record.history.view','record.component.list','record.component.view','record.component.download','record.component.share','record.component.print']);
    INSERT INTO record_acl_grants(record_id,principal_type,permission_id)
      SELECT NEW.id,'org_unit_members',id FROM permissions WHERE code=ANY(ARRAY['record.view','record.component.list','record.component.view','record.component.download']);
  END IF;
  FOR acl_scope IN SELECT * FROM (VALUES
    ('aggregation_acl_grants','aggregation_id','aggregation'),
    ('aggregation_child_aggregation_acl_defaults','aggregation_id','aggregation'),
    ('aggregation_child_record_acl_defaults','aggregation_id','record'),
    ('record_acl_grants','record_id','record')) AS scopes(table_name,owner_column,resource_type)
  LOOP
    IF (TG_TABLE_NAME='aggregations' AND acl_scope.table_name<>'record_acl_grants')
      OR (TG_TABLE_NAME='records' AND acl_scope.table_name='record_acl_grants') THEN
      EXECUTE format('INSERT INTO %I(%I,principal_type,permission_id)
        SELECT $1,principal,id FROM permissions CROSS JOIN
        (VALUES (''owning_and_higher_level_unit_managers''),(''effective_file_administrator'')) AS principals(principal)
        WHERE code=ANY(CASE WHEN principal=''owning_and_higher_level_unit_managers'' THEN $2 ELSE $3 END)',acl_scope.table_name,acl_scope.owner_column)
      USING NEW.id,
        CASE WHEN acl_scope.resource_type='aggregation' THEN ARRAY['aggregation.view','aggregation.history.view']
          ELSE ARRAY['record.view','record.component.list','record.component.view','record.component.download'] END,
        CASE WHEN acl_scope.resource_type='aggregation' THEN ARRAY['aggregation.view','aggregation.modify_metadata','aggregation.add_child','aggregation.add_record','aggregation.close','aggregation.acl.manage','aggregation.history.view']
          ELSE ARRAY['record.view','record.acl.manage','record.history.view','record.component.list','record.component.view','record.component.download','record.component.share','record.component.print'] END;
    END IF;
  END LOOP;
  RETURN NEW;
END $$;
INSERT INTO schema_migrations(version) VALUES ('048_hierarchical_oversight_acls');
COMMIT;
