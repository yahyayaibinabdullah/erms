-- Termination and partial-disposition recovery (065).
-- This migration does not open physical/digital execution or job completion.
CREATE TABLE disposition_private.recovery_context (
 transaction_id bigint NOT NULL,backend_id integer NOT NULL,command_id uuid NOT NULL,
 job_id bigint NOT NULL,root_id bigint NOT NULL DEFAULT 0,target_status integer,
 PRIMARY KEY(transaction_id,root_id)
);
CREATE FUNCTION disposition_private.recovery_active(p_job bigint DEFAULT NULL,p_root bigint DEFAULT 0,p_status integer DEFAULT NULL) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_private.recovery_context r JOIN disposition_private.command_context c USING(transaction_id,backend_id,command_id)
 WHERE r.transaction_id=txid_current() AND r.backend_id=pg_backend_pid() AND (p_job IS NULL OR r.job_id=p_job) AND r.root_id=p_root AND (p_status IS NULL OR r.target_status=p_status))
$$;
CREATE FUNCTION disposition_private.physical_covered(p_job bigint,p_root bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_physical_confirmations p WHERE p.job_id=p_job AND (
 EXISTS(SELECT 1 FROM jsonb_array_elements(p.physical_scope->'aggregations') x WHERE (x->>'root_id')::bigint=p_root) OR
 EXISTS(SELECT 1 FROM jsonb_array_elements(p.physical_scope->'records') x WHERE (x->>'root_id')::bigint=p_root)))
$$;
CREATE FUNCTION disposition_private.unit_has_digital(p_root bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(p_root)) AND medium IN ('digital','mixed')) OR
 EXISTS(SELECT 1 FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) AND medium IN ('digital','mixed'))
$$;
CREATE FUNCTION disposition_private.recovery_unit_visible(p_root bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT current_user_can_view_aggregation(p_root) AND NOT EXISTS(SELECT 1 FROM disposition_private.unit_ids(p_root) u(id)
 WHERE NOT current_user_can_view_aggregation(u.id) OR EXISTS(SELECT 1 FROM records r WHERE r.aggregation_id=u.id AND NOT current_user_can_view_record(r.id)))
$$;
CREATE FUNCTION disposition_private.recovery_roots(p_job bigint) RETURNS TABLE(root_id bigint,root_version bigint) LANGUAGE sql STABLE AS $$
 SELECT a.id,a.version FROM disposition_job_memberships m JOIN aggregations a ON a.id=m.root_aggregation_id JOIN disposition_jobs j ON j.id=m.job_id
 WHERE j.id=p_job AND j.lifecycle_state='terminated' AND m.membership_state='terminated_history' AND a.disposition_status=13
 AND m.id=(SELECT max(h.id) FROM disposition_job_memberships h WHERE h.root_aggregation_id=a.id AND h.membership_state='terminated_history')
$$;
CREATE FUNCTION disposition_private.recovery_preview(p_job bigint) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
BEGIN
 IF NOT disposition_private.can_manage() THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_authorization_required'; END IF;
 PERFORM disposition_private.require_job_access(p_job);
 IF NOT EXISTS(SELECT 1 FROM disposition_jobs WHERE id=p_job AND lifecycle_state='terminated') THEN RAISE EXCEPTION 'disposition_recovery_job_required'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_private.recovery_roots(p_job) r WHERE NOT disposition_private.recovery_unit_visible(r.root_id)) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_recovery_access_required'; END IF;
 RETURN (SELECT jsonb_build_object('affected_count',count(*),'scope_token',md5(coalesce(jsonb_agg(jsonb_build_array(root_id,root_version) ORDER BY root_id),'[]')::text)) FROM disposition_private.recovery_roots(p_job));
END $$;
CREATE FUNCTION disposition_private.recovery_facts(p_job bigint,p_root bigint) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('recovery_job_id',p_job,'root_id',p_root,
 'physical_confirmation_id',p.id,'certificate_document_id',p.certificate_document_id,'certificate_reference',p.certificate_reference,
 'preserved_digital_material',coalesce((SELECT jsonb_agg(jsonb_build_object('record_id',d.record_id,'component_id',d.id,'content_set_id',d.active_content_set_id) ORDER BY d.id)
 FROM digital_components d JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root))),'[]'))
 FROM disposition_physical_confirmations p WHERE p.job_id=p_job
$$;
CREATE OR REPLACE FUNCTION disposition_private.preserve_physical_outcome() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM disposition_physical_confirmations WHERE job_id=OLD.id) AND NOT disposition_private.physical_active(OLD.id) AND
 NOT (disposition_private.context_operation()='job_terminate' AND disposition_private.recovery_active(OLD.id)) AND
 (NEW.lifecycle_state IS DISTINCT FROM OLD.lifecycle_state OR NEW.workflow_stage IS DISTINCT FROM OLD.workflow_stage OR NEW.disposition_status IS DISTINCT FROM OLD.disposition_status OR NEW.assigned_user_id IS DISTINCT FROM OLD.assigned_user_id) THEN RAISE EXCEPTION 'disposition_physical_recovery_required'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION disposition_private.guard_recovery_resource() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE root bigint;data jsonb;old_data jsonb;target integer;
BEGIN
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
CREATE TRIGGER a_disposition_recovery_guard BEFORE UPDATE ON aggregations FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_recovery_resource();
CREATE TRIGGER a_disposition_recovery_guard BEFORE UPDATE ON records FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_recovery_resource();

CREATE OR REPLACE FUNCTION disposition_private.allowed_transition(old_status integer,new_status integer,cause text) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT old_status=new_status OR CASE cause
 WHEN 'eligibility_evaluate' THEN old_status=1 AND new_status BETWEEN 2 AND 5
 WHEN 'eligibility_accelerate' THEN old_status=1 AND new_status BETWEEN 2 AND 5
 WHEN 'membership_add' THEN (old_status,new_status) IN ((2,6),(3,7),(4,8),(5,9))
 WHEN 'membership_remove' THEN (old_status,new_status) IN ((6,2),(7,3),(8,4),(9,5))
 WHEN 'job_terminate' THEN (old_status,new_status) IN ((6,2),(7,3),(8,4),(9,5),(6,13),(6,10))
 WHEN 'resolve_partial' THEN old_status=13 AND new_status BETWEEN 2 AND 5
 WHEN 'selective_decide' THEN old_status=8 AND new_status IN (2,3,5)
 WHEN 'final_complete' THEN (old_status,new_status) IN ((6,10),(7,11),(9,12))
 WHEN 'recalculate' THEN old_status NOT IN (10,11,12,13) AND new_status BETWEEN 1 AND 9
 ELSE false END
$$;
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
  UPDATE aggregations SET disposition_status=10,final_disposition_at=physical.confirmed_at,final_disposition_by_user_id=physical.confirmed_by_user_id,disposition_job_id=recovery_job,destruction_number=(SELECT destruction_number FROM disposition_jobs WHERE id=recovery_job),final_disposition_event_id=event_id WHERE id IN (SELECT disposition_private.unit_ids(p_root));
  UPDATE records SET disposition_status=10,final_disposition_at=physical.confirmed_at,final_disposition_by_user_id=physical.confirmed_by_user_id,disposition_job_id=recovery_job,destruction_number=(SELECT destruction_number FROM disposition_jobs WHERE id=recovery_job),final_disposition_event_id=event_id WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root));
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
CREATE OR REPLACE FUNCTION disposition_private.capture_recalculation(p_root bigint,p_cause text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE previous jsonb; status smallint;
BEGIN
 IF EXISTS(SELECT 1 FROM disposition_job_memberships m JOIN disposition_jobs j ON j.id=m.job_id WHERE m.root_aggregation_id=p_root AND m.membership_state='active' AND j.lifecycle_state='active' AND disposition_private.physical_covered(j.id,p_root)) THEN RAISE EXCEPTION 'disposition_physical_recovery_required'; END IF;
 SELECT disposition_status INTO status FROM aggregations WHERE id=p_root AND parent_aggregation_id IS NULL;
 IF status NOT BETWEEN 1 AND 9 OR status IS NULL THEN RETURN; END IF;
 BEGIN
  SELECT to_jsonb(e) INTO previous FROM disposition_private.eligibility(p_root) e;
 EXCEPTION WHEN datetime_field_overflow OR numeric_value_out_of_range THEN
  -- A pre-055 policy may contain an unrepresentable due date. Preserve its
  -- rule/provenance and explicit calculation failure so an authorized repair
  -- can succeed. A new invalid result still fails the entire policy change.
  SELECT jsonb_build_object('root_id',a.id,'date_closed',a.date_closed,'database_now',CURRENT_TIMESTAMP,
   'calculated_disposition_at',NULL,'calculation_error','unrepresentable_due_timestamp',
   'rule_snapshot',to_jsonb(rule)||jsonb_build_object('definition',CASE rule.rule_source
    WHEN 'aggregation' THEN (SELECT to_jsonb(r) FROM aggregation_retention_rules r WHERE r.id=rule.rule_id)
    ELSE (SELECT to_jsonb(r) FROM classification_retention_rules r WHERE r.id=rule.rule_id) END))
  INTO previous FROM aggregations a CROSS JOIN LATERAL aggregation_effective_retention_rule(a.id) rule WHERE a.id=p_root;
 END;
 INSERT INTO disposition_private.recalculation_context(transaction_id,backend_id,root_id,old_evaluation,old_status,cause)
 VALUES(txid_current(),pg_backend_pid(),p_root,previous,status,p_cause) ON CONFLICT DO NOTHING;
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
 RETURN to_jsonb(job);
END $$;
CREATE FUNCTION disposition_private.resolve_partial(p_job bigint,p_root bigint,p_root_version bigint,p_status integer,p_confirm boolean,p_count integer,p_token text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE job disposition_jobs%ROWTYPE;member record;acting bigint;key uuid;preview jsonb;counted integer:=0;facts jsonb;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'resolve_partial' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 SELECT acting_role_id,command_id INTO acting,key FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 PERFORM disposition_private.require_actor(acting);
 IF p_status IS NULL OR p_status NOT BETWEEN 2 AND 5 THEN RAISE EXCEPTION 'disposition_recovery_status_invalid'; END IF;
 SELECT * INTO job FROM disposition_jobs WHERE id=p_job FOR UPDATE;
 IF job.lifecycle_state IS DISTINCT FROM 'terminated' THEN RAISE EXCEPTION 'disposition_recovery_job_required'; END IF;
 PERFORM disposition_private.require_job_access(p_job);
 PERFORM 1 FROM aggregations WHERE id IN (SELECT root_id FROM disposition_private.recovery_roots(p_job)) ORDER BY id FOR UPDATE;
 IF p_root IS NULL THEN
  preview:=disposition_private.recovery_preview(p_job);
  IF p_confirm IS DISTINCT FROM true THEN RAISE EXCEPTION 'disposition_confirmation_required'; END IF;
  IF p_token IS DISTINCT FROM preview->>'scope_token' OR p_count IS DISTINCT FROM (preview->>'affected_count')::integer THEN RAISE EXCEPTION 'disposition_recovery_stale'; END IF;
 END IF;
 FOR member IN SELECT * FROM disposition_private.recovery_roots(p_job) WHERE p_root IS NULL OR root_id=p_root ORDER BY root_id LOOP
  PERFORM disposition_private.lock_current_blockers(member.root_id);
  IF NOT disposition_private.recovery_unit_visible(member.root_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_recovery_access_required'; END IF;
  IF p_root IS NOT NULL AND member.root_version IS DISTINCT FROM p_root_version THEN RAISE EXCEPTION 'disposition_recovery_stale'; END IF;
  IF NOT disposition_private.physical_covered(p_job,member.root_id) THEN RAISE EXCEPTION 'disposition_recovery_scope_invalid'; END IF;
  INSERT INTO disposition_private.recovery_context VALUES(txid_current(),pg_backend_pid(),key,p_job,member.root_id,p_status);
  facts:=disposition_private.recovery_facts(p_job,member.root_id)||jsonb_build_object('command_id',key,'old_status',13,'new_status',p_status,'bulk',p_root IS NULL);
  PERFORM disposition_private.transition_unit(member.root_id,member.root_version,p_status);
  PERFORM append_domain_event('aggregation',member.root_id,'DISPOSITION_PARTIAL_RESOLVED',facts);
  counted:=counted+1;
 END LOOP;
 IF counted=0 THEN RAISE EXCEPTION 'disposition_recovery_empty'; END IF;
 PERFORM append_domain_event('disposition_job',p_job,CASE WHEN p_root IS NULL THEN 'DISPOSITION_PARTIAL_BULK_RESOLVED' ELSE 'DISPOSITION_PARTIAL_RESOLVED' END,jsonb_build_object('recovery_job_id',p_job,'command_id',key,'affected_count',counted,'old_status',13,'new_status',p_status,'root_id',p_root,'certificate_document_id',(SELECT certificate_document_id FROM disposition_physical_confirmations WHERE job_id=p_job)));
 DELETE FROM disposition_private.recovery_context WHERE transaction_id=txid_current();
 RETURN jsonb_build_object('job_id',p_job,'affected_count',counted,'new_status',p_status,'command_id',key);
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
     AND a.membership_state='active' AND b.membership_state='active') same_job FROM links l)
 SELECT kind,id,relationship_type_id,source_id,target_id,source_root,target_root,internal,same_job,NOT(internal OR same_job OR EXISTS(SELECT 1 FROM disposition_job_memberships a JOIN disposition_job_memberships b ON b.job_id=a.job_id JOIN disposition_jobs j ON j.id=a.job_id JOIN aggregations sa ON sa.id=a.root_aggregation_id JOIN aggregations ta ON ta.id=b.root_aggregation_id WHERE j.lifecycle_state='terminated' AND a.root_aggregation_id=source_root AND b.root_aggregation_id=target_root AND a.membership_state IN ('terminated_history','completed_history') AND b.membership_state IN ('terminated_history','completed_history') AND (sa.disposition_status=10 OR ta.disposition_status=10) AND EXISTS(SELECT 1 FROM event_history e WHERE e.entity_type='disposition_job' AND e.entity_id=j.id AND e.operation='DISPOSITION_TERMINATION_OUTCOMES' AND e.metadata->'retained_relationships' @> jsonb_build_array(jsonb_build_array(scoped.kind,scoped.id))))) FROM scoped
$$;
REVOKE ALL ON ALL TABLES IN SCHEMA disposition_private FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA disposition_private FROM PUBLIC;

CREATE INDEX disposition_physical_scope_lookup ON disposition_physical_confirmations USING gin(physical_scope jsonb_path_ops);
CREATE FUNCTION disposition_private.physical_item_remaining(p_kind text,p_id bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT NOT EXISTS(SELECT 1 FROM disposition_physical_confirmations WHERE physical_scope @> jsonb_build_object(p_kind,jsonb_build_array(jsonb_build_object('id',p_id))))
$$;

CREATE OR REPLACE FUNCTION disposition_private.physical_scope(p_job bigint) RETURNS jsonb LANGUAGE sql STABLE AS $$
 WITH units AS (SELECT m.root_aggregation_id,unit.id FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.unit_ids(m.root_aggregation_id) unit(id) WHERE m.job_id=p_job AND m.membership_state='active')
 SELECT jsonb_build_object('aggregations',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',a.id,'root_id',u.root_aggregation_id,'medium',a.medium) ORDER BY a.id),'[]') FROM units u JOIN aggregations a ON a.id=u.id WHERE a.medium IN ('physical','mixed') AND disposition_private.physical_item_remaining('aggregations',a.id)),
 'records',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',r.id,'aggregation_id',r.aggregation_id,'root_id',u.root_aggregation_id,'medium',r.medium) ORDER BY r.id),'[]') FROM units u JOIN records r ON r.aggregation_id=u.id WHERE r.medium IN ('physical','mixed') AND disposition_private.physical_item_remaining('records',r.id)))
$$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA disposition_private FROM PUBLIC;

CREATE OR REPLACE FUNCTION protect_held_resource() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE blocked boolean;
DECLARE allowed_old jsonb;
DECLARE allowed_new jsonb;
BEGIN
    PERFORM lock_hold_policy_shared();
    -- Recording an immutable physical outcome or redirecting preserved material
    -- changes only disposition bookkeeping; the hold and all content remain.
    IF TG_OP='UPDATE' AND disposition_private.context_operation() IN ('job_terminate','resolve_partial')
      AND disposition_private.recovery_active(NULL,disposition_private.root_id(CASE WHEN TG_TABLE_NAME='aggregations' THEN OLD.id ELSE (to_jsonb(OLD)->>'aggregation_id')::bigint END),NEW.disposition_status)
      AND ((OLD.disposition_status=6 AND NEW.disposition_status IN (10,13)) OR (OLD.disposition_status=13 AND NEW.disposition_status BETWEEN 2 AND 5))
      AND (to_jsonb(NEW)-ARRAY['disposition_status','version','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','final_disposition_event_id'])=(to_jsonb(OLD)-ARRAY['disposition_status','version','final_disposition_at','final_disposition_by_user_id','disposition_job_id','destruction_number','final_disposition_event_id']) THEN
        PERFORM disposition_private.require_command(); RETURN NEW;
    END IF;

    -- Leaving a job/terminating it restores eligibility and preserves the hold.
    -- This is status-only bookkeeping, never destruction or a metadata override.
    IF TG_OP='UPDATE' AND disposition_private.context_operation() IN ('membership_remove','job_terminate')
      AND OLD.disposition_status BETWEEN 6 AND 9 AND NEW.disposition_status=OLD.disposition_status-4
      AND (to_jsonb(NEW)-ARRAY['disposition_status','version'])=(to_jsonb(OLD)-ARRAY['disposition_status','version']) THEN
        PERFORM disposition_private.require_command(); RETURN NEW;
    END IF;
    IF TG_OP='UPDATE' AND disposition_private.hook_applying()
      AND OLD.disposition_status BETWEEN 1 AND 9 AND NEW.disposition_status BETWEEN 1 AND 9
      AND (to_jsonb(NEW)-ARRAY['disposition_status','version'])=(to_jsonb(OLD)-ARRAY['disposition_status','version']) THEN
        PERFORM disposition_private.require_command(); RETURN NEW;
    END IF;
    IF TG_OP='UPDATE' AND OLD.disposition_status=1 AND NEW.disposition_status BETWEEN 2 AND 5
      AND disposition_private.context_operation()='eligibility_evaluate'
      AND (to_jsonb(NEW)-ARRAY['disposition_status','version'])=(to_jsonb(OLD)-ARRAY['disposition_status','version']) THEN
        PERFORM disposition_private.require_command(); RETURN NEW;
    END IF;
    IF TG_OP='DELETE' THEN
        IF TG_TABLE_NAME='aggregations' THEN
            WITH RECURSIVE subtree AS (
                SELECT OLD.id AS id UNION ALL
                SELECT child.id FROM aggregations child JOIN subtree parent ON child.parent_aggregation_id=parent.id
            )
            SELECT EXISTS(
                SELECT 1 FROM subtree WHERE resource_has_effective_hold('aggregation',subtree.id)
                UNION ALL
                SELECT 1 FROM records record JOIN subtree ON subtree.id=record.aggregation_id
                WHERE resource_has_effective_hold('record',record.id)
            ) INTO blocked;
        ELSE
            blocked:=resource_has_effective_hold('record',OLD.id);
        END IF;
        IF blocked THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='effective_hold_prevents_deletion'; END IF;
        RETURN OLD;
    END IF;

    IF TG_TABLE_NAME='aggregations' THEN
        blocked:=resource_state_changes_blocked('aggregation',OLD.id);
        IF NEW.parent_aggregation_id IS DISTINCT FROM OLD.parent_aggregation_id THEN
            IF blocked OR (NEW.parent_aggregation_id IS NOT NULL AND EXISTS(
                SELECT 1 FROM effective_holds_for_aggregation(NEW.parent_aggregation_id) WHERE preserve_resource_state
            )) THEN
                RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='effective_hold_prevents_metadata_change';
            END IF;
            IF EXISTS(
                WITH old_holds AS (SELECT hold_id FROM effective_holds_for_aggregation(OLD.id)),
                     new_ancestor_holds AS (
                         SELECT hold_id FROM effective_holds_for_aggregation(NEW.parent_aggregation_id)
                         UNION SELECT hold_id FROM hold_aggregation_assignments WHERE aggregation_id=OLD.id AND hold_is_effective(hold_id)
                     ), changed AS ((SELECT * FROM old_holds EXCEPT SELECT * FROM new_ancestor_holds)
                                    UNION (SELECT * FROM new_ancestor_holds EXCEPT SELECT * FROM old_holds))
                SELECT 1 FROM changed WHERE NOT current_hold_actor_is_manager(changed.hold_id)
            ) THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='hold_held_item_management_required_for_held_move'; END IF;
        END IF;
        IF blocked THEN
            allowed_old:=to_jsonb(OLD)-ARRAY['security_level_id','owning_org_unit_id','assigned_location','current_location',
                'inherit_acl_from_parent','resource_acl_version','child_aggregation_acl_version','child_record_acl_version','version'];
            allowed_new:=to_jsonb(NEW)-ARRAY['security_level_id','owning_org_unit_id','assigned_location','current_location',
                'inherit_acl_from_parent','resource_acl_version','child_aggregation_acl_version','child_record_acl_version','version'];
            IF allowed_old IS DISTINCT FROM allowed_new THEN
                RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='effective_hold_prevents_metadata_change';
            END IF;
        END IF;
    ELSE
        blocked:=resource_state_changes_blocked('record',OLD.id);
        IF NEW.aggregation_id IS DISTINCT FROM OLD.aggregation_id THEN
            IF blocked OR EXISTS(SELECT 1 FROM effective_holds_for_aggregation(NEW.aggregation_id)
                                 WHERE preserve_resource_state) THEN
                RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='effective_hold_prevents_metadata_change';
            END IF;
            IF EXISTS(
                WITH old_holds AS (SELECT hold_id FROM effective_holds_for_record(OLD.id)),
                     new_holds AS (
                         SELECT hold_id FROM effective_holds_for_aggregation(NEW.aggregation_id)
                         UNION SELECT hold_id FROM hold_record_assignments WHERE record_id=OLD.id AND hold_is_effective(hold_id)
                     ), changed AS ((SELECT * FROM old_holds EXCEPT SELECT * FROM new_holds)
                                    UNION (SELECT * FROM new_holds EXCEPT SELECT * FROM old_holds))
                SELECT 1 FROM changed WHERE NOT current_hold_actor_is_manager(changed.hold_id)
            ) THEN RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='hold_held_item_management_required_for_held_move'; END IF;
        END IF;
        IF blocked THEN
            allowed_old:=to_jsonb(OLD)-ARRAY['security_level_id','owning_org_unit_id','inherit_acl_from_parent',
                'resource_acl_version','version'];
            allowed_new:=to_jsonb(NEW)-ARRAY['security_level_id','owning_org_unit_id','inherit_acl_from_parent',
                'resource_acl_version','version'];
            IF allowed_old IS DISTINCT FROM allowed_new THEN
                RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE='effective_hold_prevents_metadata_change';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION current_user_can_view_event_resource(
  p_entity_type text, p_entity_id bigint, p_before jsonb, p_after jsonb
) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE record_id bigint;
DECLARE historical_level_id bigint;
DECLARE disposition_job bigint;
DECLARE proposal_data jsonb;
BEGIN
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
      WHERE m.job_id=disposition_job AND (NOT current_user_can_view_aggregation(unit.id)
        OR EXISTS(SELECT 1 FROM records r WHERE r.aggregation_id=unit.id AND NOT current_user_can_view_record(r.id))));
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

CREATE OR REPLACE VIEW authorized_event_history AS
SELECT event.id,event.occurred_at,event.transaction_id,event.entity_type,event.entity_id,
       event.operation,
       CASE WHEN visible.allowed THEN event.actor_user_id END AS actor_user_id,
       CASE WHEN visible.allowed THEN event.actor_name END AS actor_name,
       CASE WHEN visible.allowed THEN event.actor_email END AS actor_email,
       event.actor_type,
       event.source,event.request_id,event.correlation_id,
       CASE WHEN visible.allowed THEN event.before_state ELSE NULL END AS before_state,
       CASE WHEN visible.allowed THEN event.after_state ELSE NULL END AS after_state,
       CASE WHEN visible.allowed THEN event.changed_fields ELSE ARRAY[]::text[] END AS changed_fields,
       CASE WHEN visible.allowed THEN event.reason ELSE NULL END AS reason,
       CASE WHEN visible.allowed THEN event.metadata
            ELSE jsonb_build_object('redacted',true,'reason','resource_access_denied') END AS metadata
FROM event_history event
CROSS JOIN LATERAL (
  SELECT current_user_can_view_event_resource(
    event.entity_type,event.entity_id,
    COALESCE(event.before_state,CASE WHEN event.entity_type LIKE 'disposition_%' THEN event.metadata->'before' END),
    COALESCE(event.after_state,CASE WHEN event.entity_type='aggregation' AND event.metadata ? 'recovery_job_id' THEN event.metadata WHEN event.entity_type LIKE 'disposition_%' THEN event.metadata->'after' END)
  ) AS allowed
) visible;
INSERT INTO schema_migrations(version) VALUES('065_disposition_recovery') ON CONFLICT DO NOTHING;
