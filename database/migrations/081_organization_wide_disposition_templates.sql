-- Allow organization-wide template management without a job instance.
BEGIN;
ALTER TABLE disposition_template_revisions ALTER COLUMN uploaded_from_job_id DROP NOT NULL;
CREATE OR REPLACE FUNCTION disposition_private.guard_template_revision() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE command disposition_private.command_receipts%ROWTYPE;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'disposition_template_immutable'; END IF;
 PERFORM disposition_private.require_command();
 SELECT r.* INTO command FROM disposition_private.command_context c
 JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 IF command.operation<>'document_save' OR command.payload->>'template_upload' IS DISTINCT FROM 'true'
 OR NOT disposition_private.can_revise_template(command.acting_role_id)
 OR NEW.acting_role_id<>command.acting_role_id OR NEW.uploaded_by_user_id<>current_user_id()
 OR NEW.actor_type<>'user' OR NEW.uploaded_at<>CURRENT_TIMESTAMP
 OR command.payload->>'checksum' IS DISTINCT FROM NEW.checksum
 OR command.payload->>'kind' IS DISTINCT FROM NEW.document_type
 OR command.payload->>'filename' IS DISTINCT FROM NEW.original_filename
 OR command.payload->>'job_id' IS DISTINCT FROM NEW.uploaded_from_job_id::text
 OR (NEW.uploaded_from_job_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM disposition_jobs WHERE id=NEW.uploaded_from_job_id AND job_type='destruction'))
 THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_template_forbidden'; END IF;
 IF NEW.revision_number<>(SELECT coalesce(max(revision_number),0)+1 FROM disposition_template_revisions WHERE document_type=NEW.document_type)
 THEN RAISE EXCEPTION 'disposition_template_stale'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION disposition_private.audit_template_revision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM append_domain_event(CASE WHEN NEW.uploaded_from_job_id IS NULL THEN 'disposition_template_revision' ELSE 'disposition_job' END,COALESCE(NEW.uploaded_from_job_id,NEW.id),'TEMPLATE_REVISED',
 jsonb_build_object('template_type',NEW.document_type,'template_revision_id',NEW.id,
 'template_revision',NEW.revision_number,'original_filename',NEW.original_filename,
 'checksum_algo','sha256','checksum',NEW.checksum,'uploaded_by_user_id',NEW.uploaded_by_user_id,
 'acting_role_id',NEW.acting_role_id,'actor_type',NEW.actor_type,'uploaded_at',NEW.uploaded_at));
 RETURN NULL;
END $$;
INSERT INTO schema_migrations(version) VALUES('081_organization_wide_disposition_templates') ON CONFLICT DO NOTHING;
COMMIT;
