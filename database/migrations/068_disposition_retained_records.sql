-- Phase21 part3: minimal, read-only outcomes and ordinary-access exclusion.
-- Execution remains closed pending the owning completion/release verification.
CREATE TABLE disposition_retained_records (
 resource_kind text NOT NULL CHECK(resource_kind IN ('aggregation','record')),resource_id bigint NOT NULL,
 root_id bigint NOT NULL REFERENCES aggregations(id),job_id bigint NOT NULL REFERENCES disposition_jobs(id),
 run_id bigint REFERENCES disposition_destruction_runs(id),parent_resource_id bigint,
 classification_id bigint NOT NULL REFERENCES classifications(id),owning_org_unit_id bigint NOT NULL REFERENCES org_units(id),
 date_closed timestamptz,calculated_disposition_at timestamptz,rule_snapshot jsonb NOT NULL,
 acceleration jsonb NOT NULL DEFAULT '[]',security_level_id bigint NOT NULL REFERENCES security_levels(id),
 access_snapshot jsonb NOT NULL,medium text NOT NULL CHECK(medium IN ('physical','digital','mixed')),
 destruction_number text NOT NULL,executor_user_id bigint NOT NULL REFERENCES users(id),executor_name text NOT NULL,
 destroyed_at timestamptz NOT NULL,physical_confirmation_id bigint REFERENCES disposition_physical_confirmations(id),
 digital_confirmation_event_id bigint REFERENCES event_history(id),final_event_id bigint NOT NULL REFERENCES event_history(id),
 classification_snapshot jsonb NOT NULL DEFAULT '{}',owner_snapshot jsonb NOT NULL DEFAULT '{}',
 method text NOT NULL CHECK(method IN ('confirmed_physical','postgresql_transactional_erasure')),
 PRIMARY KEY(resource_kind,resource_id)
);
CREATE INDEX disposition_retained_job_root ON disposition_retained_records(job_id,root_id,resource_kind,resource_id);
CREATE FUNCTION disposition_private.retained_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' OR NOT disposition_private.destruction_active('finalize',NEW.root_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_retained_record_immutable'; END IF;
 SELECT jsonb_build_object('id',id,'code',code,'title',title,'classification_scheme_id',classification_scheme_id) INTO NEW.classification_snapshot FROM classifications WHERE id=NEW.classification_id;
 SELECT jsonb_build_object('id',id,'code',code,'name',name) INTO NEW.owner_snapshot FROM org_units WHERE id=NEW.owning_org_unit_id;
 RETURN NEW;
END $$;
CREATE TRIGGER disposition_retained_guard BEFORE INSERT OR UPDATE OR DELETE ON disposition_retained_records FOR EACH ROW EXECUTE FUNCTION disposition_private.retained_guard();

ALTER TABLE aggregations ALTER COLUMN aggregation_number DROP NOT NULL,ALTER COLUMN title DROP NOT NULL,ALTER COLUMN date_opened DROP NOT NULL;
ALTER TABLE records ALTER COLUMN record_number DROP NOT NULL,ALTER COLUMN title DROP NOT NULL,ALTER COLUMN date_originated DROP NOT NULL;
ALTER TABLE aggregations ADD CONSTRAINT live_aggregation_identity_required CHECK(disposition_status=10 OR (aggregation_number IS NOT NULL AND title IS NOT NULL AND date_opened IS NOT NULL));
ALTER TABLE records ADD CONSTRAINT live_record_identity_required CHECK(disposition_status=10 OR (record_number IS NOT NULL AND title IS NOT NULL AND date_originated IS NOT NULL));

-- An allow-list, never a list of known content keys: unknown nested fields do
-- not become permanent proof accidentally. Required disposition rationale and
-- attributed review notes remain authorized workflow evidence (extension18.3).
CREATE TABLE disposition_private.destruction_identities (
 transaction_id bigint NOT NULL,backend_id integer NOT NULL,root_id bigint NOT NULL,identities jsonb NOT NULL,
 PRIMARY KEY(transaction_id,root_id)
);
CREATE FUNCTION disposition_private.capture_retiring_identities(p_root bigint) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 INSERT INTO disposition_private.destruction_identities SELECT txid_current(),pg_backend_pid(),p_root,jsonb_build_object(
 'aggregation_ids',(SELECT coalesce(jsonb_agg(id),'[]') FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root))),
 'record_ids',(SELECT coalesce(jsonb_agg(id),'[]') FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root))),
 'component_ids',(SELECT coalesce(jsonb_agg(DISTINCT identity),'[]') FROM (SELECT source_component_id AS identity FROM disposition_destruction_manifest_items WHERE root_id=p_root AND source_component_id IS NOT NULL UNION SELECT e.entity_id FROM event_history e WHERE e.entity_type IN ('digital_component','record_component') AND ((e.before_state->>'record_id') IN (SELECT id::text FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root))) OR (e.after_state->>'record_id') IN (SELECT id::text FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)))) AND NOT EXISTS(SELECT 1 FROM digital_components d JOIN records r ON r.id=d.record_id WHERE d.id=e.entity_id AND r.aggregation_id NOT IN (SELECT disposition_private.unit_ids(p_root)))) identities),
 'aggregation_numbers',(SELECT coalesce(jsonb_agg(DISTINCT number),'[]') FROM (SELECT aggregation_number AS number FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root)) UNION ALL SELECT before_state->>'aggregation_number' FROM event_history WHERE entity_type='aggregation' AND entity_id IN (SELECT disposition_private.unit_ids(p_root)) UNION ALL SELECT after_state->>'aggregation_number' FROM event_history WHERE entity_type='aggregation' AND entity_id IN (SELECT disposition_private.unit_ids(p_root))) names WHERE number IS NOT NULL),
 'record_numbers',(SELECT coalesce(jsonb_agg(record_number),'[]') FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root))))
 ON CONFLICT(transaction_id,root_id) DO NOTHING;
END $$;
CREATE FUNCTION disposition_private.retained_json(p_data jsonb) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE result jsonb;item record;value jsonb;
BEGIN
 IF p_data IS NULL THEN RETURN NULL; END IF;
 IF jsonb_typeof(p_data)='array' THEN
  SELECT coalesce(jsonb_agg(disposition_private.retained_json(v)),'[]') INTO result FROM jsonb_array_elements(p_data) v;RETURN result;
 ELSIF jsonb_typeof(p_data)<>'object' THEN RETURN p_data; END IF;
 result:='{}';
 FOR item IN SELECT * FROM jsonb_each(p_data) LOOP
  IF item.key=ANY(ARRAY['id','job_id','job_number','job_type','root_id','root_aggregation_id','governing_root_id','aggregation_id','parent_aggregation_id','record_id','source_id','target_id','relationship_id','relationship_type_id','resource_kind','resource_id','source_root_id','target_root_id','is_internal','is_same_job','medium','disposition_status','old_status','new_status','classification_id','owning_org_unit_id','security_level_id','date_closed','calculated_disposition_at','eligible_status','final_disposition','rule_source','rule_id','defined_by_aggregation_id','defined_by_classification_id','current_period_years','intermediate_period_years','justification','override_justification','accelerated_at','accelerated_by_user_id','acceleration_reason','acceleration','old_evaluation','new_evaluation','rule_snapshot','rule','definition','before','after','acting_role_id','actor_user_id','user_id','executor_user_id','executor_name','confirmed_by_user_id','confirmed_at','completed_at','review_stage','review_round','round_number','decision','decided_at','decision_reason','reason','review_notes','round_id','approval_round_id','physical_confirmation_id','certificate_document_id','request_document_id','approval_letter_document_id','rejection_letter_document_id','document_id','digital_component_id','checksum_algo','checksum_value','checksum','size_in_bytes','component_id','content_set_id','source_component_id','source_content_set_id','count','counts','command_id','operation','run_id','evidence_version','origin','version','source','roots','aggregations','records','components','unit','units','effects','results','post_membership','post_rules','membership_snapshot','proposal_snapshot','proposals','proposed_values','proposal_id','proposal_type','proposal_state','state','executed','execution_result','approval_execution','request_facts','recorded_by_user_id','recorded_at','author_user_id','proposer_user_id','original_proposer_user_id','last_edited_by_user_id','destination_role_id','destination_user_id','assigned_user_id','created_by_user_id','task_id','task_type','workflow_stage','lifecycle_state','review_route','snapshot','fields','groups','template','template_revision_id','template_version','template_checksum','template_reference','approval_round','membership_id','component_order','physical_scope','confirmation_text','confirmation_version','certificate_reference','destruction_number','transfer_number','total_units','affected_count','outcomes','preserved_digital_material','recovery_job_id','bulk','retained_relationships','old_rule','new_rule','error_code','method','event_id','final_disposition_event_id','final_disposition_at','final_disposition_by_user_id','disposition_job_id','captured_at','generated_at','due','access_snapshot','inherit_acl_from_parent','resource_acl_version','child_aggregation_acl_version','child_record_acl_version','default_child_aggregation_acl_mode','default_child_record_acl_mode','principal_type','role_id','permission_id','grants','authorization_checks','retention_rule_override','acceleration_events']) THEN
   result:=result||jsonb_build_object(item.key,disposition_private.retained_json(item.value));
  END IF;
 END LOOP;RETURN result;
END $$;

CREATE FUNCTION disposition_private.original_aggregation_access(p_user_id bigint, p_aggregation_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT user_has_global_privilege(p_user_id,'aggregation.view')
     AND EXISTS (SELECT 1 FROM user_role_assignments a
       JOIN roles r ON r.id=a.role_id JOIN security_levels rl ON rl.id=r.security_level_id
       JOIN aggregations resource ON resource.id=p_aggregation_id
       JOIN security_levels required ON required.id=resource.security_level_id
       WHERE a.user_id=p_user_id AND a.valid_from<=CURRENT_TIMESTAMP
         AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
         AND role_effectively_active(r.id) AND rl.level_number>=required.level_number)
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
CREATE OR REPLACE FUNCTION user_can_view_aggregation(p_user_id bigint,p_aggregation_id bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM aggregations WHERE id=p_aggregation_id AND disposition_status<>10) AND disposition_private.original_aggregation_access(p_user_id,p_aggregation_id)
$$;

CREATE FUNCTION disposition_private.original_record_access(p_user_id bigint, p_record_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT user_has_global_privilege(p_user_id,'record.view')
     AND EXISTS (SELECT 1 FROM user_role_assignments a
       JOIN roles r ON r.id=a.role_id JOIN security_levels rl ON rl.id=r.security_level_id
       JOIN records resource ON resource.id=p_record_id
       JOIN security_levels required ON required.id=resource.security_level_id
       WHERE a.user_id=p_user_id AND a.valid_from<=CURRENT_TIMESTAMP
         AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
         AND role_effectively_active(r.id) AND rl.level_number>=required.level_number)
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
CREATE OR REPLACE FUNCTION user_can_view_record(p_user_id bigint,p_record_id bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM records WHERE id=p_record_id AND disposition_status<>10) AND disposition_private.original_record_access(p_user_id,p_record_id)
$$;

CREATE FUNCTION disposition_private.history_resource_access(p_user bigint,p_kind text,p_id bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT (CASE WHEN EXISTS(SELECT 1 FROM disposition_retained_records WHERE resource_kind=p_kind AND resource_id=p_id) THEN user_has_global_privilege(p_user,'disposition.jobs.manage') OR user_has_global_privilege(p_user,'audit.view') ELSE true END) AND CASE p_kind WHEN 'aggregation' THEN disposition_private.original_aggregation_access(p_user,p_id) ELSE disposition_private.original_record_access(p_user,p_id) END
$$;
CREATE FUNCTION disposition_private.retained_access(p_kind text,p_id bigint,p_audit boolean DEFAULT false) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT CASE WHEN p_audit THEN user_has_global_privilege(current_user_id(),'audit.view') ELSE disposition_private.can_manage() END
 AND disposition_private.history_resource_access(current_user_id(),p_kind,p_id)
 AND EXISTS(SELECT 1 FROM disposition_retained_records WHERE resource_kind=p_kind AND resource_id=p_id)
$$;

CREATE OR REPLACE FUNCTION disposition_private.can_review_content(p_user bigint,p_job bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT NOT EXISTS(SELECT 1 FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.unit_ids(m.root_aggregation_id) unit(id)
 WHERE m.job_id=p_job AND m.membership_state='active' AND
 (NOT disposition_private.history_resource_access(p_user,'aggregation',unit.id) OR EXISTS(SELECT 1 FROM records r WHERE r.aggregation_id=unit.id AND NOT disposition_private.history_resource_access(p_user,'record',r.id))))
$$;

CREATE OR REPLACE FUNCTION disposition_private.require_job_access(p_job bigint) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state IN ('active','completed_history') AND NOT disposition_private.history_resource_access(current_user_id(),'aggregation',root_aggregation_id)) THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
END $$;

CREATE OR REPLACE FUNCTION disposition_private.guard_resource() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous jsonb; following jsonb; fields text[] := ARRAY['disposition_status','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','transfer_number','final_disposition_event_id']; operation text; inherited smallint;
BEGIN
 IF TG_OP='UPDATE' AND NEW.disposition_status=10 AND disposition_private.destruction_active('finalize',disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN OLD.id ELSE (to_jsonb(OLD)->>'aggregation_id')::bigint END)) THEN RETURN NEW; END IF;

 IF TG_OP='UPDATE' AND disposition_private.hook_applying() THEN
  IF NOT EXISTS(SELECT 1 FROM disposition_private.recalculation_context c WHERE c.transaction_id=txid_current() AND c.backend_id=pg_backend_pid() AND c.applying
   AND c.root_id=disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN NEW.id ELSE (to_jsonb(NEW)->>'aggregation_id')::bigint END) AND c.target_status=NEW.disposition_status)
   OR (to_jsonb(NEW)-ARRAY['disposition_status','version']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['disposition_status','version']) THEN RAISE EXCEPTION 'disposition_recalculation_scope_invalid'; END IF;
 END IF;
 IF TG_OP='UPDATE' AND disposition_private.context_operation()='eligibility_evaluate' AND current_setting('app.actor_type',true)='automated_process' THEN
  PERFORM disposition_private.require_command();
  IF disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN NEW.id ELSE (to_jsonb(NEW)->>'aggregation_id')::bigint END)
   IS DISTINCT FROM (SELECT (r.payload->>'root_id')::bigint FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current())
   OR OLD.disposition_status<>1 OR NEW.disposition_status NOT BETWEEN 2 AND 5
   OR (to_jsonb(NEW)-ARRAY['disposition_status','version']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['disposition_status','version']) THEN
   RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_automated_scope_invalid'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN
  IF OLD.disposition_status<>1 OR EXISTS(SELECT 1 FROM disposition_job_memberships WHERE root_aggregation_id=CASE WHEN TG_TABLE_NAME='aggregations' THEN OLD.id ELSE (to_jsonb(OLD)->>'aggregation_id')::bigint END) THEN
   RAISE EXCEPTION 'disposition_history_preserved'; END IF;
  RETURN OLD;
 END IF;
 following:=to_jsonb(NEW);
 IF TG_OP='INSERT' THEN
  IF NEW.disposition_status<>1 THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_protected_operation_required'; END IF;
  SELECT disposition_status INTO inherited FROM aggregations WHERE id=disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN (to_jsonb(NEW)->>'parent_aggregation_id')::bigint ELSE (to_jsonb(NEW)->>'aggregation_id')::bigint END);
  IF inherited BETWEEN 2 AND 5 THEN NEW.disposition_status:=inherited; END IF;
  IF (
   NEW.final_disposition_at IS NOT NULL OR NEW.final_disposition_by_user_id IS NOT NULL OR NEW.disposition_job_id IS NOT NULL
   OR NEW.destruction_number IS NOT NULL OR NEW.transfer_number IS NOT NULL OR NEW.final_disposition_event_id IS NOT NULL) THEN
   RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_protected_operation_required'; END IF;
  RETURN NEW;
 END IF;
 previous:=to_jsonb(OLD);
 IF (SELECT jsonb_object_agg(key,value) FROM jsonb_each(previous) WHERE key=ANY(fields)) IS DISTINCT FROM
    (SELECT jsonb_object_agg(key,value) FROM jsonb_each(following) WHERE key=ANY(fields)) THEN
  PERFORM disposition_private.require_command();
  operation:=disposition_private.context_operation();
  IF OLD.disposition_status IN (10,11,12) OR NOT disposition_private.allowed_transition(OLD.disposition_status,NEW.disposition_status,operation) THEN
   RAISE EXCEPTION 'disposition_invalid_transition'; END IF;
 ELSIF OLD.disposition_status IN (10,11,12) AND following IS DISTINCT FROM previous THEN RAISE EXCEPTION 'disposition_final_resource_immutable';
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION protect_closed_aggregation_hierarchy()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE closure_source_id bigint;
BEGIN
 IF TG_OP='UPDATE' AND NEW.disposition_status=10 AND disposition_private.destruction_active('finalize',disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN OLD.id ELSE (to_jsonb(OLD)->>'aggregation_id')::bigint END)) THEN RETURN NEW; END IF;

 IF TG_OP='UPDATE' AND disposition_private.context_operation() IS NOT NULL
 AND (to_jsonb(NEW)-ARRAY['disposition_status','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','transfer_number','final_disposition_event_id','version','date_updated'])=(to_jsonb(OLD)-ARRAY['disposition_status','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','transfer_number','final_disposition_event_id','version','date_updated']) THEN
  PERFORM disposition_private.require_command(); RETURN NEW;
 END IF;
 IF TG_OP='INSERT' THEN
   IF NEW.parent_aggregation_id IS NOT NULL THEN
     PERFORM assert_aggregation_effectively_open(NEW.parent_aggregation_id);
   END IF;
   RETURN NEW;
 END IF;
 IF TG_OP='DELETE' THEN
   PERFORM assert_aggregation_effectively_open(OLD.id);
   RETURN OLD;
 END IF;
 WITH RECURSIVE ancestors AS (
   SELECT id,parent_aggregation_id,date_closed,0 depth FROM aggregations WHERE id=OLD.id
   UNION ALL
   SELECT parent.id,parent.parent_aggregation_id,parent.date_closed,child.depth+1
   FROM aggregations parent JOIN ancestors child ON parent.id=child.parent_aggregation_id
 )
 SELECT id INTO closure_source_id FROM ancestors
 WHERE date_closed IS NOT NULL ORDER BY depth LIMIT 1;
 IF closure_source_id IS NOT NULL THEN
   IF OLD.parent_aggregation_id IS NULL AND NEW.parent_aggregation_id IS NULL
      AND NEW.classification_id IS DISTINCT FROM OLD.classification_id
      AND (to_jsonb(NEW)-ARRAY['classification_id','version'])=(to_jsonb(OLD)-ARRAY['classification_id','version'])
      AND current_user_can_aggregation_operation(OLD.id,'aggregation.reclassify','aggregation.reclassify') THEN RETURN NEW; END IF;
   IF current_setting('app.vital_status_change_authorized',true)='authorized'
      AND NEW.is_vital IS DISTINCT FROM OLD.is_vital
      AND (to_jsonb(NEW)-'is_vital'-'version')=(to_jsonb(OLD)-'is_vital'-'version') THEN
     RETURN NEW;
   END IF;
   IF current_setting('app.location_change_authorized',true)='authorized'
      AND (NEW.assigned_location IS DISTINCT FROM OLD.assigned_location
           OR NEW.current_location IS DISTINCT FROM OLD.current_location)
      AND (to_jsonb(NEW)-'assigned_location'-'current_location'-'version')
          =(to_jsonb(OLD)-'assigned_location'-'current_location'-'version') THEN
     RETURN NEW;
   END IF;
   IF current_setting('app.review_date_change_authorized',true)='authorized'
      AND NEW.date_of_next_review IS DISTINCT FROM OLD.date_of_next_review
      AND (to_jsonb(NEW)-'date_of_next_review'-'version')=(to_jsonb(OLD)-'date_of_next_review'-'version') THEN
     RETURN NEW;
   END IF;
   IF current_setting('app.security_level_change_authorized',true)='authorized'
      AND NEW.security_level_id IS DISTINCT FROM OLD.security_level_id
      AND (to_jsonb(NEW)-'security_level_id'-'version')=(to_jsonb(OLD)-'security_level_id'-'version') THEN
     RETURN NEW;
   END IF;
   IF closure_source_id=OLD.id AND OLD.date_closed IS NOT NULL
      AND NEW.date_closed IS NULL
      AND (to_jsonb(NEW)-'date_closed'-'version')=(to_jsonb(OLD)-'date_closed'-'version') THEN
     RETURN NEW;
   END IF;
   RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='closed aggregation metadata is immutable';
 END IF;
 RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION protect_record_in_closed_aggregation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND NEW.disposition_status=10 AND disposition_private.destruction_active('finalize',disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN OLD.id ELSE (to_jsonb(OLD)->>'aggregation_id')::bigint END)) THEN RETURN NEW; END IF;

 IF TG_OP='UPDATE' AND disposition_private.context_operation() IS NOT NULL
 AND (to_jsonb(NEW)-ARRAY['disposition_status','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','transfer_number','final_disposition_event_id','version','date_updated'])=(to_jsonb(OLD)-ARRAY['disposition_status','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','transfer_number','final_disposition_event_id','version','date_updated']) THEN
  PERFORM disposition_private.require_command(); RETURN NEW;
 END IF;
 IF TG_OP='INSERT' THEN PERFORM assert_aggregation_effectively_open(NEW.aggregation_id); RETURN NEW; END IF;
 IF TG_OP='DELETE' THEN PERFORM assert_aggregation_effectively_open(OLD.aggregation_id); RETURN OLD; END IF;
 IF current_setting('app.vital_status_change_authorized',true)='authorized' AND NEW.is_vital IS DISTINCT FROM OLD.is_vital AND (to_jsonb(NEW)-'is_vital'-'version')=(to_jsonb(OLD)-'is_vital'-'version') THEN RETURN NEW; END IF;
 IF current_setting('app.review_date_change_authorized',true)='authorized' AND NEW.date_of_next_review IS DISTINCT FROM OLD.date_of_next_review AND (to_jsonb(NEW)-'date_of_next_review'-'version')=(to_jsonb(OLD)-'date_of_next_review'-'version') THEN RETURN NEW; END IF;
 IF current_setting('app.security_level_change_authorized',true)='authorized' AND NEW.security_level_id IS DISTINCT FROM OLD.security_level_id AND (to_jsonb(NEW)-'security_level_id'-'version')=(to_jsonb(OLD)-'security_level_id'-'version') THEN RETURN NEW; END IF;
 PERFORM assert_aggregation_effectively_open(OLD.aggregation_id); RETURN NEW;
END; $$;

CREATE OR REPLACE FUNCTION disposition_private.guard_recovery_resource() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE root bigint;data jsonb;old_data jsonb;target integer;
BEGIN
 IF TG_OP='UPDATE' AND NEW.disposition_status=10 AND disposition_private.destruction_active('finalize',disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN OLD.id ELSE (to_jsonb(OLD)->>'aggregation_id')::bigint END)) THEN RETURN NEW; END IF;

 data:=to_jsonb(NEW);old_data:=to_jsonb(OLD);
 root:=disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN OLD.id ELSE (old_data->>'aggregation_id')::bigint END);
 target:=(data->>'disposition_status')::integer;
 IF OLD.disposition_status=13 AND ((data->'date_closed') IS DISTINCT FROM (old_data->'date_closed') OR (data->'parent_aggregation_id') IS DISTINCT FROM (old_data->'parent_aggregation_id') OR (data->'aggregation_id') IS DISTINCT FROM (old_data->'aggregation_id') OR (data->'medium') IS DISTINCT FROM (old_data->'medium')) THEN RAISE EXCEPTION 'disposition_recovery_command_required'; END IF;
 IF OLD.disposition_status IS DISTINCT FROM target AND (OLD.disposition_status=13 OR target=13 OR (target=10 AND disposition_private.context_operation()='job_terminate')) THEN
  PERFORM disposition_private.require_command();
  IF NOT disposition_private.recovery_active(NULL,root,target) THEN RAISE EXCEPTION 'disposition_recovery_command_required'; END IF;
 END IF;
 IF EXISTS(SELECT 1 FROM disposition_job_memberships m JOIN disposition_jobs j ON j.id=m.job_id WHERE m.root_aggregation_id=root AND m.membership_state='active' AND j.lifecycle_state='active' AND disposition_private.physical_covered(j.id,root)) AND NOT disposition_private.recovery_active(NULL,root,target) AND
 ((OLD.disposition_status IS DISTINCT FROM target) OR (data->'date_closed') IS DISTINCT FROM (old_data->'date_closed') OR (data->'parent_aggregation_id') IS DISTINCT FROM (old_data->'parent_aggregation_id') OR (data->'aggregation_id') IS DISTINCT FROM (old_data->'aggregation_id') OR (data->'classification_id') IS DISTINCT FROM (old_data->'classification_id') OR (data->'medium') IS DISTINCT FROM (old_data->'medium')) THEN RAISE EXCEPTION 'disposition_physical_recovery_required'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION disposition_private.guard_workflow() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE job disposition_jobs%ROWTYPE; prior jsonb; following jsonb; op text; uid bigint:=current_user_id(); expected_status integer;
BEGIN
 IF TG_OP='UPDATE' AND disposition_private.destruction_active('finalize') AND (disposition_private.context_operation() IN ('final_complete','job_terminate') OR current_setting('app.event_source',true)='migration') AND TG_TABLE_NAME IN ('disposition_review_rounds','disposition_review_decisions','disposition_job_documents')
 AND (to_jsonb(NEW)-ARRAY['membership_snapshot','proposal_snapshot','approval_execution','provenance'])=(to_jsonb(OLD)-ARRAY['membership_snapshot','proposal_snapshot','approval_execution','provenance'])
 AND NOT EXISTS(SELECT 1 FROM jsonb_each(to_jsonb(NEW)) x WHERE x.key=ANY(ARRAY['membership_snapshot','proposal_snapshot','approval_execution','provenance']) AND x.value IS DISTINCT FROM disposition_private.retained_history_json(to_jsonb(OLD)->x.key)) THEN RETURN NEW; END IF;

 PERFORM disposition_private.require_command();
 op:=disposition_private.context_operation();
 IF NOT (CASE TG_TABLE_NAME
 WHEN 'disposition_jobs' THEN op IN ('job_create','job_assign','job_owner_change','membership_add','membership_remove','job_terminate','final_complete','review_submit','review_decide','review_save','recalculate','selective_decide')
 WHEN 'disposition_job_memberships' THEN op IN ('membership_add','membership_remove','job_terminate','final_complete','recalculate')
 WHEN 'disposition_tasks' THEN op IN ('job_create','job_assign','task_claim','task_release','task_reassign','task_complete','review_save','review_submit','review_decide','job_terminate','final_complete')
 WHEN 'disposition_review_rounds' THEN op IN ('review_submit','review_decide','membership_add','membership_remove','recalculate')
 WHEN 'disposition_review_decisions' THEN op='review_decide'
 WHEN 'disposition_job_documents' THEN op='document_save'
 ELSE false END) THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'disposition_history_immutable'; END IF;
 following:=to_jsonb(NEW);
 IF TG_OP='UPDATE' THEN
  prior:=to_jsonb(OLD);
  IF TG_TABLE_NAME='disposition_review_decisions'
    OR (TG_TABLE_NAME='disposition_jobs' AND prior->>'lifecycle_state'<>'active')
    OR (TG_TABLE_NAME='disposition_job_memberships' AND prior->>'membership_state'<>'active')
    OR (TG_TABLE_NAME='disposition_tasks' AND prior->>'task_state' IN ('completed','cancelled'))
    OR (TG_TABLE_NAME='disposition_job_documents' AND prior->>'document_state'='available')
    OR (TG_TABLE_NAME='disposition_review_rounds' AND prior->>'invalidated_at' IS NOT NULL) THEN
   RAISE EXCEPTION 'disposition_history_immutable'; END IF;
  IF (prior->>'id') IS DISTINCT FROM (following->>'id') OR
   (prior->>'job_id') IS DISTINCT FROM (following->>'job_id') THEN RAISE EXCEPTION 'disposition_identity_immutable'; END IF;
  IF TG_TABLE_NAME<>'disposition_review_decisions' THEN NEW.version:=OLD.version+1; NEW.date_updated:=CURRENT_TIMESTAMP; END IF;
 ELSE
  IF following ? 'version' AND (following->>'version')::integer<>1 THEN RAISE EXCEPTION 'disposition_initial_version'; END IF;
 END IF;
 IF TG_TABLE_NAME='disposition_jobs' THEN
  IF TG_OP='UPDATE' AND (NEW.destruction_number IS DISTINCT FROM OLD.destruction_number OR NEW.workflow_stage IS DISTINCT FROM OLD.workflow_stage AND NEW.workflow_stage='external_approval_pending') AND NOT disposition_private.external_active(NEW.id) THEN RAISE EXCEPTION 'disposition_external_command_required'; END IF;
  IF TG_OP='UPDATE' AND NOT disposition_private.hook_applying() AND NOT disposition_private.approval_active(NEW.id) THEN PERFORM disposition_private.require_job_access(NEW.id); END IF;
  IF TG_OP='UPDATE' AND ((NEW.workflow_stage IS DISTINCT FROM OLD.workflow_stage AND NEW.workflow_stage NOT IN ('officer_correction','manager_correction')) OR NEW.disposition_status<>OLD.disposition_status) AND op<>'job_terminate' AND NOT disposition_private.approval_active(NEW.id) THEN PERFORM disposition_private.require_progress(NEW.id); END IF;
  IF TG_OP='INSERT' THEN
   IF NEW.job_type='destruction' THEN
    SELECT value#>>'{}' INTO NEW.review_route FROM application_settings WHERE key='DISPOSITION_DESTRUCTION_REVIEW_ROUTE' FOR SHARE;
    IF NEW.review_route IS NULL THEN RAISE EXCEPTION 'disposition_route_setting_required'; END IF;
    NEW.workflow_stage:=CASE WHEN NEW.review_route='records_manager_only' THEN 'manager_preparation' ELSE 'officer_preparation' END;
   ELSE NEW.review_route:=NULL; END IF;
   IF op<>'job_create' OR NEW.lifecycle_state<>'active' OR NEW.created_by_user_id<>uid OR (NEW.job_type='destruction' AND NEW.workflow_stage NOT IN ('officer_preparation','manager_preparation')) THEN RAISE EXCEPTION 'disposition_invalid_job_creation'; END IF;
   IF NEW.job_type='destruction' THEN PERFORM disposition_private.require_preparer(uid,NEW.review_route); ELSE PERFORM disposition_private.require_job_person(uid,NEW.job_type); END IF;
   NEW.date_created:=CURRENT_TIMESTAMP;
  ELSE
   IF NEW.owning_org_unit_id IS DISTINCT FROM OLD.owning_org_unit_id THEN
    IF op<>'job_owner_change' OR EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=NEW.id AND membership_state='active')
     OR NEW.current_review_round>0 OR EXISTS(SELECT 1 FROM disposition_review_rounds WHERE job_id=NEW.id)
     OR EXISTS(SELECT 1 FROM event_history WHERE entity_type='disposition_job' AND entity_id=NEW.id AND operation='REVIEW_SUBMIT') THEN RAISE EXCEPTION 'disposition_owning_unit_change_invalid'; END IF;
   END IF;
   IF NEW.review_route IS DISTINCT FROM OLD.review_route THEN RAISE EXCEPTION 'disposition_route_immutable'; END IF;
   IF NEW.job_number<>OLD.job_number OR NEW.job_type<>OLD.job_type OR NEW.created_by_user_id<>OLD.created_by_user_id OR NEW.date_created<>OLD.date_created THEN RAISE EXCEPTION 'disposition_identity_immutable'; END IF;
   IF NEW.lifecycle_state<>OLD.lifecycle_state AND NOT ((op='job_terminate' AND NEW.lifecycle_state='terminated') OR (op='final_complete' AND NEW.lifecycle_state='completed')) THEN RAISE EXCEPTION 'disposition_invalid_lifecycle_transition'; END IF;
   IF NEW.disposition_status<>OLD.disposition_status AND NOT disposition_private.allowed_transition(OLD.disposition_status,NEW.disposition_status,op) THEN RAISE EXCEPTION 'disposition_invalid_transition'; END IF;
   IF NEW.workflow_stage IS DISTINCT FROM OLD.workflow_stage AND (op NOT IN ('review_submit','review_decide','final_complete') OR NOT disposition_private.allowed_stage(OLD.workflow_stage,NEW.workflow_stage)) THEN RAISE EXCEPTION 'disposition_invalid_stage_transition'; END IF;
  END IF;
  expected_status:=CASE NEW.job_type WHEN 'destruction' THEN 6 WHEN 'permanent_transfer' THEN 7 WHEN 'selective_transfer' THEN 8 ELSE 9 END;
  IF NEW.lifecycle_state='active' AND NEW.disposition_status<>expected_status THEN RAISE EXCEPTION 'disposition_job_type_status_mismatch'; END IF;
  IF NEW.assigned_user_id IS NOT NULL AND NOT disposition_private.hook_applying() AND (TG_OP='INSERT' OR NEW.assigned_user_id IS DISTINCT FROM OLD.assigned_user_id) THEN
   IF NEW.job_type='destruction' THEN PERFORM disposition_private.require_preparer(NEW.assigned_user_id,NEW.review_route); ELSE PERFORM disposition_private.require_job_person(NEW.assigned_user_id,NEW.job_type); END IF;
   IF EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=NEW.id AND membership_state='active' AND NOT user_can_view_aggregation(NEW.assigned_user_id,root_aggregation_id)) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_assignee_access_required'; END IF;
  END IF;
  IF NEW.assigned_user_id IS NOT NULL AND NOT disposition_private.hook_applying() AND (TG_OP='INSERT' OR NEW.assigned_user_id IS DISTINCT FROM OLD.assigned_user_id) AND NOT EXISTS(
   SELECT 1 FROM users u JOIN user_role_assignments a ON a.user_id=u.id JOIN roles r ON r.id=a.role_id
   JOIN profile_privileges pp ON pp.profile_id=r.profile_id JOIN privileges p ON p.id=pp.privilege_id
   WHERE u.id=NEW.assigned_user_id AND u.status='active' AND u.account_type='person' AND r.is_information_governance
    AND role_effectively_active(r.id) AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
    AND p.code='disposition.jobs.manage') THEN RAISE EXCEPTION 'disposition_assignee_not_authorized'; END IF;
  IF TG_OP='UPDATE' AND NEW.assigned_user_id IS DISTINCT FROM OLD.assigned_user_id AND op<>'job_assign' THEN RAISE EXCEPTION 'disposition_assignment_command_required'; END IF;
  NEW.updated_by_user_id:=uid;
  IF NEW.lifecycle_state='completed' THEN
   IF NEW.job_type<>'destruction' THEN RAISE EXCEPTION 'disposition_action_not_implemented'; END IF;
   -- The Phase 21 implementation replaces this fail-closed gate only when its
   -- irreversible action, approvals/evidence and recovery contract is verified.
   RAISE EXCEPTION 'disposition_final_execution_not_implemented';
  END IF;
  IF NEW.lifecycle_state='terminated' THEN
   NEW.terminated_at:=CURRENT_TIMESTAMP; NEW.terminated_by_user_id:=uid;
  END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO job FROM disposition_jobs WHERE id=(following->>'job_id')::bigint FOR UPDATE;
 IF NOT disposition_private.hook_applying() AND NOT disposition_private.approval_active(job.id) AND NOT (op='task_release' AND current_setting('app.actor_type',true)='automated_process') THEN PERFORM disposition_private.require_job_access(job.id); END IF;
 IF NOT disposition_private.approval_active(job.id) AND TG_TABLE_NAME IN ('disposition_tasks','disposition_review_rounds','disposition_review_decisions') AND op IN ('task_complete','review_submit','review_decide','final_complete') AND NOT (op='review_decide' AND COALESCE((SELECT r.payload->>'decision' FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current())='rejected',false)) THEN PERFORM disposition_private.require_progress(job.id); END IF;
 IF job.lifecycle_state<>'active' AND NOT (TG_TABLE_NAME='disposition_job_memberships' AND op IN ('job_terminate','final_complete')) AND NOT (TG_TABLE_NAME='disposition_job_documents' AND op='document_save' AND following->>'document_type'='proposal_execution_report' AND EXISTS(SELECT 1 FROM disposition_review_rounds approved WHERE approved.job_id=job.id AND approved.round_number=(following->>'review_round')::integer AND approved.approval_execution IS NOT NULL)) THEN RAISE EXCEPTION 'disposition_inactive_job'; END IF;
 IF TG_TABLE_NAME='disposition_job_memberships' THEN
  IF (TG_OP='INSERT' AND NEW.removal_required) OR (TG_OP='UPDATE' AND (NEW.removal_required,NEW.removal_required_reason) IS DISTINCT FROM (OLD.removal_required,OLD.removal_required_reason) AND NOT disposition_private.hook_applying(NEW.root_aggregation_id)) THEN RAISE EXCEPTION 'disposition_recalculation_scope_invalid'; END IF;
  IF op IN ('membership_add','membership_remove') THEN PERFORM disposition_private.require_membership_stage(job.id); END IF;
  IF disposition_private.root_id(NEW.root_aggregation_id)<>NEW.root_aggregation_id THEN RAISE EXCEPTION 'disposition_requires_governing_root'; END IF;
  IF TG_OP='INSERT' THEN
   IF op<>'membership_add' OR NEW.membership_state<>'active' OR NEW.added_by_user_id<>uid OR job.assigned_user_id IS NULL THEN RAISE EXCEPTION 'disposition_membership_add_invalid'; END IF;
   IF NOT current_user_can_view_aggregation(NEW.root_aggregation_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
   IF EXISTS(SELECT 1 FROM disposition_job_memberships WHERE root_aggregation_id=NEW.root_aggregation_id AND membership_state='completed_history') THEN RAISE EXCEPTION 'disposition_already_completed'; END IF;
   PERFORM disposition_private.assert_admission(job.id,NEW.root_aggregation_id);
   NEW.added_at:=CURRENT_TIMESTAMP;
  ELSE
   IF NOT disposition_private.hook_applying(NEW.root_aggregation_id) AND NOT current_user_can_view_aggregation(NEW.root_aggregation_id) AND NOT (disposition_private.destruction_active('finalize',NEW.root_aggregation_id) AND disposition_private.history_resource_access(current_user_id(),'aggregation',NEW.root_aggregation_id)) AND NOT (op='job_terminate' AND disposition_private.retained_access('aggregation',NEW.root_aggregation_id,false)) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
   IF NEW.root_aggregation_id<>OLD.root_aggregation_id OR NEW.added_at<>OLD.added_at OR NEW.added_by_user_id<>OLD.added_by_user_id THEN RAISE EXCEPTION 'disposition_identity_immutable'; END IF;
   IF op='recalculate' AND disposition_private.hook_applying(NEW.root_aggregation_id) THEN
    IF (to_jsonb(NEW)-ARRAY['removal_required','removal_required_reason','version','date_updated']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['removal_required','removal_required_reason','version','date_updated']) THEN RAISE EXCEPTION 'disposition_recalculation_scope_invalid'; END IF;
   ELSIF NOT ((op='membership_remove' AND NEW.membership_state='removed') OR (op='job_terminate' AND NEW.membership_state='terminated_history') OR (op='final_complete' AND NEW.membership_state='completed_history')) THEN RAISE EXCEPTION 'disposition_invalid_membership_transition'; END IF;
   IF NEW.membership_state='removed' THEN NEW.removed_at:=CURRENT_TIMESTAMP; NEW.removed_by_user_id:=uid; END IF;
  END IF;
  UPDATE disposition_jobs SET version=version+1,date_updated=CURRENT_TIMESTAMP WHERE id=job.id;
 ELSIF TG_TABLE_NAME='disposition_tasks' THEN
  IF TG_OP='UPDATE' AND op IN ('task_claim','task_release','task_reassign') THEN
   IF (to_jsonb(NEW)-(ARRAY['task_state','claimed_by_user_id','claimed_at','released_by_user_id','released_at','reassigned_by_user_id','reassigned_at','version','date_updated'] || CASE WHEN op='task_reassign' THEN ARRAY['destination_role_id','routing_org_unit_id'] ELSE ARRAY[]::text[] END))
    IS DISTINCT FROM (to_jsonb(OLD)-(ARRAY['task_state','claimed_by_user_id','claimed_at','released_by_user_id','released_at','reassigned_by_user_id','reassigned_at','version','date_updated'] || CASE WHEN op='task_reassign' THEN ARRAY['destination_role_id','routing_org_unit_id'] ELSE ARRAY[]::text[] END)) THEN RAISE EXCEPTION 'disposition_task_command_scope_invalid'; END IF;
  END IF;
  IF op='task_release' AND current_setting('app.actor_type',true)='automated_process' THEN
   IF OLD.task_state<>'claimed' OR OLD.destination_role_id IS NULL OR disposition_private.task_eligible(OLD.claimed_by_user_id,OLD.id,OLD.destination_role_id)
    OR (SELECT r.payload->>'task_id' FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current()) IS DISTINCT FROM OLD.id::text THEN RAISE EXCEPTION 'disposition_task_command_scope_invalid'; END IF;
  END IF;
  IF TG_OP='INSERT' THEN NEW.date_created:=CURRENT_TIMESTAMP; END IF;
  IF NEW.task_state NOT IN ('cancelled','completed') AND NEW.workflow_stage<>job.workflow_stage THEN RAISE EXCEPTION 'disposition_task_stage_mismatch'; END IF;
  IF TG_OP='UPDATE' THEN
   IF NEW.task_type<>OLD.task_type OR NEW.workflow_stage<>OLD.workflow_stage OR NEW.review_round IS DISTINCT FROM OLD.review_round OR NEW.date_created<>OLD.date_created THEN RAISE EXCEPTION 'disposition_identity_immutable'; END IF;
   IF (NEW.destination_user_id,NEW.destination_role_id) IS DISTINCT FROM (OLD.destination_user_id,OLD.destination_role_id) AND op<>'task_reassign' THEN RAISE EXCEPTION 'disposition_reassignment_command_required'; END IF;
   IF op IN ('task_release','task_complete','review_decide') AND NEW.task_state<>'cancelled' AND current_setting('app.actor_type',true)='user'
   AND NOT (op='task_release' AND disposition_private.task_manager(NEW.id,(SELECT acting_role_id FROM disposition_private.command_receipts WHERE command_id=(SELECT command_id FROM disposition_private.command_context WHERE transaction_id=txid_current())))) AND ((OLD.claimed_by_user_id IS NOT NULL AND OLD.claimed_by_user_id<>uid) OR (OLD.destination_user_id IS NOT NULL AND OLD.destination_user_id<>uid) OR (OLD.destination_role_id IS NOT NULL AND OLD.claimed_by_user_id IS DISTINCT FROM uid)) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_claim_required'; END IF;
  END IF;
  IF NEW.task_state='completed' THEN
   PERFORM disposition_private.require_task_actor(NEW.id,(SELECT acting_role_id FROM disposition_private.command_receipts WHERE command_id=(SELECT command_id FROM disposition_private.command_context WHERE transaction_id=txid_current())),true);
   IF NEW.destination_role_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM user_role_assignments a WHERE a.user_id=uid AND a.role_id=NEW.destination_role_id AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(a.role_id)) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
   NEW.completed_at:=CURRENT_TIMESTAMP; NEW.completed_by_user_id:=uid;
  END IF;
  IF op IN ('task_release','task_reassign') THEN
   IF op='task_release' OR NEW.task_state='open' THEN NEW.claimed_by_user_id:=NULL; NEW.claimed_at:=NULL; END IF;
   IF op='task_release' THEN NEW.released_by_user_id:=uid; NEW.released_at:=CASE WHEN uid IS NOT NULL THEN CURRENT_TIMESTAMP END;
   ELSE NEW.reassigned_by_user_id:=uid; NEW.reassigned_at:=CURRENT_TIMESTAMP; END IF;
  END IF;
  IF TG_OP='UPDATE' AND NEW.task_state<>OLD.task_state AND NOT (
   (op='task_claim' AND OLD.task_state='open' AND NEW.task_state='claimed') OR
   (op IN ('task_release','task_reassign') AND OLD.task_state IN ('open','claimed') AND NEW.task_state IN ('open','claimed')) OR
   (op IN ('task_complete','review_submit','review_decide') AND OLD.task_state IN ('open','claimed') AND NEW.task_state='completed') OR
   (op IN ('job_assign','job_terminate','review_submit','review_decide') AND NEW.task_state='cancelled')) THEN RAISE EXCEPTION 'disposition_invalid_task_transition'; END IF;
  IF NEW.task_state='claimed' THEN
   IF NEW.destination_role_id IS NULL THEN RAISE EXCEPTION 'disposition_role_queue_required'; END IF;
   IF NOT disposition_private.task_eligible(NEW.claimed_by_user_id,NEW.id,NEW.destination_role_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
   IF op<>'task_reassign' AND NEW.claimed_by_user_id<>uid THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
   -- Saving work must preserve the original claim, including across transactions.
   IF op IN ('task_claim','task_reassign') THEN NEW.claimed_at:=CURRENT_TIMESTAMP; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='disposition_review_rounds' THEN
  IF TG_OP='UPDATE' AND NEW.approval_execution IS DISTINCT FROM OLD.approval_execution AND (OLD.approval_execution IS NOT NULL OR NOT disposition_private.approval_active(job.id)) THEN RAISE EXCEPTION 'disposition_approval_immutable'; END IF;
  IF TG_OP='INSERT' THEN
   IF NEW.approval_execution IS NOT NULL THEN RAISE EXCEPTION 'disposition_approval_immutable'; END IF;
   NEW.started_at:=CURRENT_TIMESTAMP;
   NEW.submission_reason:=COALESCE(NEW.submission_reason,(SELECT r.reason FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current()));
   NEW.proposal_snapshot:=disposition_private.proposal_snapshot(job.id,NEW.round_number);
  ELSE
   IF OLD.completed_at IS NOT NULL AND NEW.completed_at IS DISTINCT FROM OLD.completed_at THEN RAISE EXCEPTION 'disposition_history_immutable'; END IF;
   IF OLD.completed_at IS NULL AND NEW.completed_at IS NOT NULL THEN NEW.completed_at:=CURRENT_TIMESTAMP; END IF;
   IF OLD.invalidated_at IS NULL AND NEW.invalidated_at IS NOT NULL THEN NEW.invalidated_at:=CURRENT_TIMESTAMP; END IF;
  END IF;
  IF TG_OP='UPDATE' AND (NEW.round_number<>OLD.round_number OR NEW.membership_snapshot<>OLD.membership_snapshot OR NEW.started_at<>OLD.started_at OR NEW.started_by_user_id<>OLD.started_by_user_id OR NEW.submission_reason IS DISTINCT FROM OLD.submission_reason OR NEW.proposal_snapshot IS DISTINCT FROM OLD.proposal_snapshot) THEN RAISE EXCEPTION 'disposition_review_snapshot_immutable'; END IF;
  IF TG_OP='INSERT' AND (NEW.started_by_user_id<>uid OR NEW.membership_snapshot IS DISTINCT FROM disposition_private.membership_snapshot(job.id)) THEN RAISE EXCEPTION 'disposition_review_snapshot_mismatch'; END IF;
  IF TG_OP='INSERT' AND NEW.round_number<>COALESCE((SELECT max(round_number)+1 FROM disposition_review_rounds WHERE job_id=job.id),1) THEN RAISE EXCEPTION 'disposition_round_out_of_order'; END IF;
  IF TG_OP='INSERT' THEN UPDATE disposition_jobs SET current_review_round=NEW.round_number,version=version+1,date_updated=CURRENT_TIMESTAMP WHERE id=job.id; END IF;
 ELSIF TG_TABLE_NAME='disposition_review_decisions' THEN
  NEW.decided_at:=CURRENT_TIMESTAMP;
  NEW.proposal_snapshot:=disposition_private.proposal_snapshot(job.id);
  IF NEW.decision='approved' AND NEW.review_stage IN ('records_manager_review','manager_preparation','manager_correction') AND NOT disposition_private.approval_active(job.id) THEN RAISE EXCEPTION 'disposition_proposal_execution_not_implemented'; END IF;
  IF NEW.decision='approved' AND NEW.review_stage='unit_manager_review' AND EXISTS(SELECT 1 FROM disposition_review_proposals p JOIN disposition_job_memberships m ON m.job_id=p.job_id AND m.root_aggregation_id=p.governing_root_id AND m.membership_state='active' WHERE p.job_id=job.id AND p.review_round=job.current_review_round AND p.proposal_state='active' AND p.proposal_type='remove_from_job') THEN RAISE EXCEPTION 'disposition_marked_removals_require_rejection'; END IF;
  IF TG_OP<>'INSERT' OR NEW.actor_user_id<>uid OR NEW.acting_role_id<>(SELECT r.acting_role_id FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current()) OR NOT EXISTS(SELECT 1 FROM disposition_tasks t WHERE t.id=NEW.task_id AND t.job_id=NEW.job_id AND t.workflow_stage=NEW.review_stage AND (t.claimed_by_user_id=uid OR (t.destination_user_id=uid AND t.task_state='open')) AND (t.destination_role_id IS NULL OR EXISTS(SELECT 1 FROM user_role_assignments a WHERE a.user_id=uid AND a.role_id=t.destination_role_id AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(a.role_id)))) THEN RAISE EXCEPTION 'disposition_decision_context_invalid'; END IF;
  IF NEW.membership_snapshot IS DISTINCT FROM disposition_private.membership_snapshot(job.id) THEN RAISE EXCEPTION 'disposition_review_snapshot_stale'; END IF;
  IF NEW.decision='approved' AND NOT disposition_private.approval_active(job.id) AND NEW.membership_snapshot IS DISTINCT FROM (SELECT membership_snapshot FROM disposition_review_rounds WHERE id=NEW.round_id) THEN RAISE EXCEPTION 'disposition_review_snapshot_mismatch'; END IF;
 ELSIF TG_TABLE_NAME='disposition_job_documents' THEN
  IF NEW.document_type='proposal_execution_report' AND NOT EXISTS(SELECT 1 FROM disposition_review_rounds rr WHERE rr.job_id=NEW.job_id AND rr.round_number=NEW.review_round AND rr.approval_execution IS NOT NULL AND rr.id::text=NEW.provenance->>'approval_round_id' AND NEW.provenance#>'{snapshot,source}'=rr.approval_execution AND NEW.provenance#>>'{snapshot,fields,execution.reference}'=rr.approval_execution->>'command_id') THEN RAISE EXCEPTION 'disposition_execution_report_scope_invalid'; END IF;
  IF TG_OP='INSERT' THEN
   IF NEW.created_by_user_id<>uid THEN RAISE EXCEPTION 'disposition_document_actor_mismatch'; END IF;
   NEW.date_created:=CURRENT_TIMESTAMP;
  END IF;
  IF TG_OP='UPDATE' AND (NEW.document_type<>OLD.document_type OR NEW.review_round IS DISTINCT FROM OLD.review_round OR NEW.created_by_user_id<>OLD.created_by_user_id OR NEW.date_created<>OLD.date_created) THEN RAISE EXCEPTION 'disposition_identity_immutable'; END IF;
  IF NEW.record_id IS NOT NULL AND NOT current_user_can_view_record(NEW.record_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
  IF NEW.digital_component_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM digital_components c WHERE c.id=NEW.digital_component_id AND c.record_id=NEW.record_id AND (NEW.document_state<>'available' OR (c.checksum_algo=NEW.checksum_algo AND c.checksum_value=NEW.checksum))) THEN RAISE EXCEPTION 'disposition_document_component_mismatch'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION disposition_private.relationship_scope(p_root bigint)
RETURNS TABLE(resource_kind text,relationship_id bigint,relationship_type_id bigint,source_id bigint,target_id bigint,
 source_root_id bigint,target_root_id bigint,is_internal boolean,is_same_job boolean,blocks_final boolean)
LANGUAGE sql STABLE AS $$
 WITH unit AS (SELECT disposition_private.unit_ids(p_root) id), links AS (
  SELECT 'aggregation'::text kind,l.id,l.relationship_type_id,l.source_id,l.target_id,
   disposition_private.root_id(l.source_id) source_root,disposition_private.root_id(l.target_id) target_root
  FROM aggregation_relationships l WHERE l.source_id IN (SELECT id FROM unit) OR l.target_id IN (SELECT id FROM unit)
  UNION ALL
  SELECT 'record',l.id,l.relationship_type_id,l.source_id,l.target_id,
   disposition_private.root_id(s.aggregation_id),disposition_private.root_id(t.aggregation_id)
  FROM record_relationships l JOIN records s ON s.id=l.source_id JOIN records t ON t.id=l.target_id
  WHERE s.aggregation_id IN (SELECT id FROM unit) OR t.aggregation_id IN (SELECT id FROM unit)
 ), scoped AS (
  SELECT l.*,l.source_root=l.target_root internal,
   EXISTS(SELECT 1 FROM disposition_job_memberships a JOIN disposition_job_memberships b ON b.job_id=a.job_id
    JOIN disposition_jobs j ON j.id=a.job_id AND j.lifecycle_state='active'
    WHERE a.root_aggregation_id=l.source_root AND b.root_aggregation_id=l.target_root
     AND a.membership_state IN ('active','completed_history') AND b.membership_state IN ('active','completed_history')) same_job FROM links l)
 SELECT kind,id,relationship_type_id,source_id,target_id,source_root,target_root,internal,same_job,NOT(internal OR same_job OR EXISTS(SELECT 1 FROM disposition_job_memberships a JOIN disposition_job_memberships b ON b.job_id=a.job_id JOIN disposition_jobs j ON j.id=a.job_id JOIN aggregations sa ON sa.id=a.root_aggregation_id JOIN aggregations ta ON ta.id=b.root_aggregation_id WHERE j.lifecycle_state='terminated' AND a.root_aggregation_id=source_root AND b.root_aggregation_id=target_root AND a.membership_state IN ('terminated_history','completed_history') AND b.membership_state IN ('terminated_history','completed_history') AND (sa.disposition_status=10 OR ta.disposition_status=10) AND EXISTS(SELECT 1 FROM event_history e WHERE e.entity_type='disposition_job' AND e.entity_id=j.id AND e.operation='DISPOSITION_TERMINATION_OUTCOMES' AND e.metadata->'retained_relationships' @> jsonb_build_array(jsonb_build_array(scoped.kind,scoped.id))))) FROM scoped
$$;

CREATE OR REPLACE FUNCTION disposition_private.assert_unit(p_root bigint) RETURNS void LANGUAGE plpgsql AS $$
DECLARE root aggregations%ROWTYPE; member disposition_job_memberships%ROWTYPE; job disposition_jobs%ROWTYPE;
BEGIN
 SELECT * INTO root FROM aggregations WHERE id=p_root;
 IF NOT FOUND THEN RETURN; END IF;
 IF root.parent_aggregation_id IS NOT NULL THEN RAISE EXCEPTION 'disposition_requires_governing_root'; END IF;
 IF EXISTS (
  SELECT 1 FROM aggregations a WHERE a.id IN (SELECT disposition_private.unit_ids(p_root)) AND
   (a.disposition_status,a.final_disposition_at,a.final_disposition_by_user_id,a.disposition_job_id,a.destruction_number,a.transfer_number,a.final_disposition_event_id)
   IS DISTINCT FROM (root.disposition_status,root.final_disposition_at,root.final_disposition_by_user_id,root.disposition_job_id,root.destruction_number,root.transfer_number,root.final_disposition_event_id)
  UNION ALL SELECT 1 FROM records r WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) AND
   (r.disposition_status,r.final_disposition_at,r.final_disposition_by_user_id,r.disposition_job_id,r.destruction_number,r.transfer_number,r.final_disposition_event_id)
   IS DISTINCT FROM (root.disposition_status,root.final_disposition_at,root.final_disposition_by_user_id,root.disposition_job_id,root.destruction_number,root.transfer_number,root.final_disposition_event_id)
 ) THEN RAISE EXCEPTION 'disposition_unit_inconsistent'; END IF;
 SELECT * INTO member FROM disposition_job_memberships WHERE root_aggregation_id=p_root AND membership_state='active';
 IF FOUND THEN
  SELECT * INTO job FROM disposition_jobs WHERE id=member.job_id;
  IF job.lifecycle_state<>'active' OR job.assigned_user_id IS NULL THEN RAISE EXCEPTION 'disposition_active_membership_invalid'; END IF;
  IF root.disposition_status BETWEEN 6 AND 9 AND (root.disposition_status<>job.disposition_status OR root.disposition_status<>
   CASE job.job_type WHEN 'destruction' THEN 6 WHEN 'permanent_transfer' THEN 7 WHEN 'selective_transfer' THEN 8 ELSE 9 END) THEN RAISE EXCEPTION 'disposition_job_status_mismatch'; END IF;
  -- Reopened/recalculated members remain in history and block job progress
  -- until explicitly removed. They cannot acquire a free-standing pending status.
  IF root.disposition_status NOT BETWEEN 6 AND 9 AND NOT (root.disposition_status=10 AND root.disposition_job_id=member.job_id) AND NOT (member.removal_required AND root.disposition_status BETWEEN 1 AND 5) THEN
   RAISE EXCEPTION 'disposition_active_member_not_pending'; END IF;
 ELSIF root.disposition_status BETWEEN 6 AND 9 THEN RAISE EXCEPTION 'disposition_pending_requires_membership'; END IF;
 IF root.disposition_status=13 AND NOT EXISTS(SELECT 1 FROM disposition_job_memberships m JOIN disposition_jobs j ON j.id=m.job_id WHERE m.root_aggregation_id=p_root AND m.membership_state='terminated_history' AND j.lifecycle_state='terminated' AND disposition_private.physical_covered(j.id,p_root)) THEN RAISE EXCEPTION 'disposition_partial_history_required'; END IF;
 IF root.disposition_status IN (10,11,12) THEN
  SELECT * INTO job FROM disposition_jobs WHERE id=root.disposition_job_id;
  IF root.disposition_status=10 AND job.lifecycle_state IN ('active','terminated') AND EXISTS(SELECT 1 FROM disposition_retained_records p WHERE p.resource_kind='aggregation' AND p.resource_id=p_root AND p.job_id=job.id AND p.final_event_id=root.final_disposition_event_id AND p.executor_user_id=root.final_disposition_by_user_id AND p.destroyed_at=root.final_disposition_at) AND EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=job.id AND m.root_aggregation_id=p_root AND m.membership_state IN ('active','completed_history','terminated_history')) THEN RETURN; END IF;
  IF root.disposition_status=10 AND job.lifecycle_state IN ('active','terminated') AND EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=job.id AND m.root_aggregation_id=p_root AND m.membership_state IN ('active','terminated_history','completed_history')) AND EXISTS(SELECT 1 FROM event_history e WHERE e.id=root.final_disposition_event_id AND e.entity_type='aggregation' AND e.entity_id=p_root AND e.operation='DISPOSITION_UNIT_DESTROYED' AND (e.metadata->>'recovery_job_id')::bigint=job.id AND (e.metadata->>'executor_user_id')::bigint=root.final_disposition_by_user_id AND (e.metadata->>'completed_at')::timestamptz=root.final_disposition_at) AND root.destruction_number=job.destruction_number THEN RETURN; END IF;
  IF NOT FOUND OR job.lifecycle_state<>'completed' OR job.disposition_status<>root.disposition_status
    OR NOT EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=job.id AND root_aggregation_id=p_root AND membership_state='completed_history')
    OR (root.final_disposition_at,root.final_disposition_by_user_id,root.destruction_number,root.transfer_number,root.final_disposition_event_id)
       IS DISTINCT FROM (job.completed_at,job.completed_by_user_id,job.destruction_number,job.transfer_number,job.final_event_id) THEN
   RAISE EXCEPTION 'disposition_terminal_fields_inconsistent'; END IF;
 ELSE
  IF root.final_disposition_at IS NOT NULL OR root.final_disposition_by_user_id IS NOT NULL OR root.disposition_job_id IS NOT NULL
    OR root.destruction_number IS NOT NULL OR root.transfer_number IS NOT NULL OR root.final_disposition_event_id IS NOT NULL THEN
   RAISE EXCEPTION 'disposition_premature_final_fields'; END IF;
 END IF;
END $$;

CREATE OR REPLACE FUNCTION current_user_can_view_event_resource(
  p_entity_type text, p_entity_id bigint, p_before jsonb, p_after jsonb
) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
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
    RETURN record_id IS NOT NULL AND (current_user_can_view_record(record_id) OR disposition_private.retained_access('record',record_id,true) OR disposition_private.retained_access('record',record_id,false));
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

CREATE OR REPLACE VIEW authorized_aggregations_for_search AS
SELECT resource.id,
       -- Search predicates must use the true relationship. The API redacts an
       -- inaccessible parent only after filtering and adds parent_aggregation_state.
       resource.parent_aggregation_id,
       resource.classification_id,resource.aggregation_number,resource.title,resource.description,
       resource.date_created,resource.date_opened,resource.date_closed,resource.security_level_id,
       resource.inherit_acl_from_parent,resource.default_child_aggregation_acl_mode,
       resource.resource_acl_version,resource.child_aggregation_acl_version,resource.child_record_acl_version,
       resource.version,resource.owning_org_unit_id,resource.medium,resource.is_vital,
       resource.date_of_next_review,resource.assigned_location,resource.current_location,
       aggregation_effective_assigned_location(resource.id) AS effective_assigned_location,
       aggregation_effective_current_location(resource.id) AS effective_current_location,
       CASE WHEN current_user_can_view_aggregation(aggregation_effective_assigned_location_source_id(resource.id))
            THEN aggregation_effective_assigned_location_source_id(resource.id) END AS effective_assigned_location_source_aggregation_id,
       CASE WHEN current_user_can_view_aggregation(aggregation_effective_current_location_source_id(resource.id))
            THEN aggregation_effective_current_location_source_id(resource.id) END AS effective_current_location_source_aggregation_id,
       hold_state.effective_hold_count > 0 AS on_effective_hold,
       hold_state.resource_state_changes_blocked,
       hold_state.effective_hold_ids,
       resource.disposition_status,resource.final_disposition_at,resource.final_disposition_by_user_id,
       resource.disposition_job_id,resource.destruction_number,resource.transfer_number,resource.final_disposition_event_id
FROM aggregations resource
CROSS JOIN LATERAL (
    SELECT count(*)::integer effective_hold_count,
           COALESCE(bool_or(effective.preserve_resource_state),false) resource_state_changes_blocked,
           COALESCE(array_agg(effective.hold_id ORDER BY effective.hold_id),'{}'::bigint[]) effective_hold_ids
    FROM effective_holds_for_aggregation(resource.id) effective
) hold_state
WHERE resource.disposition_status<>10;

CREATE OR REPLACE VIEW authorized_records_for_search AS
SELECT resource.id,
       -- Keep the true container for filtering; API serialization performs
       -- output redaction and adds aggregation_state.
       resource.aggregation_id,
       resource.record_number,resource.title,resource.description,resource.date_created,resource.date_originated,
       resource.security_level_id,resource.inherit_acl_from_parent,resource.resource_acl_version,resource.version,
       resource.owning_org_unit_id,resource.medium,resource.is_vital,resource.date_of_next_review,
       aggregation_effective_assigned_location(resource.aggregation_id) AS effective_assigned_location,
       aggregation_effective_current_location(resource.aggregation_id) AS effective_current_location,
       CASE WHEN current_user_can_view_aggregation(aggregation_effective_assigned_location_source_id(resource.aggregation_id))
            THEN aggregation_effective_assigned_location_source_id(resource.aggregation_id) END AS effective_assigned_location_source_aggregation_id,
       CASE WHEN current_user_can_view_aggregation(aggregation_effective_current_location_source_id(resource.aggregation_id))
            THEN aggregation_effective_current_location_source_id(resource.aggregation_id) END AS effective_current_location_source_aggregation_id,
       hold_state.effective_hold_count > 0 AS on_effective_hold,
       hold_state.resource_state_changes_blocked,
       hold_state.effective_hold_ids,
       resource.disposition_status,resource.final_disposition_at,resource.final_disposition_by_user_id,
       resource.disposition_job_id,resource.destruction_number,resource.transfer_number,resource.final_disposition_event_id
FROM records resource
CROSS JOIN LATERAL (
    SELECT count(*)::integer effective_hold_count,
           COALESCE(bool_or(effective.preserve_resource_state),false) resource_state_changes_blocked,
           COALESCE(array_agg(effective.hold_id ORDER BY effective.hold_id),'{}'::bigint[]) effective_hold_ids
    FROM effective_holds_for_record(resource.id) effective
) hold_state
WHERE resource.disposition_status<>10;


CREATE FUNCTION disposition_private.retained_history_json(p_data jsonb,p_root bigint DEFAULT NULL,p_ids jsonb DEFAULT NULL) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE ids jsonb:=p_ids;item record;result jsonb;
BEGIN
 IF p_data IS NULL THEN RETURN NULL; END IF;
 IF p_root IS NULL THEN SELECT root_id INTO p_root FROM disposition_private.destruction_context WHERE transaction_id=txid_current() AND backend_id=pg_backend_pid(); END IF;
 IF ids IS NULL THEN SELECT identities INTO ids FROM disposition_private.destruction_identities WHERE transaction_id=txid_current() AND backend_id=pg_backend_pid() AND root_id=p_root;END IF;
 IF jsonb_typeof(p_data)='array' THEN SELECT coalesce(jsonb_agg(disposition_private.retained_history_json(v,p_root,ids)),'[]') INTO result FROM jsonb_array_elements(p_data) v;RETURN result;
 ELSIF jsonb_typeof(p_data)<>'object' THEN RETURN p_data; END IF;
 IF p_data->>'root_id'=p_root::text OR p_data->>'governing_root_id'=p_root::text OR p_data->>'root_aggregation_id'=p_root::text
 OR (p_data ? 'aggregation_number' AND ids->'aggregation_ids' @> jsonb_build_array(p_data->'id'))
 OR (p_data ? 'record_number' AND ids->'record_ids' @> jsonb_build_array(p_data->'id'))
 OR (p_data ? 'file_name' AND ids->'component_ids' @> jsonb_build_array(p_data->'id'))
 OR (p_data ? 'aggregation.identifier' AND ids->'aggregation_numbers' @> jsonb_build_array(p_data->'aggregation.identifier')) THEN RETURN disposition_private.retained_json(p_data); END IF;
 result:='{}';FOR item IN SELECT * FROM jsonb_each(p_data) LOOP result:=result||jsonb_build_object(item.key,disposition_private.retained_history_json(item.value,p_root,ids));END LOOP;
 RETURN result;
END $$;
CREATE FUNCTION disposition_private.retained_command_payload(p_data jsonb) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT CASE WHEN p_data ? 'snapshot' THEN jsonb_set(p_data,'{snapshot}',disposition_private.retained_history_json(p_data->'snapshot')) ELSE p_data END
$$;
CREATE OR REPLACE FUNCTION disposition_private.guard_artifact() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target record; previous disposition_job_documents%ROWTYPE; role_id bigint;
BEGIN
 IF TG_OP='UPDATE' AND disposition_private.destruction_active('finalize') AND NEW.provenance=disposition_private.retained_history_json(OLD.provenance) AND (to_jsonb(NEW)-'provenance')=(to_jsonb(OLD)-'provenance') THEN RETURN NEW; END IF;

 PERFORM disposition_private.require_command();
 SELECT r.acting_role_id INTO role_id FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 IF NEW.acting_role_id IS DISTINCT FROM role_id THEN RAISE EXCEPTION 'disposition_document_actor_mismatch'; END IF;
 IF NEW.origin IS DISTINCT FROM (CASE WHEN NEW.document_type IN ('external_rejection_letter','external_approval_letter','physical_destruction_certificate') THEN 'uploaded' ELSE 'generated' END) THEN RAISE EXCEPTION 'disposition_document_origin_invalid'; END IF;
 IF NEW.supersedes_document_id IS NOT NULL THEN
  SELECT * INTO previous FROM disposition_job_documents WHERE id=NEW.supersedes_document_id FOR UPDATE;
  IF previous.id IS NULL OR previous.origin<>'uploaded' OR NEW.origin<>'uploaded'
   OR previous.job_id<>NEW.job_id OR previous.document_type<>NEW.document_type
   OR previous.document_state<>'available' OR NEW.evidence_version<>previous.evidence_version+1
   OR NEW.review_round IS DISTINCT FROM previous.review_round
   OR EXISTS(SELECT 1 FROM disposition_job_documents WHERE supersedes_document_id=previous.id)
  THEN RAISE EXCEPTION 'disposition_evidence_version_invalid'; END IF;
  IF NOT disposition_private.can_correct_evidence(NEW.job_id,role_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_evidence_correction_forbidden'; END IF;
 ELSIF NEW.evidence_version<>1 THEN RAISE EXCEPTION 'disposition_evidence_version_invalid'; END IF;
 IF NEW.document_state='available' THEN
  SELECT * INTO target FROM disposition_private.artifact_destination(NEW.document_type);
  IF (NEW.classification_scheme_id,NEW.classification_id,NEW.aggregation_id) IS DISTINCT FROM (target.scheme_id,target.classification_id,target.aggregation_id)
  OR NOT EXISTS(SELECT 1 FROM records r WHERE r.id=NEW.record_id AND r.aggregation_id=target.aggregation_id)
  OR EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=NEW.job_id AND m.membership_state IN ('active','completed_history') AND m.root_aggregation_id=target.aggregation_id)
  THEN RAISE EXCEPTION 'disposition_document_destination_invalid'; END IF;
  IF NOT EXISTS(SELECT 1 FROM digital_components c JOIN digital_component_content_sets s ON s.id=c.active_content_set_id AND s.digital_component_id=c.id
   WHERE c.id=NEW.digital_component_id AND c.record_id=NEW.record_id AND c.content_status='available' AND s.status='active'
   AND c.checksum_algo=NEW.checksum_algo AND c.checksum_value=NEW.checksum AND s.checksum_value=NEW.checksum)
  THEN RAISE EXCEPTION 'disposition_document_content_unavailable'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION disposition_private.command_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND disposition_private.destruction_active('finalize') AND OLD.completed_at IS NOT NULL AND NEW.payload=disposition_private.retained_command_payload(OLD.payload) AND NEW.result=disposition_private.retained_history_json(OLD.result) AND (to_jsonb(NEW)-ARRAY['payload','result'])=(to_jsonb(OLD)-ARRAY['payload','result']) THEN RETURN NEW; END IF;

 IF TG_OP='DELETE' OR OLD.completed_at IS NOT NULL OR (to_jsonb(NEW)-ARRAY['result','completed_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['result','completed_at']) THEN RAISE EXCEPTION 'disposition_command_history_immutable'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION disposition_private.guard_proposal_effect() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p disposition_review_proposals%ROWTYPE;
BEGIN
 IF TG_OP='UPDATE' AND disposition_private.destruction_active('finalize',OLD.governing_root_id) AND NEW.details=disposition_private.retained_json(OLD.details) AND (to_jsonb(NEW)-'details')=(to_jsonb(OLD)-'details') THEN RETURN NEW; END IF;

 IF TG_OP<>'INSERT' OR NOT disposition_private.approval_active(NULL,NEW.governing_root_id) THEN RAISE EXCEPTION 'disposition_effect_immutable'; END IF;
 SELECT * INTO p FROM disposition_review_proposals WHERE id=NEW.proposal_id;
 IF NOT FOUND OR NOT disposition_private.approval_active(p.job_id) THEN RAISE EXCEPTION 'disposition_effect_scope_invalid'; END IF;
 NEW.actor_user_id:=current_user_id();NEW.acting_role_id:=(SELECT acting_role_id FROM disposition_private.approval_context WHERE transaction_id=txid_current());NEW.occurred_at:=CURRENT_TIMESTAMP;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION disposition_private.audit_workflow() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE before_state jsonb; after_state jsonb; command disposition_private.command_receipts%ROWTYPE;
BEGIN
 IF TG_OP='UPDATE' AND disposition_private.destruction_active('finalize') THEN RETURN NEW; END IF;

 before_state:=CASE WHEN TG_OP='UPDATE' THEN to_jsonb(OLD) END;
 after_state:=to_jsonb(NEW);
 SELECT r.* INTO command FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 PERFORM append_domain_event(CASE TG_TABLE_NAME WHEN 'disposition_jobs' THEN 'disposition_job' WHEN 'disposition_job_memberships' THEN 'disposition_job_membership' WHEN 'disposition_tasks' THEN 'disposition_task' WHEN 'disposition_review_rounds' THEN 'disposition_review_round' WHEN 'disposition_review_decisions' THEN 'disposition_review_decision' ELSE 'disposition_job_document' END,
 NEW.id, CASE WHEN disposition_private.hook_applying() THEN 'DISPOSITION_RECALCULATED' ELSE upper(command.operation) END, jsonb_build_object('command_id',command.command_id,'acting_role_id',command.acting_role_id,'before',before_state,'after',after_state),command.reason);
 RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION reject_event_history_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 -- Content minimization is confined to an actual protected erasure command.
 -- Identity, actor, operation, time, reason and event linkage cannot change.
 IF TG_OP='UPDATE' AND disposition_private.destruction_active('finalize') AND (disposition_private.context_operation() IN ('final_complete','job_terminate') OR current_setting('app.event_source',true)='migration')
 AND (NEW.before_state IS NOT DISTINCT FROM disposition_private.retained_json(OLD.before_state) OR NEW.before_state IS NOT DISTINCT FROM disposition_private.retained_history_json(OLD.before_state))
 AND (NEW.after_state IS NOT DISTINCT FROM disposition_private.retained_json(OLD.after_state) OR NEW.after_state IS NOT DISTINCT FROM disposition_private.retained_history_json(OLD.after_state))
 AND (NEW.metadata=disposition_private.retained_json(OLD.metadata) OR NEW.metadata=disposition_private.retained_history_json(OLD.metadata))
 AND (to_jsonb(NEW)-ARRAY['before_state','after_state','metadata'])=(to_jsonb(OLD)-ARRAY['before_state','after_state','metadata']) THEN RETURN NEW; END IF;
 RAISE EXCEPTION 'event history is immutable';
END $$;

CREATE FUNCTION disposition_private.retain_unit(p_job bigint,p_root bigint,p_run bigint,p_event bigint,p_at timestamptz,p_executor bigint,p_name text) RETURNS void LANGUAGE plpgsql AS $$
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
 DELETE FROM user_favourite_aggregations WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root));
 DELETE FROM user_favourite_records WHERE record_id IN (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
 UPDATE aggregations SET disposition_status=10,aggregation_number=NULL,title=NULL,description=NULL,date_opened=NULL,date_created=p_at,date_of_next_review=NULL,assigned_location=NULL,current_location=NULL,
 final_disposition_at=p_at,final_disposition_by_user_id=p_executor,disposition_job_id=p_job,destruction_number=(SELECT destruction_number FROM disposition_jobs WHERE id=p_job),final_disposition_event_id=p_event
 WHERE id IN (SELECT disposition_private.unit_ids(p_root));
 UPDATE records SET disposition_status=10,record_number=NULL,title=NULL,description=NULL,date_originated=NULL,date_created=p_at,date_of_next_review=NULL,
 final_disposition_at=p_at,final_disposition_by_user_id=p_executor,disposition_job_id=p_job,destruction_number=(SELECT destruction_number FROM disposition_jobs WHERE id=p_job),final_disposition_event_id=p_event
 WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root));
END $$;

CREATE FUNCTION disposition_private.minimize_unit_history(p_job bigint,p_root bigint) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF NOT disposition_private.destruction_active('finalize',p_root) THEN RAISE EXCEPTION 'disposition_destruction_command_required'; END IF;
 UPDATE disposition_review_rounds SET membership_snapshot=disposition_private.retained_history_json(membership_snapshot),proposal_snapshot=disposition_private.retained_history_json(proposal_snapshot),approval_execution=disposition_private.retained_history_json(approval_execution) WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root);
 UPDATE disposition_review_decisions SET membership_snapshot=disposition_private.retained_history_json(membership_snapshot) WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root);
 UPDATE disposition_job_documents SET provenance=disposition_private.retained_history_json(provenance) WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root);
 UPDATE disposition_proposal_effects SET details=disposition_private.retained_json(details) WHERE governing_root_id=p_root;
 UPDATE disposition_private.command_receipts SET payload=disposition_private.retained_command_payload(payload),result=disposition_private.retained_history_json(result)
 WHERE completed_at IS NOT NULL AND (payload->>'job_id' IN (SELECT job_id::text FROM disposition_job_memberships WHERE root_aggregation_id=p_root) OR payload->>'root_id'=p_root::text OR payload->>'task_id' IN (SELECT id::text FROM disposition_tasks WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)) OR result->>'job_id' IN (SELECT job_id::text FROM disposition_job_memberships WHERE root_aggregation_id=p_root) OR operation='job_create' AND result->>'id'=p_job::text);
 UPDATE event_history SET before_state=CASE WHEN entity_type IN ('aggregation','record','digital_component','record_component') THEN disposition_private.retained_json(before_state) ELSE disposition_private.retained_history_json(before_state) END,after_state=CASE WHEN entity_type IN ('aggregation','record','digital_component','record_component') THEN disposition_private.retained_json(after_state) ELSE disposition_private.retained_history_json(after_state) END,metadata=CASE WHEN entity_type IN ('aggregation','record','digital_component','record_component') THEN disposition_private.retained_json(metadata) ELSE disposition_private.retained_history_json(metadata) END
 WHERE (entity_type='aggregation' AND entity_id IN (SELECT disposition_private.unit_ids(p_root)))
 OR (entity_type='record' AND entity_id IN (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root))))
 OR (entity_type IN ('digital_component','record_component') AND (SELECT identities->'component_ids' FROM disposition_private.destruction_identities WHERE transaction_id=txid_current() AND root_id=p_root) @> to_jsonb(entity_id))
 OR (entity_type='disposition_job' AND entity_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root))
 OR (entity_type='disposition_task' AND entity_id IN (SELECT id FROM disposition_tasks WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)))
 OR (entity_type='disposition_review_round' AND entity_id IN (SELECT id FROM disposition_review_rounds WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)))
 OR (entity_type='disposition_review_decision' AND entity_id IN (SELECT id FROM disposition_review_decisions WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)))
 OR (entity_type='disposition_job_document' AND entity_id IN (SELECT id FROM disposition_job_documents WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)))
 OR (entity_type='disposition_job_membership' AND entity_id IN (SELECT id FROM disposition_job_memberships WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)));
END $$;

CREATE FUNCTION disposition_private.finish_digital_unit(p_run bigint,p_root bigint,p_token uuid) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE run disposition_destruction_runs%ROWTYPE;at_time timestamptz:=clock_timestamp();key uuid;event_id bigint;name text;finished boolean;physical disposition_physical_confirmations%ROWTYPE;proof_at timestamptz;proof_user bigint;
BEGIN
 PERFORM disposition_private.require_command();
 IF NOT disposition_private.digital_execution_released() THEN RAISE EXCEPTION 'disposition_digital_release_pending'; END IF;
 SELECT * INTO run FROM disposition_destruction_runs WHERE id=p_run FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM disposition_destruction_run_units WHERE run_id=p_run AND root_id=p_root AND state='running' AND claim_token=p_token) THEN RAISE EXCEPTION 'disposition_digital_claim_lost'; END IF;
 IF run.requested_by_user_id IS DISTINCT FROM current_user_id() THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_authorization_required'; END IF;
 PERFORM disposition_private.require_task_actor(run.task_id,run.acting_role_id,true);
 PERFORM disposition_private.check_digital_job(run.job_id,run.acting_role_id,false);
 IF NOT EXISTS(SELECT 1 FROM disposition_private.destruction_scopes WHERE run_id=p_run AND root_id=p_root AND scope=disposition_private.destruction_scope(p_root)) THEN
  IF disposition_private.physical_covered(run.job_id,p_root) THEN RAISE EXCEPTION 'disposition_physical_recovery_required'; END IF;
  RAISE EXCEPTION 'disposition_digital_scope_changed'; END IF;
 SELECT command_id INTO key FROM disposition_private.command_context WHERE transaction_id=txid_current();
 INSERT INTO disposition_private.destruction_context VALUES(txid_current(),pg_backend_pid(),key,p_run,p_root,p_token,'delete');
 IF NOT disposition_private.unit_has_digital(p_root) THEN
  SELECT * INTO physical FROM disposition_physical_confirmations WHERE job_id=run.job_id;
  IF physical.id IS NULL OR NOT disposition_private.physical_covered(run.job_id,p_root) THEN RAISE EXCEPTION 'disposition_physical_confirmation_required'; END IF;
  UPDATE disposition_private.destruction_context SET mode='finalize' WHERE transaction_id=txid_current();
  SELECT e.actor_name INTO name FROM event_history e WHERE e.entity_type='disposition_job' AND e.entity_id=run.job_id AND e.operation='PHYSICAL_DESTRUCTION_CONFIRMED' ORDER BY e.id LIMIT 1;
  event_id:=append_domain_event('aggregation',p_root,'DISPOSITION_UNIT_DESTROYED',jsonb_build_object('recovery_job_id',run.job_id,'root_id',p_root,'physical_confirmation_id',physical.id,'certificate_document_id',physical.certificate_document_id,'executor_user_id',physical.confirmed_by_user_id,'executor_name',name,'completed_at',physical.confirmed_at));
  PERFORM disposition_private.retain_unit(run.job_id,p_root,NULL,event_id,physical.confirmed_at,physical.confirmed_by_user_id,name);
 ELSE
 PERFORM disposition_private.erase_unit_content(p_root);
 UPDATE disposition_private.destruction_context SET mode='finalize' WHERE transaction_id=txid_current();
 SELECT u.name INTO name FROM users u WHERE u.id=current_user_id();
 event_id:=append_domain_event('aggregation',p_root,'DIGITAL_DESTRUCTION_UNIT_COMPLETED',jsonb_build_object('job_id',run.job_id,'run_id',p_run,'root_id',p_root,'executor_user_id',current_user_id(),'executor_name',name,'completed_at',at_time,'method','postgresql_transactional_erasure','command_id',key));
 PERFORM disposition_private.retain_unit(run.job_id,p_root,p_run,event_id,at_time,current_user_id(),name);
 END IF;
 UPDATE disposition_job_memberships SET membership_state='completed_history' WHERE job_id=run.job_id AND root_aggregation_id=p_root AND membership_state='active';
 UPDATE disposition_destruction_manifest_items SET destruction_state='succeeded',destroyed_at=at_time,run_id=p_run WHERE job_id=run.job_id AND root_id=p_root AND destruction_state='queued';
 UPDATE disposition_destruction_run_units SET state='succeeded',finished_at=at_time WHERE run_id=p_run AND root_id=p_root;
 SELECT NOT EXISTS(SELECT 1 FROM disposition_destruction_run_units WHERE run_id=p_run AND state<>'succeeded') INTO finished;
 UPDATE disposition_destruction_runs SET completed_units=completed_units+1,state=CASE WHEN finished THEN 'succeeded' ELSE 'running' END,finished_at=CASE WHEN finished THEN at_time END WHERE id=p_run;
 PERFORM disposition_private.minimize_unit_history(run.job_id,p_root);
 PERFORM append_domain_event('disposition_job',run.job_id,CASE WHEN finished THEN 'DIGITAL_DESTRUCTION_SUCCEEDED' ELSE 'DIGITAL_DESTRUCTION_PROGRESS' END,jsonb_build_object('run_id',p_run,'root_id',p_root,'completed_units',(SELECT completed_units FROM disposition_destruction_runs WHERE id=p_run),'job_completed',false));
 DELETE FROM disposition_private.destruction_identities WHERE transaction_id=txid_current();
 DELETE FROM disposition_private.destruction_context WHERE transaction_id=txid_current();
 RETURN jsonb_build_object('run_id',p_run,'root_id',p_root,'state','succeeded','run_finished',finished);
END $$;

CREATE FUNCTION disposition_private.original_request_approval_current(p_job bigint,p_round bigint) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE rr disposition_review_rounds%ROWTYPE;facts jsonb;rules jsonb;
BEGIN
 SELECT * INTO rr FROM disposition_review_rounds WHERE id=p_round AND job_id=p_job AND round_number=(SELECT current_review_round FROM disposition_jobs WHERE id=p_job);
 IF NOT FOUND OR rr.invalidated_at IS NOT NULL OR rr.approval_execution IS NULL OR jsonb_array_length(rr.approval_execution->'post_membership')=0 THEN RETURN false; END IF;
 facts:=disposition_private.request_facts(p_job);
 IF rr.approval_execution ? 'request_facts' THEN
  RETURN disposition_private.review_fingerprint(facts)=disposition_private.review_fingerprint(rr.approval_execution->'request_facts');
 END IF;
 -- Pre-062 approvals have only immutable versions/rules; do not invent a past
 -- semantic snapshot. Accept them only while the exact saved facts still match.
 SELECT COALESCE(jsonb_agg(jsonb_build_object('root_id',m.root_aggregation_id,'rule',e.rule_snapshot)),'[]') INTO rules
 FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.eligibility(m.root_aggregation_id) e WHERE m.job_id=p_job AND m.membership_state='active';
 RETURN disposition_private.review_fingerprint(disposition_private.membership_snapshot(p_job))=disposition_private.review_fingerprint(rr.approval_execution->'post_membership')
 AND disposition_private.review_fingerprint(rules)=disposition_private.review_fingerprint(rr.approval_execution->'post_rules');
END $$;
CREATE OR REPLACE FUNCTION disposition_private.request_approval_current(p_job bigint,p_round bigint) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM disposition_retained_records WHERE job_id=p_job) THEN
  RETURN EXISTS(SELECT 1 FROM disposition_review_rounds rr WHERE rr.id=p_round AND rr.job_id=p_job AND rr.round_number=(SELECT current_review_round FROM disposition_jobs WHERE id=p_job) AND rr.invalidated_at IS NULL AND rr.approval_execution IS NOT NULL)
   AND NOT EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=p_job AND m.membership_state='active' AND NOT EXISTS(SELECT 1 FROM disposition_private.destruction_scopes s JOIN disposition_destruction_runs r ON r.id=s.run_id WHERE r.job_id=p_job AND s.root_id=m.root_aggregation_id AND s.scope=disposition_private.destruction_scope(m.root_aggregation_id)));
 END IF;
 RETURN disposition_private.original_request_approval_current(p_job,p_round);
END $$;

CREATE FUNCTION disposition_private.retain_physical_outcome(p_job bigint,p_root bigint,p_event bigint,p_at timestamptz,p_executor bigint,p_name text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE key uuid;
BEGIN
 IF NOT disposition_private.recovery_active(p_job,p_root,10) THEN RAISE EXCEPTION 'disposition_recovery_command_required'; END IF;
 SELECT command_id INTO key FROM disposition_private.command_context WHERE transaction_id=txid_current();
 INSERT INTO disposition_private.destruction_context VALUES(txid_current(),pg_backend_pid(),key,NULL,p_root,NULL,'finalize') ON CONFLICT(transaction_id) DO UPDATE SET root_id=p_root;
 PERFORM disposition_private.retain_unit(p_job,p_root,NULL,p_event,p_at,p_executor,p_name);
 PERFORM disposition_private.minimize_unit_history(p_job,p_root);
END $$;
CREATE OR REPLACE FUNCTION disposition_private.transition_unit(p_root bigint,p_version bigint,p_status integer)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE root aggregations%ROWTYPE; uid bigint:=current_user_id(); event_id bigint; op text; recovery_job bigint; physical disposition_physical_confirmations%ROWTYPE; executor_name text;
BEGIN
 PERFORM disposition_private.require_command();
 op:=disposition_private.context_operation();
 SELECT * INTO root FROM aggregations WHERE id=p_root FOR UPDATE;
 IF NOT FOUND OR root.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 IF root.parent_aggregation_id IS NOT NULL THEN RAISE EXCEPTION 'disposition_requires_governing_root'; END IF;
 IF p_status NOT BETWEEN 1 AND 13 OR NOT disposition_private.allowed_transition(root.disposition_status,p_status,op) THEN RAISE EXCEPTION 'disposition_invalid_transition'; END IF;
 IF p_status IN (10,11,12,13) AND NOT (op='job_terminate' AND p_status IN (10,13) AND disposition_private.recovery_active(NULL,p_root,p_status)) THEN RAISE EXCEPTION 'disposition_action_not_implemented'; END IF;
 IF root.date_closed IS NULL AND p_status<>1 AND op<>'eligibility_accelerate' THEN RAISE EXCEPTION 'disposition_root_not_closed'; END IF;
 PERFORM 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root)) ORDER BY id FOR UPDATE;
 PERFORM 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) ORDER BY id FOR UPDATE;
 IF NOT disposition_private.hook_applying(p_root) AND NOT disposition_private.approval_active(NULL,p_root) AND current_setting('app.actor_type',true)='user' AND NOT user_can_view_aggregation(uid,p_root) THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 IF root.disposition_status=p_status AND (NOT disposition_private.hook_applying(p_root) OR NOT EXISTS(
  SELECT 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root)) AND disposition_status<>p_status
  UNION ALL SELECT 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) AND disposition_status<>p_status)) THEN RETURN; END IF;
 event_id:=append_domain_event('aggregation',p_root,'DISPOSITION_STATUS_CHANGED',jsonb_build_object(
  'old_status',root.disposition_status,'new_status',p_status,'operation',op,
  'command_id',(SELECT command_id FROM disposition_private.command_context WHERE transaction_id=txid_current())));
 IF p_status=10 THEN
  SELECT job_id INTO recovery_job FROM disposition_private.recovery_context WHERE transaction_id=txid_current() AND root_id=p_root;
  SELECT * INTO physical FROM disposition_physical_confirmations WHERE job_id=recovery_job;
  IF physical.id IS NULL OR NOT disposition_private.physical_covered(recovery_job,p_root) OR disposition_private.unit_has_digital(p_root) THEN RAISE EXCEPTION 'disposition_recovery_scope_invalid'; END IF;
  SELECT e.actor_name INTO executor_name FROM event_history e WHERE e.entity_type='disposition_job' AND e.entity_id=recovery_job AND e.operation='PHYSICAL_DESTRUCTION_CONFIRMED' AND e.metadata#>>'{after,id}'=physical.id::text ORDER BY e.id LIMIT 1;
  event_id:=append_domain_event('aggregation',p_root,'DISPOSITION_UNIT_DESTROYED',jsonb_build_object('recovery_job_id',recovery_job,'root_id',p_root,'physical_confirmation_id',physical.id,'certificate_document_id',physical.certificate_document_id,'executor_user_id',physical.confirmed_by_user_id,'executor_name',coalesce(executor_name,(SELECT name FROM users WHERE id=physical.confirmed_by_user_id)),'completed_at',physical.confirmed_at));
  PERFORM disposition_private.retain_physical_outcome(recovery_job,p_root,event_id,physical.confirmed_at,physical.confirmed_by_user_id,coalesce(executor_name,(SELECT name FROM users WHERE id=physical.confirmed_by_user_id)));
  RETURN;
 END IF;
 UPDATE aggregations SET disposition_status=p_status WHERE id IN (SELECT disposition_private.unit_ids(p_root)) AND disposition_status IS DISTINCT FROM p_status;
 UPDATE records SET disposition_status=p_status WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) AND disposition_status IS DISTINCT FROM p_status;
END $$;
CREATE OR REPLACE FUNCTION disposition_private.terminate_job(p_job bigint,p_version integer,p_confirm boolean) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE job disposition_jobs%ROWTYPE;member record;root aggregations%ROWTYPE;key uuid;target integer;facts jsonb;outcomes jsonb:='[]';retained_links jsonb;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'job_terminate' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 IF p_confirm IS DISTINCT FROM true THEN RAISE EXCEPTION 'disposition_confirmation_required'; END IF;
 PERFORM pg_advisory_xact_lock(7357,1);
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF NOT FOUND OR job.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 IF job.lifecycle_state<>'active' THEN RAISE EXCEPTION 'disposition_inactive_job'; END IF;
 PERFORM disposition_private.require_job_access(p_job);
 SELECT command_id INTO key FROM disposition_private.command_context WHERE transaction_id=txid_current();
 INSERT INTO disposition_private.recovery_context VALUES(txid_current(),pg_backend_pid(),key,p_job,0,NULL);
 FOR member IN SELECT * FROM disposition_job_memberships WHERE job_id=p_job AND membership_state IN ('active','completed_history') ORDER BY root_aggregation_id FOR UPDATE LOOP
  PERFORM disposition_private.lock_current_blockers(member.root_aggregation_id);
  SELECT * INTO root FROM aggregations WHERE id=member.root_aggregation_id;
  IF NOT disposition_private.recovery_unit_visible(root.id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_recovery_access_required'; END IF;
  IF root.disposition_status IN (10,11,12) THEN target:=root.disposition_status;
  ELSIF job.job_type='destruction' AND disposition_private.physical_covered(p_job,root.id) THEN
   target:=CASE WHEN disposition_private.unit_has_digital(root.id) THEN 13 ELSE 10 END;
   facts:=disposition_private.recovery_facts(p_job,root.id);
  ELSE target:=CASE WHEN member.removal_required THEN root.disposition_status ELSE job.disposition_status-4 END;facts:=NULL;
  END IF;
  IF root.disposition_status<>target THEN
   INSERT INTO disposition_private.recovery_context VALUES(txid_current(),pg_backend_pid(),key,p_job,root.id,target);
   PERFORM disposition_private.transition_unit(root.id,root.version,target);
   IF target=13 THEN PERFORM append_domain_event('aggregation',root.id,'DISPOSITION_PARTIALLY_DISPOSED',facts||jsonb_build_object('command_id',key,'old_status',root.disposition_status,'new_status',target)); END IF;
  END IF;
  IF member.membership_state='active' THEN UPDATE disposition_job_memberships SET membership_state='terminated_history' WHERE id=member.id; END IF;
  outcomes:=outcomes||jsonb_build_array(jsonb_build_object('root_id',root.id,'old_status',root.disposition_status,'new_status',target));
 END LOOP;
 SELECT coalesce(jsonb_agg(DISTINCT jsonb_build_array(l.resource_kind,l.relationship_id)),'[]') INTO retained_links FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.relationship_scope(m.root_aggregation_id) l WHERE m.job_id=p_job AND l.source_root_id IN (SELECT root_aggregation_id FROM disposition_job_memberships WHERE job_id=p_job) AND l.target_root_id IN (SELECT root_aggregation_id FROM disposition_job_memberships WHERE job_id=p_job);
 UPDATE disposition_tasks SET task_state='cancelled' WHERE job_id=p_job AND task_state IN ('open','claimed');
 UPDATE disposition_jobs SET lifecycle_state='terminated',disposition_status=job.disposition_status-4,termination_reason=current_setting('app.change_reason',true) WHERE id=p_job RETURNING * INTO job;
 PERFORM append_domain_event('disposition_job',p_job,'DISPOSITION_TERMINATION_OUTCOMES',jsonb_build_object('command_id',key,'outcomes',outcomes,'retained_relationships',retained_links));
 DELETE FROM disposition_private.recovery_context WHERE transaction_id=txid_current();
 DELETE FROM disposition_private.destruction_identities WHERE transaction_id=txid_current();
 DELETE FROM disposition_private.destruction_context WHERE transaction_id=txid_current();
 RETURN to_jsonb(job);
END $$;
CREATE OR REPLACE FUNCTION disposition_private.recovery_unit_visible(p_root bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT (current_user_can_view_aggregation(p_root) OR disposition_private.retained_access('aggregation',p_root,false)) AND NOT EXISTS(SELECT 1 FROM disposition_private.unit_ids(p_root) u(id)
 WHERE NOT (current_user_can_view_aggregation(u.id) OR disposition_private.retained_access('aggregation',u.id,false)) OR EXISTS(SELECT 1 FROM records r WHERE r.aggregation_id=u.id AND NOT (current_user_can_view_record(r.id) OR disposition_private.retained_access('record',r.id,false))))
$$;

DO $$
DECLARE root aggregations%ROWTYPE;captured_name text;
BEGIN
 FOR root IN SELECT a.* FROM aggregations a WHERE parent_aggregation_id IS NULL AND disposition_status=10 AND NOT EXISTS(SELECT 1 FROM disposition_retained_records WHERE resource_kind='aggregation' AND resource_id=a.id) LOOP
  IF NOT disposition_private.physical_covered(root.disposition_job_id,root.id) OR EXISTS(SELECT 1 FROM digital_components d JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(root.id))) THEN RAISE EXCEPTION 'disposition_existing_destroyed_content_requires_review'; END IF;
  SELECT metadata->>'executor_name' INTO captured_name FROM event_history WHERE id=root.final_disposition_event_id;
  IF captured_name IS NULL THEN RAISE EXCEPTION 'disposition_existing_outcome_requires_review'; END IF;
  PERFORM set_config('app.user_id','',true),set_config('app.actor_type','automated_process',true),set_config('app.actor_name','Migration068',true),set_config('app.event_source','migration',true);
  INSERT INTO disposition_private.destruction_context VALUES(txid_current(),pg_backend_pid(),NULL,NULL,root.id,NULL,'finalize');
  PERFORM disposition_private.retain_unit(root.disposition_job_id,root.id,NULL,root.final_disposition_event_id,root.final_disposition_at,root.final_disposition_by_user_id,captured_name);
  PERFORM disposition_private.minimize_unit_history(root.disposition_job_id,root.id);
  PERFORM append_domain_event('aggregation',root.id,'DISPOSITION_RETAINED_RECORD_MIGRATED',jsonb_build_object('job_id',root.disposition_job_id,'root_id',root.id,'event_id',root.final_disposition_event_id));
  DELETE FROM disposition_private.destruction_identities WHERE transaction_id=txid_current();
  DELETE FROM disposition_private.destruction_context WHERE transaction_id=txid_current();
 END LOOP;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA disposition_private FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA disposition_private FROM PUBLIC;
INSERT INTO schema_migrations(version) VALUES('068_disposition_retained_records') ON CONFLICT DO NOTHING;
