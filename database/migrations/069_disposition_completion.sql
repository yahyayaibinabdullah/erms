-- Recoverable completion. Operational release remains closed until Phase 23.
-- This private row is a worker checkpoint, not a new job lifecycle or task type.
CREATE TABLE disposition_private.completion_work (
 job_id bigint PRIMARY KEY REFERENCES disposition_jobs(id),
 request_id uuid NOT NULL UNIQUE,
 task_id bigint NOT NULL REFERENCES disposition_tasks(id),
 requested_by_user_id bigint NOT NULL REFERENCES users(id),
 acting_role_id bigint NOT NULL REFERENCES roles(id),
 state text NOT NULL CHECK(state IN ('queued','running','failed','succeeded')),
 requested_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 started_at timestamptz,finished_at timestamptz,claim_token uuid,
 last_error_code text,document_id bigint UNIQUE REFERENCES disposition_job_documents(id)
);
CREATE TABLE disposition_private.completion_context (
 transaction_id bigint PRIMARY KEY,backend_id integer NOT NULL,
 command_id uuid NOT NULL,job_id bigint NOT NULL
);
CREATE INDEX disposition_completion_pending ON disposition_private.completion_work(job_id) WHERE state IN ('queued','running');
REVOKE ALL ON disposition_private.completion_work,disposition_private.completion_context FROM PUBLIC;
CREATE FUNCTION disposition_private.completion_active(p_job bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_private.completion_context x JOIN disposition_private.command_context c USING(transaction_id,backend_id,command_id)
 WHERE x.transaction_id=txid_current() AND x.backend_id=pg_backend_pid() AND x.job_id=p_job)
$$;
CREATE UNIQUE INDEX disposition_one_digital_certificate ON disposition_job_documents(job_id) WHERE document_type='digital_destruction_certificate';
CREATE UNIQUE INDEX disposition_one_certificate_download ON disposition_tasks(job_id) WHERE task_type='certificate_download';

CREATE FUNCTION disposition_private.check_completion(p_job bigint,p_task bigint,p_role bigint) RETURNS void LANGUAGE plpgsql AS $$
DECLARE j disposition_jobs%ROWTYPE;
BEGIN
 PERFORM pg_advisory_xact_lock(7357,1);
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 PERFORM disposition_private.require_actor(p_role);
 PERFORM disposition_private.require_job_access(p_job);
 IF NOT disposition_private.person_role(current_user_id(),p_role) OR NOT disposition_private.review_role(p_job,'records_manager_review',p_role) OR NOT disposition_private.can_review_content(current_user_id(),p_job) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_manager_role_required'; END IF;
 IF j.job_type IS DISTINCT FROM 'destruction' OR j.lifecycle_state IS DISTINCT FROM 'active' OR j.workflow_stage IS DISTINCT FROM 'digital_destruction' THEN RAISE EXCEPTION 'disposition_completion_stage_invalid'; END IF;
 PERFORM disposition_private.require_task_actor(p_task,p_role,true);
 IF NOT EXISTS(SELECT 1 FROM disposition_tasks WHERE id=p_task AND job_id=p_job AND task_type='digital_destruction') THEN RAISE EXCEPTION 'disposition_completion_stage_invalid'; END IF;
 IF NOT EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='completed_history') OR EXISTS(SELECT 1 FROM disposition_job_memberships m JOIN aggregations a ON a.id=m.root_aggregation_id WHERE m.job_id=p_job AND (m.membership_state='active' OR m.membership_state='completed_history' AND (a.disposition_status<>10 OR a.disposition_job_id IS DISTINCT FROM p_job OR NOT EXISTS(SELECT 1 FROM disposition_retained_records p WHERE p.resource_kind='aggregation' AND p.resource_id=a.id AND p.job_id=p_job)))) THEN RAISE EXCEPTION 'disposition_completion_unfinished'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_destruction_runs WHERE job_id=p_job AND state IN ('queued','running')) THEN RAISE EXCEPTION 'disposition_completion_unfinished'; END IF;
 IF NOT EXISTS(SELECT 1 FROM disposition_retained_records WHERE job_id=p_job AND method='postgresql_transactional_erasure') THEN RAISE EXCEPTION 'disposition_completion_stage_invalid'; END IF;
END $$;

CREATE FUNCTION disposition_private.activate_certificate(p_job bigint,p_request uuid,p_token uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE w disposition_private.completion_work%ROWTYPE;acting bigint;key uuid;
BEGIN
 PERFORM disposition_private.require_command();
 SELECT * INTO w FROM disposition_private.completion_work WHERE job_id=p_job FOR UPDATE;
 SELECT acting_role_id,command_id INTO acting,key FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 IF disposition_private.context_operation()<>'document_save' OR w.request_id IS DISTINCT FROM p_request OR w.claim_token IS DISTINCT FROM p_token OR w.state IS DISTINCT FROM 'running' OR w.requested_by_user_id IS DISTINCT FROM current_user_id() OR w.acting_role_id IS DISTINCT FROM acting THEN RAISE EXCEPTION 'disposition_certificate_claim_lost'; END IF;
 PERFORM disposition_private.check_completion(p_job,w.task_id,acting);
 INSERT INTO disposition_private.completion_context VALUES(txid_current(),pg_backend_pid(),key,p_job);
END $$;

CREATE FUNCTION disposition_private.finish_destruction_job(p_job bigint,p_document bigint DEFAULT NULL) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE j disposition_jobs%ROWTYPE;acting bigint;key uuid;t record;physical disposition_physical_confirmations%ROWTYPE;root record;eid bigint;at_time timestamptz;executor bigint;executor_name text;download_id bigint;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'final_complete' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT acting_role_id,command_id INTO acting,key FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 PERFORM pg_advisory_xact_lock(7357,1);
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF j.lifecycle_state IS DISTINCT FROM 'active' OR j.job_type IS DISTINCT FROM 'destruction' THEN RAISE EXCEPTION 'disposition_completion_stage_invalid'; END IF;
 PERFORM disposition_private.require_actor(acting);
 PERFORM disposition_private.require_job_access(p_job);
 IF NOT disposition_private.review_role(p_job,'records_manager_review',acting) OR NOT disposition_private.person_role(current_user_id(),acting) OR NOT disposition_private.can_review_content(current_user_id(),p_job) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_manager_role_required'; END IF;
 IF p_document IS NOT NULL THEN
  IF NOT disposition_private.digital_execution_released() THEN RAISE EXCEPTION 'disposition_digital_release_pending'; END IF;
  SELECT task_id INTO download_id FROM disposition_private.completion_work WHERE job_id=p_job AND state='running' AND requested_by_user_id=current_user_id() AND acting_role_id=acting;
  PERFORM disposition_private.check_completion(p_job,download_id,acting);
  IF NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.id=p_document AND d.job_id=p_job AND d.document_type='digital_destruction_certificate' AND d.document_state='available' AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id) AND d.provenance->>'completion_request_id'=(SELECT request_id::text FROM disposition_private.completion_work WHERE job_id=p_job)) THEN RAISE EXCEPTION 'disposition_certificate_required'; END IF;
 ELSE
  IF NOT disposition_private.physical_execution_released() THEN RAISE EXCEPTION 'disposition_physical_release_pending'; END IF;
  SELECT * INTO physical FROM disposition_physical_confirmations WHERE job_id=p_job;
  IF j.workflow_stage<>'physical_destruction' OR physical.id IS NULL OR physical.confirmed_by_user_id<>current_user_id() OR disposition_private.has_digital_material(p_job) OR NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.id=physical.certificate_document_id AND d.document_state='available' AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id)) THEN RAISE EXCEPTION 'disposition_physical_certificate_required'; END IF;
 END IF;
 INSERT INTO disposition_private.completion_context VALUES(txid_current(),pg_backend_pid(),key,p_job);
 IF p_document IS NULL THEN
  -- Confirmation and completion share the caller's transaction. Reuse the
  -- verified physical-proof/minimization primitive, never digital deletion.
  FOR root IN SELECT a.id,a.version FROM disposition_job_memberships m JOIN aggregations a ON a.id=m.root_aggregation_id WHERE m.job_id=p_job AND m.membership_state='active' ORDER BY a.id LOOP
   IF NOT disposition_private.physical_covered(p_job,root.id) OR disposition_private.unit_has_digital(root.id) THEN RAISE EXCEPTION 'disposition_recovery_scope_invalid'; END IF;
   INSERT INTO disposition_private.recovery_context VALUES(txid_current(),pg_backend_pid(),key,p_job,root.id,10);
   PERFORM disposition_private.transition_unit(root.id,root.version,10);
   UPDATE disposition_job_memberships SET membership_state='completed_history' WHERE job_id=p_job AND root_aggregation_id=root.id AND membership_state='active';
  END LOOP;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='completed_history') OR EXISTS(SELECT 1 FROM disposition_job_memberships m JOIN aggregations a ON a.id=m.root_aggregation_id WHERE m.job_id=p_job AND (m.membership_state='active' OR m.membership_state='completed_history' AND (a.disposition_status<>10 OR a.disposition_job_id IS DISTINCT FROM p_job))) THEN RAISE EXCEPTION 'disposition_completion_unfinished'; END IF;
 SELECT destroyed_at,executor_user_id,p.executor_name INTO at_time,executor,executor_name FROM disposition_retained_records p WHERE p.job_id=p_job ORDER BY destroyed_at DESC,resource_kind,resource_id LIMIT 1;
 IF at_time IS NULL THEN RAISE EXCEPTION 'disposition_completion_unfinished'; END IF;
 eid:=append_domain_event('disposition_job',p_job,'DESTRUCTION_JOB_COMPLETED',jsonb_build_object('job_id',p_job,'certificate_document_id',coalesce(p_document,physical.certificate_document_id),'digital_certificate',p_document IS NOT NULL,'executor_user_id',executor,'executor_name',executor_name,'completed_at',at_time));
 -- Close current digital queues while their task eligibility is still active.
 IF p_document IS NOT NULL THEN
  UPDATE disposition_tasks SET task_state='completed' WHERE id=download_id;
  UPDATE disposition_tasks SET task_state='cancelled' WHERE job_id=p_job AND task_type='digital_destruction' AND task_state IN ('open','claimed');
 END IF;
 UPDATE disposition_jobs SET workflow_stage='certificate_generation',lifecycle_state='completed',disposition_status=10,completed_at=at_time,completed_by_user_id=executor,completed_by_name=executor_name,final_event_id=eid WHERE id=p_job;
 IF p_document IS NOT NULL THEN
  INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,review_round,destination_user_id) VALUES(p_job,'certificate_download','certificate_generation',j.current_review_round,current_user_id()) RETURNING id INTO download_id;
  UPDATE disposition_private.completion_work SET state='succeeded',finished_at=clock_timestamp(),last_error_code=NULL,document_id=p_document WHERE job_id=p_job;
 END IF;
 DELETE FROM disposition_private.recovery_context WHERE transaction_id=txid_current();
 DELETE FROM disposition_private.destruction_identities WHERE transaction_id=txid_current();
 DELETE FROM disposition_private.destruction_context WHERE transaction_id=txid_current();
 DELETE FROM disposition_private.completion_context WHERE transaction_id=txid_current();
 RETURN jsonb_build_object('job_id',p_job,'lifecycle_state','completed','certificate_document_id',coalesce(p_document,physical.certificate_document_id),'download_task_id',CASE WHEN p_document IS NOT NULL THEN download_id END);
END $$;

CREATE FUNCTION disposition_private.finish_certificate_download(p_job bigint,p_document bigint) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE t disposition_tasks%ROWTYPE;acting bigint;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'task_complete' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT acting_role_id INTO acting FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 SELECT * INTO t FROM disposition_tasks WHERE job_id=p_job AND task_type='certificate_download' AND task_state='open' AND destination_user_id=current_user_id() FOR UPDATE;
 IF t.id IS NULL OR NOT EXISTS(SELECT 1 FROM disposition_job_documents WHERE id=p_document AND job_id=p_job AND document_type='digital_destruction_certificate') THEN RAISE EXCEPTION 'disposition_certificate_task_unavailable'; END IF;
 PERFORM disposition_private.require_task_actor(t.id,acting,true);
 PERFORM append_domain_event('disposition_job',p_job,'DIGITAL_CERTIFICATE_DOWNLOADED',jsonb_build_object('certificate_document_id',p_document,'task_id',t.id,'acting_role_id',acting));
 UPDATE disposition_tasks SET task_state='completed' WHERE id=t.id;
 RETURN jsonb_build_object('job_id',p_job,'task_id',t.id,'downloaded',true);
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
   IF op<>'final_complete' OR NOT disposition_private.completion_active(NEW.id) THEN RAISE EXCEPTION 'disposition_completion_command_required'; END IF;
   IF EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=NEW.id AND membership_state='active') OR NOT EXISTS(SELECT 1 FROM disposition_retained_records WHERE job_id=NEW.id) THEN RAISE EXCEPTION 'disposition_completion_unfinished'; END IF;
  END IF;
  IF NEW.lifecycle_state='terminated' THEN
   NEW.terminated_at:=CURRENT_TIMESTAMP; NEW.terminated_by_user_id:=uid;
  END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO job FROM disposition_jobs WHERE id=(following->>'job_id')::bigint FOR UPDATE;
 IF NOT disposition_private.hook_applying() AND NOT disposition_private.approval_active(job.id) AND NOT (op='task_release' AND current_setting('app.actor_type',true)='automated_process') THEN PERFORM disposition_private.require_job_access(job.id); END IF;
 IF NOT disposition_private.approval_active(job.id) AND TG_TABLE_NAME IN ('disposition_tasks','disposition_review_rounds','disposition_review_decisions') AND op IN ('task_complete','review_submit','review_decide','final_complete') AND NOT (op='review_decide' AND COALESCE((SELECT r.payload->>'decision' FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current())='rejected',false)) THEN PERFORM disposition_private.require_progress(job.id); END IF;
 IF job.lifecycle_state<>'active' AND NOT (TG_TABLE_NAME='disposition_tasks' AND following->>'task_type'='certificate_download' AND job.lifecycle_state='completed' AND ((TG_OP='INSERT' AND op='final_complete' AND disposition_private.completion_active(job.id)) OR (TG_OP='UPDATE' AND op='task_complete'))) AND NOT (TG_TABLE_NAME='disposition_job_memberships' AND op IN ('job_terminate','final_complete')) AND NOT (TG_TABLE_NAME='disposition_job_documents' AND op='document_save' AND following->>'document_type'='proposal_execution_report' AND EXISTS(SELECT 1 FROM disposition_review_rounds approved WHERE approved.job_id=job.id AND approved.round_number=(following->>'review_round')::integer AND approved.approval_execution IS NOT NULL)) THEN RAISE EXCEPTION 'disposition_inactive_job'; END IF;
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
   IF job.lifecycle_state='completed' AND NOT EXISTS(SELECT 1 FROM event_history WHERE transaction_id=txid_current() AND entity_type='disposition_job' AND entity_id=job.id AND operation='DIGITAL_CERTIFICATE_DOWNLOADED' AND metadata->>'task_id'=NEW.id::text) THEN RAISE EXCEPTION 'disposition_certificate_download_required'; END IF;
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
   ((op IN ('task_complete','review_submit','review_decide') OR op='final_complete' AND disposition_private.completion_active(job.id)) AND OLD.task_state IN ('open','claimed') AND NEW.task_state='completed') OR
   ((op IN ('job_assign','job_terminate','review_submit','review_decide') OR op='final_complete' AND disposition_private.completion_active(job.id)) AND NEW.task_state='cancelled')) THEN RAISE EXCEPTION 'disposition_invalid_task_transition'; END IF;
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

CREATE OR REPLACE FUNCTION disposition_private.preserve_physical_outcome() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM disposition_physical_confirmations WHERE job_id=OLD.id) AND NOT disposition_private.physical_active(OLD.id) AND
 NOT disposition_private.completion_active(OLD.id) AND
 NOT (disposition_private.context_operation()='job_terminate' AND disposition_private.recovery_active(OLD.id)) AND
 (NEW.lifecycle_state IS DISTINCT FROM OLD.lifecycle_state OR NEW.workflow_stage IS DISTINCT FROM OLD.workflow_stage OR NEW.disposition_status IS DISTINCT FROM OLD.disposition_status OR NEW.assigned_user_id IS DISTINCT FROM OLD.assigned_user_id) THEN RAISE EXCEPTION 'disposition_physical_recovery_required'; END IF;
 RETURN NEW;
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
 IF p_status IN (10,11,12,13) AND NOT ((op='job_terminate' AND p_status IN (10,13) OR op='final_complete' AND p_status=10 AND EXISTS(SELECT 1 FROM disposition_private.recovery_context x WHERE x.transaction_id=txid_current() AND x.root_id=p_root AND disposition_private.completion_active(x.job_id))) AND disposition_private.recovery_active(NULL,p_root,p_status)) THEN RAISE EXCEPTION 'disposition_action_not_implemented'; END IF;
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
  IF root.disposition_status=10 AND job.lifecycle_state IN ('active','terminated','completed') AND EXISTS(SELECT 1 FROM disposition_retained_records p WHERE p.resource_kind='aggregation' AND p.resource_id=p_root AND p.job_id=job.id AND p.final_event_id=root.final_disposition_event_id AND p.executor_user_id=root.final_disposition_by_user_id AND p.destroyed_at=root.final_disposition_at) AND EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=job.id AND m.root_aggregation_id=p_root AND m.membership_state IN ('active','completed_history','terminated_history')) THEN RETURN; END IF;
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

CREATE OR REPLACE FUNCTION disposition_private.guard_artifact() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target record; previous disposition_job_documents%ROWTYPE; role_id bigint;
BEGIN
 IF TG_OP='UPDATE' AND disposition_private.destruction_active('finalize') AND NEW.provenance=disposition_private.retained_history_json(OLD.provenance) AND (to_jsonb(NEW)-'provenance')=(to_jsonb(OLD)-'provenance') THEN RETURN NEW; END IF;

 PERFORM disposition_private.require_command();
 IF NEW.document_type='digital_destruction_certificate' AND NOT disposition_private.completion_active(NEW.job_id) THEN RAISE EXCEPTION 'disposition_completion_command_required'; END IF;
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

CREATE OR REPLACE FUNCTION disposition_private.review_role(p_job bigint,p_stage text,p_role bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 WITH RECURSIVE chain AS (
 SELECT id,parent_org_unit_id,file_administrator_role_id,0 depth FROM org_units WHERE id=(SELECT owning_org_unit_id FROM disposition_jobs WHERE id=p_job)
 UNION ALL SELECT p.id,p.parent_org_unit_id,p.file_administrator_role_id,c.depth+1 FROM org_units p JOIN chain c ON p.id=c.parent_org_unit_id)
 SELECT CASE (CASE WHEN p_stage IN ('physical_destruction','digital_destruction','certificate_generation') THEN 'records_manager_review' ELSE p_stage END)
 WHEN 'file_administrator_review' THEN p_role=(SELECT file_administrator_role_id FROM chain WHERE file_administrator_role_id IS NOT NULL ORDER BY depth LIMIT 1)
 WHEN 'unit_manager_review' THEN p_role=(SELECT managing_role_id FROM org_units WHERE id=(SELECT owning_org_unit_id FROM disposition_jobs WHERE id=p_job))
 WHEN 'records_manager_review' THEN EXISTS(SELECT 1 FROM roles r JOIN profiles p ON p.id=r.profile_id
 JOIN profile_privileges pp ON pp.profile_id=p.id JOIN privileges v ON v.id=pp.privilege_id
 WHERE r.id=p_role AND p.code='INFO_GOV_MGR' AND r.is_information_governance AND v.code='disposition.jobs.manage')
 ELSE false END
$$;

CREATE OR REPLACE FUNCTION disposition_private.task_eligible(p_user bigint,p_task bigint,p_role bigint DEFAULT NULL) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT COALESCE(EXISTS(SELECT 1 FROM disposition_tasks t JOIN disposition_jobs j ON j.id=t.job_id
 WHERE t.id=p_task AND (j.lifecycle_state='active' OR j.lifecycle_state='completed' AND t.task_type='certificate_download')
 AND disposition_private.can_review_content(p_user,j.id) AND
 CASE WHEN t.task_type='certificate_download' THEN t.destination_user_id=p_user AND EXISTS(SELECT 1 FROM roles r WHERE disposition_private.person_role(p_user,r.id) AND disposition_private.review_role(j.id,'records_manager_review',r.id) AND (p_role IS NULL OR r.id=p_role)) WHEN t.destination_user_id IS NOT NULL THEN t.destination_user_id=p_user AND j.assigned_user_id=p_user
 AND disposition_private.governance_person(p_user,CASE WHEN j.review_route='records_manager_only' THEN 'INFO_GOV_MGR' ELSE 'INFO_GOV_OFFICER' END)
 AND (p_role IS NULL OR EXISTS(SELECT 1 FROM roles r JOIN profiles p ON p.id=r.profile_id
 JOIN profile_privileges pp ON pp.profile_id=p.id JOIN privileges v ON v.id=pp.privilege_id
 WHERE r.id=p_role AND r.is_information_governance AND v.code='disposition.jobs.manage'
 AND p.code=CASE WHEN j.review_route='records_manager_only' THEN 'INFO_GOV_MGR' ELSE 'INFO_GOV_OFFICER' END
 AND disposition_private.person_role(p_user,r.id)))
 ELSE disposition_private.person_role(p_user,t.destination_role_id)
 AND disposition_private.review_role(j.id,t.workflow_stage,t.destination_role_id)
 AND (p_role IS NULL OR p_role=t.destination_role_id) END),false)
$$;

CREATE OR REPLACE FUNCTION disposition_private.finish_digital_unit(p_run bigint,p_root bigint,p_token uuid) RETURNS jsonb LANGUAGE plpgsql AS $$
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
 IF finished AND NOT EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=run.job_id AND membership_state='active') THEN
  INSERT INTO disposition_private.completion_work(job_id,request_id,task_id,requested_by_user_id,acting_role_id,state) VALUES(run.job_id,key,run.task_id,run.requested_by_user_id,run.acting_role_id,'queued') ON CONFLICT(job_id) DO NOTHING;
 END IF;
 DELETE FROM disposition_private.destruction_identities WHERE transaction_id=txid_current();
 DELETE FROM disposition_private.destruction_context WHERE transaction_id=txid_current();
 RETURN jsonb_build_object('run_id',p_run,'root_id',p_root,'state','succeeded','run_finished',finished);
END $$;

INSERT INTO disposition_private.completion_work(job_id,request_id,task_id,requested_by_user_id,acting_role_id,state)
SELECT DISTINCT ON(r.job_id) r.job_id,r.request_id,r.task_id,r.requested_by_user_id,r.acting_role_id,'queued'
FROM disposition_destruction_runs r JOIN disposition_jobs j ON j.id=r.job_id
WHERE r.state='succeeded' AND j.lifecycle_state='active' AND j.workflow_stage='digital_destruction'
AND EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=j.id AND m.membership_state='completed_history')
AND NOT EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=j.id AND m.membership_state='active')
ORDER BY r.job_id,r.run_number DESC ON CONFLICT(job_id) DO NOTHING;
-- Exact acknowledgement of a committed physical-only confirmation must remain
-- retryable after that same operation closes its task and job. This is not
-- permission to work a completed task: every new command still uses its gate.
CREATE FUNCTION disposition_private.physical_confirmation_retry(p_id uuid,p_role bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_private.command_receipts r
 JOIN disposition_tasks t ON t.id=(r.payload->>'task_id')::bigint
 JOIN disposition_jobs j ON j.id=t.job_id
 JOIN disposition_physical_confirmations p ON p.task_id=t.id AND p.job_id=j.id
 JOIN disposition_job_documents d ON d.id=p.certificate_document_id
 WHERE r.command_id=p_id AND r.operation='review_decide' AND r.completed_at IS NOT NULL
 AND r.actor_user_id=current_user_id() AND r.acting_role_id=p_role AND j.lifecycle_state='completed'
 AND d.provenance->>'physical_command_id'=p_id::text
 AND disposition_private.person_role(current_user_id(),p_role)
 AND disposition_private.review_role(j.id,'records_manager_review',p_role)
 AND disposition_private.can_review_content(current_user_id(),j.id)
 AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id))
$$;

CREATE OR REPLACE FUNCTION disposition_private.begin_command(p_id uuid,p_operation text,p_payload jsonb,p_role bigint,p_reason text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE previous disposition_private.command_receipts%ROWTYPE;
BEGIN
 PERFORM pg_advisory_xact_lock(7357,1);
 IF p_operation IN ('task_claim','task_release','task_reassign','task_complete','review_save','review_submit','review_decide') AND p_payload ? 'task_id' AND NOT (p_operation='review_decide' AND disposition_private.physical_confirmation_retry(p_id,p_role)) THEN
  PERFORM disposition_private.require_task_command((p_payload->>'task_id')::bigint,p_role,p_operation);
 ELSE PERFORM disposition_private.require_actor(p_role); END IF;
 IF p_reason IS NULL OR p_reason ~ '^[[:space:]]*$' THEN RAISE EXCEPTION 'disposition_reason_required'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_private.command_context WHERE transaction_id=txid_current()) THEN RAISE EXCEPTION 'disposition_nested_command'; END IF;
 SELECT * INTO previous FROM disposition_private.command_receipts WHERE command_id=p_id FOR UPDATE;
 IF FOUND THEN
  IF previous.actor_type IS DISTINCT FROM 'user' OR previous.actor_user_id IS DISTINCT FROM current_user_id() OR previous.acting_role_id IS DISTINCT FROM p_role OR previous.operation<>p_operation
    OR previous.payload IS DISTINCT FROM p_payload OR previous.reason IS DISTINCT FROM p_reason THEN
    RAISE EXCEPTION USING ERRCODE='23505',MESSAGE='disposition_command_conflict'; END IF;
  IF previous.completed_at IS NULL THEN RAISE EXCEPTION 'disposition_incomplete_command'; END IF;
  -- Returning a committed result still obeys current resource access.
  IF previous.payload ? 'job_id' THEN PERFORM disposition_private.require_job_access((previous.payload->>'job_id')::bigint);
  ELSIF p_operation='job_create' AND previous.result ? 'id' THEN PERFORM disposition_private.require_job_access((previous.result->>'id')::bigint);
  ELSIF previous.payload ? 'membership_id' THEN PERFORM disposition_private.require_job_access((SELECT job_id FROM disposition_job_memberships WHERE id=(previous.payload->>'membership_id')::bigint));
  ELSIF p_operation='eligibility_accelerate' AND previous.payload ? 'root_id' AND NOT current_user_can_view_aggregation((previous.payload->>'root_id')::bigint) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
  RETURN previous.result;
 END IF;
 INSERT INTO disposition_private.command_receipts(command_id,actor_user_id,acting_role_id,operation,payload,reason)
 VALUES(p_id,current_user_id(),p_role,p_operation,p_payload,p_reason);
 INSERT INTO disposition_private.command_context VALUES(txid_current(),pg_backend_pid(),p_id);
 PERFORM set_config('app.change_reason',p_reason,true);
 RETURN NULL;
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA disposition_private FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA disposition_private FROM PUBLIC;
INSERT INTO schema_migrations(version) VALUES('069_disposition_completion') ON CONFLICT DO NOTHING;
