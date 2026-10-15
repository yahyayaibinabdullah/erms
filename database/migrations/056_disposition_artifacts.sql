BEGIN;
SELECT set_config('app.actor_type','automated_process',true),set_config('app.event_source','migration',true),set_config('app.actor_name','Database migration 056',true),set_config('app.change_reason','Install governed disposition artifact versions',true);
-- Artifact versions retain their own governed record and destination snapshot.
ALTER TABLE disposition_job_documents
 ADD COLUMN origin text CHECK (origin IN ('uploaded','generated')),
 ADD COLUMN supersedes_document_id bigint UNIQUE REFERENCES disposition_job_documents(id) ON DELETE RESTRICT,
 ADD COLUMN evidence_version integer NOT NULL DEFAULT 1 CHECK(evidence_version>0),
 ADD COLUMN classification_scheme_id bigint REFERENCES classification_schemes(id) ON DELETE RESTRICT,
 ADD COLUMN classification_id bigint REFERENCES classifications(id) ON DELETE RESTRICT,
 ADD COLUMN aggregation_id bigint REFERENCES aggregations(id) ON DELETE RESTRICT,
 ADD COLUMN acting_role_id bigint REFERENCES roles(id) ON DELETE RESTRICT,
 ADD COLUMN provenance jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(provenance)='object');
-- Upgrade only what can be recovered from an existing governed reference.
-- Never invent an original settings snapshot or uploader role for legacy rows.
ALTER TABLE disposition_job_documents DISABLE TRIGGER disposition_guard;
ALTER TABLE disposition_job_documents DISABLE TRIGGER disposition_audit;
UPDATE disposition_job_documents d SET
 origin=CASE WHEN document_type IN ('external_rejection_letter','external_approval_letter','physical_destruction_certificate') THEN 'uploaded' ELSE 'generated' END,
 aggregation_id=r.aggregation_id,classification_id=a.classification_id,
 classification_scheme_id=cl.classification_scheme_id,
 provenance=jsonb_build_object('legacy_destination_reconstructed',true)
 FROM records r JOIN aggregations a ON a.id=r.aggregation_id
 JOIN classifications cl ON cl.id=a.classification_id WHERE r.id=d.record_id;
UPDATE disposition_job_documents SET origin=CASE WHEN document_type IN ('external_rejection_letter','external_approval_letter','physical_destruction_certificate') THEN 'uploaded' ELSE 'generated' END WHERE origin IS NULL;
ALTER TABLE disposition_job_documents ENABLE TRIGGER disposition_guard;
ALTER TABLE disposition_job_documents ENABLE TRIGGER disposition_audit;
ALTER TABLE disposition_job_documents ALTER COLUMN origin SET NOT NULL;
CREATE INDEX disposition_documents_job_page ON disposition_job_documents(job_id,id DESC);
CREATE INDEX disposition_documents_record ON disposition_job_documents(record_id);
CREATE INDEX disposition_documents_component ON disposition_job_documents(digital_component_id);

CREATE FUNCTION disposition_private.can_correct_evidence(p_job bigint,p_role bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM disposition_jobs j JOIN users u ON u.id=current_user_id()
 JOIN user_role_assignments a ON a.user_id=u.id JOIN roles r ON r.id=a.role_id
 JOIN profiles profile ON profile.id=r.profile_id
 JOIN profile_privileges pp ON pp.profile_id=r.profile_id JOIN privileges p ON p.id=pp.privilege_id
 WHERE j.id=p_job AND j.job_type='destruction' AND j.lifecycle_state='active'
 AND u.status='active' AND u.account_type='person' AND r.id=p_role
 AND r.is_information_governance AND role_effectively_active(r.id)
 AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
 AND p.code='disposition.jobs.manage' AND (profile.code='INFO_GOV_MGR'
 OR (profile.code='INFO_GOV_OFFICER' AND j.assigned_user_id=u.id)))
$$;

-- Stable locks shared with grouped settings updates. A save never mixes settings
-- revisions; classification changes cannot race the selected open root.
CREATE FUNCTION disposition_private.artifact_destination(p_type text)
RETURNS TABLE(scheme_id bigint,classification_id bigint,aggregation_id bigint) LANGUAGE plpgsql AS $$
DECLARE scheme bigint; dest bigint; root bigint; setting_name text;
BEGIN
 IF p_type NOT IN ('destruction_request','external_rejection_letter','external_approval_letter','physical_destruction_certificate','digital_destruction_certificate','proposal_execution_report','physical_preparation_report') THEN RAISE EXCEPTION 'disposition_document_type_invalid'; END IF;
 setting_name:=CASE WHEN p_type IN ('destruction_request','proposal_execution_report','physical_preparation_report') THEN 'DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID' ELSE 'DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID' END;
 PERFORM 1 FROM application_settings WHERE key IN ('DISPOSITION_CLASSIFICATION_SCHEME_ID','DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID','DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID') ORDER BY key FOR SHARE;
 SELECT (value#>>'{}')::bigint INTO scheme FROM application_settings WHERE key='DISPOSITION_CLASSIFICATION_SCHEME_ID';
 SELECT (value#>>'{}')::bigint INTO dest FROM application_settings WHERE key=setting_name;
 IF scheme IS NULL OR dest IS NULL THEN RAISE EXCEPTION 'disposition_destination_unset'; END IF;
 PERFORM 1 FROM classifications c WHERE c.id=dest AND c.classification_scheme_id=scheme AND c.is_terminal FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'disposition_destination_invalid'; END IF;
 SELECT a.id INTO root FROM aggregations a WHERE a.parent_aggregation_id IS NULL
 AND a.date_closed IS NULL AND a.classification_id=dest ORDER BY a.date_opened DESC,a.id DESC LIMIT 1 FOR SHARE;
 IF root IS NULL THEN RAISE EXCEPTION 'disposition_destination_open_root_missing'; END IF;
 RETURN QUERY SELECT scheme,dest,root;
END $$;

CREATE FUNCTION disposition_private.guard_artifact() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target record; previous disposition_job_documents%ROWTYPE; role_id bigint;
BEGIN
 PERFORM disposition_private.require_command();
 SELECT r.acting_role_id INTO role_id FROM disposition_private.command_context c JOIN disposition_private.command_receipts r USING(command_id) WHERE c.transaction_id=txid_current();
 IF NEW.acting_role_id IS DISTINCT FROM role_id THEN RAISE EXCEPTION 'disposition_document_actor_mismatch'; END IF;
 IF NEW.origin IS DISTINCT FROM (CASE WHEN NEW.document_type IN ('external_rejection_letter','external_approval_letter','physical_destruction_certificate') THEN 'uploaded' ELSE 'generated' END) THEN RAISE EXCEPTION 'disposition_document_origin_invalid'; END IF;
 IF NEW.supersedes_document_id IS NOT NULL THEN
  SELECT * INTO previous FROM disposition_job_documents WHERE id=NEW.supersedes_document_id FOR UPDATE;
  IF previous.id IS NULL OR previous.origin<>'uploaded' OR NEW.origin<>'uploaded'
   OR previous.job_id<>NEW.job_id OR previous.document_type<>NEW.document_type
   OR previous.document_state<>'available' OR NEW.evidence_version<>previous.evidence_version+1
   OR NEW.review_round IS DISTINCT FROM previous.review_round
   OR EXISTS(SELECT 1 FROM disposition_job_documents WHERE supersedes_document_id=previous.id)
  THEN RAISE EXCEPTION 'disposition_evidence_version_invalid'; END IF;
  IF NOT disposition_private.can_correct_evidence(NEW.job_id,role_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_evidence_correction_forbidden'; END IF;
 ELSIF NEW.evidence_version<>1 THEN RAISE EXCEPTION 'disposition_evidence_version_invalid'; END IF;
 IF NEW.document_state='available' THEN
  SELECT * INTO target FROM disposition_private.artifact_destination(NEW.document_type);
  IF (NEW.classification_scheme_id,NEW.classification_id,NEW.aggregation_id) IS DISTINCT FROM (target.scheme_id,target.classification_id,target.aggregation_id)
  OR NOT EXISTS(SELECT 1 FROM records r WHERE r.id=NEW.record_id AND r.aggregation_id=target.aggregation_id)
  OR EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=NEW.job_id AND m.membership_state IN ('active','completed_history') AND m.root_aggregation_id=target.aggregation_id)
  THEN RAISE EXCEPTION 'disposition_document_destination_invalid'; END IF;
  IF NOT EXISTS(SELECT 1 FROM digital_components c JOIN digital_component_content_sets s ON s.id=c.active_content_set_id AND s.digital_component_id=c.id
   WHERE c.id=NEW.digital_component_id AND c.record_id=NEW.record_id AND c.content_status='available' AND s.status='active'
   AND c.checksum_algo=NEW.checksum_algo AND c.checksum_value=NEW.checksum AND s.checksum_value=NEW.checksum)
  THEN RAISE EXCEPTION 'disposition_document_content_unavailable'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER disposition_z_artifact_gate BEFORE INSERT OR UPDATE ON disposition_job_documents FOR EACH ROW EXECUTE FUNCTION disposition_private.guard_artifact();

-- Ordinary component replacement/removal cannot erase historical job evidence.
-- Corrections always create another record and component instead.
CREATE FUNCTION disposition_private.preserve_artifact_content() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE component bigint; rec bigint;
BEGIN
 IF TG_TABLE_NAME='digital_components' THEN
  component:=OLD.id;
  IF TG_OP='UPDATE' AND (to_jsonb(OLD)-ARRAY['version','date_updated','component_order'])=(to_jsonb(NEW)-ARRAY['version','date_updated','component_order']) THEN RETURN NEW; END IF;
 ELSIF TG_TABLE_NAME='digital_component_content_sets' THEN component:=COALESCE(NEW.digital_component_id,OLD.digital_component_id);
 ELSE SELECT digital_component_id INTO component FROM digital_component_content_sets WHERE id=COALESCE(NEW.content_set_id,OLD.content_set_id); END IF;
 IF EXISTS(SELECT 1 FROM disposition_job_documents WHERE digital_component_id=component AND document_state='available') THEN
  RAISE EXCEPTION 'disposition_evidence_version_preserved'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER disposition_preserve_content BEFORE UPDATE OR DELETE ON digital_components FOR EACH ROW EXECUTE FUNCTION disposition_private.preserve_artifact_content();
CREATE TRIGGER disposition_preserve_content BEFORE INSERT OR UPDATE OR DELETE ON digital_component_content_sets FOR EACH ROW EXECUTE FUNCTION disposition_private.preserve_artifact_content();
CREATE TRIGGER disposition_preserve_content BEFORE INSERT OR UPDATE OR DELETE ON digital_component_blobs FOR EACH ROW EXECUTE FUNCTION disposition_private.preserve_artifact_content();

-- A stored artifact must never be moved into its own job's destruction unit.
CREATE FUNCTION disposition_private.artifact_outside_job() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM disposition_job_documents d JOIN records r ON r.id=d.record_id
 JOIN disposition_job_memberships m ON m.job_id=d.job_id AND m.membership_state IN ('active','completed_history')
 WHERE disposition_private.root_id(r.aggregation_id)=m.root_aggregation_id) THEN
  RAISE EXCEPTION 'disposition_evidence_inside_job'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER disposition_evidence_outside_job AFTER INSERT OR UPDATE ON disposition_job_memberships DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION disposition_private.artifact_outside_job();
CREATE CONSTRAINT TRIGGER disposition_evidence_outside_job AFTER UPDATE ON records DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN(OLD.aggregation_id IS DISTINCT FROM NEW.aggregation_id) EXECUTE FUNCTION disposition_private.artifact_outside_job();
CREATE CONSTRAINT TRIGGER disposition_evidence_outside_job AFTER UPDATE ON aggregations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN(OLD.parent_aggregation_id IS DISTINCT FROM NEW.parent_aggregation_id) EXECUTE FUNCTION disposition_private.artifact_outside_job();

CREATE OR REPLACE FUNCTION current_user_can_view_event_resource(
  p_entity_type text, p_entity_id bigint, p_before jsonb, p_after jsonb
) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE record_id bigint;
DECLARE historical_level_id bigint;
DECLARE disposition_job bigint;
BEGIN
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

COMMIT;
