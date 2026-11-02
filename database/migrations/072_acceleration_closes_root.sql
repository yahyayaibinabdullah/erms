-- Acceleration closes an open governing root atomically before eligibility.
BEGIN;
CREATE OR REPLACE FUNCTION disposition_private.accelerate(p_root bigint,p_version bigint) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE root aggregations%ROWTYPE; evaluation record;
BEGIN
 PERFORM disposition_private.require_command();
 IF disposition_private.context_operation()<>'eligibility_accelerate' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 PERFORM disposition_private.lock_current_blockers(p_root);
 SELECT * INTO root FROM aggregations WHERE id=p_root;
 IF NOT FOUND OR root.version<>p_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='disposition_stale_version'; END IF;
 IF NOT current_user_can_view_aggregation(p_root) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_resource_access_required'; END IF;
 IF root.parent_aggregation_id IS NOT NULL THEN RAISE EXCEPTION 'disposition_requires_governing_root'; END IF;
 IF root.disposition_status<>1 OR EXISTS(SELECT 1 FROM disposition_job_memberships WHERE root_aggregation_id=p_root AND membership_state='active') THEN RAISE EXCEPTION 'disposition_acceleration_state_invalid'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_private.protection_blockers(p_root)) THEN RAISE EXCEPTION 'disposition_admission_blocked'; END IF;
 IF root.date_closed IS NULL THEN
  IF NOT current_user_can_aggregation_operation(p_root,'aggregation.close','aggregation.close') THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='insufficient_privilege'; END IF;
  UPDATE aggregations SET date_closed=CURRENT_TIMESTAMP WHERE id=p_root RETURNING * INTO root;
 END IF;
 SELECT * INTO evaluation FROM disposition_private.eligibility(p_root);
 IF evaluation.eligible_status IS NULL THEN RAISE EXCEPTION 'disposition_retention_rule_required'; END IF;
 PERFORM disposition_private.transition_unit(p_root,root.version,evaluation.eligible_status);
 PERFORM append_domain_event('aggregation',p_root,'DISPOSITION_ACCELERATED',to_jsonb(evaluation));
 RETURN jsonb_build_object('root_id',p_root,'status',evaluation.eligible_status);
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
 IF root.date_closed IS NULL AND p_status<>1 THEN RAISE EXCEPTION 'disposition_root_not_closed'; END IF;
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
INSERT INTO schema_migrations(version) VALUES('072_acceleration_closes_root');
COMMIT;
