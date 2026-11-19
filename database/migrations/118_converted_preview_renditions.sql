BEGIN;

-- Private, disposable per-open PDF output shared by all API replicas.
CREATE UNLOGGED TABLE public.preview_renditions (
    open_id uuid PRIMARY KEY,
    session_id bigint NOT NULL REFERENCES public.login_sessions(id) ON DELETE CASCADE,
    content_set_id bigint REFERENCES public.digital_component_content_sets(id) ON DELETE CASCADE,
    draft_component_id bigint REFERENCES public.record_draft_components(id) ON DELETE CASCADE,
    source_checksum text NOT NULL,
    size_in_bytes bigint NOT NULL CHECK (size_in_bytes > 0),
    checksum text NOT NULL,
    rendering_method text NOT NULL,
    expires_at timestamptz NOT NULL,
    CHECK (num_nonnulls(content_set_id, draft_component_id) = 1)
);
CREATE INDEX preview_renditions_session_idx ON public.preview_renditions (session_id);
CREATE INDEX preview_renditions_content_idx ON public.preview_renditions (content_set_id) WHERE content_set_id IS NOT NULL;
CREATE INDEX preview_renditions_draft_idx ON public.preview_renditions (draft_component_id) WHERE draft_component_id IS NOT NULL;
CREATE INDEX preview_renditions_expiry_idx ON public.preview_renditions (expires_at);

CREATE UNLOGGED TABLE public.preview_rendition_chunks (
    open_id uuid NOT NULL REFERENCES public.preview_renditions(open_id) ON DELETE CASCADE,
    chunk_no integer NOT NULL CHECK (chunk_no >= 0),
    content bytea NOT NULL CHECK (octet_length(content) BETWEEN 1 AND 262144),
    PRIMARY KEY (open_id, chunk_no)
);
ALTER TABLE public.preview_rendition_chunks ALTER COLUMN content SET STORAGE EXTERNAL;

INSERT INTO public.schema_migrations(version) VALUES ('118_converted_preview_renditions');
COMMIT;
