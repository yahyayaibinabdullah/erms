BEGIN;
SELECT set_config('app.event_source','migration',true);

CREATE FUNCTION public.user_has_type_grant(p_user bigint, p_kind text, p_type bigint, p_use boolean)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT p_type IS NULL OR EXISTS (
        SELECT FROM resource_type_role_grants g
        JOIN user_role_assignments a ON a.role_id = g.role_id
        WHERE (g.kind, g.type_id) = (p_kind, p_type)
          AND (NOT p_use OR g.can_use) AND a.user_id = p_user
          AND a.valid_from <= CURRENT_TIMESTAMP
          AND (a.valid_until IS NULL OR a.valid_until > CURRENT_TIMESTAMP)
          AND role_effectively_active(a.role_id)
    )
$$;

CREATE FUNCTION public.user_passes_type_gate(p_user bigint, p_kind text, p_type bigint, p_level bigint, p_use boolean)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT p_type IS NULL OR user_has_type_grant(p_user, p_kind, p_type, p_use)
                          OR user_has_governance_clearance(p_user, p_level)
$$;

CREATE FUNCTION public.type_operation_requires_use(p_permission text) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
RETURN p_permission NOT IN ('aggregation.view','record.view','record.component.list','record.component.view',
                            'record.component.download','record.component.print','record.history.view','aggregation.history.view');

CREATE OR REPLACE FUNCTION disposition_private.original_record_access(p_user_id bigint, p_record_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT user_has_global_privilege(p_user_id,'record.view')
     AND EXISTS (SELECT 1 FROM user_role_assignments a
       JOIN roles r ON r.id=a.role_id JOIN security_levels rl ON rl.id=r.security_level_id
       JOIN records resource ON resource.id=p_record_id
       JOIN security_levels required ON required.id=resource.security_level_id
       WHERE a.user_id=p_user_id AND a.valid_from<=CURRENT_TIMESTAMP
         AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
         AND role_effectively_active(r.id) AND rl.level_number>=required.level_number
         AND (resource.type_id IS NULL OR user_passes_type_gate(p_user_id,'record',resource.type_id,resource.security_level_id,false)))
     AND (
       user_has_record_permission(p_user_id,p_record_id,'record.view')
       OR EXISTS (SELECT 1 FROM user_role_assignments a
         JOIN roles r ON r.id=a.role_id JOIN security_levels rl ON rl.id=r.security_level_id
         JOIN records resource ON resource.id=p_record_id
         JOIN security_levels required ON required.id=resource.security_level_id
         WHERE a.user_id=p_user_id AND r.is_information_governance
           AND a.valid_from<=CURRENT_TIMESTAMP
           AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(r.id) AND rl.level_number>=required.level_number)
     )
$$;

CREATE OR REPLACE FUNCTION public.user_can_record_operation(p_user_id bigint, p_record_id bigint, p_privilege text, p_permission text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT user_can_view_record(p_user_id,p_record_id)
     AND user_has_global_privilege(p_user_id,p_privilege)
     AND (NOT type_operation_requires_use(p_permission) OR EXISTS (
         SELECT FROM records resource WHERE resource.id=p_record_id
           AND user_passes_type_gate(p_user_id,'record',resource.type_id,resource.security_level_id,true)))
     AND (user_has_record_permission(p_user_id,p_record_id,p_permission)
          OR EXISTS(SELECT 1 FROM records resource
                    WHERE resource.id=p_record_id
                      AND user_has_governance_clearance(p_user_id,resource.security_level_id)))
$$;

CREATE OR REPLACE FUNCTION disposition_private.original_aggregation_access(p_user_id bigint, p_aggregation_id bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT user_has_global_privilege(p_user_id,'aggregation.view')
     AND EXISTS (SELECT 1 FROM user_role_assignments a
       JOIN roles r ON r.id=a.role_id JOIN security_levels rl ON rl.id=r.security_level_id
       JOIN aggregations resource ON resource.id=p_aggregation_id
       JOIN security_levels required ON required.id=resource.security_level_id
       WHERE a.user_id=p_user_id AND a.valid_from<=CURRENT_TIMESTAMP
         AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
         AND role_effectively_active(r.id) AND rl.level_number>=required.level_number
         AND (resource.type_id IS NULL OR user_passes_type_gate(p_user_id,'aggregation',resource.type_id,resource.security_level_id,false)))
     AND (
       user_has_aggregation_permission(p_user_id,p_aggregation_id,'aggregation.view')
       OR EXISTS (SELECT 1 FROM user_role_assignments a
         JOIN roles r ON r.id=a.role_id JOIN security_levels rl ON rl.id=r.security_level_id
         JOIN aggregations resource ON resource.id=p_aggregation_id
         JOIN security_levels required ON required.id=resource.security_level_id
         WHERE a.user_id=p_user_id AND r.is_information_governance
           AND a.valid_from<=CURRENT_TIMESTAMP
           AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
           AND role_effectively_active(r.id) AND rl.level_number>=required.level_number)
     )
$$;

CREATE OR REPLACE FUNCTION public.user_can_aggregation_operation(p_user_id bigint, p_aggregation_id bigint, p_privilege text, p_permission text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT user_can_view_aggregation(p_user_id,p_aggregation_id)
     AND user_has_global_privilege(p_user_id,p_privilege)
     AND (NOT type_operation_requires_use(p_permission) OR EXISTS (
         SELECT FROM aggregations resource WHERE resource.id=p_aggregation_id
           AND user_passes_type_gate(p_user_id,'aggregation',resource.type_id,resource.security_level_id,true)))
     AND (user_has_aggregation_permission(p_user_id,p_aggregation_id,p_permission)
          OR EXISTS(SELECT 1 FROM aggregations resource
                    WHERE resource.id=p_aggregation_id
                      AND user_has_governance_clearance(p_user_id,resource.security_level_id)))
$$;

CREATE OR REPLACE FUNCTION public.current_user_can_record_component_operation(p_record_id bigint, p_privilege text, p_permission text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  SELECT current_user_can_record_operation(p_record_id,p_privilege,p_permission)
$$;

INSERT INTO public.privileges(code,name,description,category)
VALUES ('aggregations.administer','Administer aggregation types','Maintain aggregation types, fields, choices and role grants.','administration'),
       ('records.administer','Administer record types','Maintain record types, fields, choices and role grants.','administration')
ON CONFLICT DO NOTHING;
INSERT INTO public.profile_privileges(profile_id,privilege_id)
SELECT profile.id, privilege.id FROM public.profiles profile CROSS JOIN public.privileges privilege
WHERE profile.code IN ('ALL_PRIVS','INFO_GOV_MGR','INFO_GOV_OFFICER')
  AND privilege.code IN ('aggregations.administer','records.administer')
ON CONFLICT (profile_id,privilege_id) DO NOTHING;

CREATE FUNCTION public.resource_field_json(literal public.resource_field_literal) RETURNS jsonb
LANGUAGE sql STABLE STRICT
RETURN coalesce(to_jsonb(literal.text_value), to_jsonb(literal.integer_value),
                to_jsonb(literal.decimal_value::text), to_jsonb(literal.boolean_value),
                to_jsonb(literal.date_value), to_jsonb(literal.datetime_value), to_jsonb(literal.choice_id));

CREATE TRIGGER aggregation_types_history AFTER INSERT OR UPDATE OR DELETE ON public.aggregation_types
    FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('aggregation_type');
CREATE TRIGGER record_types_history AFTER INSERT OR UPDATE OR DELETE ON public.record_types
    FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('record_type');
CREATE TRIGGER resource_type_field_history AFTER INSERT OR UPDATE OR DELETE ON public.resource_type_fields
    FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('resource_type_field');
CREATE TRIGGER resource_field_choice_history AFTER INSERT OR UPDATE OR DELETE ON public.resource_field_choices
    FOR EACH ROW EXECUTE FUNCTION public.record_entity_history('resource_field_choice');

CREATE FUNCTION public.audit_type_role_grant() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior jsonb; following jsonb;
BEGIN
    IF TG_OP <> 'INSERT' THEN prior := to_jsonb(OLD); END IF;
    IF TG_OP <> 'DELETE' THEN following := to_jsonb(NEW); END IF;
    PERFORM append_domain_event((coalesce(following,prior)->>'kind') || '_type',
            ((coalesce(following,prior))->>'type_id')::bigint, 'TYPE_ROLE_GRANT_CHANGED',
            jsonb_build_object('before',prior,'after',following));
    RETURN NULL;
END $$;
CREATE TRIGGER type_role_grant_history AFTER INSERT OR UPDATE OR DELETE ON public.resource_type_role_grants
    FOR EACH ROW EXECUTE FUNCTION public.audit_type_role_grant();

CREATE OR REPLACE FUNCTION disposition_private.retain_unit(p_job bigint, p_root bigint, p_run bigint, p_event bigint, p_at timestamp with time zone, p_executor bigint, p_name text) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE physical_id bigint;rule jsonb;due timestamptz;acceleration jsonb;item record;
BEGIN
 IF NOT disposition_private.destruction_active('finalize',p_root) THEN RAISE EXCEPTION 'disposition_destruction_command_required'; END IF;
 PERFORM disposition_private.capture_retiring_identities(p_root);
 SELECT id INTO physical_id FROM disposition_physical_confirmations WHERE job_id=p_job;
 SELECT e.rule_snapshot,e.calculated_disposition_at INTO rule,due FROM disposition_private.eligibility(p_root) e;
 SELECT coalesce(jsonb_agg(disposition_private.retained_json(metadata) ORDER BY id),'[]') INTO acceleration FROM event_history WHERE entity_type='aggregation' AND entity_id=p_root AND operation IN ('DISPOSITION_ACCELERATED','DISPOSITION_RECALCULATED');
 INSERT INTO disposition_retained_records(resource_kind,resource_id,root_id,job_id,run_id,parent_resource_id,classification_id,owning_org_unit_id,date_closed,calculated_disposition_at,rule_snapshot,acceleration,security_level_id,access_snapshot,medium,destruction_number,executor_user_id,executor_name,destroyed_at,physical_confirmation_id,digital_confirmation_event_id,final_event_id,method)
 SELECT 'aggregation',a.id,p_root,p_job,p_run,a.parent_aggregation_id,root.classification_id,a.owning_org_unit_id,root.date_closed,due,rule,acceleration,a.security_level_id,
 jsonb_build_object('inherit_acl_from_parent',a.inherit_acl_from_parent,'resource_acl_version',a.resource_acl_version,'grants',(SELECT coalesce(jsonb_agg(to_jsonb(g)-'id'),'[]') FROM aggregation_acl_grants g WHERE g.aggregation_id=a.id)),a.medium,j.destruction_number,p_executor,p_name,p_at,physical_id,CASE WHEN p_run IS NOT NULL THEN p_event END,p_event,CASE WHEN p_run IS NULL THEN 'confirmed_physical' ELSE 'postgresql_transactional_erasure' END
 FROM aggregations a JOIN aggregations root ON root.id=p_root JOIN disposition_jobs j ON j.id=p_job WHERE a.id IN (SELECT disposition_private.unit_ids(p_root));
 INSERT INTO disposition_retained_records(resource_kind,resource_id,root_id,job_id,run_id,parent_resource_id,classification_id,owning_org_unit_id,date_closed,calculated_disposition_at,rule_snapshot,acceleration,security_level_id,access_snapshot,medium,destruction_number,executor_user_id,executor_name,destroyed_at,physical_confirmation_id,digital_confirmation_event_id,final_event_id,method)
 SELECT 'record',r.id,p_root,p_job,p_run,r.aggregation_id,root.classification_id,r.owning_org_unit_id,root.date_closed,due,rule,acceleration,r.security_level_id,
 jsonb_build_object('inherit_acl_from_parent',r.inherit_acl_from_parent,'resource_acl_version',r.resource_acl_version,'grants',(SELECT coalesce(jsonb_agg(to_jsonb(g)-'id'),'[]') FROM record_acl_grants g WHERE g.record_id=r.id)),r.medium,j.destruction_number,p_executor,p_name,p_at,physical_id,CASE WHEN p_run IS NOT NULL THEN p_event END,p_event,CASE WHEN p_run IS NULL THEN 'confirmed_physical' ELSE 'postgresql_transactional_erasure' END
 FROM records r JOIN aggregations root ON root.id=p_root JOIN disposition_jobs j ON j.id=p_job WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root));
 -- The retained resource keeps its type for access decisions. Its descriptive
 -- metadata is erased in the same transaction as the other business values.
 DELETE FROM resource_type_values WHERE kind='aggregation' AND resource_id IN (SELECT disposition_private.unit_ids(p_root));
 DELETE FROM resource_type_values WHERE kind='record' AND resource_id IN
   (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
 DELETE FROM user_favourite_aggregations WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root));
 DELETE FROM user_favourite_records WHERE record_id IN (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
 UPDATE aggregations SET disposition_status=10,description=NULL,date_opened=NULL,date_created=p_at,date_of_next_review=NULL,assigned_location=NULL,current_location=NULL,
 final_disposition_at=p_at,final_disposition_by_user_id=p_executor,disposition_job_id=p_job,destruction_number=(SELECT destruction_number FROM disposition_jobs WHERE id=p_job),final_disposition_event_id=p_event
 WHERE id IN (SELECT disposition_private.unit_ids(p_root));
 UPDATE records SET disposition_status=10,description=NULL,date_originated=NULL,date_created=p_at,date_of_next_review=NULL,
 final_disposition_at=p_at,final_disposition_by_user_id=p_executor,disposition_job_id=p_job,destruction_number=(SELECT destruction_number FROM disposition_jobs WHERE id=p_job),final_disposition_event_id=p_event
 WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root));
END $$;

CREATE FUNCTION public.guard_typed_resource_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE actor bigint := current_user_id();
BEGIN
    -- Owner/seed/migration SQL is outside delegated user authority. Requests
    -- and user-attributed workflow commands supply their actor transactionally.
    IF actor IS NOT NULL THEN
        PERFORM pg_advisory_xact_lock_shared(1163021645,1);
        IF TG_OP <> 'INSERT' AND NOT user_passes_type_gate(actor,TG_ARGV[0],OLD.type_id,OLD.security_level_id,true) THEN
            RAISE EXCEPTION USING ERRCODE='42501', MESSAGE='insufficient_type_access';
        END IF;
        IF TG_OP <> 'DELETE' AND NOT user_passes_type_gate(actor,TG_ARGV[0],NEW.type_id,NEW.security_level_id,true) THEN
            RAISE EXCEPTION USING ERRCODE='42501', MESSAGE='insufficient_type_access';
        END IF;
    END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER aggregation_type_use_insert AFTER INSERT ON public.aggregations
    FOR EACH ROW WHEN (NEW.type_id IS NOT NULL) EXECUTE FUNCTION public.guard_typed_resource_mutation('aggregation');
CREATE TRIGGER aggregation_type_use_update AFTER UPDATE ON public.aggregations
    FOR EACH ROW WHEN (OLD.type_id IS NOT NULL OR NEW.type_id IS NOT NULL) EXECUTE FUNCTION public.guard_typed_resource_mutation('aggregation');
CREATE TRIGGER aggregation_type_use_delete AFTER DELETE ON public.aggregations
    FOR EACH ROW WHEN (OLD.type_id IS NOT NULL) EXECUTE FUNCTION public.guard_typed_resource_mutation('aggregation');
CREATE TRIGGER record_type_use_insert AFTER INSERT ON public.records
    FOR EACH ROW WHEN (NEW.type_id IS NOT NULL) EXECUTE FUNCTION public.guard_typed_resource_mutation('record');
CREATE TRIGGER record_type_use_update AFTER UPDATE ON public.records
    FOR EACH ROW WHEN (OLD.type_id IS NOT NULL OR NEW.type_id IS NOT NULL) EXECUTE FUNCTION public.guard_typed_resource_mutation('record');
CREATE TRIGGER record_type_use_delete AFTER DELETE ON public.records
    FOR EACH ROW WHEN (OLD.type_id IS NOT NULL) EXECUTE FUNCTION public.guard_typed_resource_mutation('record');

-- History viewers may know the identity of a type whose instance values
-- they may not read. Keep the immutable snapshot separate from this projection.
CREATE FUNCTION public.resource_type_history_access() RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
BEGIN
    RETURN (WITH effective AS MATERIALIZED (
        SELECT r.id,level.level_number,r.is_information_governance FROM user_role_assignments a
          JOIN roles r ON r.id=a.role_id JOIN security_levels level ON level.id=r.security_level_id
         WHERE a.user_id=current_user_id() AND a.valid_from<=CURRENT_TIMESTAMP
           AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(r.id)
    ), clearance AS (
        SELECT max(level_number) AS ordinary,
               max(level_number) FILTER (WHERE is_information_governance) AS governance FROM effective
    )
    SELECT jsonb_build_object(
        'types', (SELECT jsonb_object_agg(g.kind || '/' || g.type_id,true) FROM resource_type_role_grants g
                   WHERE g.role_id IN (SELECT id FROM effective)),
        'levels', (SELECT jsonb_object_agg(id,true) FROM security_levels WHERE level_number<=clearance.ordinary),
        'governance', (SELECT jsonb_object_agg(id,true) FROM security_levels WHERE level_number<=clearance.governance))
      FROM clearance);
END $$;

CREATE FUNCTION public.resource_type_history_side(p_kind text, snapshot jsonb, access jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    IF p_kind NOT IN ('aggregation','record') OR snapshot->>'type_id' IS NULL THEN RETURN snapshot; END IF;
    IF (access->'governance') ? (snapshot->>'security_level_id')
       OR ((access->'levels') ? (snapshot->>'security_level_id')
           AND (access->'types') ? (p_kind || '/' || (snapshot->>'type_id'))) THEN RETURN snapshot; END IF;
    RETURN jsonb_build_object('type_id',snapshot->'type_id','type_name',snapshot->'type_name','values_withheld',true);
END $$;

CREATE FUNCTION public.resource_type_history_metadata(p_kind text, operation text, payload jsonb, access jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    IF operation <> 'TYPE_METADATA_CHANGED' OR p_kind NOT IN ('aggregation','record') THEN RETURN payload; END IF;
    RETURN payload || jsonb_build_object('before',resource_type_history_side(p_kind,payload->'before',access),
                                         'after',resource_type_history_side(p_kind,payload->'after',access));
END $$;

CREATE FUNCTION public.stamp_event_type_name(p_kind text,snapshot jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE label text;
BEGIN
    IF snapshot->>'type_id' IS NULL THEN RETURN snapshot; END IF;
    SELECT name INTO label FROM resource_types WHERE kind=p_kind AND id=(snapshot->>'type_id')::bigint;
    RETURN snapshot || jsonb_build_object('type_name',label);
END $$;

CREATE FUNCTION public.stamp_resource_type_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.operation='TYPE_METADATA_CHANGED' THEN
        NEW.metadata := NEW.metadata || jsonb_build_object(
              'before',stamp_event_type_name(NEW.entity_type,NEW.metadata->'before'),
              'after',stamp_event_type_name(NEW.entity_type,NEW.metadata->'after'));
    ELSE
        NEW.before_state := stamp_event_type_name(NEW.entity_type,NEW.before_state);
        NEW.after_state := stamp_event_type_name(NEW.entity_type,NEW.after_state);
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER stamp_resource_type_history BEFORE INSERT ON public.event_history
    FOR EACH ROW WHEN (NEW.entity_type IN ('record','aggregation') AND
        (NEW.operation='TYPE_METADATA_CHANGED' OR NEW.before_state->>'type_id' IS NOT NULL OR NEW.after_state->>'type_id' IS NOT NULL))
    EXECUTE FUNCTION public.stamp_resource_type_history();
CREATE OR REPLACE FUNCTION public.current_user_can_view_event_resource(p_entity_type text, p_entity_id bigint, p_before jsonb, p_after jsonb) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $_$
DECLARE record_id bigint;
DECLARE historical_level_id bigint;
DECLARE disposition_job bigint;
DECLARE proposal_data jsonb;
BEGIN
 IF p_entity_type IN ('aggregation','record') AND EXISTS(SELECT 1 FROM disposition_retained_records WHERE resource_kind=p_entity_type AND resource_id=p_entity_id) THEN RETURN disposition_private.retained_access(p_entity_type,p_entity_id,true) OR disposition_private.retained_access(p_entity_type,p_entity_id,false); END IF;

 IF p_entity_type='aggregation' AND p_after ? 'recovery_job_id' THEN
  IF NOT disposition_private.recovery_unit_visible(p_entity_id) THEN RETURN false; END IF;
  IF NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.id=(p_after->>'certificate_document_id')::bigint AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id)) THEN RETURN false; END IF;
 END IF;
 IF p_entity_type='disposition_job' AND COALESCE(p_after,p_before) ? 'certificate_document_id' AND NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.id=(COALESCE(p_after,p_before)->>'certificate_document_id')::bigint AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id)) THEN RETURN false; END IF;
  IF p_entity_type='disposition_job' AND COALESCE(p_after,p_before) ? 'request_document_id' THEN
    IF EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.id IN (
      (COALESCE(p_after,p_before)->>'request_document_id')::bigint,
      (COALESCE(p_after,p_before)->>'approval_letter_document_id')::bigint,
      (COALESCE(p_after,p_before)->>'rejection_letter_document_id')::bigint)
      AND (NOT current_user_can_view_record(d.record_id) OR NOT current_user_can_list_record_components(d.record_id))) THEN RETURN false; END IF;
  END IF;

  IF p_entity_type='disposition_review_proposal' THEN
   SELECT job_id INTO disposition_job FROM disposition_review_proposals WHERE id=p_entity_id;
   RETURN disposition_job IS NOT NULL AND disposition_private.proposal_visible(p_before) AND disposition_private.proposal_visible(p_after)
    AND current_user_can_view_event_resource('disposition_job',disposition_job,NULL,NULL);
  ELSIF p_entity_type='disposition_review_note' THEN
   SELECT job_id INTO disposition_job FROM disposition_review_notes WHERE id=p_entity_id;
   RETURN disposition_job IS NOT NULL AND current_user_can_view_event_resource('disposition_job',disposition_job,NULL,NULL);
  END IF;
  FOR proposal_data IN SELECT value FROM jsonb_array_elements(COALESCE(p_before->'proposal_snapshot','[]')) UNION ALL SELECT value FROM jsonb_array_elements(COALESCE(p_after->'proposal_snapshot','[]')) LOOP
   IF NOT disposition_private.proposal_visible(proposal_data) THEN RETURN false; END IF;
  END LOOP;
  IF p_entity_type IN ('disposition_job','disposition_job_membership','disposition_task','disposition_review_round','disposition_review_decision','disposition_job_document') THEN
    CASE p_entity_type
    WHEN 'disposition_job' THEN disposition_job:=p_entity_id;
    WHEN 'disposition_job_membership' THEN SELECT job_id INTO disposition_job FROM disposition_job_memberships WHERE id=p_entity_id;
    WHEN 'disposition_task' THEN SELECT job_id INTO disposition_job FROM disposition_tasks WHERE id=p_entity_id;
    WHEN 'disposition_review_round' THEN SELECT job_id INTO disposition_job FROM disposition_review_rounds WHERE id=p_entity_id;
    WHEN 'disposition_review_decision' THEN SELECT job_id INTO disposition_job FROM disposition_review_decisions WHERE id=p_entity_id;
    WHEN 'disposition_job_document' THEN
      SELECT job_id,d.record_id INTO disposition_job,record_id FROM disposition_job_documents d WHERE id=p_entity_id;
      IF record_id IS NOT NULL AND NOT current_user_can_view_record(record_id) THEN RETURN false; END IF;
      IF EXISTS(SELECT 1 FROM disposition_job_documents d JOIN disposition_job_documents previous ON previous.id=d.supersedes_document_id
        WHERE d.id=p_entity_id AND NOT current_user_can_view_record(previous.record_id)) THEN RETURN false; END IF;
    END CASE;
    IF disposition_job IS NULL OR NOT EXISTS(SELECT 1 FROM disposition_jobs WHERE id=disposition_job) THEN RETURN false; END IF;
    -- Historical snapshots may identify former members and their descendants.
    -- Apply existing whole-event redaction if any protected resource is hidden.
    RETURN NOT EXISTS(SELECT 1 FROM disposition_job_memberships m
      CROSS JOIN LATERAL disposition_private.unit_ids(m.root_aggregation_id) unit(id)
      WHERE m.job_id=disposition_job AND (NOT disposition_private.history_resource_access(current_user_id(),'aggregation',unit.id)
        OR EXISTS(SELECT 1 FROM records r WHERE r.aggregation_id=unit.id AND NOT disposition_private.history_resource_access(current_user_id(),'record',r.id))));
  END IF;
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
      IF p_before->>'type_id' IS NOT NULL OR p_after->>'type_id' IS NOT NULL
         OR EXISTS (SELECT FROM aggregations WHERE id=p_entity_id AND type_id IS NOT NULL) THEN
          RETURN current_user_can_aggregation_operation(p_entity_id,'audit.view','aggregation.history.view');
      END IF;
      RETURN current_user_can_view_aggregation(p_entity_id);
    END IF;
    historical_level_id := COALESCE(
      CASE WHEN (p_before->>'security_level_id') ~ '^[0-9]+$' THEN (p_before->>'security_level_id')::bigint END,
      CASE WHEN (p_after->>'security_level_id') ~ '^[0-9]+$' THEN (p_after->>'security_level_id')::bigint END
    );
  ELSIF p_entity_type='record' THEN
    IF EXISTS (SELECT 1 FROM records WHERE id=p_entity_id) THEN
      IF p_before->>'type_id' IS NOT NULL OR p_after->>'type_id' IS NOT NULL
         OR EXISTS (SELECT FROM records WHERE id=p_entity_id AND type_id IS NOT NULL) THEN
          RETURN current_user_can_record_operation(p_entity_id,'audit.view','record.history.view');
      END IF;
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
    RETURN record_id IS NOT NULL AND (current_user_can_view_record(record_id) OR disposition_private.retained_access('record',record_id,true) OR disposition_private.retained_access('record',record_id,false));
  ELSE
    RETURN true;
  END IF;
  IF historical_level_id IS NOT NULL THEN
    -- A deleted resource has no live row. Its final assignment still governs
    -- access to its history, alongside the original historical-clearance rule.
    IF EXISTS (SELECT 1 FROM event_history e WHERE e.entity_type=p_entity_type AND e.entity_id=p_entity_id
               AND e.operation='DELETE' AND e.before_state->>'type_id' IS NOT NULL
               AND NOT user_passes_type_gate(current_user_id(),p_entity_type,(e.before_state->>'type_id')::bigint,
                                              (e.before_state->>'security_level_id')::bigint,false)) THEN RETURN false; END IF;
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
END $_$;

CREATE OR REPLACE VIEW public.authorized_event_history AS
 WITH history_access AS MATERIALIZED (SELECT public.resource_type_history_access() AS rights)
 SELECT event.id,
    event.occurred_at,
    event.transaction_id,
    event.entity_type,
    event.entity_id,
    event.operation,
        CASE
            WHEN visible.allowed THEN event.actor_user_id
            ELSE NULL::bigint
        END AS actor_user_id,
        CASE
            WHEN visible.allowed THEN event.actor_name
            ELSE NULL::text
        END AS actor_name,
        CASE
            WHEN visible.allowed THEN event.actor_email
            ELSE NULL::text
        END AS actor_email,
    event.actor_type,
    event.source,
    event.request_id,
    event.correlation_id,
        CASE
            WHEN visible.allowed THEN public.resource_type_history_side(event.entity_type,event.before_state,(SELECT rights FROM history_access))
            ELSE NULL::jsonb
        END AS before_state,
        CASE
            WHEN visible.allowed THEN public.resource_type_history_side(event.entity_type,event.after_state,(SELECT rights FROM history_access))
            ELSE NULL::jsonb
        END AS after_state,
        CASE
            WHEN visible.allowed THEN event.changed_fields
            ELSE ARRAY[]::text[]
        END AS changed_fields,
        CASE
            WHEN visible.allowed THEN event.reason
            ELSE NULL::text
        END AS reason,
        CASE
            WHEN visible.allowed THEN public.resource_type_history_metadata(event.entity_type,event.operation,event.metadata,(SELECT rights FROM history_access))
            ELSE jsonb_build_object('redacted', true, 'reason', 'resource_access_denied')
        END AS metadata
   FROM (public.event_history event
     CROSS JOIN LATERAL ( SELECT public.current_user_can_view_event_resource(event.entity_type, event.entity_id, COALESCE(event.before_state,
                CASE
                    WHEN (event.entity_type ~~ 'disposition_%'::text OR event.operation='TYPE_METADATA_CHANGED') THEN (event.metadata -> 'before'::text)
                    ELSE NULL::jsonb
                END), COALESCE(event.after_state,
                CASE
                    WHEN ((event.entity_type = 'aggregation'::text) AND (event.metadata ? 'recovery_job_id'::text)) THEN event.metadata
                    WHEN (event.entity_type ~~ 'disposition_%'::text OR event.operation='TYPE_METADATA_CHANGED') THEN (event.metadata -> 'after'::text)
                    ELSE NULL::jsonb
                END)) AS allowed OFFSET 0) visible);

INSERT INTO public.schema_migrations(version) VALUES ('120_resource_type_access');
COMMIT;
