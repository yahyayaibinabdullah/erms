BEGIN;
SELECT set_config('app.event_source','migration',true),
       set_config('app.change_reason','Assign type-specific field codes',true);
LOCK TABLE public.resource_types IN SHARE ROW EXCLUSIVE MODE;
ALTER TABLE public.resource_type_fields ADD COLUMN code text;
ALTER TABLE public.resource_type_fields ADD CONSTRAINT resource_field_code_unique UNIQUE (kind,type_id,code);

CREATE FUNCTION public.resource_field_code(value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
RETURN trim(both '_' from regexp_replace(upper(normalize(value) COLLATE pg_catalog."und-x-icu"),
                                         '[^[:alnum:]]+', '_', 'g'));

-- Reserve every natural spelling before allocating suffixes for collisions.
WITH candidates AS (
    SELECT id,kind,type_id,coalesce(nullif(public.resource_field_code(name),''),'FIELD_' || id) AS base_code
    FROM public.resource_type_fields
), first_fields AS (
    SELECT DISTINCT ON (kind,type_id,base_code) id,base_code FROM candidates
    ORDER BY kind,type_id,base_code,id
)
UPDATE public.resource_type_fields f SET code=first_fields.base_code
FROM first_fields WHERE first_fields.id=f.id;

DO $$
DECLARE field record; suffix bigint; candidate text;
BEGIN
    FOR field IN SELECT id,kind,type_id,coalesce(nullif(public.resource_field_code(name),''),'FIELD_' || id) AS base_code
                 FROM public.resource_type_fields WHERE code IS NULL ORDER BY id LOOP
        suffix := 2;
        LOOP
            candidate := field.base_code || '_' || suffix;
            EXIT WHEN NOT EXISTS (SELECT FROM public.resource_type_fields
                                  WHERE kind=field.kind AND type_id=field.type_id AND code=candidate);
            suffix := suffix+1;
        END LOOP;
        UPDATE public.resource_type_fields SET code=candidate WHERE id=field.id;
    END LOOP;
END $$;

UPDATE public.resource_types t SET name=t.name
WHERE EXISTS (SELECT FROM public.resource_type_fields f WHERE (f.kind,f.type_id)=(t.kind,t.id));
ALTER TABLE public.resource_type_fields ALTER COLUMN code SET NOT NULL,
    ADD CONSTRAINT resource_field_code_format CHECK (code <> '' AND code = public.resource_field_code(code));

CREATE FUNCTION public.assign_resource_field_code() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' AND NEW.code IS NULL THEN
        NEW.code := coalesce(nullif(public.resource_field_code(NEW.name), ''), 'FIELD_' || NEW.id);
    ELSE
        NEW.code := public.resource_field_code(NEW.code);
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER resource_fields_assign_code BEFORE INSERT OR UPDATE OF code ON public.resource_type_fields
    FOR EACH ROW EXECUTE FUNCTION public.assign_resource_field_code();

INSERT INTO public.schema_migrations(version) VALUES ('128_resource_field_codes');
COMMIT;
