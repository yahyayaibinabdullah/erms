-- Retained destroyed metadata must not enlarge dashboard live-resource scans.
-- Keep these narrow: titles and other mutable/large metadata stay in the heap.
BEGIN;
CREATE INDEX IF NOT EXISTS aggregations_dashboard_live_idx
    ON public.aggregations (id) WHERE disposition_status<>10;
CREATE INDEX IF NOT EXISTS records_dashboard_live_idx
    ON public.records (id) WHERE disposition_status<>10;
INSERT INTO schema_migrations(version) VALUES ('101_dashboard_live_resource_indexes')
    ON CONFLICT (version) DO NOTHING;
COMMIT;
