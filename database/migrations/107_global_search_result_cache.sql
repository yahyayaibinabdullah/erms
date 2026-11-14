BEGIN;

CREATE UNLOGGED TABLE public.global_search_results (
    session_id bigint NOT NULL REFERENCES public.login_sessions(id) ON DELETE CASCADE,
    tab_id uuid NOT NULL,
    user_id bigint NOT NULL,
    requires_tab_id boolean NOT NULL,
    search_id uuid NOT NULL,
    fingerprint text NOT NULL,
    hits jsonb NOT NULL,
    truncated boolean NOT NULL,
    started_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    PRIMARY KEY (session_id, tab_id),
    CHECK (jsonb_typeof(hits) = 'array' AND jsonb_array_length(hits) <= 1000)
);

CREATE INDEX global_search_results_expiry_idx ON public.global_search_results (expires_at);

INSERT INTO schema_migrations(version) VALUES('107_global_search_result_cache');
COMMIT;
