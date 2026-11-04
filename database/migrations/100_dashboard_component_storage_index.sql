-- Cover record-scoped component totals without loading component metadata.
BEGIN;
CREATE INDEX IF NOT EXISTS digital_components_dashboard_storage_idx
    ON public.digital_components (record_id) INCLUDE (size_in_bytes);
INSERT INTO schema_migrations(version) VALUES ('100_dashboard_component_storage_index')
    ON CONFLICT (version) DO NOTHING;
COMMIT;
