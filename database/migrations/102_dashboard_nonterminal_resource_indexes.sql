-- All completed disposition outcomes are outside the dashboard live scope.
-- Replace the already-deployed status-10-only indexes without rewriting 101.
BEGIN;
DROP INDEX IF EXISTS public.aggregations_dashboard_live_idx;
DROP INDEX IF EXISTS public.records_dashboard_live_idx;
CREATE INDEX aggregations_dashboard_live_idx
    ON public.aggregations (id) WHERE disposition_status NOT IN (10,11,12);
CREATE INDEX records_dashboard_live_idx
    ON public.records (id) WHERE disposition_status NOT IN (10,11,12);
INSERT INTO schema_migrations(version) VALUES ('102_dashboard_nonterminal_resource_indexes')
    ON CONFLICT (version) DO NOTHING;
COMMIT;
