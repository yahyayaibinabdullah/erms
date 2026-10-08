BEGIN;
SELECT set_config('app.actor_type','automated_process',true), set_config('app.actor_name','Resource relationship installation',true), set_config('app.event_source','migration',true);
-- Phase 1: named resource relationships; disposition enforcement is deferred.
CREATE TABLE relationship_types (
 id bigserial PRIMARY KEY,
 resource_kind text NOT NULL CHECK(resource_kind IN ('aggregation','record')),
 code text NOT NULL CHECK(code ~ '^[a-z][a-z0-9_]*$'),
 forward_name text NOT NULL CHECK(btrim(forward_name)<>''),
 reverse_name text NOT NULL CHECK(btrim(reverse_name)<>''),
 is_symmetric boolean NOT NULL DEFAULT false,
 is_active boolean NOT NULL DEFAULT true,
 translations jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(translations)='object'),
 version integer NOT NULL DEFAULT 1,
 date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(resource_kind,code),
 CHECK(NOT is_symmetric OR forward_name=reverse_name)
);
CREATE TABLE aggregation_relationships (
 id bigserial PRIMARY KEY,
 relationship_type_id bigint NOT NULL REFERENCES relationship_types(id) ON DELETE RESTRICT,
 source_id bigint NOT NULL REFERENCES aggregations(id) ON DELETE CASCADE,
 target_id bigint NOT NULL REFERENCES aggregations(id) ON DELETE CASCADE,
 date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CHECK(source_id<>target_id),
 UNIQUE(relationship_type_id,source_id,target_id)
);
CREATE INDEX aggregation_relationships_target_idx ON aggregation_relationships(target_id,id);
CREATE INDEX aggregation_relationships_source_idx ON aggregation_relationships(source_id,id);
CREATE TABLE record_relationships (
 id bigserial PRIMARY KEY,
 relationship_type_id bigint NOT NULL REFERENCES relationship_types(id) ON DELETE RESTRICT,
 source_id bigint NOT NULL REFERENCES records(id) ON DELETE CASCADE,
 target_id bigint NOT NULL REFERENCES records(id) ON DELETE CASCADE,
 date_created timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CHECK(source_id<>target_id),
 UNIQUE(relationship_type_id,source_id,target_id)
);
CREATE INDEX record_relationships_target_idx ON record_relationships(target_id,id);
CREATE INDEX record_relationships_source_idx ON record_relationships(source_id,id);
CREATE FUNCTION guard_relationship_type() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT user_has_global_privilege(current_user_id(),'relationships.administer')
    AND COALESCE(current_setting('app.event_source',true),'') NOT IN ('seeding','migration') THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='relationships_administer_required';
 END IF;
 IF TG_OP='UPDATE' AND (NEW.resource_kind,NEW.code,NEW.is_symmetric)
     IS DISTINCT FROM (OLD.resource_kind,OLD.code,OLD.is_symmetric) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='relationship_type_identity_immutable';
 END IF;
 IF TG_OP<>'DELETE' THEN
  IF NOT COALESCE(jsonb_typeof(NEW.translations->'ar')='object',false)
     OR NOT COALESCE(jsonb_typeof(NEW.translations->'ar'->'forward_name')='string',false)
     OR NOT COALESCE(jsonb_typeof(NEW.translations->'ar'->'reverse_name')='string',false)
     OR btrim(NEW.translations->'ar'->>'forward_name')=''
     OR btrim(NEW.translations->'ar'->>'reverse_name')=''
     OR (NEW.is_symmetric AND NEW.translations->'ar'->>'forward_name'
                             IS DISTINCT FROM NEW.translations->'ar'->>'reverse_name') THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='relationship_arabic_labels_required';
  END IF;
 END IF;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER relationship_types_guard BEFORE INSERT OR UPDATE OR DELETE ON relationship_types
FOR EACH ROW EXECUTE FUNCTION guard_relationship_type();
CREATE TRIGGER relationship_types_version BEFORE UPDATE ON relationship_types
FOR EACH ROW EXECUTE FUNCTION bump_entity_version();
CREATE TRIGGER relationship_types_history AFTER INSERT OR UPDATE OR DELETE ON relationship_types
FOR EACH ROW EXECUTE FUNCTION record_entity_history('relationship_type');

CREATE FUNCTION guard_resource_relationship() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE item record; definition relationship_types; kind text;
BEGIN
 kind:=TG_ARGV[0];
 -- A parent resource deletion is authorized by its own existing deletion path.
 -- Permit only genuine FK cascades; explicit unlinking still requires both endpoints.
 IF TG_OP='DELETE' AND pg_trigger_depth()>1 THEN
  IF (kind='aggregation' AND (NOT EXISTS(SELECT 1 FROM aggregations WHERE id=OLD.source_id)
                             OR NOT EXISTS(SELECT 1 FROM aggregations WHERE id=OLD.target_id)))
     OR (kind='record' AND (NOT EXISTS(SELECT 1 FROM records WHERE id=OLD.source_id)
                           OR NOT EXISTS(SELECT 1 FROM records WHERE id=OLD.target_id))) THEN
   RETURN OLD;
  END IF;
 END IF;
 IF TG_OP='UPDATE' THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='relationship_immutable_remove_and_recreate';
 END IF;
 IF NOT user_has_global_privilege(current_user_id(),'relationships.link') THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='relationships_link_required';
 END IF;
 item:=CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
 SELECT * INTO definition FROM relationship_types WHERE id=item.relationship_type_id FOR SHARE;
 IF definition.resource_kind IS DISTINCT FROM kind THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='relationship_type_scope_mismatch';
 END IF;
 IF TG_OP='INSERT' AND NOT definition.is_active THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='relationship_type_inactive';
 END IF;
 IF kind='aggregation' THEN
  PERFORM id FROM aggregations WHERE id IN (item.source_id,item.target_id) ORDER BY id FOR SHARE;
  IF NOT current_user_can_view_aggregation(item.source_id) OR NOT current_user_can_view_aggregation(item.target_id) THEN
   RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='relationship_endpoint_access_required';
  END IF;
 ELSE
  PERFORM id FROM records WHERE id IN (item.source_id,item.target_id) ORDER BY id FOR SHARE;
  IF NOT current_user_can_view_record(item.source_id) OR NOT current_user_can_view_record(item.target_id) THEN
   RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='relationship_endpoint_access_required';
  END IF;
 END IF;
 IF TG_OP='INSERT' AND definition.is_symmetric AND NEW.source_id>NEW.target_id THEN
  NEW.source_id:=item.target_id; NEW.target_id:=item.source_id;
 END IF;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER aggregation_relationships_guard BEFORE INSERT OR UPDATE OR DELETE ON aggregation_relationships
FOR EACH ROW EXECUTE FUNCTION guard_resource_relationship('aggregation');
CREATE TRIGGER aggregation_relationships_history AFTER INSERT OR DELETE ON aggregation_relationships
FOR EACH ROW EXECUTE FUNCTION record_entity_history('aggregation_relationship');
CREATE TRIGGER record_relationships_guard BEFORE INSERT OR UPDATE OR DELETE ON record_relationships
FOR EACH ROW EXECUTE FUNCTION guard_resource_relationship('record');
CREATE TRIGGER record_relationships_history AFTER INSERT OR DELETE ON record_relationships
FOR EACH ROW EXECUTE FUNCTION record_entity_history('record_relationship');
CREATE OR REPLACE FUNCTION current_user_can_view_event_resource(
  p_entity_type text, p_entity_id bigint, p_before jsonb, p_after jsonb
) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE record_id bigint;
DECLARE historical_level_id bigint;
BEGIN
  IF p_entity_type IN ('aggregation_relationship','record_relationship') THEN
    IF p_entity_type='aggregation_relationship' THEN
      RETURN current_user_can_view_aggregation((COALESCE(p_after,p_before)->>'source_id')::bigint)
         AND current_user_can_view_aggregation((COALESCE(p_after,p_before)->>'target_id')::bigint);
    END IF;
    RETURN current_user_can_view_record((COALESCE(p_after,p_before)->>'source_id')::bigint)
       AND current_user_can_view_record((COALESCE(p_after,p_before)->>'target_id')::bigint);
  END IF;
  IF p_entity_type='aggregation' THEN
    IF EXISTS (SELECT 1 FROM aggregations WHERE id=p_entity_id) THEN
      RETURN current_user_can_view_aggregation(p_entity_id);
    END IF;
    historical_level_id := COALESCE(
      CASE WHEN (p_before->>'security_level_id') ~ '^[0-9]+$' THEN (p_before->>'security_level_id')::bigint END,
      CASE WHEN (p_after->>'security_level_id') ~ '^[0-9]+$' THEN (p_after->>'security_level_id')::bigint END
    );
  ELSIF p_entity_type='record' THEN
    IF EXISTS (SELECT 1 FROM records WHERE id=p_entity_id) THEN
      RETURN current_user_can_view_record(p_entity_id);
    END IF;
    historical_level_id := COALESCE(
      CASE WHEN (p_before->>'security_level_id') ~ '^[0-9]+$' THEN (p_before->>'security_level_id')::bigint END,
      CASE WHEN (p_after->>'security_level_id') ~ '^[0-9]+$' THEN (p_after->>'security_level_id')::bigint END
    );
  ELSIF p_entity_type IN ('digital_component','record_component') THEN
    SELECT component.record_id INTO record_id FROM digital_components component WHERE component.id=p_entity_id;
    IF record_id IS NULL THEN
      record_id := COALESCE(
        CASE WHEN (p_after->>'record_id') ~ '^[0-9]+$' THEN (p_after->>'record_id')::bigint END,
        CASE WHEN (p_before->>'record_id') ~ '^[0-9]+$' THEN (p_before->>'record_id')::bigint END
      );
    END IF;
    RETURN record_id IS NOT NULL AND current_user_can_view_record(record_id);
  ELSE
    RETURN true;
  END IF;
  IF historical_level_id IS NOT NULL THEN
    RETURN user_has_global_privilege(current_user_id(),'audit.view') AND EXISTS (
      SELECT 1 FROM user_role_assignments assignment
      JOIN roles role ON role.id=assignment.role_id
      JOIN security_levels role_level ON role_level.id=role.security_level_id
      JOIN security_levels required ON required.id=historical_level_id
      WHERE assignment.user_id=current_user_id()
        AND assignment.valid_from<=CURRENT_TIMESTAMP
        AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
        AND role_effectively_active(role.id)
        AND role_level.level_number>=required.level_number
    );
  END IF;
  RETURN false;
END $$;
INSERT INTO privileges(code,name,description,category) VALUES
 ('relationships.link','Link Records and Aggregations','Create and remove named links between resources you can view.','record'),
 ('relationships.administer','Administer Relationship Types','Maintain aggregation and record relationship catalogues.','administration');
INSERT INTO profile_privileges(profile_id,privilege_id)
SELECT p.id,v.id FROM profiles p CROSS JOIN privileges v
WHERE p.code IN ('ALL_PRIVS','INFO_GOV_OFFICER','INFO_GOV_MGR')
AND v.code IN ('relationships.link','relationships.administer') ON CONFLICT DO NOTHING;
INSERT INTO schema_migrations(version) VALUES ('049_resource_relationships') ON CONFLICT DO NOTHING;
COMMIT;
