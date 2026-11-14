BEGIN;

-- All record/aggregation search screens now share this existing UNLOGGED slot.
-- Rename in place: preserve entries, expiry, login-session cascade, indexes and
-- the (session_id, tab_id) key. Deploy the API and cleanup worker together after
-- this migration; older binaries refer to the previous table name.
ALTER TABLE public.global_search_results RENAME TO search_results_cache;
ALTER TABLE public.search_results_cache RENAME CONSTRAINT global_search_results_pkey TO search_results_cache_pkey;
ALTER TABLE public.search_results_cache RENAME CONSTRAINT global_search_results_hits_check TO search_results_cache_hits_check;
ALTER TABLE public.search_results_cache RENAME CONSTRAINT global_search_results_session_id_fkey TO search_results_cache_session_id_fkey;
ALTER INDEX public.global_search_results_expiry_idx RENAME TO search_results_cache_expiry_idx;

INSERT INTO public.schema_migrations(version) VALUES ('111_shared_search_results_cache');
COMMIT;
