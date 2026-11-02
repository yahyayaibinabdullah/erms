-- Permit compatible medium changes without rewriting contained resources.
BEGIN;
CREATE OR REPLACE FUNCTION public.aggregation_medium_contents_compatible(p_aggregation bigint, p_medium text) RETURNS boolean
    LANGUAGE sql VOLATILE
    AS $$
    WITH RECURSIVE subtree AS (
        SELECT id,medium FROM aggregations WHERE id=p_aggregation
        UNION ALL
        SELECT child.id,child.medium FROM aggregations child
        JOIN subtree parent ON child.parent_aggregation_id=parent.id
    )
    SELECT NOT EXISTS (SELECT 1 FROM subtree WHERE id<>p_aggregation AND medium IS DISTINCT FROM p_medium)
       AND NOT EXISTS (SELECT 1 FROM records r JOIN subtree s ON s.id=r.aggregation_id
                       WHERE p_medium<>'mixed' AND r.medium IS DISTINCT FROM p_medium)
       AND NOT EXISTS (SELECT 1 FROM record_drafts d JOIN subtree s ON s.id=d.aggregation_id
                       WHERE d.medium IS NOT NULL AND p_medium<>'mixed' AND d.medium IS DISTINCT FROM p_medium)
$$;

CREATE OR REPLACE FUNCTION public.enforce_aggregation_medium_hierarchy() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE parent_medium text;
BEGIN
    IF NEW.parent_aggregation_id IS NOT NULL THEN
        SELECT medium INTO parent_medium FROM aggregations
         WHERE id=NEW.parent_aggregation_id FOR UPDATE;
        IF parent_medium IS NULL OR NEW.medium IS DISTINCT FROM parent_medium THEN
            RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='aggregation_medium_mismatch',
                MESSAGE='aggregation_medium_mismatch: a child aggregation must use its parent medium';
        END IF;
    END IF;
    -- The UPDATE already locks this aggregation. Child/record/draft writers
    -- acquire the same parent row FOR UPDATE before checking their medium.
    -- VOLATILE validation sees commits made before that lock was acquired.
    IF TG_OP='UPDATE' AND NEW.medium IS DISTINCT FROM OLD.medium
       AND NOT aggregation_medium_contents_compatible(OLD.id,NEW.medium) THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='aggregation_medium_contents_conflict',
            MESSAGE='aggregation_medium_contents_conflict: the selected medium conflicts with contained aggregations, records or drafts';
    END IF;
    RETURN NEW;
END;
$$;

INSERT INTO schema_migrations(version) VALUES('092_compatible_aggregation_medium_changes') ON CONFLICT DO NOTHING;
COMMIT;
