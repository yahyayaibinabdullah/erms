-- Use database indexing policy when an explicit API session context is absent.
-- Upgrade only: new empty databases use database/schema.sql alone.
BEGIN;

CREATE OR REPLACE FUNCTION schedule_component_content_indexing()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    active_set digital_component_content_sets%ROWTYPE;
    schedule_trigger text;
BEGIN
    IF NEW.content_status<>'available' OR NEW.active_content_set_id IS NULL THEN
        UPDATE digital_component_search_documents SET status='stale',date_updated=CURRENT_TIMESTAMP
         WHERE digital_component_id=NEW.id;
        RETURN NEW;
    END IF;
    SELECT * INTO STRICT active_set FROM digital_component_content_sets
     WHERE id=NEW.active_content_set_id AND digital_component_id=NEW.id AND status='active';
    schedule_trigger:=CASE WHEN TG_OP='INSERT' OR OLD.active_content_set_id IS NULL THEN 'upload' ELSE 'replacement' END;
    UPDATE digital_component_search_documents SET status='stale',date_updated=CURRENT_TIMESTAMP
     WHERE digital_component_id=NEW.id AND content_set_id IS DISTINCT FROM active_set.id;
    INSERT INTO digital_component_search_documents(
        digital_component_id,record_id,content_set_id,content_checksum_algo,content_checksum_value,
        status,extraction_config_version,index_config_version,date_updated
    ) VALUES (NEW.id,NEW.record_id,active_set.id,active_set.checksum_algo,active_set.checksum_value,
              'pending','tika-4.0.0-ocr-eng-ara-v1','fts-content-v1',CURRENT_TIMESTAMP)
    ON CONFLICT(digital_component_id) DO UPDATE SET
        record_id=EXCLUDED.record_id,content_set_id=EXCLUDED.content_set_id,
        content_checksum_algo=EXCLUDED.content_checksum_algo,
        content_checksum_value=EXCLUDED.content_checksum_value,status='pending',
        extraction_config_version=EXCLUDED.extraction_config_version,
        index_config_version=EXCLUDED.index_config_version,indexed_at=NULL,
        last_error_code=NULL,last_error_summary=NULL,date_updated=CURRENT_TIMESTAMP;
    IF coalesce(nullif(current_setting('app.content_indexing_scheduling_enabled',true),''),
        (SELECT value#>>'{}' FROM application_settings WHERE key='CONTENT_INDEXING_SCHEDULING_ENABLED'))::boolean IS DISTINCT FROM true THEN
        RETURN NEW;
    END IF;
    INSERT INTO content_indexing_jobs(
        digital_component_id,record_id,content_set_id,content_checksum_algo,content_checksum_value,
        trigger,extraction_config_version,index_config_version,extractor_version,required_capabilities
    ) VALUES (NEW.id,NEW.record_id,active_set.id,active_set.checksum_algo,active_set.checksum_value,
              schedule_trigger,'tika-4.0.0-ocr-eng-ara-v1','fts-content-v1','4.0.0',
              jsonb_build_object('mime_type',NEW.mime_type,'max_input_bytes',52428800))
    ON CONFLICT(digital_component_id,content_set_id,extraction_config_version,index_config_version,extractor_version)
        WHERE status IN ('queued','leased') DO NOTHING;
    RETURN NEW;
END $$;

INSERT INTO schema_migrations(version) VALUES('051_database_indexing_policy') ON CONFLICT DO NOTHING;
COMMIT;
