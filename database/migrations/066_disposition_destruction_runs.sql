-- Durable digital execution, part 1 of Phase 21. Execution remains closed.
CREATE TABLE disposition_destruction_runs (
 id bigserial PRIMARY KEY,job_id bigint NOT NULL REFERENCES disposition_jobs(id) ON DELETE RESTRICT,
 request_id uuid NOT NULL UNIQUE,run_number integer NOT NULL CHECK(run_number>0),
 state text NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','running','succeeded','failed')),
 requested_by_user_id bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 requested_by_name text NOT NULL,acting_role_id bigint NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
 task_id bigint NOT NULL REFERENCES disposition_tasks(id) ON DELETE RESTRICT,
 requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),started_at timestamptz,finished_at timestamptz,
 total_units integer NOT NULL CHECK(total_units>0),completed_units integer NOT NULL DEFAULT 0 CHECK(completed_units>=0),
 failed_units integer NOT NULL DEFAULT 0 CHECK(failed_units>=0),last_error_code text,last_error_message text,
 version bigint NOT NULL DEFAULT 1 CHECK(version>0),
 UNIQUE(job_id,run_number),CHECK(completed_units+failed_units<=total_units),
 CHECK((last_error_code IS NULL)=(last_error_message IS NULL)),
 CHECK(last_error_message IS NULL OR length(last_error_message)<=200)
);
CREATE UNIQUE INDEX disposition_destruction_one_active ON disposition_destruction_runs(job_id) WHERE state IN ('queued','running');
CREATE INDEX disposition_destruction_claim ON disposition_destruction_runs(id) WHERE state IN ('queued','running');
CREATE TABLE disposition_destruction_run_units (
 id bigserial PRIMARY KEY,run_id bigint NOT NULL REFERENCES disposition_destruction_runs(id) ON DELETE RESTRICT,
 root_id bigint NOT NULL REFERENCES aggregations(id) ON DELETE RESTRICT,
 state text NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','running','succeeded','failed')),
 started_at timestamptz,finished_at timestamptz,attempt_count integer NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
 last_error_code text,last_error_message text,version bigint NOT NULL DEFAULT 1 CHECK(version>0),
 claim_token uuid,UNIQUE(run_id,root_id),CHECK((last_error_code IS NULL)=(last_error_message IS NULL))
);
CREATE INDEX disposition_destruction_units_claim ON disposition_destruction_run_units(run_id,state,id);
CREATE TABLE disposition_destruction_manifest_items (
 id bigserial PRIMARY KEY,job_id bigint NOT NULL REFERENCES disposition_jobs(id) ON DELETE RESTRICT,
 root_id bigint NOT NULL REFERENCES aggregations(id) ON DELETE RESTRICT,
 resource_kind text NOT NULL CHECK(resource_kind IN ('aggregation','record','component')),
 resource_id bigint NOT NULL,record_id bigint,source_component_id bigint,source_content_set_id bigint,
 checksum_algo text,checksum_value text,size_in_bytes bigint CHECK(size_in_bytes>=0),
 medium text NOT NULL CHECK(medium IN ('physical','digital','mixed')),
 destruction_state text NOT NULL DEFAULT 'queued' CHECK(destruction_state IN ('queued','succeeded')),
 destroyed_at timestamptz,run_id bigint NOT NULL REFERENCES disposition_destruction_runs(id) ON DELETE RESTRICT,
 CHECK((destruction_state='succeeded')=(destroyed_at IS NOT NULL)),
 CHECK((checksum_algo IS NULL)=(checksum_value IS NULL))
);
-- Component/content-set IDs are immutable snapshots, deliberately not FKs.
CREATE UNIQUE INDEX disposition_destruction_manifest_identity ON disposition_destruction_manifest_items(job_id,resource_kind,resource_id,coalesce(source_content_set_id,0));
CREATE INDEX disposition_destruction_manifest_root ON disposition_destruction_manifest_items(job_id,root_id,id);
CREATE TABLE disposition_private.destruction_context (
 transaction_id bigint PRIMARY KEY,backend_id integer NOT NULL,command_id uuid,
 run_id bigint,root_id bigint,claim_token uuid,mode text NOT NULL CHECK(mode IN ('request','claim','fail','delete','finalize'))
);
CREATE TABLE disposition_private.destruction_scopes (
 run_id bigint NOT NULL REFERENCES disposition_destruction_runs(id) ON DELETE RESTRICT,
 root_id bigint NOT NULL REFERENCES aggregations(id) ON DELETE RESTRICT,scope jsonb NOT NULL,
 PRIMARY KEY(run_id,root_id)
);
CREATE FUNCTION disposition_private.digital_execution_released() RETURNS boolean LANGUAGE sql IMMUTABLE AS $$ SELECT false $$;
CREATE FUNCTION disposition_private.destruction_active(p_mode text DEFAULT NULL,p_root bigint DEFAULT NULL) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_private.destruction_context d WHERE d.transaction_id=txid_current() AND d.backend_id=pg_backend_pid()
 AND (p_mode IS NULL OR d.mode=p_mode) AND (p_root IS NULL OR d.root_id=p_root)
 AND (d.command_id IS NULL OR EXISTS(SELECT 1 FROM disposition_private.command_context c WHERE c.transaction_id=d.transaction_id AND c.backend_id=d.backend_id AND c.command_id=d.command_id)))
$$;
CREATE FUNCTION disposition_private.destruction_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' OR NOT disposition_private.destruction_active() THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_destruction_command_required'; END IF;
 IF TG_OP='UPDATE' AND ((TG_TABLE_NAME IN ('disposition_destruction_runs','disposition_destruction_run_units') AND (to_jsonb(OLD)->>'state') IN ('succeeded','failed')) OR (TG_TABLE_NAME='disposition_destruction_manifest_items' AND (to_jsonb(OLD)->>'destruction_state')='succeeded')) THEN RAISE EXCEPTION 'disposition_destruction_history_immutable'; END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME IN ('disposition_destruction_runs','disposition_destruction_run_units') THEN NEW.version:=OLD.version+1; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER disposition_destruction_guard BEFORE INSERT OR UPDATE OR DELETE ON disposition_destruction_runs FOR EACH ROW EXECUTE FUNCTION disposition_private.destruction_guard();
CREATE TRIGGER disposition_destruction_guard BEFORE INSERT OR UPDATE OR DELETE ON disposition_destruction_run_units FOR EACH ROW EXECUTE FUNCTION disposition_private.destruction_guard();
CREATE TRIGGER disposition_destruction_guard BEFORE INSERT OR UPDATE OR DELETE ON disposition_destruction_manifest_items FOR EACH ROW EXECUTE FUNCTION disposition_private.destruction_guard();
CREATE FUNCTION disposition_private.destruction_scope(p_root bigint) RETURNS jsonb LANGUAGE sql STABLE SET timezone='UTC' AS $$
 SELECT jsonb_build_object(
 'aggregations',(SELECT coalesce(jsonb_agg(jsonb_build_array(a.id,a.version,a.parent_aggregation_id,a.classification_id,a.owning_org_unit_id,a.security_level_id,a.medium,a.date_closed,a.disposition_status) ORDER BY a.id),'[]') FROM aggregations a WHERE a.id IN (SELECT disposition_private.unit_ids(p_root))),
 'records',(SELECT coalesce(jsonb_agg(jsonb_build_array(r.id,r.version,r.aggregation_id,r.owning_org_unit_id,r.security_level_id,r.medium,r.disposition_status) ORDER BY r.id),'[]') FROM records r WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root))),
 'components',(SELECT coalesce(jsonb_agg(jsonb_build_array(d.id,d.version,d.record_id,d.active_content_set_id,d.checksum_algo,d.checksum_value,d.size_in_bytes,d.storage_backend) ORDER BY d.id),'[]') FROM digital_components d JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root))),
 'rule',(SELECT jsonb_build_object('due',e.calculated_disposition_at,'rule',e.rule_snapshot) FROM disposition_private.eligibility(p_root) e))
$$;
CREATE FUNCTION disposition_private.check_digital_job(p_job bigint,p_role bigint,p_initial boolean DEFAULT false) RETURNS void LANGUAGE plpgsql AS $$
DECLARE j disposition_jobs%ROWTYPE;root bigint;
BEGIN
 PERFORM pg_advisory_xact_lock(7357,1);
 PERFORM disposition_private.lock_request_facts(p_job);
 SELECT * INTO j FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 PERFORM disposition_private.require_actor(p_role);
 IF NOT disposition_private.review_role(p_job,'records_manager_review',p_role) OR NOT disposition_private.person_role(current_user_id(),p_role) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_manager_role_required'; END IF;
 PERFORM disposition_private.require_job_access(p_job);
 IF j.lifecycle_state IS DISTINCT FROM 'active' OR j.job_type<>'destruction' OR j.workflow_stage<>'digital_destruction' THEN RAISE EXCEPTION 'disposition_digital_stage_invalid'; END IF;
 PERFORM disposition_private.require_preparer(j.assigned_user_id,j.review_route);
 IF NOT EXISTS(SELECT 1 FROM disposition_external_approvals a JOIN disposition_review_rounds rr ON rr.id=a.round_id JOIN disposition_job_documents doc ON doc.id=a.approval_letter_document_id
 WHERE a.job_id=j.id AND a.decision='approved' AND rr.round_number=j.current_review_round AND rr.approval_execution IS NOT NULL AND rr.invalidated_at IS NULL
 AND a.destruction_number=j.destruction_number AND doc.document_state='available' AND current_user_can_view_record(doc.record_id) AND current_user_can_list_record_components(doc.record_id)) THEN RAISE EXCEPTION 'disposition_approval_invalidated'; END IF;
 IF p_initial AND NOT EXISTS(SELECT 1 FROM disposition_external_approvals a JOIN disposition_review_rounds rr ON rr.id=a.round_id WHERE a.job_id=j.id AND rr.round_number=j.current_review_round AND disposition_private.request_approval_current(j.id,rr.id)) THEN RAISE EXCEPTION 'disposition_approval_invalidated'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active' AND removal_required) THEN RAISE EXCEPTION 'disposition_removal_required'; END IF;
 FOR root IN SELECT root_aggregation_id FROM disposition_job_memberships WHERE job_id=p_job AND membership_state='active' ORDER BY root_aggregation_id LOOP
  PERFORM disposition_private.lock_current_blockers(root);
  IF NOT disposition_private.recovery_unit_visible(root) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
  IF EXISTS(SELECT 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(root)) AND (date_closed IS NULL AND id=root OR disposition_status<>6)) OR EXISTS(SELECT 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(root)) AND disposition_status<>6) THEN RAISE EXCEPTION 'disposition_digital_scope_changed'; END IF;
  IF EXISTS(SELECT 1 FROM disposition_private.protection_blockers(root)) OR EXISTS(SELECT 1 FROM disposition_private.relationship_scope(root) WHERE blocks_final) THEN
   IF disposition_private.physical_covered(p_job,root) THEN RAISE EXCEPTION 'disposition_physical_recovery_required'; END IF;
   RAISE EXCEPTION 'disposition_digital_blocked';
  END IF;
  IF EXISTS(SELECT 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(root)) AND medium IN ('physical','mixed') AND disposition_private.physical_item_remaining('aggregations',id)) OR EXISTS(SELECT 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(root)) AND medium IN ('physical','mixed') AND disposition_private.physical_item_remaining('records',id)) THEN RAISE EXCEPTION 'disposition_physical_confirmation_required'; END IF;
 END LOOP;
END $$;
CREATE FUNCTION disposition_private.request_digital(p_task bigint,p_job_version bigint,p_task_version bigint,p_confirm boolean) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE j disposition_jobs%ROWTYPE;t disposition_tasks%ROWTYPE;acting bigint;key uuid;previous disposition_destruction_runs%ROWTYPE;created bigint;root bigint;total integer;
BEGIN
 PERFORM disposition_private.require_command();
 IF NOT disposition_private.digital_execution_released() THEN RAISE EXCEPTION 'disposition_digital_release_pending'; END IF;
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
REVOKE ALL ON ALL TABLES IN SCHEMA disposition_private FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA disposition_private FROM PUBLIC;
INSERT INTO schema_migrations(version) VALUES('066_disposition_destruction_runs') ON CONFLICT DO NOTHING;
