-- Routine admission retains attribution without requiring a reason.
-- Older copies omitted their history entry. Reconciliation must never replay
-- pre-084 definitions over the later reason-free task-claim behavior.
BEGIN;
DO $migration$
DECLARE
 command_source text;
 reason_check text;
 permits_expected boolean;
 permits_missing_reason boolean;
 newer_claims boolean;
BEGIN
 IF EXISTS(SELECT 1 FROM schema_migrations WHERE version='079_disposition_admission_reason') THEN
  RETURN;
 END IF;
 SELECT prosrc INTO command_source FROM pg_proc
  WHERE oid=to_regprocedure('disposition_private.begin_command(uuid,text,jsonb,bigint,text)');
 newer_claims:=COALESCE(command_source ~* 'p_operation[[:space:]]+NOT[[:space:]]+IN[[:space:]]*\([[:space:]]*''job_create''[[:space:]]*,[[:space:]]*''membership_add''[[:space:]]*,[[:space:]]*''task_claim''[[:space:]]*\)',false);
 IF EXISTS(SELECT 1 FROM schema_migrations WHERE version='084_reasonless_task_claim') OR newer_claims THEN
  -- Verify the superseding contract without changing the routine or constraint.
  SELECT pg_get_expr(conbin,conrelid) INTO reason_check FROM pg_constraint
   WHERE conrelid='disposition_private.command_receipts'::regclass
     AND conname='command_receipts_reason_check' AND contype='c' AND convalidated;
  IF NOT newer_claims OR reason_check IS NULL THEN
   RAISE EXCEPTION '079 reconciliation requires the intact post-084 admission/claim contract; inspect schema drift';
  END IF;
  EXECUTE format('SELECT bool_and(%s) FROM (VALUES (''job_create''::text,''''::text),(''membership_add'',''''),(''task_claim'',''''),(''review_submit'',''Reviewed'')) AS candidate(operation,reason)',reason_check)
   INTO permits_expected;
  EXECUTE format('SELECT bool_or(%s) FROM (VALUES (''review_submit''::text,''''::text),(''job_assign'','''')) AS candidate(operation,reason)',reason_check)
   INTO permits_missing_reason;
  IF permits_expected IS DISTINCT FROM true OR permits_missing_reason IS DISTINCT FROM false THEN
   RAISE EXCEPTION '079 reconciliation requires the intact post-084 reason constraint; inspect schema drift';
  END IF;
 ELSE
  EXECUTE $upgrade$
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
$upgrade$;
 END IF;
 INSERT INTO schema_migrations(version) VALUES('079_disposition_admission_reason') ON CONFLICT DO NOTHING;
END $migration$;
COMMIT;
