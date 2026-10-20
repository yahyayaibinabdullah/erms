-- Remove temporary implementation release gates. Existing actor, permission,
-- stage, confirmation, approval, hold/security and private-command guards remain.
BEGIN;
CREATE OR REPLACE FUNCTION disposition_private.check_physical_work(p_task bigint,p_job_version integer,p_task_version integer,p_role bigint) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE j disposition_jobs%ROWTYPE;t disposition_tasks%ROWTYPE;root bigint;
BEGIN
 PERFORM pg_advisory_xact_lock(7357,1);
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task;
 PERFORM disposition_private.lock_request_facts(t.job_id);
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task FOR UPDATE;
 SELECT * INTO j FROM disposition_jobs WHERE id=t.job_id;
 PERFORM disposition_private.require_task_actor(t.id,p_role,true);
 IF NOT disposition_private.person_role(current_user_id(),p_role) OR NOT disposition_private.review_role(j.id,'records_manager_review',p_role) THEN RAISE EXCEPTION 'disposition_manager_role_required'; END IF;
 IF t.version IS DISTINCT FROM p_task_version OR j.version IS DISTINCT FROM p_job_version THEN RAISE EXCEPTION 'disposition_stale_task'; END IF;
 IF j.lifecycle_state<>'active' OR j.workflow_stage<>'physical_destruction' OR t.task_type<>'physical_destruction' OR EXISTS(SELECT 1 FROM disposition_physical_confirmations WHERE job_id=j.id) THEN RAISE EXCEPTION 'disposition_physical_stage_invalid'; END IF;
 IF NOT EXISTS(SELECT 1 FROM disposition_external_approvals a JOIN disposition_review_rounds r ON r.id=a.round_id WHERE a.job_id=j.id AND a.decision='approved' AND r.round_number=j.current_review_round AND disposition_private.request_approval_current(j.id,r.id)) THEN RAISE EXCEPTION 'disposition_approval_invalidated'; END IF;
 PERFORM disposition_private.require_progress(j.id);
 FOR root IN SELECT root_aggregation_id FROM disposition_job_memberships WHERE job_id=j.id AND membership_state='active' ORDER BY root_aggregation_id LOOP
  PERFORM disposition_private.lock_current_blockers(root);
  IF EXISTS(SELECT 1 FROM disposition_private.protection_blockers(root)) OR EXISTS(SELECT 1 FROM disposition_private.relationship_scope(root) WHERE blocks_final) THEN RAISE EXCEPTION 'disposition_physical_blocked'; END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.job_id=j.id AND d.document_type='physical_preparation_report' AND d.document_state='available') THEN RAISE EXCEPTION 'disposition_physical_report_required'; END IF;
 RETURN disposition_private.physical_scope(j.id);
END $$;

CREATE OR REPLACE FUNCTION disposition_private.guard_physical_confirmation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE acting bigint;key uuid;t disposition_tasks%ROWTYPE;doc disposition_job_documents%ROWTYPE;
BEGIN
 PERFORM disposition_private.require_command();
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'disposition_physical_immutable'; END IF;
 IF NOT disposition_private.physical_active(NEW.job_id) OR disposition_private.context_operation()<>'review_decide' THEN RAISE EXCEPTION 'disposition_physical_required'; END IF;
 SELECT acting_role_id,command_id INTO acting,key FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 SELECT * INTO t FROM disposition_tasks WHERE id=NEW.task_id;
 PERFORM disposition_private.check_physical_work(t.id,(SELECT version FROM disposition_jobs WHERE id=NEW.job_id),t.version,acting);
 SELECT * INTO doc FROM disposition_job_documents WHERE id=NEW.certificate_document_id;
 IF t.job_id IS DISTINCT FROM NEW.job_id OR doc.id IS NULL OR doc.job_id<>NEW.job_id OR doc.document_type<>'physical_destruction_certificate' OR doc.document_state<>'available' OR doc.created_by_user_id IS DISTINCT FROM current_user_id() OR doc.provenance->>'physical_command_id' IS DISTINCT FROM key::text OR doc.provenance->>'certificate_reference' IS DISTINCT FROM NEW.certificate_reference OR NOT current_user_can_view_record(doc.record_id) OR NOT current_user_can_list_record_components(doc.record_id) THEN RAISE EXCEPTION 'disposition_physical_certificate_required'; END IF;
 IF NEW.confirmed_by_user_id IS DISTINCT FROM current_user_id() OR NEW.acting_role_id IS DISTINCT FROM acting OR NEW.physical_scope IS DISTINCT FROM disposition_private.physical_scope(NEW.job_id) THEN RAISE EXCEPTION 'disposition_physical_scope_invalid'; END IF;
 NEW.confirmed_at:=CURRENT_TIMESTAMP;
 NEW.confirmation_version:=1;
 NEW.confirmation_text:='أؤكد إتمام الإتلاف الورقي بنجاح / I confirm that physical destruction was completed successfully.';
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION disposition_private.request_digital(p_task bigint,p_job_version bigint,p_task_version bigint,p_confirm boolean) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE j disposition_jobs%ROWTYPE;t disposition_tasks%ROWTYPE;acting bigint;key uuid;previous disposition_destruction_runs%ROWTYPE;created bigint;root bigint;total integer;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'final_complete' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT acting_role_id,command_id INTO acting,key FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task FOR UPDATE;
 SELECT * INTO j FROM disposition_jobs WHERE id=t.job_id FOR UPDATE;
 PERFORM disposition_private.require_task_actor(t.id,acting,true);
 IF t.task_type<>'digital_destruction' OR t.version IS DISTINCT FROM p_task_version OR j.version IS DISTINCT FROM p_job_version THEN RAISE EXCEPTION 'disposition_stale_task'; END IF;
 IF p_confirm IS DISTINCT FROM true THEN RAISE EXCEPTION 'disposition_digital_confirmation_required'; END IF;
 SELECT * INTO previous FROM disposition_destruction_runs WHERE job_id=j.id ORDER BY run_number DESC LIMIT 1;
 IF previous.state IN ('queued','running') THEN RAISE EXCEPTION 'disposition_digital_already_running'; END IF;
 IF previous.state='succeeded' THEN RAISE EXCEPTION 'disposition_digital_already_succeeded'; END IF;
 IF previous.last_error_code='disposition_physical_recovery_required' THEN RAISE EXCEPTION 'disposition_physical_recovery_required'; END IF;
 PERFORM disposition_private.check_digital_job(j.id,acting,true);
 SELECT count(*) INTO total FROM disposition_job_memberships WHERE job_id=j.id AND membership_state='active';
 IF total=0 THEN RAISE EXCEPTION 'disposition_digital_already_succeeded'; END IF;
 INSERT INTO disposition_private.destruction_context VALUES(txid_current(),pg_backend_pid(),key,NULL,NULL,NULL,'request');
 INSERT INTO disposition_destruction_runs(job_id,request_id,run_number,requested_by_user_id,requested_by_name,acting_role_id,task_id,total_units)
 VALUES(j.id,key,coalesce(previous.run_number,0)+1,current_user_id(),(SELECT name FROM users WHERE id=current_user_id()),acting,t.id,total) RETURNING id INTO created;
 UPDATE disposition_private.destruction_context SET run_id=created WHERE transaction_id=txid_current();
 FOR root IN SELECT root_aggregation_id FROM disposition_job_memberships WHERE job_id=j.id AND membership_state='active' ORDER BY root_aggregation_id LOOP
  INSERT INTO disposition_destruction_run_units(run_id,root_id) VALUES(created,root);
  INSERT INTO disposition_private.destruction_scopes VALUES(created,root,disposition_private.destruction_scope(root));
 END LOOP;
 PERFORM append_domain_event('disposition_job',j.id,'DIGITAL_DESTRUCTION_REQUESTED',jsonb_build_object('run_id',created,'command_id',key,'total_units',total,'confirmed',true,'confirmation_version',1,'confirmation_text','أؤكد أن على وثق إتلاف المحتوى الرقمي / I confirm that Wathiq should destroy the digital content'));
 DELETE FROM disposition_private.destruction_context WHERE transaction_id=txid_current();
 RETURN jsonb_build_object('run_id',created,'job_id',j.id,'state','queued','total_units',total);
END $$;

CREATE OR REPLACE FUNCTION disposition_private.finish_digital_unit(p_run bigint,p_root bigint,p_token uuid) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE run disposition_destruction_runs%ROWTYPE;at_time timestamptz:=clock_timestamp();key uuid;event_id bigint;name text;finished boolean;physical disposition_physical_confirmations%ROWTYPE;proof_at timestamptz;proof_user bigint;
BEGIN
 PERFORM disposition_private.require_command();
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

CREATE OR REPLACE FUNCTION disposition_private.finish_destruction_job(p_job bigint,p_document bigint DEFAULT NULL) RETURNS jsonb LANGUAGE plpgsql AS $$
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
  SELECT task_id INTO download_id FROM disposition_private.completion_work WHERE job_id=p_job AND state='running' AND requested_by_user_id=current_user_id() AND acting_role_id=acting;
  PERFORM disposition_private.check_completion(p_job,download_id,acting);
  IF NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.id=p_document AND d.job_id=p_job AND d.document_type='digital_destruction_certificate' AND d.document_state='available' AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id) AND d.provenance->>'completion_request_id'=(SELECT request_id::text FROM disposition_private.completion_work WHERE job_id=p_job)) THEN RAISE EXCEPTION 'disposition_certificate_required'; END IF;
 ELSE
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

DROP FUNCTION IF EXISTS disposition_private.physical_execution_released();
DROP FUNCTION IF EXISTS disposition_private.digital_execution_released();
INSERT INTO schema_migrations(version) VALUES('071_remove_destruction_release_gates') ON CONFLICT DO NOTHING;
COMMIT;
