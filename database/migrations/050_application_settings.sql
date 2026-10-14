BEGIN;

-- Shared configuration foundation. Categories belong only to the Python registry.
CREATE TABLE IF NOT EXISTS application_settings_state (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 database_id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
 installation_kind text NOT NULL CHECK(installation_kind IN ('fresh','upgrade'))
);
INSERT INTO application_settings_state(singleton,installation_kind)
 VALUES(true,'upgrade') ON CONFLICT(singleton) DO NOTHING;
CREATE TABLE IF NOT EXISTS application_settings (
 id bigserial UNIQUE NOT NULL,
 key text PRIMARY KEY,
 value jsonb NOT NULL,
 protected_secret bytea,
 provenance text NOT NULL DEFAULT 'default' CHECK(provenance IN ('default','configured','migrated')),
 version bigint NOT NULL DEFAULT 1 CHECK(version>0),
 date_updated timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_by_user_id bigint,
 scheme_reference_id bigint GENERATED ALWAYS AS
  (CASE WHEN key='DISPOSITION_CLASSIFICATION_SCHEME_ID' AND jsonb_typeof(value)='number'
    THEN (value#>>'{}')::bigint END) STORED REFERENCES classification_schemes(id) ON DELETE RESTRICT,
 classification_reference_id bigint GENERATED ALWAYS AS
  (CASE WHEN key IN ('DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID','DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID')
    AND jsonb_typeof(value)='number' THEN (value#>>'{}')::bigint END)
  STORED REFERENCES classifications(id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS application_settings_migration_keys (
 migration_id text NOT NULL CHECK(btrim(migration_id)<>''),
 key text NOT NULL REFERENCES application_settings(key) ON DELETE RESTRICT,
 completed_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 completed_by_user_id bigint NOT NULL,
 resulting_version bigint NOT NULL CHECK(resulting_version>0),
 PRIMARY KEY(migration_id,key)
);
CREATE OR REPLACE FUNCTION application_setting_value_valid(p_key text,p_value jsonb,p_secret bytea)
 RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT COALESCE(CASE p_key
 WHEN 'DEFAULT_WORKING_TIMEZONE' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]' AND EXISTS(SELECT 1 FROM pg_timezone_names WHERE name=p_value#>>'{}'))
 WHEN 'DEFAULT_ROOT_AGGREGATION_MEDIUM' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]' AND (p_value#>>'{}') IN ('digital','physical','mixed'))
 WHEN 'REVIEW_WARNING_WINDOW_DAYS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 0 AND 9223372036854775807)
 WHEN 'MAX_UPLOAD_SIZE_BYTES' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'CONTENT_SEGMENT_SIZE_BYTES' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 67108864)
 WHEN 'CONTENT_SEGMENT_CHECKSUMS_ENABLED' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='boolean')
 WHEN 'CONTENT_UPLOAD_SESSION_TTL_SECONDS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'CONTENT_CLEANUP_INTERVAL_SECONDS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'DOCUMENT_CONVERSION_TIMEOUT_SECONDS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'MAX_RENDITION_SIZE_BYTES' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'AUTH_SESSION_IDLE_MINUTES' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'AUTH_SESSION_ABSOLUTE_HOURS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'AUTH_LOCKOUT_ATTEMPTS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'AUTH_LOCKOUT_MINUTES' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'AUTH_PASSWORD_MIN_LENGTH' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 8 AND 9223372036854775807)
 WHEN 'AUTH_SESSION_RETENTION_DAYS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 0 AND 9223372036854775807)
 WHEN 'AUTH_SESSION_CLEANUP_INTERVAL_SECONDS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'AUTH_SESSION_CLEANUP_BATCH_SIZE' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'DASHBOARD_FAVOURITE_ITEM_LIMIT' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'DASHBOARD_RECENT_ITEM_LIMIT' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'DASHBOARD_RECENT_DAYS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'DASHBOARD_REVIEW_PREVIEW_LIMIT' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'CLASSIFICATION_RECENT_SELECTION_LIMIT' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'USER_DETAILS_SESSION_LIMIT' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'FULL_TEXT_SEARCH_ENABLED' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='boolean')
 WHEN 'CONTENT_INDEXING_SCHEDULING_ENABLED' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='boolean')
 WHEN 'CONTENT_INDEXING_HISTORY_RETENTION_DAYS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 0 AND 9223372036854775807)
 WHEN 'CONTENT_INDEXING_CLEANUP_INTERVAL_SECONDS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'CONTENT_INDEXING_CLEANUP_BATCH_SIZE' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'TEXT_INDEXER_CREDENTIAL_HISTORY_RETENTION_DAYS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 0 AND 9223372036854775807)
 WHEN 'TEXT_INDEXER_RATE_LIMIT_PER_MINUTE' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'SEARCH_RATE_LIMIT_PER_MINUTE' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'MANUAL_REINDEX_RATE_LIMIT_PER_MINUTE' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'AUDIT_TRAIL_SEARCH_RESULT_LIMIT' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'DISPOSITION_DESTRUCTION_REVIEW_ROUTE' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]' AND (p_value#>>'{}') IN ('standard','simplified','records_manager_only'))
 WHEN 'DISPOSITION_CLASSIFICATION_SCHEME_ID' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)))
 WHEN 'DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)))
 WHEN 'DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)))
 WHEN 'DISPOSITION_EXTERNAL_AUTHORITY_NAME' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]')
 WHEN 'DISPOSITION_EXTERNAL_AUTHORITY_EMAIL' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]' AND (p_value#>>'{}') ~ '^[^[:space:]@]+@[^[:space:]@]+$')))
 WHEN 'DISPOSITION_DESTRUCTION_REMINDER_MONTHS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 WHEN 'SMTP_HOST' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]')))
 WHEN 'SMTP_PORT' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 65535)))
 WHEN 'SMTP_SECURITY' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]' AND (p_value#>>'{}') IN ('starttls','implicit_tls'))))
 WHEN 'SMTP_AUTH_ENABLED' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='boolean')))
 WHEN 'SMTP_USERNAME' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]')))
 WHEN 'SMTP_PASSWORD' THEN p_value='null'::jsonb AND (p_secret IS NULL OR convert_from(p_secret,'UTF8') ~ '^fernet:v1:[A-Za-z0-9_=-]+$')
 WHEN 'SMTP_SENDER_EMAIL' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]' AND (p_value#>>'{}') ~ '^[^[:space:]@]+@[^[:space:]@]+$')))
 WHEN 'SMTP_SENDER_NAME' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]')))
 WHEN 'SMTP_REPLY_TO_EMAIL' THEN p_secret IS NULL AND ((p_value='null'::jsonb OR (jsonb_typeof(p_value)='string' AND btrim(p_value#>>'{}')<>'' AND (p_value#>>'{}') !~ E'[\r\n]' AND (p_value#>>'{}') ~ '^[^[:space:]@]+@[^[:space:]@]+$')))
 WHEN 'SMTP_TIMEOUT_SECONDS' THEN p_secret IS NULL AND (jsonb_typeof(p_value)='number' AND p_value::text ~ '^[0-9]+$' AND (p_value#>>'{}')::numeric BETWEEN 1 AND 9223372036854775807)
 ELSE false END,false)
$$;
CREATE OR REPLACE FUNCTION guard_application_setting() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE installer boolean;
BEGIN
 installer := current_user_id() IS NULL AND
  COALESCE(current_setting('app.event_source',true),'') IN ('seeding','migration');
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='application_settings_protected';
 END IF;
 IF TG_OP='INSERT' AND NOT installer THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='application_settings_protected';
 END IF;
 IF TG_OP='UPDATE' THEN
  IF NOT user_has_global_privilege(current_user_id(),'app.settings.manage') OR
     NOT EXISTS(SELECT 1 FROM users WHERE id=current_user_id() AND account_type='person' AND status='active') THEN
   RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='application_settings_access_denied';
  END IF;
  IF btrim(COALESCE(current_setting('app.change_reason',true),''))='' THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_reason_required';
  END IF;
  IF (NEW.id,NEW.key) IS DISTINCT FROM (OLD.id,OLD.key) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_identity_immutable';
  END IF;
  NEW.version:=OLD.version+1;
  NEW.date_updated:=CURRENT_TIMESTAMP;
  NEW.updated_by_user_id:=current_user_id();
  IF NEW.provenance='default' THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_provenance_invalid';
  END IF;
 END IF;
 IF NOT application_setting_value_valid(NEW.key,NEW.value,NEW.protected_secret) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_setting_value_invalid';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS application_settings_guard ON application_settings;
CREATE TRIGGER application_settings_guard BEFORE INSERT OR UPDATE OR DELETE ON application_settings
 FOR EACH ROW EXECUTE FUNCTION guard_application_setting();
CREATE OR REPLACE FUNCTION audit_application_setting() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE safe jsonb;
BEGIN
 safe:=jsonb_build_object('setting_key',NEW.key,'version',NEW.version,'provenance',NEW.provenance);
 IF NEW.key='SMTP_PASSWORD' THEN
  safe:=safe||jsonb_build_object('credential_changed',TG_OP='UPDATE','is_set',NEW.protected_secret IS NOT NULL);
 ELSE
  safe:=safe||jsonb_build_object('new_value',NEW.value,
   'old_value',CASE WHEN TG_OP='UPDATE' THEN OLD.value END);
 END IF;
 PERFORM append_domain_event('application_setting',NEW.id,
  CASE WHEN TG_OP='INSERT' THEN 'APPLICATION_SETTING_SEEDED' ELSE 'APPLICATION_SETTING_CHANGED' END,safe);
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS application_settings_audit ON application_settings;
CREATE TRIGGER application_settings_audit AFTER INSERT OR UPDATE ON application_settings
 FOR EACH ROW EXECUTE FUNCTION audit_application_setting();
CREATE OR REPLACE FUNCTION application_settings_set_valid() RETURNS boolean LANGUAGE sql STABLE AS $$
 WITH dest AS (
  SELECT (SELECT value FROM application_settings WHERE key='DISPOSITION_CLASSIFICATION_SCHEME_ID') AS scheme
 ), auth AS (
  SELECT (SELECT value FROM application_settings WHERE key='SMTP_AUTH_ENABLED') AS enabled,
   (SELECT value FROM application_settings WHERE key='SMTP_USERNAME') AS username,
   (SELECT protected_secret IS NOT NULL FROM application_settings WHERE key='SMTP_PASSWORD') AS password_set
 )
 SELECT NOT EXISTS(
  SELECT 1 FROM application_settings s LEFT JOIN classifications c ON c.id=s.classification_reference_id
  CROSS JOIN dest WHERE s.classification_reference_id IS NOT NULL AND
   (dest.scheme='null'::jsonb OR NOT c.is_terminal OR c.classification_scheme_id<>(dest.scheme#>>'{}')::bigint)
 ) AND NOT EXISTS(SELECT 1 FROM auth WHERE enabled='true'::jsonb
  AND (username='null'::jsonb OR NOT password_set))

$$;
CREATE OR REPLACE FUNCTION check_application_settings_set() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT application_settings_set_valid() THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_group_inconsistent';
 END IF;
 RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS application_settings_set_constraint ON application_settings;
CREATE CONSTRAINT TRIGGER application_settings_set_constraint AFTER INSERT OR UPDATE ON application_settings
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_application_settings_set();
DROP TRIGGER IF EXISTS classifications_settings_destination_constraint ON classifications;
CREATE CONSTRAINT TRIGGER classifications_settings_destination_constraint AFTER UPDATE ON classifications
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_application_settings_set();
CREATE OR REPLACE FUNCTION guard_settings_migration_completion() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' OR NOT user_has_global_privilege(current_user_id(),'app.settings.manage') OR
    btrim(COALESCE(current_setting('app.change_reason',true),''))='' OR
    NEW.completed_by_user_id<>current_user_id() OR
    NEW.resulting_version<>(SELECT version FROM application_settings WHERE key=NEW.key) THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='application_settings_completion_protected';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS application_settings_migration_guard ON application_settings_migration_keys;
CREATE TRIGGER application_settings_migration_guard BEFORE INSERT OR UPDATE OR DELETE ON application_settings_migration_keys
 FOR EACH ROW EXECUTE FUNCTION guard_settings_migration_completion();
CREATE OR REPLACE FUNCTION apply_application_settings(p_changes jsonb,p_reason text,p_migration_id text DEFAULT NULL)
 RETURNS void LANGUAGE plpgsql AS $$
DECLARE item jsonb; old_row application_settings%ROWTYPE; submitted text[]; related text[];
 previous_reason text; previous_source text; new_value jsonb; new_secret bytea; group_name text;
BEGIN
 IF NOT user_has_global_privilege(current_user_id(),'app.settings.manage') OR
    NOT EXISTS(SELECT 1 FROM users WHERE id=current_user_id() AND account_type='person' AND status='active') THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='application_settings_access_denied';
 END IF;
 IF btrim(COALESCE(p_reason,''))='' THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_reason_required';
 END IF;
 IF jsonb_typeof(p_changes)<>'array' OR jsonb_array_length(p_changes) NOT BETWEEN 1 AND 51 THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_invalid_update';
 END IF;
 SELECT array_agg(value->>'key' ORDER BY value->>'key') INTO submitted FROM jsonb_array_elements(p_changes);
 IF cardinality(submitted)<>(SELECT count(DISTINCT k) FROM unnest(submitted) k) OR
    EXISTS(SELECT 1 FROM unnest(submitted) k WHERE k IS NULL OR NOT EXISTS(SELECT 1 FROM application_settings WHERE key=k)) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_invalid_update';
 END IF;
 FOREACH group_name IN ARRAY ARRAY['destinations','smtp'] LOOP
  related:=CASE group_name WHEN 'destinations' THEN ARRAY['DISPOSITION_CLASSIFICATION_SCHEME_ID','DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID','DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID']::text[] ELSE ARRAY['SMTP_AUTH_ENABLED','SMTP_HOST','SMTP_PASSWORD','SMTP_PORT','SMTP_REPLY_TO_EMAIL','SMTP_SECURITY','SMTP_SENDER_EMAIL','SMTP_SENDER_NAME','SMTP_TIMEOUT_SECONDS','SMTP_USERNAME']::text[] END;
  IF submitted&&related AND NOT submitted@>related THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_group_required';
  END IF;
 END LOOP;
 IF p_migration_id IS NOT NULL AND btrim(p_migration_id)='' THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_invalid_update';
 END IF;
 -- Stable row lock order shared with concurrent grouped administration/migration.
 PERFORM 1 FROM application_settings WHERE key=ANY(submitted) ORDER BY key FOR UPDATE;
 previous_reason:=current_setting('app.change_reason',true);
 previous_source:=current_setting('app.event_source',true);
 PERFORM set_config('app.change_reason',p_reason,true);
 IF p_migration_id IS NOT NULL THEN PERFORM set_config('app.event_source','migration',true); END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(p_changes) ORDER BY value->>'key' LOOP
  SELECT * INTO old_row FROM application_settings WHERE key=item->>'key';
  IF p_migration_id IS NOT NULL AND EXISTS(SELECT 1 FROM application_settings_migration_keys
    WHERE migration_id=p_migration_id AND key=old_row.key) THEN CONTINUE; END IF;
  IF NOT COALESCE(jsonb_typeof(item->'expected_version')='number' AND item->>'expected_version' ~ '^[1-9][0-9]*$' AND
     (item->>'expected_version')::numeric=old_row.version,false) THEN
   RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='application_settings_stale_version';
  END IF;
  new_value:=COALESCE(item->'value',old_row.value);
  new_secret:=CASE WHEN item ? 'encrypted_secret' THEN
   CASE WHEN item->>'encrypted_secret' IS NULL THEN NULL ELSE convert_to(item->>'encrypted_secret','UTF8') END
   ELSE old_row.protected_secret END;
  IF old_row.key='SMTP_PASSWORD' AND new_value<>'null'::jsonb THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_setting_value_invalid';
  END IF;
  IF p_migration_id IS NOT NULL AND old_row.provenance<>'default' AND
     (new_value,new_secret) IS DISTINCT FROM (old_row.value,old_row.protected_secret) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_migration_conflict';
  END IF;
  IF (p_migration_id IS NULL AND (item ? 'value' OR item ? 'encrypted_secret')) OR
     (p_migration_id IS NOT NULL AND old_row.provenance='default' AND (item ? 'value' OR item ? 'encrypted_secret')) THEN
   UPDATE application_settings SET value=new_value,protected_secret=new_secret,
    provenance=CASE WHEN p_migration_id IS NULL THEN 'configured' ELSE 'migrated' END WHERE key=old_row.key;
  END IF;
  IF p_migration_id IS NOT NULL THEN
   INSERT INTO application_settings_migration_keys(migration_id,key,completed_by_user_id,resulting_version)
    SELECT p_migration_id,key,current_user_id(),version FROM application_settings WHERE key=old_row.key;
   PERFORM append_domain_event('application_setting',old_row.id,'APPLICATION_SETTINGS_MIGRATION_COMPLETED',
    jsonb_build_object('setting_key',old_row.key,'migration_id',p_migration_id));
  END IF;
 END LOOP;
 IF NOT application_settings_set_valid() THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='application_settings_group_inconsistent';
 END IF;
 PERFORM set_config('app.change_reason',COALESCE(previous_reason,''),true);
 PERFORM set_config('app.event_source',COALESCE(previous_source,''),true);
END $$;

CREATE OR REPLACE FUNCTION reject_application_settings_removal() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='application_settings_protected'; END $$;
DROP TRIGGER IF EXISTS application_settings_reject_truncate ON application_settings;
CREATE TRIGGER application_settings_reject_truncate BEFORE TRUNCATE ON application_settings
 FOR EACH STATEMENT EXECUTE FUNCTION reject_application_settings_removal();
DROP TRIGGER IF EXISTS application_settings_state_immutable ON application_settings_state;
CREATE TRIGGER application_settings_state_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON application_settings_state
 FOR EACH STATEMENT EXECUTE FUNCTION reject_application_settings_removal();
DROP TRIGGER IF EXISTS application_settings_migration_reject_truncate ON application_settings_migration_keys;
CREATE TRIGGER application_settings_migration_reject_truncate BEFORE TRUNCATE ON application_settings_migration_keys
 FOR EACH STATEMENT EXECUTE FUNCTION reject_application_settings_removal();

-- Defaults are installation data, not configuration imported from an environment.
DO $$
DECLARE previous_source text:=current_setting('app.event_source',true);
BEGIN
 PERFORM set_config('app.event_source','seeding',true);
 INSERT INTO application_settings(key,value) VALUES
  ('DEFAULT_WORKING_TIMEZONE','"Asia/Dubai"'::jsonb),
  ('DEFAULT_ROOT_AGGREGATION_MEDIUM','"mixed"'::jsonb),
  ('REVIEW_WARNING_WINDOW_DAYS','30'::jsonb),
  ('MAX_UPLOAD_SIZE_BYTES','52428800'::jsonb),
  ('CONTENT_SEGMENT_SIZE_BYTES','16777216'::jsonb),
  ('CONTENT_SEGMENT_CHECKSUMS_ENABLED','true'::jsonb),
  ('CONTENT_UPLOAD_SESSION_TTL_SECONDS','86400'::jsonb),
  ('CONTENT_CLEANUP_INTERVAL_SECONDS','3600'::jsonb),
  ('DOCUMENT_CONVERSION_TIMEOUT_SECONDS','60'::jsonb),
  ('MAX_RENDITION_SIZE_BYTES','104857600'::jsonb),
  ('AUTH_SESSION_IDLE_MINUTES','30'::jsonb),
  ('AUTH_SESSION_ABSOLUTE_HOURS','12'::jsonb),
  ('AUTH_LOCKOUT_ATTEMPTS','5'::jsonb),
  ('AUTH_LOCKOUT_MINUTES','15'::jsonb),
  ('AUTH_PASSWORD_MIN_LENGTH','12'::jsonb),
  ('AUTH_SESSION_RETENTION_DAYS','90'::jsonb),
  ('AUTH_SESSION_CLEANUP_INTERVAL_SECONDS','3600'::jsonb),
  ('AUTH_SESSION_CLEANUP_BATCH_SIZE','500'::jsonb),
  ('DASHBOARD_FAVOURITE_ITEM_LIMIT','5'::jsonb),
  ('DASHBOARD_RECENT_ITEM_LIMIT','4'::jsonb),
  ('DASHBOARD_RECENT_DAYS','30'::jsonb),
  ('DASHBOARD_REVIEW_PREVIEW_LIMIT','5'::jsonb),
  ('CLASSIFICATION_RECENT_SELECTION_LIMIT','4'::jsonb),
  ('USER_DETAILS_SESSION_LIMIT','5'::jsonb),
  ('FULL_TEXT_SEARCH_ENABLED','false'::jsonb),
  ('CONTENT_INDEXING_SCHEDULING_ENABLED','false'::jsonb),
  ('CONTENT_INDEXING_HISTORY_RETENTION_DAYS','365'::jsonb),
  ('CONTENT_INDEXING_CLEANUP_INTERVAL_SECONDS','3600'::jsonb),
  ('CONTENT_INDEXING_CLEANUP_BATCH_SIZE','500'::jsonb),
  ('TEXT_INDEXER_CREDENTIAL_HISTORY_RETENTION_DAYS','365'::jsonb),
  ('TEXT_INDEXER_RATE_LIMIT_PER_MINUTE','600'::jsonb),
  ('SEARCH_RATE_LIMIT_PER_MINUTE','600'::jsonb),
  ('MANUAL_REINDEX_RATE_LIMIT_PER_MINUTE','60'::jsonb),
  ('AUDIT_TRAIL_SEARCH_RESULT_LIMIT','1000'::jsonb),
  ('DISPOSITION_DESTRUCTION_REVIEW_ROUTE','"standard"'::jsonb),
  ('DISPOSITION_CLASSIFICATION_SCHEME_ID','null'::jsonb),
  ('DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID','null'::jsonb),
  ('DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID','null'::jsonb),
  ('DISPOSITION_EXTERNAL_AUTHORITY_NAME','"Sharjah Archives"'::jsonb),
  ('DISPOSITION_EXTERNAL_AUTHORITY_EMAIL','null'::jsonb),
  ('DISPOSITION_DESTRUCTION_REMINDER_MONTHS','6'::jsonb),
  ('SMTP_HOST','null'::jsonb),
  ('SMTP_PORT','null'::jsonb),
  ('SMTP_SECURITY','null'::jsonb),
  ('SMTP_AUTH_ENABLED','null'::jsonb),
  ('SMTP_USERNAME','null'::jsonb),
  ('SMTP_PASSWORD','null'::jsonb),
  ('SMTP_SENDER_EMAIL','null'::jsonb),
  ('SMTP_SENDER_NAME','null'::jsonb),
  ('SMTP_REPLY_TO_EMAIL','null'::jsonb),
  ('SMTP_TIMEOUT_SECONDS','30'::jsonb)
 ON CONFLICT(key) DO NOTHING;
 PERFORM set_config('app.event_source',COALESCE(previous_source,''),true);
END $$;
INSERT INTO privileges(code,name,description,category)
 VALUES('app.settings.manage','Manage Application Settings','Manage validated application configuration and protected SMTP credentials.','administration')
 ON CONFLICT DO NOTHING;
INSERT INTO profile_privileges(profile_id,privilege_id)
 SELECT p.id,v.id FROM profiles p CROSS JOIN privileges v WHERE p.code IN ('SYS_ADMIN','ALL_PRIVS') AND v.code='app.settings.manage'
 ON CONFLICT DO NOTHING;
INSERT INTO schema_migrations(version) VALUES('050_application_settings') ON CONFLICT DO NOTHING;

COMMIT;
