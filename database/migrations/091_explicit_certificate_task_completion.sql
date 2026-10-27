BEGIN;
DROP FUNCTION IF EXISTS disposition_private.finish_certificate_download(bigint,bigint);
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
  INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,review_round,destination_user_id) VALUES(p_job,'certificate_download','certificate_generation',j.current_review_round,current_user_id()) RETURNING id INTO download_id;
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

CREATE OR REPLACE FUNCTION disposition_private.complete_certificate_task(p_job bigint,p_task bigint,p_version bigint) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE t disposition_tasks%ROWTYPE;j disposition_jobs%ROWTYPE;acting bigint;doc bigint;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'final_complete' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT acting_role_id INTO acting FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 SELECT * INTO t FROM disposition_tasks WHERE id=p_task AND job_id=p_job AND task_type='certificate_download' FOR UPDATE;
 IF t.id IS NULL OR t.task_state NOT IN ('open','claimed') THEN RAISE EXCEPTION 'disposition_certificate_task_unavailable'; END IF;
 IF t.version<>p_version THEN RAISE EXCEPTION 'disposition_stale_task'; END IF;
 PERFORM disposition_private.require_task_actor(t.id,acting,true);
 SELECT id INTO doc FROM disposition_job_documents WHERE job_id=p_job AND document_type='digital_destruction_certificate' AND document_state='available';
 IF doc IS NULL THEN RAISE EXCEPTION 'disposition_certificate_required'; END IF;
 IF j.lifecycle_state='completed' THEN
  INSERT INTO disposition_private.completion_context VALUES(txid_current(),pg_backend_pid(),(SELECT command_id FROM disposition_private.command_context WHERE transaction_id=txid_current()),p_job);
  PERFORM append_domain_event('disposition_job',p_job,'CERTIFICATE_TASK_COMPLETED',jsonb_build_object('task_id',t.id,'certificate_document_id',doc));
  UPDATE disposition_tasks SET task_state='completed' WHERE id=t.id;
  DELETE FROM disposition_private.completion_context WHERE transaction_id=txid_current();
  RETURN jsonb_build_object('job_id',p_job,'task_id',t.id,'lifecycle_state','completed');
 END IF;
 RETURN disposition_private.finish_destruction_job(p_job,doc);
END $$;
REVOKE ALL ON FUNCTION disposition_private.complete_certificate_task(bigint,bigint,bigint) FROM PUBLIC;

DO $$ DECLARE definition text; BEGIN
 definition:=pg_get_functiondef('disposition_private.guard_workflow()'::regprocedure);
 definition:=replace(definition,$old$operation='DIGITAL_CERTIFICATE_DOWNLOADED' AND metadata$old$,$new$operation IN ('DIGITAL_CERTIFICATE_DOWNLOADED','CERTIFICATE_TASK_COMPLETED') AND metadata$new$);
 definition:=replace(definition,$old$(TG_OP='UPDATE' AND op='task_complete')$old$,$new$(TG_OP='UPDATE' AND (op='task_complete' OR op='final_complete' AND disposition_private.completion_active(job.id)))$new$);
 definition:=replace(definition,$old$IF EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=NEW.id AND membership_state='active') OR NOT EXISTS(SELECT 1 FROM disposition_retained_records WHERE job_id=NEW.id) THEN RAISE EXCEPTION 'disposition_completion_unfinished'; END IF;$old$,$new$IF EXISTS(SELECT 1 FROM disposition_tasks WHERE job_id=NEW.id AND task_state IN ('open','claimed')) OR EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=NEW.id AND membership_state='active') OR NOT EXISTS(SELECT 1 FROM disposition_retained_records WHERE job_id=NEW.id) THEN RAISE EXCEPTION 'disposition_completion_unfinished'; END IF;$new$);
 EXECUTE definition;
END $$;
-- Repair the earlier premature completion marker, without changing destruction
-- proof, issued certificate bytes, tasks, or immutable historical events.
-- ALTER TABLE takes an exclusive lock; the guards are restored before commit.
SELECT set_config('app.user_id','',true),set_config('app.actor_type','automated_process',true),
 set_config('app.actor_name','Certificate task completion migration',true),
 set_config('app.event_source','migration',true),
 set_config('app.change_reason','Keep destruction jobs active until their final certificate task is completed',true);
DO $$ DECLARE old_job disposition_jobs%ROWTYPE; BEGIN
 IF EXISTS(SELECT 1 FROM disposition_jobs j JOIN disposition_tasks t ON t.job_id=j.id
  WHERE j.lifecycle_state='completed' AND j.job_type='destruction' AND j.workflow_stage='certificate_generation'
  AND t.task_type='certificate_download' AND t.task_state IN ('open','claimed')) THEN
  ALTER TABLE disposition_jobs DISABLE TRIGGER disposition_guard;
  ALTER TABLE disposition_jobs DISABLE TRIGGER disposition_audit;
  ALTER TABLE disposition_jobs DISABLE TRIGGER disposition_preserve_physical;
  FOR old_job IN SELECT j.* FROM disposition_jobs j WHERE j.lifecycle_state='completed'
   AND j.job_type='destruction' AND j.workflow_stage='certificate_generation'
   AND EXISTS(SELECT 1 FROM disposition_tasks t WHERE t.job_id=j.id AND t.task_type='certificate_download' AND t.task_state IN ('open','claimed')) FOR UPDATE LOOP
   UPDATE disposition_jobs SET lifecycle_state='active',disposition_status=6,
    completed_at=NULL,completed_by_user_id=NULL,completed_by_name=NULL,final_event_id=NULL,
    version=version+1,date_updated=clock_timestamp() WHERE id=old_job.id;
   PERFORM append_domain_event('disposition_job',old_job.id,'DISPOSITION_RECALCULATED',
    jsonb_build_object('previous_completion_event_id',old_job.final_event_id,'previous_completed_at',old_job.completed_at,
      'lifecycle_state','active','workflow_stage','certificate_generation'),
    'Certificate saved; final certificate task still requires explicit completion');
  END LOOP;
  SET CONSTRAINTS ALL IMMEDIATE;
  ALTER TABLE disposition_jobs ENABLE TRIGGER disposition_guard;
  ALTER TABLE disposition_jobs ENABLE TRIGGER disposition_audit;
  ALTER TABLE disposition_jobs ENABLE TRIGGER disposition_preserve_physical;
  SET CONSTRAINTS ALL DEFERRED;
 END IF;
END $$;
INSERT INTO schema_migrations(version) VALUES('091_explicit_certificate_task_completion') ON CONFLICT DO NOTHING;
COMMIT;
