-- Restore a reopened member through compatible acceleration without a membership round trip.
BEGIN;
CREATE OR REPLACE FUNCTION disposition_private.accelerate(p_root bigint, p_version bigint) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE root aggregations%ROWTYPE; evaluation record;
 member disposition_job_memberships%ROWTYPE; job disposition_jobs%ROWTYPE; target integer;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'eligibility_accelerate' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 PERFORM disposition_private.lock_current_blockers(p_root);
 SELECT * INTO root FROM aggregations WHERE id=p_root;
 IF NOT FOUND OR root.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 IF NOT current_user_can_view_aggregation(p_root) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 IF root.parent_aggregation_id IS NOT NULL THEN RAISE EXCEPTION 'disposition_requires_governing_root'; END IF;
 IF root.disposition_status<>1 THEN RAISE EXCEPTION 'disposition_acceleration_state_invalid'; END IF;
 SELECT * INTO member FROM disposition_job_memberships WHERE root_aggregation_id=p_root AND membership_state='active' FOR UPDATE;
 IF FOUND THEN
  SELECT * INTO job FROM disposition_jobs WHERE id=member.job_id FOR UPDATE;
  PERFORM disposition_private.require_job_access(job.id);
  IF job.lifecycle_state<>'active' THEN RAISE EXCEPTION 'disposition_inactive_job'; END IF;
  IF NOT member.removal_required OR member.removal_required_reason IS DISTINCT FROM 'reopened' THEN RAISE EXCEPTION 'disposition_acceleration_state_invalid'; END IF;
  IF job.job_type='destruction' AND NOT EXISTS(WITH RECURSIVE owners AS (
   SELECT id,parent_org_unit_id FROM org_units WHERE id=root.owning_org_unit_id
   UNION ALL SELECT p.id,p.parent_org_unit_id FROM org_units p JOIN owners c ON p.id=c.parent_org_unit_id)
   SELECT 1 FROM owners WHERE id=job.owning_org_unit_id) THEN RAISE EXCEPTION 'disposition_owning_unit_mismatch'; END IF;
 END IF;
 SELECT * INTO evaluation FROM disposition_private.eligibility(p_root);
 IF evaluation.eligible_status IS NULL THEN RAISE EXCEPTION 'disposition_retention_rule_required'; END IF;
 IF member.id IS NOT NULL AND evaluation.eligible_status IS DISTINCT FROM job.disposition_status-4 THEN RAISE EXCEPTION 'disposition_job_type_status_mismatch'; END IF;
 IF root.date_closed IS NULL THEN
  IF NOT current_user_can_aggregation_operation(p_root,'aggregation.close','aggregation.close') THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='insufficient_privilege'; END IF;
  UPDATE aggregations SET date_closed=CURRENT_TIMESTAMP WHERE id=p_root RETURNING * INTO root;
 END IF;
 SELECT * INTO evaluation FROM disposition_private.eligibility(p_root);
 target:=evaluation.eligible_status;
 IF member.id IS NOT NULL THEN
  target:=job.disposition_status;
  -- Reuse the private, transaction-scoped unit context only for this exact
  -- restoration. Closure already passed the ordinary permissions/hold guards.
  INSERT INTO disposition_private.recalculation_context(transaction_id,backend_id,root_id,old_evaluation,old_status,cause,applying,target_status)
   VALUES(txid_current(),pg_backend_pid(),p_root,to_jsonb(evaluation),root.disposition_status,'accelerated',true,target);
  UPDATE disposition_job_memberships SET removal_required=false,removal_required_reason=NULL WHERE id=member.id;
 END IF;
 PERFORM disposition_private.transition_unit(p_root,root.version,target);
 IF member.id IS NOT NULL THEN
  DELETE FROM disposition_private.recalculation_context WHERE transaction_id=txid_current() AND backend_id=pg_backend_pid() AND root_id=p_root;
 END IF;
 PERFORM disposition_private.assert_unit(p_root);
 PERFORM append_domain_event('aggregation',p_root,'DISPOSITION_ACCELERATED',to_jsonb(evaluation)||jsonb_build_object('job_id',member.job_id,'membership_id',member.id,'new_status',target,'removal_required',false));
 RETURN jsonb_build_object('root_id',p_root,'status',target);
END $$;

CREATE OR REPLACE FUNCTION disposition_private.allowed_transition(old_status integer, new_status integer, cause text) RETURNS boolean
    LANGUAGE sql IMMUTABLE
    AS $$
 SELECT old_status=new_status OR CASE cause
 WHEN 'eligibility_evaluate' THEN old_status=1 AND new_status BETWEEN 2 AND 5
 WHEN 'eligibility_accelerate' THEN old_status=1 AND new_status BETWEEN 2 AND 9
 WHEN 'membership_add' THEN (old_status,new_status) IN ((2,6),(3,7),(4,8),(5,9))
 WHEN 'membership_remove' THEN (old_status,new_status) IN ((6,2),(7,3),(8,4),(9,5))
 WHEN 'job_terminate' THEN (old_status,new_status) IN ((6,2),(7,3),(8,4),(9,5),(6,13),(6,10))
 WHEN 'resolve_partial' THEN old_status=13 AND new_status BETWEEN 2 AND 5
 WHEN 'selective_decide' THEN old_status=8 AND new_status IN (2,3,5)
 WHEN 'final_complete' THEN (old_status,new_status) IN ((6,10),(7,11),(9,12))
 WHEN 'recalculate' THEN old_status NOT IN (10,11,12,13) AND new_status BETWEEN 1 AND 9
 ELSE false END
$$;

CREATE OR REPLACE FUNCTION disposition_private.assert_unit(p_root bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
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
  -- until explicitly removed or restored by compatible in-job acceleration.
  -- They cannot acquire a free-standing pending status.
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

CREATE OR REPLACE FUNCTION disposition_private.guard_resource() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE previous jsonb; following jsonb; fields text[] := ARRAY['disposition_status','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','transfer_number','final_disposition_event_id']; operation text; inherited smallint;
BEGIN
 IF TG_OP='UPDATE' AND NEW.disposition_status=10 AND disposition_private.destruction_active('finalize',disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN OLD.id ELSE (to_jsonb(OLD)->>'aggregation_id')::bigint END)) THEN RETURN NEW; END IF;

 IF TG_OP='UPDATE' AND disposition_private.context_operation()='eligibility_accelerate' AND NEW.disposition_status BETWEEN 6 AND 9
  AND NOT disposition_private.hook_applying(disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN NEW.id ELSE (to_jsonb(NEW)->>'aggregation_id')::bigint END)) THEN
  RAISE EXCEPTION 'disposition_recalculation_scope_invalid';
 END IF;
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
   -- Creation precedes preparation: either authorized governance profile may create.
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

INSERT INTO schema_migrations(version) VALUES('093_restore_reopened_job_members') ON CONFLICT DO NOTHING;
COMMIT;
