-- Complete decision snapshot minimization (070).
-- Minimize both decision snapshots atomically under the existing exact-value
-- history guard. Review rationale, actor and permanent provenance survive.
BEGIN;
CREATE OR REPLACE FUNCTION disposition_private.minimize_unit_history(p_job bigint,p_root bigint) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF NOT disposition_private.destruction_active('finalize',p_root) THEN RAISE EXCEPTION 'disposition_destruction_command_required'; END IF;
 UPDATE disposition_review_rounds SET membership_snapshot=disposition_private.retained_history_json(membership_snapshot),proposal_snapshot=disposition_private.retained_history_json(proposal_snapshot),approval_execution=disposition_private.retained_history_json(approval_execution) WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root);
 UPDATE disposition_review_decisions SET membership_snapshot=disposition_private.retained_history_json(membership_snapshot),proposal_snapshot=disposition_private.retained_history_json(proposal_snapshot) WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root);
 UPDATE disposition_job_documents SET provenance=disposition_private.retained_history_json(provenance) WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root);
 UPDATE disposition_proposal_effects SET details=disposition_private.retained_json(details) WHERE governing_root_id=p_root;
 UPDATE disposition_private.command_receipts SET payload=disposition_private.retained_command_payload(payload),result=disposition_private.retained_history_json(result)
 WHERE completed_at IS NOT NULL AND (payload->>'job_id' IN (SELECT job_id::text FROM disposition_job_memberships WHERE root_aggregation_id=p_root) OR payload->>'root_id'=p_root::text OR payload->>'task_id' IN (SELECT id::text FROM disposition_tasks WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)) OR result->>'job_id' IN (SELECT job_id::text FROM disposition_job_memberships WHERE root_aggregation_id=p_root) OR operation='job_create' AND result->>'id'=p_job::text);
 UPDATE event_history SET before_state=CASE WHEN entity_type IN ('aggregation','record','digital_component','record_component') THEN disposition_private.retained_json(before_state) ELSE disposition_private.retained_history_json(before_state) END,after_state=CASE WHEN entity_type IN ('aggregation','record','digital_component','record_component') THEN disposition_private.retained_json(after_state) ELSE disposition_private.retained_history_json(after_state) END,metadata=CASE WHEN entity_type IN ('aggregation','record','digital_component','record_component') THEN disposition_private.retained_json(metadata) ELSE disposition_private.retained_history_json(metadata) END
 WHERE (entity_type='aggregation' AND entity_id IN (SELECT disposition_private.unit_ids(p_root)))
 OR (entity_type='record' AND entity_id IN (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root))))
 OR (entity_type IN ('digital_component','record_component') AND (SELECT identities->'component_ids' FROM disposition_private.destruction_identities WHERE transaction_id=txid_current() AND root_id=p_root) @> to_jsonb(entity_id))
 OR (entity_type='disposition_job' AND entity_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root))
 OR (entity_type='disposition_task' AND entity_id IN (SELECT id FROM disposition_tasks WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)))
 OR (entity_type='disposition_review_round' AND entity_id IN (SELECT id FROM disposition_review_rounds WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)))
 OR (entity_type='disposition_review_decision' AND entity_id IN (SELECT id FROM disposition_review_decisions WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)))
 OR (entity_type='disposition_job_document' AND entity_id IN (SELECT id FROM disposition_job_documents WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)))
 OR (entity_type='disposition_job_membership' AND entity_id IN (SELECT id FROM disposition_job_memberships WHERE job_id IN (SELECT job_id FROM disposition_job_memberships WHERE root_aggregation_id=p_root)));
END $$;

INSERT INTO schema_migrations(version) VALUES('070_disposition_decision_minimization') ON CONFLICT DO NOTHING;
COMMIT;
