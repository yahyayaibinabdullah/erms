-- Match dashboard latest-per-resource activity ordering without sorting the
-- complete actor history. This index contains only governed resource edits.
BEGIN;
CREATE INDEX IF NOT EXISTS event_history_dashboard_resource_latest_idx
    ON public.event_history (actor_user_id, entity_type, entity_id, operation, occurred_at DESC, id DESC)
    WHERE entity_type IN ('aggregation', 'record') AND operation IN ('CREATE', 'UPDATE');
INSERT INTO schema_migrations(version) VALUES ('098_dashboard_resource_activity_index')
    ON CONFLICT (version) DO NOTHING;
COMMIT;
