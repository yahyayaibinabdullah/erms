-- Snapshot the selected scheme/classification identities in Settings events.
-- Upgrade only: new empty databases use database/schema.sql alone.
-- Existing immutable audit events and configured settings are unchanged.
BEGIN;

CREATE OR REPLACE FUNCTION audit_application_setting() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE safe jsonb; reference_field text;
BEGIN
 safe:=jsonb_build_object('setting_key',NEW.key,'version',NEW.version,'provenance',NEW.provenance);
 IF NEW.key='SMTP_PASSWORD' THEN
  safe:=safe||jsonb_build_object('credential_changed',TG_OP='UPDATE','is_set',NEW.protected_secret IS NOT NULL);
 ELSE
  safe:=safe||jsonb_build_object('new_value',NEW.value,
   'old_value',CASE WHEN TG_OP='UPDATE' THEN OLD.value END);
  reference_field:=CASE
   WHEN NEW.key='DISPOSITION_CLASSIFICATION_SCHEME_ID' THEN 'classification_scheme_id'
   WHEN NEW.key IN ('DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID',
                   'DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID') THEN 'classification_id'
  END;
  IF reference_field IS NOT NULL THEN
   -- Persist identities at the change, rather than resolving mutable names
   -- when an administrator later opens the historical event.
   safe:=safe||jsonb_build_object(
    'new_reference',event_reference_identity(reference_field,(NEW.value#>>'{}')::bigint),
    'old_reference',CASE WHEN TG_OP='UPDATE' THEN
     event_reference_identity(reference_field,(OLD.value#>>'{}')::bigint) END);
  END IF;
 END IF;
 PERFORM append_domain_event('application_setting',NEW.id,
  CASE WHEN TG_OP='INSERT' THEN 'APPLICATION_SETTING_SEEDED' ELSE 'APPLICATION_SETTING_CHANGED' END,safe);
 RETURN NEW;
END $$;

INSERT INTO schema_migrations(version) VALUES('052_application_settings_reference_audit') ON CONFLICT DO NOTHING;
COMMIT;
