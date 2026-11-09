-- Final certificate completion uses the existing Records Manager queue lifecycle.
-- Existing unfinished tasks keep their IDs and eligible assignee as claimant.
BEGIN;
CREATE OR REPLACE FUNCTION disposition_private.finish_destruction_job(p_job bigint, p_document bigint DEFAULT NULL::bigint) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
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
  IF EXISTS(SELECT 1 FROM disposition_private.completion_work WHERE job_id=p_job AND state='running') THEN
   SELECT task_id INTO download_id FROM disposition_private.completion_work WHERE job_id=p_job AND state='running' AND requested_by_user_id=current_user_id() AND acting_role_id=acting;
   PERFORM disposition_private.check_completion(p_job,download_id,acting);
  ELSE
   SELECT id INTO download_id FROM disposition_tasks WHERE job_id=p_job AND task_type='certificate_download' AND task_state IN ('open','claimed') FOR UPDATE;
   IF j.workflow_stage<>'certificate_generation' OR download_id IS NULL OR NOT EXISTS(SELECT 1 FROM disposition_private.completion_work WHERE job_id=p_job AND state='succeeded' AND document_id=p_document) THEN RAISE EXCEPTION 'disposition_certificate_required'; END IF;
   PERFORM disposition_private.require_task_actor(download_id,acting,true);
  END IF;
  IF NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.id=p_document AND d.job_id=p_job AND d.document_type='digital_destruction_certificate' AND d.document_state='available' AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id) AND d.provenance->>'completion_request_id'=(SELECT request_id::text FROM disposition_private.completion_work WHERE job_id=p_job)) THEN RAISE EXCEPTION 'disposition_certificate_required'; END IF;
 ELSE
  SELECT * INTO physical FROM disposition_physical_confirmations WHERE job_id=p_job;
  IF j.workflow_stage<>'physical_destruction' OR physical.id IS NULL OR physical.confirmed_by_user_id<>current_user_id() OR disposition_private.has_digital_material(p_job) OR NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.id=physical.certificate_document_id AND d.document_state='available' AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id)) THEN RAISE EXCEPTION 'disposition_physical_certificate_required'; END IF;
 END IF;
 INSERT INTO disposition_private.completion_context VALUES(txid_current(),pg_backend_pid(),key,p_job);
 -- Saving the certificate prepares the last human task; it does not finish the job.
 IF p_document IS NOT NULL AND EXISTS(SELECT 1 FROM disposition_private.completion_work WHERE job_id=p_job AND state='running') THEN
  UPDATE disposition_tasks SET task_state='completed' WHERE id=download_id;
  UPDATE disposition_tasks SET task_state='cancelled' WHERE job_id=p_job AND task_type='digital_destruction' AND task_state IN ('open','claimed');
  UPDATE disposition_jobs SET workflow_stage='certificate_generation' WHERE id=p_job;
  INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,review_round,destination_role_id,task_state,claimed_by_user_id,claimed_at)
  VALUES(p_job,'certificate_download','certificate_generation',j.current_review_round,acting,'claimed',current_user_id(),CURRENT_TIMESTAMP) RETURNING id INTO download_id;
  UPDATE disposition_private.completion_work SET state='succeeded',finished_at=clock_timestamp(),last_error_code=NULL,document_id=p_document WHERE job_id=p_job;
  PERFORM append_domain_event('disposition_job',p_job,'DIGITAL_CERTIFICATE_SAVED',jsonb_build_object('certificate_document_id',p_document,'task_id',download_id));
  DELETE FROM disposition_private.completion_context WHERE transaction_id=txid_current();
  RETURN jsonb_build_object('job_id',p_job,'lifecycle_state','active','certificate_document_id',p_document,'download_task_id',download_id);
 END IF;

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

 DELETE FROM disposition_private.recovery_context WHERE transaction_id=txid_current();
 DELETE FROM disposition_private.destruction_identities WHERE transaction_id=txid_current();
 DELETE FROM disposition_private.destruction_context WHERE transaction_id=txid_current();
 DELETE FROM disposition_private.completion_context WHERE transaction_id=txid_current();
 RETURN jsonb_build_object('job_id',p_job,'lifecycle_state','completed','certificate_document_id',coalesce(p_document,physical.certificate_document_id),'task_id',CASE WHEN p_document IS NOT NULL THEN download_id END);
END $$;

CREATE OR REPLACE FUNCTION disposition_private.task_eligible(p_user bigint, p_task bigint, p_role bigint DEFAULT NULL::bigint) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
 SELECT COALESCE(EXISTS(SELECT 1 FROM disposition_tasks t JOIN disposition_jobs j ON j.id=t.job_id
 WHERE t.id=p_task AND (j.lifecycle_state='active' OR j.lifecycle_state='completed' AND t.task_type='certificate_download')
 AND disposition_private.can_review_content(p_user,j.id) AND
 (t.task_type<>'certificate_download' OR EXISTS(
  SELECT 1 FROM disposition_job_documents d JOIN records certificate ON certificate.id=d.record_id
  WHERE d.job_id=j.id AND d.document_type='digital_destruction_certificate' AND d.document_state='available'
   AND user_can_view_record(p_user,d.record_id)
   AND (user_has_record_permission(p_user,d.record_id,'record.component.list') OR user_has_governance_clearance(p_user,certificate.security_level_id)))) AND
 CASE WHEN t.task_type='certificate_download' AND t.destination_user_id IS NOT NULL THEN t.destination_user_id=p_user AND EXISTS(SELECT 1 FROM roles r WHERE disposition_private.person_role(p_user,r.id) AND disposition_private.review_role(j.id,'records_manager_review',r.id) AND (p_role IS NULL OR r.id=p_role)) WHEN t.destination_user_id IS NOT NULL THEN t.destination_user_id=p_user AND j.assigned_user_id=p_user
 AND disposition_private.preparer_eligible(p_user,j.review_route)
 AND (p_role IS NULL OR EXISTS(SELECT 1 FROM roles r JOIN profiles p ON p.id=r.profile_id
 JOIN profile_privileges pp ON pp.profile_id=p.id JOIN privileges v ON v.id=pp.privilege_id
 WHERE r.id=p_role AND r.is_information_governance AND v.code='disposition.jobs.manage'
 AND (p.code='INFO_GOV_MGR' OR j.review_route<>'records_manager_only' AND p.code='INFO_GOV_OFFICER')
 AND disposition_private.person_role(p_user,r.id)))
 ELSE disposition_private.person_role(p_user,t.destination_role_id)
 AND disposition_private.review_role(j.id,t.workflow_stage,t.destination_role_id)
 AND (p_role IS NULL OR p_role=t.destination_role_id) END),false)
$$;

CREATE OR REPLACE FUNCTION disposition_private.guard_workflow() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
 PERFORM disposition_private.check_operation_write(CASE WHEN TG_TABLE_NAME='disposition_jobs' THEN NEW.id ELSE (following->>'job_id')::bigint END);
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
   IF NEW.assigned_user_id IS NULL THEN RAISE EXCEPTION 'disposition_assignment_required'; END IF;
   -- Creation requires one eligible preparer; either governance profile may create.
   IF NOT (disposition_private.governance_person(uid,'INFO_GOV_OFFICER') OR disposition_private.governance_person(uid,'INFO_GOV_MGR')) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_assignee_not_authorized'; END IF;
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
   IF EXISTS(SELECT 1 FROM disposition_tasks WHERE job_id=NEW.id AND task_state IN ('open','claimed')) OR EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=NEW.id AND membership_state='active') OR NOT EXISTS(SELECT 1 FROM disposition_retained_records WHERE job_id=NEW.id) THEN RAISE EXCEPTION 'disposition_completion_unfinished'; END IF;
  END IF;
  IF NEW.lifecycle_state='terminated' THEN
   NEW.terminated_at:=CURRENT_TIMESTAMP; NEW.terminated_by_user_id:=uid;
  END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO job FROM disposition_jobs WHERE id=(following->>'job_id')::bigint FOR UPDATE;
 IF NOT disposition_private.hook_applying() AND NOT disposition_private.approval_active(job.id) AND NOT (op='task_release' AND current_setting('app.actor_type',true)='automated_process') THEN PERFORM disposition_private.require_job_access(job.id); END IF;
 IF NOT disposition_private.approval_active(job.id) AND TG_TABLE_NAME IN ('disposition_tasks','disposition_review_rounds','disposition_review_decisions') AND op IN ('task_complete','review_submit','review_decide','final_complete') AND NOT (op='review_decide' AND COALESCE((SELECT r.payload->>'decision' FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current())='rejected',false)) THEN PERFORM disposition_private.require_progress(job.id); END IF;
 IF job.lifecycle_state<>'active' AND NOT (TG_TABLE_NAME='disposition_tasks' AND following->>'task_type'='certificate_download' AND job.lifecycle_state='completed' AND ((TG_OP='INSERT' AND op='final_complete' AND disposition_private.completion_active(job.id)) OR (TG_OP='UPDATE' AND (op='task_complete' OR op='final_complete' AND disposition_private.completion_active(job.id))))) AND NOT (TG_TABLE_NAME='disposition_job_memberships' AND op IN ('job_terminate','final_complete')) AND NOT (TG_TABLE_NAME='disposition_job_documents' AND op='document_save' AND following->>'document_type'='proposal_execution_report' AND EXISTS(SELECT 1 FROM disposition_review_rounds approved WHERE approved.job_id=job.id AND approved.round_number=(following->>'review_round')::integer AND approved.approval_execution IS NOT NULL)) THEN RAISE EXCEPTION 'disposition_inactive_job'; END IF;
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
   IF op IN ('recalculate','eligibility_accelerate') AND disposition_private.hook_applying(NEW.root_aggregation_id) THEN
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
   IF job.lifecycle_state='completed' AND NOT EXISTS(SELECT 1 FROM event_history WHERE transaction_id=txid_current() AND entity_type='disposition_job' AND entity_id=job.id AND operation IN ('DIGITAL_CERTIFICATE_DOWNLOADED','CERTIFICATE_TASK_COMPLETED') AND metadata->>'task_id'=NEW.id::text) THEN RAISE EXCEPTION 'disposition_certificate_download_required'; END IF;
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
   -- A newly inserted claimed certificate task is not visible to task_eligible
   -- yet. Validate its supplied queue/person under the protected completion context.
   IF TG_OP='INSERT' AND NEW.task_type='certificate_download' AND op='final_complete' AND disposition_private.completion_active(job.id) THEN
    IF NEW.claimed_by_user_id IS DISTINCT FROM uid
     OR NOT disposition_private.person_role(uid,NEW.destination_role_id)
     OR NOT disposition_private.review_role(job.id,'records_manager_review',NEW.destination_role_id)
     OR NEW.destination_role_id IS DISTINCT FROM (SELECT acting_role_id FROM disposition_private.command_receipts WHERE command_id=(SELECT command_id FROM disposition_private.command_context WHERE transaction_id=txid_current()))
     OR NOT disposition_private.can_review_content(uid,job.id)
     OR NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.job_id=job.id AND d.document_type='digital_destruction_certificate' AND d.document_state='available' AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id))
    THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
   ELSIF NOT disposition_private.task_eligible(NEW.claimed_by_user_id,NEW.id,NEW.destination_role_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
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

-- Convert only unfinished legacy direct certificate tasks. Preserve each task
-- ID, original creation time, saved certificate, destruction proof and history.
SELECT set_config('app.user_id','',true),set_config('app.actor_type','automated_process',true),
 set_config('app.actor_name','Final certificate queue migration',true),
 set_config('app.event_source','migration',true),
 set_config('app.change_reason','Make unfinished final certificate tasks releasable and reassignable',true);
LOCK TABLE disposition_tasks IN SHARE ROW EXCLUSIVE MODE;
DO $$ DECLARE prior disposition_tasks%ROWTYPE; following disposition_tasks%ROWTYPE; queue_id bigint; claimant bigint; BEGIN
 IF EXISTS(SELECT 1 FROM disposition_tasks t JOIN disposition_jobs j ON j.id=t.job_id
  WHERE t.task_type='certificate_download' AND t.destination_user_id IS NOT NULL
   AND t.task_state IN ('open','claimed') AND j.lifecycle_state='active' AND j.workflow_stage='certificate_generation') THEN
  ALTER TABLE disposition_tasks DISABLE TRIGGER disposition_guard;
  ALTER TABLE disposition_tasks DISABLE TRIGGER disposition_audit;
  FOR prior IN SELECT t.* FROM disposition_tasks t JOIN disposition_jobs j ON j.id=t.job_id
   WHERE t.task_type='certificate_download' AND t.destination_user_id IS NOT NULL
    AND t.task_state IN ('open','claimed') AND j.lifecycle_state='active' AND j.workflow_stage='certificate_generation'
   ORDER BY t.id FOR UPDATE OF t LOOP
   SELECT r.id INTO queue_id FROM roles r
    WHERE disposition_private.review_role(prior.job_id,'certificate_generation',r.id)
    ORDER BY disposition_private.task_eligible(prior.destination_user_id,prior.id,r.id) DESC,
     role_effectively_active(r.id) DESC,
     (r.id=(SELECT acting_role_id FROM disposition_private.completion_work WHERE job_id=prior.job_id)) DESC NULLS LAST,r.id LIMIT 1;
   IF queue_id IS NULL THEN RAISE EXCEPTION 'disposition_final_certificate_manager_queue_required'; END IF;
   claimant:=CASE WHEN disposition_private.person_role(prior.destination_user_id,queue_id)
     AND disposition_private.task_eligible(prior.destination_user_id,prior.id,queue_id) THEN prior.destination_user_id ELSE NULL END;
   UPDATE disposition_tasks SET destination_user_id=NULL,destination_role_id=queue_id,
    task_state=CASE WHEN claimant IS NULL THEN 'open' ELSE 'claimed' END,claimed_by_user_id=claimant,
    claimed_at=CASE WHEN claimant IS NOT NULL THEN coalesce(prior.claimed_at,CURRENT_TIMESTAMP) END,
    version=version+1,date_updated=clock_timestamp() WHERE id=prior.id RETURNING * INTO following;
   PERFORM append_domain_event('disposition_task',prior.id,'TASK_REASSIGN',
    jsonb_build_object('before',to_jsonb(prior),'after',to_jsonb(following),'migration','106_final_certificate_task_queue'),
    'Make unfinished final certificate tasks releasable and reassignable');
  END LOOP;
  SET CONSTRAINTS ALL IMMEDIATE;
  ALTER TABLE disposition_tasks ENABLE TRIGGER disposition_guard;
  ALTER TABLE disposition_tasks ENABLE TRIGGER disposition_audit;
  SET CONSTRAINTS ALL DEFERRED;
 END IF;
END $$;
INSERT INTO schema_migrations(version) VALUES('106_final_certificate_task_queue') ON CONFLICT DO NOTHING;
COMMIT;
