-- Link each newly recorded proposal event to its existing command receipt.
-- Historical events remain unchanged; no new privilege, state or table.
BEGIN;
CREATE OR REPLACE FUNCTION disposition_private.audit_review_work() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE operation text;
BEGIN
 operation:=CASE WHEN TG_TABLE_NAME='disposition_review_notes' THEN 'REVIEW_NOTES_SAVED'
 WHEN TG_OP='INSERT' AND to_jsonb(NEW)->>'carried_from_proposal_id' IS NOT NULL THEN 'REVIEW_PROPOSAL_CARRIED'
 WHEN TG_OP='INSERT' THEN 'REVIEW_PROPOSAL_CREATED'
 WHEN to_jsonb(NEW)->>'proposal_state'='executed' THEN 'REVIEW_PROPOSAL_EXECUTED'
 WHEN to_jsonb(NEW)->>'proposal_state'='withdrawn' THEN 'REVIEW_PROPOSAL_WITHDRAWN' ELSE 'REVIEW_PROPOSAL_REVISED' END;
 PERFORM append_domain_event(CASE WHEN TG_TABLE_NAME='disposition_review_notes' THEN 'disposition_review_note' ELSE 'disposition_review_proposal' END,NEW.id,operation,
 jsonb_build_object('command_id',(SELECT command_id FROM disposition_private.command_context WHERE transaction_id=txid_current()),'before',CASE WHEN TG_OP='UPDATE' THEN to_jsonb(OLD) END,'after',to_jsonb(NEW),
 'acting_role_id',(SELECT r.acting_role_id FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current())));
 RETURN NULL;
END $$;

INSERT INTO schema_migrations(version) VALUES('097_bulk_disposition_audit_link') ON CONFLICT (version) DO NOTHING;
COMMIT;
