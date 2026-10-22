BEGIN;
-- Routine admission retains attribution without requiring a reason.
ALTER TABLE disposition_private.command_receipts DROP CONSTRAINT command_receipts_reason_check;
ALTER TABLE disposition_private.command_receipts ADD CONSTRAINT command_receipts_reason_check
 CHECK(operation IN ('job_create','membership_add') OR btrim(reason)<>'');
CREATE OR REPLACE FUNCTION disposition_private.begin_command(p_id uuid,p_operation text,p_payload jsonb,p_role bigint,p_reason text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE previous disposition_private.command_receipts%ROWTYPE;
BEGIN
 p_reason:=COALESCE(p_reason,'');
 PERFORM pg_advisory_xact_lock(7357,1);
 IF p_operation IN ('task_claim','task_release','task_reassign','task_complete','review_save','review_submit','review_decide') AND p_payload ? 'task_id' AND NOT (p_operation='review_decide' AND disposition_private.physical_confirmation_retry(p_id,p_role)) THEN
  PERFORM disposition_private.require_task_command((p_payload->>'task_id')::bigint,p_role,p_operation);
 ELSE PERFORM disposition_private.require_actor(p_role); END IF;
 IF p_operation NOT IN ('job_create','membership_add') AND (p_reason IS NULL OR p_reason ~ '^[[:space:]]*$') THEN RAISE EXCEPTION 'disposition_reason_required'; END IF;
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
COMMIT;
