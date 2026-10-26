BEGIN;
-- Intermediate reviewers may complete a review with redacted related resources.
CREATE OR REPLACE FUNCTION disposition_private.decide_review_work(p_task bigint,p_job_version integer,p_task_version integer,p_decision text,p_reason text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE t disposition_tasks%ROWTYPE; j disposition_jobs%ROWTYPE; round_id bigint; acting bigint; identity bigint; reason text;
BEGIN
 IF disposition_private.context_operation() IS DISTINCT FROM 'review_decide' THEN RAISE EXCEPTION 'disposition_command_scope_invalid'; END IF;
 t:=disposition_private.review_context(p_task,p_job_version,p_task_version);
 SELECT * INTO j FROM disposition_jobs WHERE id=t.job_id;
 IF t.workflow_stage NOT IN ('file_administrator_review','unit_manager_review','records_manager_review') OR p_decision NOT IN ('approved','rejected') OR (t.workflow_stage='file_administrator_review' AND p_decision<>'approved') THEN RAISE EXCEPTION 'disposition_review_decision_invalid'; END IF;
 IF t.workflow_stage='records_manager_review' AND p_decision='approved' THEN RAISE EXCEPTION 'disposition_proposal_execution_not_implemented'; END IF;
 IF p_decision='rejected' AND (p_reason IS NULL OR p_reason ~ '^[[:space:]]*$') THEN RAISE EXCEPTION 'disposition_decision_reason_required'; END IF;
 -- Intermediate completion records the review; it does not authorize proposal execution.
 -- Proposal writes and final Records Manager approval retain their full access checks.
 reason:=COALESCE(NULLIF(btrim(p_reason),''),CASE WHEN p_decision='rejected' THEN 'Return marked aggregations for correction' ELSE 'Complete authorized review' END);
 SELECT id INTO round_id FROM disposition_review_rounds WHERE job_id=j.id AND round_number=j.current_review_round;
 SELECT r.acting_role_id INTO acting FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 INSERT INTO disposition_review_decisions(job_id,round_id,review_stage,decision,task_id,actor_user_id,acting_role_id,reason,membership_snapshot)
 VALUES(j.id,round_id,t.workflow_stage,p_decision,t.id,current_user_id(),acting,reason,disposition_private.membership_snapshot(j.id)) RETURNING id INTO identity;
 UPDATE disposition_tasks SET task_state='completed' WHERE id=t.id;
 IF p_decision='rejected' THEN PERFORM disposition_private.route_correction(j.id);
 ELSE PERFORM disposition_private.route_review(j.id,CASE WHEN t.workflow_stage='file_administrator_review' THEN 'unit_manager_review' ELSE 'records_manager_review' END); END IF;
 RETURN jsonb_build_object('decision_id',identity,'job_id',j.id,'workflow_stage',(SELECT workflow_stage FROM disposition_jobs WHERE id=j.id),'job_version',(SELECT version FROM disposition_jobs WHERE id=j.id));
END $$;
INSERT INTO schema_migrations(version) VALUES('086_intermediate_review_completion') ON CONFLICT DO NOTHING;
COMMIT;
