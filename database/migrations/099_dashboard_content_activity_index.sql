-- Bound personal component-view activity by actor and time using a compact
-- covering index rather than scanning unrelated resource/security history.
BEGIN;
CREATE INDEX IF NOT EXISTS event_history_dashboard_content_views_idx
    ON public.event_history (actor_user_id, occurred_at DESC, id DESC) INCLUDE (entity_id, operation)
    WHERE entity_type='digital_component' AND operation='CONTENT_VIEWED';
INSERT INTO schema_migrations(version) VALUES ('099_dashboard_content_activity_index')
    ON CONFLICT (version) DO NOTHING;
COMMIT;
