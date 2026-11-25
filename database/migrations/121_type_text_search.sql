BEGIN;
SELECT set_config('app.event_source','migration',true);
LOCK TABLE public.aggregations, public.records, public.resource_type_values IN SHARE ROW EXCLUSIVE MODE;

-- Field IDs give the source a stable order across renames, translation and form reordering.
CREATE FUNCTION public.resource_type_search_text(p_kind text, p_id bigint)
RETURNS text LANGUAGE sql STABLE STRICT AS $$
    SELECT string_agg((v.value).text_value, ' ' ORDER BY v.field_id)
      FROM public.resource_type_values v
     WHERE v.kind=p_kind AND v.resource_id=p_id AND v.data_type='text'
$$;

CREATE FUNCTION public.resource_metadata_vector(config regconfig, number text, title text, description text, type_text text)
RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT setweight(to_tsvector(config,coalesce(number,'')),'A') ||
           setweight(to_tsvector(config,coalesce(title,'')),'A') ||
           setweight(to_tsvector(config,coalesce(description,'')),'B') ||
           setweight(to_tsvector(config,coalesce(type_text,'')),'B')
$$;

CREATE OR REPLACE FUNCTION public.refresh_aggregation_metadata_search_document() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO aggregation_search_documents(
        aggregation_id,search_vector,text_search_config,indexed_at,index_config_version
    ) VALUES (
        NEW.id,
        public.resource_metadata_vector('pg_catalog.simple',NEW.aggregation_number,NEW.title,NEW.description,
            CASE WHEN NEW.type_id IS NOT NULL THEN public.resource_type_search_text('aggregation',NEW.id) END),
        'pg_catalog.simple'::regconfig,
        CURRENT_TIMESTAMP,
        'fts-metadata-v1'
    )
    ON CONFLICT(aggregation_id) DO UPDATE SET
        search_vector=EXCLUDED.search_vector,
        text_search_config=EXCLUDED.text_search_config,
        indexed_at=EXCLUDED.indexed_at,
        index_config_version=EXCLUDED.index_config_version;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.refresh_record_metadata_search_document() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO record_search_documents(
        record_id,search_vector,text_search_config,indexed_at,index_config_version
    ) VALUES (
        NEW.id,
        public.resource_metadata_vector('pg_catalog.simple',NEW.record_number,NEW.title,NEW.description,
            CASE WHEN NEW.type_id IS NOT NULL THEN public.resource_type_search_text('record',NEW.id) END),
        'pg_catalog.simple'::regconfig,
        CURRENT_TIMESTAMP,
        'fts-metadata-v1'
    )
    ON CONFLICT(record_id) DO UPDATE SET
        search_vector=EXCLUDED.search_vector,
        text_search_config=EXCLUDED.text_search_config,
        indexed_at=EXCLUDED.indexed_at,
        index_config_version=EXCLUDED.index_config_version;
    RETURN NEW;
END;
$$;


-- Value-store statements can affect many fields of either kind. Lock each surviving
-- owner before rereading its complete text, so independent concurrent edits see
-- the latest committed values. Owner deletion itself cascades the document.
CREATE FUNCTION public.refresh_type_metadata_documents(p_kind text, ids bigint[])
RETURNS void LANGUAGE plpgsql STRICT AS $$
DECLARE owners regclass; documents regclass; pk text; number_col text;
BEGIN
    IF p_kind NOT IN ('record','aggregation') THEN RAISE EXCEPTION 'Unknown resource kind'; END IF;
    owners := ('public.' || p_kind || 's')::regclass;
    documents := ('public.' || p_kind || '_search_documents')::regclass;
    pk := p_kind || '_id';
    number_col := p_kind || '_number';
    EXECUTE format('SELECT id FROM %s WHERE id=ANY($1) ORDER BY id FOR NO KEY UPDATE',owners) USING ids;
    EXECUTE format('INSERT INTO %s AS existing (%I,search_vector,text_search_config,indexed_at,index_config_version)
        SELECT r.id,public.resource_metadata_vector(coalesce(d.text_search_config,''pg_catalog.simple''::regconfig),
                   r.%I,r.title,r.description,public.resource_type_search_text($2,r.id)),
               coalesce(d.text_search_config,''pg_catalog.simple''::regconfig),CURRENT_TIMESTAMP,''fts-metadata-v1''
          FROM %s r LEFT JOIN %s d ON d.%I=r.id WHERE r.id=ANY($1)
         ORDER BY r.id
        ON CONFLICT (%I) DO UPDATE SET search_vector=EXCLUDED.search_vector,indexed_at=EXCLUDED.indexed_at
        WHERE existing.search_vector IS DISTINCT FROM EXCLUDED.search_vector',
        documents,pk,number_col,owners,documents,pk,pk) USING ids,p_kind;
END $$;

CREATE FUNCTION public.refresh_changed_type_search_text() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE changes text; batch record;
BEGIN
    IF TG_OP='UPDATE' THEN
        -- Capacity updates and writes to non-text fields have no search effect.
        changes := 'SELECT kind,resource_id FROM (
            (SELECT kind,resource_id,field_id,(value).text_value FROM new_values WHERE data_type=''text''
             EXCEPT SELECT kind,resource_id,field_id,(value).text_value FROM old_values WHERE data_type=''text'')
            UNION ALL
            (SELECT kind,resource_id,field_id,(value).text_value FROM old_values WHERE data_type=''text''
             EXCEPT SELECT kind,resource_id,field_id,(value).text_value FROM new_values WHERE data_type=''text'')
        ) changed';
    ELSE
        changes := format('SELECT kind,resource_id FROM %I WHERE data_type=''text''',
                          CASE WHEN TG_OP='INSERT' THEN 'new_values' ELSE 'old_values' END);
    END IF;
    FOR batch IN EXECUTE 'SELECT kind,array_agg(DISTINCT resource_id ORDER BY resource_id) AS ids
        FROM (' || changes || ') changed GROUP BY kind,resource_id / 10000 ORDER BY kind,resource_id / 10000'
    LOOP
        PERFORM public.refresh_type_metadata_documents(batch.kind,batch.ids);
    END LOOP;
    RETURN NULL;
END $$;

-- PostgreSQL fires statement triggers on the explicit target relation. Cover both
-- writes through the partitioned parent and writes directly to a kind partition.
CREATE TRIGGER refresh_type_text_insert AFTER INSERT ON public.resource_type_values
    REFERENCING NEW TABLE AS new_values FOR EACH STATEMENT EXECUTE FUNCTION public.refresh_changed_type_search_text();
CREATE TRIGGER refresh_type_text_update AFTER UPDATE ON public.resource_type_values
    REFERENCING OLD TABLE AS old_values NEW TABLE AS new_values FOR EACH STATEMENT EXECUTE FUNCTION public.refresh_changed_type_search_text();
CREATE TRIGGER refresh_type_text_delete AFTER DELETE ON public.resource_type_values
    REFERENCING OLD TABLE AS old_values FOR EACH STATEMENT EXECUTE FUNCTION public.refresh_changed_type_search_text();
CREATE TRIGGER refresh_type_text_insert AFTER INSERT ON public.record_type_values
    REFERENCING NEW TABLE AS new_values FOR EACH STATEMENT EXECUTE FUNCTION public.refresh_changed_type_search_text();
CREATE TRIGGER refresh_type_text_update AFTER UPDATE ON public.record_type_values
    REFERENCING OLD TABLE AS old_values NEW TABLE AS new_values FOR EACH STATEMENT EXECUTE FUNCTION public.refresh_changed_type_search_text();
CREATE TRIGGER refresh_type_text_delete AFTER DELETE ON public.record_type_values
    REFERENCING OLD TABLE AS old_values FOR EACH STATEMENT EXECUTE FUNCTION public.refresh_changed_type_search_text();
CREATE TRIGGER refresh_type_text_insert AFTER INSERT ON public.aggregation_type_values
    REFERENCING NEW TABLE AS new_values FOR EACH STATEMENT EXECUTE FUNCTION public.refresh_changed_type_search_text();
CREATE TRIGGER refresh_type_text_update AFTER UPDATE ON public.aggregation_type_values
    REFERENCING OLD TABLE AS old_values NEW TABLE AS new_values FOR EACH STATEMENT EXECUTE FUNCTION public.refresh_changed_type_search_text();
CREATE TRIGGER refresh_type_text_delete AFTER DELETE ON public.aggregation_type_values
    REFERENCING OLD TABLE AS old_values FOR EACH STATEMENT EXECUTE FUNCTION public.refresh_changed_type_search_text();

-- Only resources with stored text need a populated upgrade. Other search
-- documents retain their vector, timestamps and version. Bound each refresh.
SELECT public.refresh_type_metadata_documents(kind,array_agg(DISTINCT resource_id ORDER BY resource_id))
  FROM public.resource_type_values WHERE data_type='text'
 GROUP BY kind,resource_id / 10000 ORDER BY kind,resource_id / 10000;

INSERT INTO public.schema_migrations(version) VALUES ('121_type_text_search');
COMMIT;
