-- Indexed filenames and uncommon text configurations; existing data is preserved.
BEGIN;
CREATE INDEX digital_components_filename_vector_gin ON public.digital_components
    USING gin (to_tsvector('pg_catalog.simple', coalesce(file_name, '')));

CREATE INDEX component_search_other_config_idx ON public.digital_component_search_chunks (text_search_config)
    WHERE text_search_config NOT IN ('pg_catalog.simple'::regconfig, 'pg_catalog.english'::regconfig, 'pg_catalog.arabic'::regconfig);

CREATE INDEX record_search_other_config_idx ON public.record_search_documents (text_search_config)
    WHERE text_search_config <> 'pg_catalog.simple'::regconfig;

CREATE INDEX aggregation_search_other_config_idx ON public.aggregation_search_documents (text_search_config)
    WHERE text_search_config <> 'pg_catalog.simple'::regconfig;

INSERT INTO public.schema_migrations(version) VALUES ('109_search_candidate_indexes');
COMMIT;
