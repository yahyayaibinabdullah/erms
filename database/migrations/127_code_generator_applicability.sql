BEGIN;

-- Preserve the meaning, counters, versions and immutable history of schema 126.
-- ALTER TABLE holds its access-exclusive lock until COMMIT. Suppress only the
-- configuration-edit guards/history while backfilling this representation.
ALTER TABLE public.code_generators ADD COLUMN applies_to text;
ALTER TABLE public.code_generators DISABLE TRIGGER code_generators_guard;
ALTER TABLE public.code_generators DISABLE TRIGGER code_generators_history;
UPDATE public.code_generators SET applies_to=CASE WHEN type_id IS NULL THEN 'all' ELSE 'type' END;
ALTER TABLE public.code_generators ALTER COLUMN applies_to SET DEFAULT 'all';
ALTER TABLE public.code_generators ALTER COLUMN applies_to SET NOT NULL;
ALTER TABLE public.code_generators DROP CONSTRAINT code_generators_primary_overlap;
DROP INDEX public.code_generators_enabled_primary;
ALTER TABLE public.code_generators DROP COLUMN type_population;
ALTER TABLE public.code_generators ADD COLUMN type_population int8range GENERATED ALWAYS AS (
        CASE WHEN applies_to='all' THEN int8range(NULL,NULL)
             WHEN applies_to='untyped' THEN int8range(0,1,'[)')
             WHEN type_id=9223372036854775807 THEN int8range(type_id,NULL,'[)')
             ELSE int8range(type_id,type_id+1,'[)') END) STORED;
ALTER TABLE public.code_generators ADD CONSTRAINT code_generators_applicability CHECK (
        applies_to IN ('all','untyped','type') AND
        ((applies_to='type')=(type_id IS NOT NULL)));
ALTER TABLE public.code_generators DROP CONSTRAINT code_generators_target_shape;
ALTER TABLE public.code_generators ADD CONSTRAINT code_generators_target_shape CHECK (
        (primary_field IS NOT NULL AND field_id IS NULL) OR
        (primary_field IS NULL AND field_id IS NOT NULL AND type_id IS NOT NULL) OR
        (NOT enabled AND primary_field IS NULL AND field_id IS NULL AND type_id IS NULL AND applies_to='all'));
ALTER TABLE public.code_generators ADD CONSTRAINT code_generators_primary_overlap EXCLUDE USING gist
    (kind WITH =, primary_field WITH =, type_population WITH &&)
    WHERE (enabled AND primary_field IS NOT NULL);
CREATE UNIQUE INDEX code_generators_enabled_primary
    ON public.code_generators(kind,primary_field,applies_to,coalesce(type_id,0))
    WHERE enabled AND primary_field IS NOT NULL;

CREATE OR REPLACE FUNCTION public.code_generator_snapshot(definition public.code_generators) RETURNS jsonb
LANGUAGE sql STABLE STRICT AS $$
    SELECT (to_jsonb(definition)-'type_population'-'field_data_type') || jsonb_build_object(
        'start',trunc(definition.start)::text,'increment',trunc(definition.increment)::text,
        'target_snapshot',jsonb_build_object('kind',definition.kind,'primary_field',definition.primary_field,
            'applies_to',definition.applies_to,
            'type_id',definition.type_id,'type_name',(SELECT name FROM resource_types WHERE kind=definition.kind AND id=definition.type_id),
            'field_id',definition.field_id,'field_name',(SELECT name FROM resource_type_fields WHERE id=definition.field_id)))
$$;

ALTER TABLE public.code_generators ENABLE TRIGGER code_generators_guard;
ALTER TABLE public.code_generators ENABLE TRIGGER code_generators_history;
INSERT INTO public.schema_migrations(version) VALUES ('127_code_generator_applicability');
COMMIT;
