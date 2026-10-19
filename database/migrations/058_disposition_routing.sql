BEGIN;
SELECT set_config('app.user_id','',true),set_config('app.actor_type','automated_process',true),
 set_config('app.actor_name','Database migration 058',true),set_config('app.event_source','migration',true),
 set_config('app.change_reason','Install destruction routing and shared task operations',true);

-- Message snapshots may be built inside a disposition command SAVEPOINT.
-- A tuple's xmin can be a child XID, while pg_current_xact_id is always the
-- top-level XID. Map xmin to the nearest full XID (wrap-aware), then accept
-- only a visible, still-in-progress inserting transaction. MVCC never exposes
-- another transaction's uncommitted envelope. Committed envelopes remain sealed.
CREATE OR REPLACE FUNCTION messaging_snapshot_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE inserting_low bigint; current_full bigint:=pg_current_xact_id()::text::bigint; inserting_full bigint;
BEGIN
 SELECT xmin::text::bigint INTO inserting_low FROM message_envelopes WHERE id=NEW.envelope_id;
 IF inserting_low IS NOT NULL THEN
  inserting_full:=current_full+mod(inserting_low-mod(current_full,4294967296)+4294967296+2147483648,4294967296)-2147483648;
  IF inserting_full>0 AND pg_xact_status(inserting_full::text::xid8)='in progress' THEN RETURN NEW; END IF;
 END IF;
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='message_snapshot_already_committed';
END $$;

-- Earlier jobs have never entered an implemented review route. Preserve their
-- preparation and history; Standard is the historical/default route.
ALTER TABLE disposition_private.command_receipts DROP CONSTRAINT disposition_command_actor,
 ADD CONSTRAINT disposition_command_actor CHECK (
 (actor_type='user' AND actor_user_id IS NOT NULL AND acting_role_id IS NOT NULL)
 OR (actor_type='automated_process' AND actor_user_id IS NULL AND acting_role_id IS NULL AND operation IN ('eligibility_evaluate','task_release')));
ALTER TABLE disposition_jobs ADD COLUMN review_route text;
ALTER TABLE disposition_jobs DISABLE TRIGGER disposition_guard;
ALTER TABLE disposition_jobs DISABLE TRIGGER disposition_audit;
UPDATE disposition_jobs SET review_route='standard' WHERE job_type='destruction';
-- Drain deferred whole-unit checks before changing trigger enablement.
SET CONSTRAINTS ALL IMMEDIATE;
ALTER TABLE disposition_jobs ENABLE TRIGGER disposition_guard;
ALTER TABLE disposition_jobs ENABLE TRIGGER disposition_audit;
SET CONSTRAINTS ALL DEFERRED;
ALTER TABLE disposition_jobs ADD CONSTRAINT disposition_saved_route CHECK (
 (job_type='destruction' AND review_route IS NOT NULL AND review_route IN ('standard','simplified','records_manager_only'))
 OR (job_type<>'destruction' AND review_route IS NULL));
ALTER TABLE disposition_tasks ADD COLUMN routing_org_unit_id bigint REFERENCES org_units(id) ON DELETE RESTRICT;
CREATE INDEX disposition_tasks_current_stage ON disposition_tasks(job_id,workflow_stage,task_state,id);

CREATE FUNCTION disposition_private.person_role(p_user bigint,p_role bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM users u JOIN user_role_assignments a ON a.user_id=u.id JOIN roles r ON r.id=a.role_id
 WHERE u.id=p_user AND u.status='active' AND u.account_type='person' AND r.id=p_role
 AND role_effectively_active(r.id) AND NOT r.is_system AND r.account_type_restriction IS DISTINCT FROM 'service'
 AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP))
$$;
CREATE FUNCTION disposition_private.governance_person(p_user bigint,p_profile text) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM roles r JOIN profiles p ON p.id=r.profile_id
 JOIN profile_privileges pp ON pp.profile_id=p.id JOIN privileges v ON v.id=pp.privilege_id
 WHERE p.code=p_profile AND r.is_information_governance AND v.code='disposition.jobs.manage'
 AND disposition_private.person_role(p_user,r.id))
$$;
CREATE FUNCTION disposition_private.require_preparer(p_user bigint,p_route text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF NOT disposition_private.governance_person(p_user,CASE WHEN p_route='records_manager_only' THEN 'INFO_GOV_MGR' ELSE 'INFO_GOV_OFFICER' END)
 THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_assignee_not_authorized'; END IF;
END $$;
CREATE FUNCTION disposition_private.can_review_content(p_user bigint,p_job bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT NOT EXISTS(SELECT 1 FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.unit_ids(m.root_aggregation_id) unit(id)
 WHERE m.job_id=p_job AND m.membership_state='active' AND
 (NOT user_can_view_aggregation(p_user,unit.id) OR EXISTS(SELECT 1 FROM records r WHERE r.aggregation_id=unit.id AND NOT user_can_view_record(p_user,r.id))))
$$;
-- Responsibility comes from current authoritative designations, not role names,
-- profile guesses, an inherited ACL grant, or yesterday's task assignment.
CREATE FUNCTION disposition_private.review_role(p_job bigint,p_stage text,p_role bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 WITH RECURSIVE chain AS (
 SELECT id,parent_org_unit_id,file_administrator_role_id,0 depth FROM org_units WHERE id=(SELECT owning_org_unit_id FROM disposition_jobs WHERE id=p_job)
 UNION ALL SELECT p.id,p.parent_org_unit_id,p.file_administrator_role_id,c.depth+1 FROM org_units p JOIN chain c ON p.id=c.parent_org_unit_id)
 SELECT CASE p_stage
 WHEN 'file_administrator_review' THEN p_role=(SELECT file_administrator_role_id FROM chain WHERE file_administrator_role_id IS NOT NULL ORDER BY depth LIMIT 1)
 WHEN 'unit_manager_review' THEN p_role=(SELECT managing_role_id FROM org_units WHERE id=(SELECT owning_org_unit_id FROM disposition_jobs WHERE id=p_job))
 WHEN 'records_manager_review' THEN EXISTS(SELECT 1 FROM roles r JOIN profiles p ON p.id=r.profile_id
 JOIN profile_privileges pp ON pp.profile_id=p.id JOIN privileges v ON v.id=pp.privilege_id
 WHERE r.id=p_role AND p.code='INFO_GOV_MGR' AND r.is_information_governance AND v.code='disposition.jobs.manage')
 ELSE false END
$$;
CREATE FUNCTION disposition_private.task_eligible(p_user bigint,p_task bigint,p_role bigint DEFAULT NULL) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT COALESCE(EXISTS(SELECT 1 FROM disposition_tasks t JOIN disposition_jobs j ON j.id=t.job_id
 WHERE t.id=p_task AND j.lifecycle_state='active'
 AND disposition_private.can_review_content(p_user,j.id) AND
 CASE WHEN t.destination_user_id IS NOT NULL THEN t.destination_user_id=p_user AND j.assigned_user_id=p_user
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
CREATE FUNCTION disposition_private.task_manager(p_task bigint,p_role bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_tasks t JOIN roles r ON r.id=p_role
 JOIN profile_privileges pp ON pp.profile_id=r.profile_id JOIN privileges v ON v.id=pp.privilege_id
 WHERE t.id=p_task AND current_setting('app.actor_type',true)='user' AND r.is_information_governance AND v.code='disposition.jobs.manage'
 AND disposition_private.person_role(current_user_id(),p_role)
 AND disposition_private.can_review_content(current_user_id(),t.job_id))
$$;
CREATE FUNCTION disposition_private.require_task_command(p_task bigint,p_role bigint,p_operation text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF p_operation IN ('task_release','task_reassign') AND disposition_private.task_manager(p_task,p_role) THEN RETURN; END IF;
 PERFORM disposition_private.require_task_actor(p_task,p_role,false);
END $$;

CREATE FUNCTION disposition_private.require_task_actor(p_task bigint,p_role bigint,p_work boolean DEFAULT false) RETURNS void LANGUAGE plpgsql AS $$
DECLARE t disposition_tasks%ROWTYPE;
BEGIN
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task;
 IF current_setting('app.actor_type',true) IS DISTINCT FROM 'user' OR NOT disposition_private.task_eligible(current_user_id(),p_task,p_role)
 THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
 IF p_work AND (t.task_state NOT IN ('open','claimed') OR t.workflow_stage IS DISTINCT FROM (SELECT workflow_stage FROM disposition_jobs WHERE id=t.job_id)) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
 IF p_work AND t.destination_role_id IS NOT NULL AND (t.task_state<>'claimed' OR t.claimed_by_user_id IS DISTINCT FROM current_user_id())
 THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_claim_required'; END IF;
END $$;

CREATE OR REPLACE FUNCTION disposition_private.begin_command(p_id uuid,p_operation text,p_payload jsonb,p_role bigint,p_reason text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE previous disposition_private.command_receipts%ROWTYPE;
BEGIN
 PERFORM pg_advisory_xact_lock(7357,1);
 IF p_operation IN ('task_claim','task_release','task_reassign','task_complete','review_decide') AND p_payload ? 'task_id' THEN
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

CREATE OR REPLACE FUNCTION disposition_private.require_command() RETURNS void LANGUAGE plpgsql AS $$
DECLARE command disposition_private.command_receipts%ROWTYPE;
BEGIN
 IF disposition_private.hook_applying() THEN RETURN; END IF;
 SELECT r.* INTO command FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id)
 WHERE c.transaction_id=txid_current() AND c.backend_id=pg_backend_pid() AND r.completed_at IS NULL;
 IF NOT FOUND OR command.actor_user_id IS DISTINCT FROM current_user_id()
 OR command.actor_type IS DISTINCT FROM current_setting('app.actor_type',true) THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_protected_operation_required'; END IF;
 IF command.actor_type='automated_process' THEN
  IF command.operation NOT IN ('eligibility_evaluate','task_release') OR command.actor_user_id IS NOT NULL OR command.acting_role_id IS NOT NULL THEN
   RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_protected_operation_required'; END IF;
 ELSE
  IF command.operation IN ('task_claim','task_release','task_reassign','task_complete','review_decide') AND command.payload ? 'task_id' THEN
   PERFORM disposition_private.require_task_command((command.payload->>'task_id')::bigint,command.acting_role_id,command.operation);
  ELSE PERFORM disposition_private.require_actor(command.acting_role_id); END IF;
 END IF;
END $$;

CREATE OR REPLACE FUNCTION disposition_private.guard_workflow() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE job disposition_jobs%ROWTYPE; prior jsonb; following jsonb; op text; uid bigint:=current_user_id(); expected_status integer;
BEGIN
 PERFORM disposition_private.require_command();
 op:=disposition_private.context_operation();
 IF NOT (CASE TG_TABLE_NAME
 WHEN 'disposition_jobs' THEN op IN ('job_create','job_assign','job_owner_change','membership_add','membership_remove','job_terminate','final_complete','review_submit','review_decide','recalculate','selective_decide')
 WHEN 'disposition_job_memberships' THEN op IN ('membership_add','membership_remove','job_terminate','final_complete','recalculate')
 WHEN 'disposition_tasks' THEN op IN ('job_create','job_assign','task_claim','task_release','task_reassign','task_complete','review_submit','review_decide','job_terminate','final_complete')
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
  IF TG_OP='UPDATE' AND NOT disposition_private.hook_applying() THEN PERFORM disposition_private.require_job_access(NEW.id); END IF;
  IF TG_OP='UPDATE' AND ((NEW.workflow_stage IS DISTINCT FROM OLD.workflow_stage AND NEW.workflow_stage NOT IN ('officer_correction','manager_correction')) OR NEW.disposition_status<>OLD.disposition_status) AND op<>'job_terminate' THEN PERFORM disposition_private.require_progress(NEW.id); END IF;
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
 IF NOT disposition_private.hook_applying() AND NOT (op='task_release' AND current_setting('app.actor_type',true)='automated_process') THEN PERFORM disposition_private.require_job_access(job.id); END IF;
 IF TG_TABLE_NAME IN ('disposition_tasks','disposition_review_rounds','disposition_review_decisions') AND op IN ('task_complete','review_submit','review_decide','final_complete') THEN PERFORM disposition_private.require_progress(job.id); END IF;
 IF job.lifecycle_state<>'active' AND NOT (TG_TABLE_NAME='disposition_job_memberships' AND op IN ('job_terminate','final_complete')) THEN RAISE EXCEPTION 'disposition_inactive_job'; END IF;
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
   IF NOT disposition_private.hook_applying(NEW.root_aggregation_id) AND NOT current_user_can_view_aggregation(NEW.root_aggregation_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
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
   (op IN ('task_complete','review_decide') AND OLD.task_state IN ('open','claimed') AND NEW.task_state='completed') OR
   (op IN ('job_assign','job_terminate','review_submit','review_decide') AND NEW.task_state='cancelled')) THEN RAISE EXCEPTION 'disposition_invalid_task_transition'; END IF;
  IF NEW.task_state='claimed' THEN
   IF NEW.destination_role_id IS NULL THEN RAISE EXCEPTION 'disposition_role_queue_required'; END IF;
   IF NOT disposition_private.task_eligible(NEW.claimed_by_user_id,NEW.id,NEW.destination_role_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
   IF op<>'task_reassign' AND NEW.claimed_by_user_id<>uid THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
   NEW.claimed_at:=CURRENT_TIMESTAMP;
  END IF;
 ELSIF TG_TABLE_NAME='disposition_review_rounds' THEN
  IF TG_OP='INSERT' THEN NEW.started_at:=CURRENT_TIMESTAMP;
  ELSE
   IF OLD.completed_at IS NOT NULL AND NEW.completed_at IS DISTINCT FROM OLD.completed_at THEN RAISE EXCEPTION 'disposition_history_immutable'; END IF;
   IF OLD.completed_at IS NULL AND NEW.completed_at IS NOT NULL THEN NEW.completed_at:=CURRENT_TIMESTAMP; END IF;
   IF OLD.invalidated_at IS NULL AND NEW.invalidated_at IS NOT NULL THEN NEW.invalidated_at:=CURRENT_TIMESTAMP; END IF;
  END IF;
  IF TG_OP='UPDATE' AND (NEW.round_number<>OLD.round_number OR NEW.membership_snapshot<>OLD.membership_snapshot OR NEW.started_at<>OLD.started_at OR NEW.started_by_user_id<>OLD.started_by_user_id) THEN RAISE EXCEPTION 'disposition_review_snapshot_immutable'; END IF;
  IF TG_OP='INSERT' AND (NEW.started_by_user_id<>uid OR NEW.membership_snapshot IS DISTINCT FROM disposition_private.membership_snapshot(job.id)) THEN RAISE EXCEPTION 'disposition_review_snapshot_mismatch'; END IF;
  IF TG_OP='INSERT' AND NEW.round_number<>COALESCE((SELECT max(round_number)+1 FROM disposition_review_rounds WHERE job_id=job.id),1) THEN RAISE EXCEPTION 'disposition_round_out_of_order'; END IF;
  IF TG_OP='INSERT' THEN UPDATE disposition_jobs SET current_review_round=NEW.round_number,version=version+1,date_updated=CURRENT_TIMESTAMP WHERE id=job.id; END IF;
 ELSIF TG_TABLE_NAME='disposition_review_decisions' THEN
  NEW.decided_at:=CURRENT_TIMESTAMP;
  IF TG_OP<>'INSERT' OR NEW.actor_user_id<>uid OR NEW.acting_role_id<>(SELECT r.acting_role_id FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current()) OR NOT EXISTS(SELECT 1 FROM disposition_tasks t WHERE t.id=NEW.task_id AND t.job_id=NEW.job_id AND t.workflow_stage=NEW.review_stage AND (t.claimed_by_user_id=uid OR (t.destination_user_id=uid AND t.task_state='open')) AND (t.destination_role_id IS NULL OR EXISTS(SELECT 1 FROM user_role_assignments a WHERE a.user_id=uid AND a.role_id=t.destination_role_id AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(a.role_id)))) THEN RAISE EXCEPTION 'disposition_decision_context_invalid'; END IF;
  IF NEW.membership_snapshot IS DISTINCT FROM disposition_private.membership_snapshot(job.id) THEN RAISE EXCEPTION 'disposition_review_snapshot_stale'; END IF;
  IF NEW.membership_snapshot IS DISTINCT FROM (SELECT membership_snapshot FROM disposition_review_rounds WHERE id=NEW.round_id) THEN RAISE EXCEPTION 'disposition_review_snapshot_mismatch'; END IF;
 ELSIF TG_TABLE_NAME='disposition_job_documents' THEN
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

CREATE OR REPLACE FUNCTION disposition_private.require_membership_stage(p_job bigint) RETURNS void LANGUAGE plpgsql AS $$
DECLARE job disposition_jobs%ROWTYPE;
BEGIN
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job;
 IF job.lifecycle_state<>'active' THEN RAISE EXCEPTION 'disposition_inactive_job'; END IF;
 IF job.job_type='destruction' AND job.workflow_stage NOT IN ('officer_preparation','officer_correction','manager_preparation','manager_correction') THEN
 RAISE EXCEPTION 'disposition_membership_stage_invalid'; END IF;
 IF job.job_type='destruction' THEN
  IF job.assigned_user_id IS DISTINCT FROM current_user_id() THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_assigned_preparer_required'; END IF;
  PERFORM disposition_private.require_preparer(current_user_id(),job.review_route);
 END IF;
END $$;

CREATE OR REPLACE FUNCTION disposition_private.assert_admission(p_job bigint,p_root bigint) RETURNS void LANGUAGE plpgsql AS $$
DECLARE job disposition_jobs%ROWTYPE; root aggregations%ROWTYPE;
BEGIN
 PERFORM disposition_private.require_command();
 PERFORM disposition_private.lock_current_blockers(p_root);
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 SELECT * INTO root FROM aggregations WHERE id=p_root;
 PERFORM disposition_private.require_membership_stage(p_job);
 IF NOT current_user_can_view_aggregation(p_root) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 IF root.parent_aggregation_id IS NOT NULL THEN RAISE EXCEPTION 'disposition_requires_governing_root'; END IF;
 IF job.assigned_user_id IS NULL THEN RAISE EXCEPTION 'disposition_assignment_required'; END IF;
 IF job.job_type='destruction' THEN PERFORM disposition_private.require_preparer(job.assigned_user_id,job.review_route); ELSE PERFORM disposition_private.require_job_person(job.assigned_user_id,job.job_type); END IF;
 IF NOT user_can_view_aggregation(job.assigned_user_id,p_root) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_assignee_access_required'; END IF;
 IF root.date_closed IS NULL THEN RAISE EXCEPTION 'disposition_root_not_closed'; END IF;
 IF root.disposition_status NOT BETWEEN 2 AND 5 OR root.disposition_status<>job.disposition_status-4 THEN RAISE EXCEPTION 'disposition_job_type_status_mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_private.protection_blockers(p_root)) THEN RAISE EXCEPTION 'disposition_admission_blocked'; END IF;
 IF job.job_type='destruction' AND NOT EXISTS(WITH RECURSIVE owners AS (
 SELECT id,parent_org_unit_id FROM org_units WHERE id=root.owning_org_unit_id
 UNION ALL SELECT p.id,p.parent_org_unit_id FROM org_units p JOIN owners c ON p.id=c.parent_org_unit_id)
 SELECT 1 FROM owners WHERE id=job.owning_org_unit_id) THEN RAISE EXCEPTION 'disposition_owning_unit_mismatch'; END IF;
END $$;

CREATE OR REPLACE FUNCTION disposition_private.add_items(p_job bigint,p_version integer,p_items jsonb) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE job disposition_jobs%ROWTYPE; item jsonb; root aggregations%ROWTYPE; member bigint; results jsonb:='[]'; code text;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'membership_add' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF NOT FOUND OR job.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 PERFORM disposition_private.require_job_access(p_job);
 IF jsonb_typeof(p_items)<>'array' OR jsonb_array_length(p_items) NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'disposition_selection_bounds_invalid'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(p_items) LOOP
  BEGIN
   SELECT * INTO root FROM aggregations WHERE id=(item->>'root_id')::bigint AND current_user_can_view_aggregation(id) FOR UPDATE;
   IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
   IF root.version<>(item->>'expected_version')::bigint THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
   INSERT INTO disposition_job_memberships(job_id,root_aggregation_id,added_by_user_id) VALUES(p_job,root.id,current_user_id()) RETURNING id INTO member;
   PERFORM disposition_private.transition_unit(root.id,root.version,job.disposition_status);
   PERFORM disposition_private.assert_unit(root.id);
   results:=results||jsonb_build_array(jsonb_build_object('root_id',root.id,'success',true,'membership_id',member));
  EXCEPTION WHEN SQLSTATE 'P0001' OR SQLSTATE '42501' OR unique_violation OR SQLSTATE '40001' THEN
   GET STACKED DIAGNOSTICS code=MESSAGE_TEXT;
   IF code NOT IN ('disposition_assigned_preparer_required','disposition_resource_access_required','disposition_stale_version','disposition_assignment_required','disposition_assignee_not_authorized','disposition_assignee_access_required','disposition_root_not_closed','disposition_job_type_status_mismatch','disposition_admission_blocked','disposition_owning_unit_mismatch','disposition_requires_governing_root','disposition_membership_stage_invalid','disposition_already_completed','disposition_inactive_job') THEN code:='disposition_item_not_added'; END IF;
   results:=results||jsonb_build_array(jsonb_build_object('root_id',item->'root_id','success',false,'code',code));
  END;
 END LOOP;
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job;
 RETURN jsonb_build_object('items',results,'job_version',job.version);
END $$;

-- One direct preparation/correction task. Reassignment cancels the previous
-- responsibility without rewriting the earlier claimant or saved work.
CREATE FUNCTION disposition_private.preparation_task() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.job_type<>'destruction' THEN RETURN NULL; END IF;
 IF TG_OP='UPDATE' THEN
  IF NEW.assigned_user_id IS NOT DISTINCT FROM OLD.assigned_user_id THEN RETURN NULL; END IF;
  UPDATE disposition_tasks SET task_state='cancelled' WHERE job_id=NEW.id AND destination_user_id IS NOT NULL AND task_state IN ('open','claimed');
 END IF;
 IF NEW.assigned_user_id IS NOT NULL AND NEW.workflow_stage IN ('officer_preparation','officer_correction','manager_preparation','manager_correction') THEN
  INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,review_round,destination_user_id)
  VALUES(NEW.id,CASE WHEN NEW.workflow_stage LIKE '%correction' THEN 'correction' ELSE 'preparation' END,NEW.workflow_stage,NULLIF(NEW.current_review_round,0),NEW.assigned_user_id);
 END IF;
 RETURN NULL;
END $$;
CREATE TRIGGER disposition_preparation_task AFTER INSERT OR UPDATE OF assigned_user_id ON disposition_jobs FOR EACH ROW EXECUTE FUNCTION disposition_private.preparation_task();

CREATE OR REPLACE FUNCTION disposition_private.claim_task(p_task bigint,p_version integer) RETURNS integer LANGUAGE plpgsql AS $$
DECLARE t disposition_tasks%ROWTYPE; next_version integer; acting_role bigint;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'task_claim' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task FOR UPDATE;
 IF NOT FOUND OR t.version<>p_version OR t.task_state<>'open' THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_task'; END IF;
 IF t.destination_role_id IS NULL THEN RAISE EXCEPTION 'disposition_role_queue_required'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_tasks other WHERE other.job_id=t.job_id AND other.workflow_stage=t.workflow_stage AND other.task_state='claimed' AND other.id<>t.id) THEN RAISE EXCEPTION 'disposition_task_already_claimed'; END IF;
 SELECT r.acting_role_id INTO acting_role FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 PERFORM disposition_private.require_task_actor(p_task,acting_role,false);
 UPDATE disposition_tasks SET task_state='claimed',claimed_by_user_id=current_user_id() WHERE id=p_task RETURNING version INTO next_version;
 RETURN next_version;
END $$;

CREATE FUNCTION disposition_private.release_task(p_task bigint,p_version integer) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE t disposition_tasks%ROWTYPE;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'task_release' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task FOR UPDATE;
 IF NOT FOUND OR t.version<>p_version OR t.task_state<>'claimed' OR t.destination_role_id IS NULL THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_task'; END IF;
 UPDATE disposition_tasks SET task_state='open' WHERE id=p_task RETURNING * INTO t;
 RETURN to_jsonb(t);
END $$;
CREATE FUNCTION disposition_private.reassign_task(p_task bigint,p_version integer,p_user bigint,p_queue bigint DEFAULT NULL) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE t disposition_tasks%ROWTYPE; acting bigint; target bigint;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'task_reassign' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task FOR UPDATE;
 IF NOT FOUND OR t.version<>p_version OR t.task_state NOT IN ('open','claimed') OR t.destination_role_id IS NULL THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_task'; END IF;
 -- Current claimant may hand over to another eligible person in the SAME queue.
 -- Broader job reassignment remains the separate management command.
 SELECT r.acting_role_id INTO acting FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 IF t.claimed_by_user_id IS DISTINCT FROM current_user_id() AND NOT disposition_private.task_manager(p_task,acting) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_claim_required'; END IF;
 target:=COALESCE(p_queue,t.destination_role_id);
 IF target<>t.destination_role_id AND (NOT disposition_private.task_manager(p_task,acting) OR p_user IS NOT NULL OR NOT disposition_private.review_role(t.job_id,t.workflow_stage,target)
 OR NOT EXISTS(SELECT 1 FROM users u WHERE disposition_private.person_role(u.id,target) AND disposition_private.can_review_content(u.id,t.job_id))) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
 IF p_user IS NOT NULL AND NOT disposition_private.task_eligible(p_user,p_task,t.destination_role_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_task_ineligible'; END IF;
 UPDATE disposition_tasks SET task_state=CASE WHEN p_user IS NULL THEN 'open' ELSE 'claimed' END,claimed_by_user_id=p_user,destination_role_id=target,routing_org_unit_id=CASE WHEN t.workflow_stage='records_manager_review' THEN NULL ELSE (SELECT org_unit_id FROM roles WHERE id=target) END WHERE id=p_task RETURNING * INTO t;
 RETURN to_jsonb(t);
END $$;

-- Routing primitives are INTERNAL. Phase 14's submission/decision service
-- validates its complete proposal/mark set before traversing any review edge.
-- There is deliberately no HTTP "set stage" or generic task-complete endpoint.
CREATE FUNCTION disposition_private.route_review(p_job bigint,p_stage text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE j disposition_jobs%ROWTYPE; role_id bigint; source_unit bigint; destinations bigint[]; selected_stage text:=p_stage; skipped boolean:=false;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation() NOT IN ('review_submit','review_decide') THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF j.job_type<>'destruction' OR j.lifecycle_state<>'active' THEN RAISE EXCEPTION 'disposition_inactive_job'; END IF;
 IF j.review_route='records_manager_only' THEN RAISE EXCEPTION 'disposition_combined_approval_required'; END IF;
 IF p_stage='file_administrator_review' THEN
  IF j.review_route<>'standard' THEN RAISE EXCEPTION 'disposition_saved_route_mismatch'; END IF;
  WITH RECURSIVE chain AS (
   SELECT id,parent_org_unit_id,file_administrator_role_id,0 depth FROM org_units WHERE id=j.owning_org_unit_id
   UNION ALL SELECT p.id,p.parent_org_unit_id,p.file_administrator_role_id,c.depth+1 FROM org_units p JOIN chain c ON p.id=c.parent_org_unit_id)
  SELECT file_administrator_role_id,id INTO role_id,source_unit FROM chain WHERE file_administrator_role_id IS NOT NULL ORDER BY depth LIMIT 1;
  IF role_id IS NULL THEN selected_stage:='unit_manager_review';skipped:=true; END IF;
 END IF;
 IF selected_stage='unit_manager_review' THEN
  IF j.review_route<>'standard' THEN RAISE EXCEPTION 'disposition_saved_route_mismatch'; END IF;
  SELECT managing_role_id,id INTO role_id,source_unit FROM org_units WHERE id=j.owning_org_unit_id;
 END IF;
 IF selected_stage IN ('file_administrator_review','unit_manager_review') THEN destinations:=ARRAY[role_id];
 ELSIF selected_stage='records_manager_review' THEN
  SELECT array_agg(r.id ORDER BY r.id) INTO destinations FROM roles r WHERE disposition_private.review_role(p_job,selected_stage,r.id)
   AND EXISTS(SELECT 1 FROM users u WHERE disposition_private.person_role(u.id,r.id) AND disposition_private.can_review_content(u.id,p_job));
 ELSE RAISE EXCEPTION 'disposition_review_stage_invalid'; END IF;
 IF destinations IS NULL OR cardinality(destinations)=0 THEN RAISE EXCEPTION 'disposition_reviewer_unavailable'; END IF;
 FOREACH role_id IN ARRAY destinations LOOP
  IF role_id IS NULL OR NOT EXISTS(SELECT 1 FROM users u WHERE disposition_private.person_role(u.id,role_id) AND disposition_private.can_review_content(u.id,p_job))
  THEN RAISE EXCEPTION 'disposition_reviewer_unavailable'; END IF;
 END LOOP;
 -- All resolution checks precede writes; configured-but-unusable never falls back.
 UPDATE disposition_tasks SET task_state='cancelled' WHERE job_id=p_job AND task_state IN ('open','claimed');
 UPDATE disposition_jobs SET workflow_stage=selected_stage WHERE id=p_job;
 FOREACH role_id IN ARRAY destinations LOOP
  INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,review_round,destination_role_id,routing_org_unit_id)
  VALUES(p_job,selected_stage,selected_stage,j.current_review_round,role_id,source_unit);
 END LOOP;
 PERFORM append_domain_event('disposition_job',p_job,'TASK_ROUTED',jsonb_build_object('review_route',j.review_route,'workflow_stage',selected_stage,'routing_org_unit_id',source_unit,'role_ids',destinations,'file_administrator_skipped',skipped,'skip_reason',CASE WHEN skipped THEN 'not_configured' END));
 RETURN jsonb_build_object('workflow_stage',selected_stage,'file_administrator_skipped',skipped,'routing_org_unit_id',source_unit);
END $$;
CREATE FUNCTION disposition_private.start_review(p_job bigint,p_version integer) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE j disposition_jobs%ROWTYPE; result jsonb;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'review_submit' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF NOT FOUND OR j.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 PERFORM disposition_private.require_membership_stage(p_job);
 PERFORM disposition_private.require_preparer(current_user_id(),j.review_route);
 IF j.review_route='records_manager_only' THEN RAISE EXCEPTION 'disposition_combined_approval_required'; END IF;
 IF NOT EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active') THEN RAISE EXCEPTION 'disposition_empty_job'; END IF;
 PERFORM disposition_private.require_progress(p_job);
 PERFORM disposition_private.require_job_access(p_job);
 IF NOT disposition_private.can_review_content(current_user_id(),p_job) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 INSERT INTO disposition_review_rounds(job_id,round_number,started_by_user_id,membership_snapshot)
 VALUES(p_job,j.current_review_round+1,current_user_id(),disposition_private.membership_snapshot(p_job));
 result:=disposition_private.route_review(p_job,CASE WHEN j.review_route='standard' THEN 'file_administrator_review' ELSE 'records_manager_review' END);
 RETURN result||jsonb_build_object('review_round',j.current_review_round+1);
END $$;
CREATE FUNCTION disposition_private.start_manager_round(p_job bigint,p_version integer) RETURNS integer LANGUAGE plpgsql AS $$
DECLARE j disposition_jobs%ROWTYPE; acting bigint;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'review_decide' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF NOT FOUND OR j.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 IF j.review_route<>'records_manager_only' THEN RAISE EXCEPTION 'disposition_saved_route_mismatch'; END IF;
 PERFORM disposition_private.require_membership_stage(p_job);
 SELECT r.acting_role_id INTO acting FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 IF NOT disposition_private.review_role(p_job,'records_manager_review',acting) OR NOT disposition_private.person_role(current_user_id(),acting)
 THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_manager_role_required'; END IF;
 PERFORM disposition_private.require_progress(p_job);
 IF NOT disposition_private.can_review_content(current_user_id(),p_job) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 IF NOT EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active') THEN RAISE EXCEPTION 'disposition_empty_job'; END IF;
 INSERT INTO disposition_review_rounds(job_id,round_number,started_by_user_id,membership_snapshot)
 VALUES(p_job,j.current_review_round+1,current_user_id(),disposition_private.membership_snapshot(p_job));
 RETURN j.current_review_round+1;
END $$;

CREATE FUNCTION disposition_private.route_correction(p_job bigint) RETURNS void LANGUAGE plpgsql AS $$
DECLARE j disposition_jobs%ROWTYPE;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'review_decide' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 PERFORM disposition_private.require_preparer(j.assigned_user_id,j.review_route);
 IF NOT disposition_private.can_review_content(j.assigned_user_id,p_job) THEN RAISE EXCEPTION 'disposition_assignee_access_required'; END IF;
 UPDATE disposition_tasks SET task_state='cancelled' WHERE job_id=p_job AND task_state IN ('open','claimed');
 UPDATE disposition_review_rounds SET completed_at=CURRENT_TIMESTAMP WHERE job_id=p_job AND round_number=j.current_review_round AND completed_at IS NULL AND invalidated_at IS NULL;
 UPDATE disposition_jobs SET workflow_stage=CASE WHEN j.review_route='records_manager_only' THEN 'manager_correction' ELSE 'officer_correction' END WHERE id=p_job RETURNING * INTO j;
 INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,review_round,destination_user_id)
 VALUES(p_job,'correction',j.workflow_stage,j.current_review_round,j.assigned_user_id);
END $$;

-- Bounded worker operation only releases an actually ineligible claimant; it
-- cannot assign, decide, change saved work, or grant resource access.
CREATE FUNCTION disposition_private.reconcile_task(p_task bigint,p_command uuid) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE t disposition_tasks%ROWTYPE; result jsonb;
BEGIN
 IF current_setting('app.actor_type',true) IS DISTINCT FROM 'automated_process' OR current_user_id() IS NOT NULL THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_worker_required'; END IF;
 PERFORM pg_advisory_xact_lock(7357,1);
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task FOR UPDATE;
 IF NOT FOUND OR t.task_state<>'claimed' OR t.destination_role_id IS NULL OR disposition_private.task_eligible(t.claimed_by_user_id,t.id,t.destination_role_id) THEN RETURN jsonb_build_object('changed',false); END IF;
 IF EXISTS(SELECT 1 FROM disposition_private.command_context WHERE transaction_id=txid_current()) THEN RAISE EXCEPTION 'disposition_nested_command'; END IF;
 INSERT INTO disposition_private.command_receipts(command_id,actor_type,operation,payload,reason)
 VALUES(p_command,'automated_process','task_release',jsonb_build_object('task_id',p_task),'Claimant no longer eligible');
 INSERT INTO disposition_private.command_context VALUES(txid_current(),pg_backend_pid(),p_command);
 PERFORM set_config('app.change_reason','Claimant no longer eligible',true);
 UPDATE disposition_tasks SET task_state='open' WHERE id=p_task;
 result:=jsonb_build_object('changed',true,'task_id',p_task);
 PERFORM disposition_private.finish_command(result);
 RETURN result;
END $$;


ALTER TABLE disposition_tasks DISABLE TRIGGER disposition_guard;
ALTER TABLE disposition_tasks DISABLE TRIGGER disposition_audit;
DO $$
DECLARE t disposition_tasks%ROWTYPE;
BEGIN
 FOR t IN INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,review_round,destination_user_id)
  SELECT j.id,CASE WHEN j.workflow_stage LIKE '%correction' THEN 'correction' ELSE 'preparation' END,j.workflow_stage,NULLIF(j.current_review_round,0),j.assigned_user_id
  FROM disposition_jobs j WHERE j.job_type='destruction' AND j.lifecycle_state='active' AND j.assigned_user_id IS NOT NULL
  AND j.workflow_stage IN ('officer_preparation','officer_correction')
  AND NOT EXISTS(SELECT 1 FROM disposition_tasks x WHERE x.job_id=j.id AND x.task_state IN ('open','claimed')) RETURNING *
 LOOP
  PERFORM append_domain_event('disposition_task',t.id,'TASK_ROUTED',jsonb_build_object('after',to_jsonb(t),'review_route','standard','migration','058_disposition_routing'));
 END LOOP;
END $$;
ALTER TABLE disposition_tasks ENABLE TRIGGER disposition_guard;
ALTER TABLE disposition_tasks ENABLE TRIGGER disposition_audit;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA disposition_private FROM PUBLIC;
INSERT INTO schema_migrations(version) VALUES('058_disposition_routing');
COMMIT;
