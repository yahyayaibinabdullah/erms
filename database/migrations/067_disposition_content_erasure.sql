-- Phase 21 part 2: actual PostgreSQL storage/derivative deletion and copy fence.
-- Old workers have no durable working-copy receipts. Upgrade only after
-- draining/stopping them and cleaning their owned legacy scratch directories.
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM content_indexing_jobs WHERE status='leased') OR EXISTS(SELECT 1 FROM text_indexing_workers WHERE active_until>CURRENT_TIMESTAMP) THEN RAISE EXCEPTION 'processing_copy_upgrade_requires_drained_indexers'; END IF;
END $$;
CREATE TABLE disposition_private.processing_copies (
 token uuid PRIMARY KEY,component_id bigint NOT NULL REFERENCES digital_components(id) ON DELETE RESTRICT,
 owner_user_id bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 kind text NOT NULL CHECK(kind IN ('rendition','text_indexing')),worker_id text,
 indexing_job_id bigint,indexing_generation bigint,created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX disposition_processing_copies_component ON disposition_private.processing_copies(component_id);
CREATE FUNCTION disposition_private.content_reserved(p_record bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM records r JOIN disposition_job_memberships m ON m.root_aggregation_id=disposition_private.root_id(r.aggregation_id)
 JOIN disposition_destruction_runs run ON run.job_id=m.job_id WHERE r.id=p_record AND run.state IN ('queued','running'))
$$;
CREATE FUNCTION disposition_private.register_processing_copy(p_token uuid,p_component bigint,p_owner bigint,p_kind text,p_worker text DEFAULT NULL,p_job bigint DEFAULT NULL,p_generation bigint DEFAULT NULL) RETURNS void LANGUAGE plpgsql AS $$
DECLARE rec bigint;
BEGIN
 PERFORM pg_advisory_xact_lock(7357,1);
 SELECT record_id INTO rec FROM digital_components WHERE id=p_component FOR SHARE;
 IF rec IS NULL OR EXISTS(SELECT 1 FROM records WHERE id=rec AND disposition_status=10) THEN RAISE EXCEPTION 'content_unavailable'; END IF;
 IF disposition_private.content_reserved(rec) THEN RAISE EXCEPTION 'disposition_processing_cleanup_required'; END IF;
 INSERT INTO disposition_private.processing_copies VALUES(p_token,p_component,p_owner,p_kind,p_worker,p_job,p_generation,clock_timestamp()) ON CONFLICT(token) DO NOTHING;
 IF NOT EXISTS(SELECT 1 FROM disposition_private.processing_copies WHERE token=p_token AND component_id=p_component AND owner_user_id=p_owner AND kind=p_kind AND worker_id IS NOT DISTINCT FROM p_worker AND indexing_job_id IS NOT DISTINCT FROM p_job AND indexing_generation IS NOT DISTINCT FROM p_generation) THEN RAISE EXCEPTION 'processing_copy_conflict'; END IF;
END $$;
CREATE FUNCTION disposition_private.erase_unit_content(p_root bigint) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF NOT disposition_private.destruction_active('delete',p_root) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='disposition_destruction_command_required'; END IF;
 IF EXISTS(SELECT 1 FROM disposition_private.processing_copies p JOIN digital_components d ON d.id=p.component_id JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root))) THEN RAISE EXCEPTION 'disposition_processing_cleanup_required'; END IF;
 IF EXISTS(SELECT 1 FROM digital_components d JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root)) AND d.storage_backend<>'postgresql') THEN RAISE EXCEPTION 'disposition_storage_backend_unsupported'; END IF;
 -- Remove attempt/error/operation fields too: none is permanent disposition proof.
 DELETE FROM content_indexing_batch_items WHERE component_identifier IN (SELECT d.id FROM digital_components d JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
 DELETE FROM content_indexing_attempts WHERE record_id IN (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
 DELETE FROM content_indexing_jobs WHERE record_id IN (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
 DELETE FROM digital_component_search_documents WHERE record_id IN (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
 DELETE FROM digital_component_blobs WHERE content_set_id IN (SELECT s.id FROM digital_component_content_sets s JOIN digital_components d ON d.id=s.digital_component_id JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
 DELETE FROM digital_component_content_sets WHERE digital_component_id IN (SELECT d.id FROM digital_components d JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
 DELETE FROM digital_components WHERE record_id IN (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(p_root)));
END $$;

CREATE OR REPLACE FUNCTION protect_component_in_closed_aggregation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP='DELETE' AND disposition_private.destruction_active('delete',disposition_private.root_id((SELECT aggregation_id FROM records WHERE id=OLD.record_id))) THEN RETURN OLD; END IF;

    IF TG_OP = 'INSERT' THEN
        PERFORM assert_record_effectively_open(NEW.record_id);
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM assert_record_effectively_open(OLD.record_id);
        RETURN OLD;
    END IF;

    PERFORM assert_record_effectively_open(OLD.record_id);
    IF NEW.record_id IS DISTINCT FROM OLD.record_id THEN
        PERFORM assert_record_effectively_open(NEW.record_id);
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION protect_blob_in_closed_aggregation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    target_content_set_id bigint;
BEGIN
    IF TG_OP='DELETE' AND disposition_private.destruction_active('delete',disposition_private.root_id((SELECT aggregation_id FROM records WHERE id=(SELECT d.record_id FROM digital_component_content_sets s JOIN digital_components d ON d.id=s.digital_component_id WHERE s.id=OLD.content_set_id)))) THEN RETURN OLD; END IF;

    target_content_set_id := CASE WHEN TG_OP = 'DELETE'
        THEN OLD.content_set_id ELSE NEW.content_set_id END;
    PERFORM assert_record_effectively_open(
        (SELECT dc.record_id
           FROM digital_component_content_sets content_set
           JOIN digital_components dc ON dc.id = content_set.digital_component_id
          WHERE content_set.id = target_content_set_id)
    );
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE OR REPLACE FUNCTION protect_content_set_in_closed_aggregation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    target_component_id bigint;
BEGIN
    IF TG_OP='DELETE' AND disposition_private.destruction_active('delete',disposition_private.root_id((SELECT aggregation_id FROM records WHERE id=(SELECT record_id FROM digital_components WHERE id=OLD.digital_component_id)))) THEN RETURN OLD; END IF;

    target_component_id := CASE WHEN TG_OP = 'DELETE'
        THEN OLD.digital_component_id ELSE NEW.digital_component_id END;
    PERFORM assert_record_effectively_open(
        (SELECT record_id FROM digital_components WHERE id = target_component_id)
    );
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA disposition_private FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA disposition_private FROM PUBLIC;
INSERT INTO schema_migrations(version) VALUES('067_disposition_content_erasure') ON CONFLICT DO NOTHING;
