BEGIN;

-- Uploads only. Versioned repository defaults remain packaged source assets;
-- neither schema creation nor an upgrade executes a seed or reads a file.
CREATE TABLE disposition_template_revisions (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 document_type text NOT NULL CHECK (document_type IN ('destruction_request','digital_destruction_certificate','proposal_execution_report','physical_preparation_report')),
 revision_number integer NOT NULL CHECK (revision_number>0),
 original_filename text NOT NULL CHECK (btrim(original_filename)<>'' AND lower(right(original_filename,5))='.docx'),
 content bytea NOT NULL CHECK (octet_length(content)>0),
 checksum text NOT NULL CHECK (checksum=encode(sha256(content),'hex')),
 uploaded_by_user_id bigint NOT NULL REFERENCES users(id),
 acting_role_id bigint NOT NULL REFERENCES roles(id),
 actor_type text NOT NULL DEFAULT 'user' CHECK (actor_type='user'),
 uploaded_from_job_id bigint NOT NULL REFERENCES disposition_jobs(id),
 uploaded_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(document_type,revision_number)
);

CREATE FUNCTION disposition_private.can_revise_template(p_role bigint) RETURNS boolean
LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM users u JOIN user_role_assignments a ON a.user_id=u.id
 JOIN roles r ON r.id=a.role_id JOIN profiles profile ON profile.id=r.profile_id
 JOIN profile_privileges pp ON pp.profile_id=r.profile_id JOIN privileges p ON p.id=pp.privilege_id
 WHERE u.id=current_user_id() AND u.status='active' AND u.account_type='person'
 AND r.id=p_role AND r.is_information_governance AND role_effectively_active(r.id)
 AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
 AND profile.code IN ('INFO_GOV_OFFICER','INFO_GOV_MGR') AND p.code='disposition.jobs.manage')
$$;

CREATE FUNCTION disposition_private.guard_template_revision() RETURNS trigger LANGUAGE plpgsql AS $$
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
 OR NOT EXISTS(SELECT 1 FROM disposition_jobs WHERE id=NEW.uploaded_from_job_id AND job_type='destruction')
 THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_template_forbidden'; END IF;
 IF NEW.revision_number<>(SELECT coalesce(max(revision_number),0)+1 FROM disposition_template_revisions WHERE document_type=NEW.document_type)
 THEN RAISE EXCEPTION 'disposition_template_stale'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER disposition_template_guard BEFORE INSERT OR UPDATE OR DELETE ON disposition_template_revisions
FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_template_revision();

CREATE FUNCTION disposition_private.audit_template_revision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM append_domain_event('disposition_job',NEW.uploaded_from_job_id,'TEMPLATE_REVISED',
 jsonb_build_object('template_type',NEW.document_type,'template_revision_id',NEW.id,
 'template_revision',NEW.revision_number,'original_filename',NEW.original_filename,
 'checksum_algo','sha256','checksum',NEW.checksum,'uploaded_by_user_id',NEW.uploaded_by_user_id,
 'acting_role_id',NEW.acting_role_id,'actor_type',NEW.actor_type,'uploaded_at',NEW.uploaded_at));
 RETURN NULL;
END $$;
CREATE TRIGGER disposition_template_audit AFTER INSERT ON disposition_template_revisions
FOR EACH ROW EXECUTE FUNCTION disposition_private.audit_template_revision();

COMMIT;
