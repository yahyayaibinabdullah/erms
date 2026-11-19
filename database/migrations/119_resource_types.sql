BEGIN;

ALTER TABLE public.aggregations ADD COLUMN type_id bigint;
ALTER TABLE public.records ADD COLUMN type_id bigint;

-- Resource metadata types. Both catalogues share definitions and validation.
CREATE FUNCTION public.resource_type_has_text(input text) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
RETURN btrim(input, U&'\0009\000A\000B\000C\000D\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000') <> '';

-- The existing translation trigger validates enabled languages and the shape of
-- each translation. Apply the same Unicode nonblank rule to translated names.
CREATE FUNCTION public.resource_type_names_present(translations jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
RETURN NOT EXISTS (SELECT FROM jsonb_each(translations) AS locale(tag, fields)
                   WHERE NOT public.resource_type_has_text(fields ->> 'name'));

CREATE TABLE public.resource_types (
    kind text NOT NULL,
    id bigint GENERATED ALWAYS AS IDENTITY,
    name text NOT NULL CHECK (public.resource_type_has_text(name)),
    description text,
    translations jsonb CHECK (public.resource_type_names_present(translations)),
    version bigint NOT NULL DEFAULT 1,
    PRIMARY KEY (kind, id),
    UNIQUE (kind, name)
) PARTITION BY LIST (kind);

CREATE TABLE public.aggregation_types PARTITION OF public.resource_types FOR VALUES IN ('aggregation');
CREATE TABLE public.record_types PARTITION OF public.resource_types FOR VALUES IN ('record');
ALTER TABLE public.aggregation_types ADD UNIQUE (id);
ALTER TABLE public.record_types ADD UNIQUE (id);

ALTER TABLE public.aggregations ADD FOREIGN KEY (type_id) REFERENCES public.aggregation_types (id);
ALTER TABLE public.records ADD FOREIGN KEY (type_id) REFERENCES public.record_types (id);
ALTER TABLE public.aggregations ADD UNIQUE (id, type_id);
ALTER TABLE public.records ADD UNIQUE (id, type_id);
CREATE INDEX aggregation_type_assignments ON public.aggregations (type_id) WHERE type_id IS NOT NULL;
CREATE INDEX record_type_assignments ON public.records (type_id) WHERE type_id IS NOT NULL;

-- A row grants See. Use is an additional bit on that same role's See grant.
CREATE TABLE public.resource_type_role_grants (
    kind text NOT NULL,
    type_id bigint NOT NULL,
    role_id bigint NOT NULL REFERENCES public.roles (id) ON DELETE CASCADE,
    can_use boolean NOT NULL DEFAULT false,
    PRIMARY KEY (kind, type_id, role_id),
    FOREIGN KEY (kind, type_id) REFERENCES public.resource_types ON DELETE CASCADE
);
CREATE INDEX resource_type_grants_by_role ON public.resource_type_role_grants (role_id, kind, type_id);

CREATE TYPE public.resource_field_literal AS (
    text_value text,
    integer_value bigint,
    decimal_value numeric,
    boolean_value boolean,
    date_value date,
    datetime_value timestamptz,
    choice_id bigint
);

CREATE FUNCTION public.resource_field_valid(data_type text, max_length integer, required boolean,
                                            literal public.resource_field_literal) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE
RETURN CASE WHEN literal IS NOT DISTINCT FROM NULL THEN NOT required ELSE
    num_nonnulls(literal.text_value, literal.integer_value, literal.decimal_value, literal.boolean_value,
                 literal.date_value, literal.datetime_value, literal.choice_id) = 1
    AND coalesce(CASE data_type
        WHEN 'text' THEN char_length(literal.text_value) <= max_length
                         AND (NOT required OR public.resource_type_has_text(literal.text_value))
        WHEN 'integer' THEN literal.integer_value IS NOT NULL
        WHEN 'decimal' THEN literal.decimal_value NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
        WHEN 'boolean' THEN literal.boolean_value IS NOT NULL
        WHEN 'date' THEN isfinite(literal.date_value)
        WHEN 'datetime' THEN isfinite(literal.datetime_value)
        WHEN 'single_choice' THEN literal.choice_id IS NOT NULL
    END, false) END;

CREATE TABLE public.resource_type_fields (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind text NOT NULL,
    type_id bigint NOT NULL,
    name text NOT NULL CHECK (public.resource_type_has_text(name)),
    translations jsonb CHECK (public.resource_type_names_present(translations)
                              AND NOT jsonb_path_exists(translations, '$.*.description')),
    version bigint NOT NULL DEFAULT 1,
    display_order integer NOT NULL,
    required boolean NOT NULL DEFAULT false,
    data_type text NOT NULL CHECK (data_type IN ('text','integer','decimal','boolean','date','datetime','single_choice')),
    max_length integer,
    default_value public.resource_field_literal,
    default_choice_id bigint GENERATED ALWAYS AS ((default_value).choice_id) STORED,
    text_capacity integer GENERATED ALWAYS AS (coalesce(max_length, 0)) STORED,
    CHECK ((data_type = 'text' AND max_length IS NOT NULL AND max_length > 0) OR
           (data_type <> 'text' AND max_length IS NULL)),
    CHECK (default_value IS NOT DISTINCT FROM NULL OR
           public.resource_field_valid(data_type, max_length, required, default_value)),
    FOREIGN KEY (kind, type_id) REFERENCES public.resource_types ON DELETE CASCADE,
    UNIQUE (kind, type_id, name),
    UNIQUE (kind, type_id, id, data_type),
    UNIQUE (id, text_capacity),
    UNIQUE (id, data_type)
);

CREATE TABLE public.resource_field_choices (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    field_id bigint NOT NULL,
    data_type text GENERATED ALWAYS AS ('single_choice'::text) STORED,
    name text NOT NULL CHECK (public.resource_type_has_text(name)),
    translations jsonb CHECK (public.resource_type_names_present(translations)
                              AND NOT jsonb_path_exists(translations, '$.*.description')),
    version bigint NOT NULL DEFAULT 1,
    display_order integer NOT NULL,
    UNIQUE (field_id, id),
    FOREIGN KEY (field_id, data_type) REFERENCES public.resource_type_fields (id, data_type) ON DELETE CASCADE
);
ALTER TABLE public.resource_type_fields ADD FOREIGN KEY (id, default_choice_id)
    REFERENCES public.resource_field_choices (field_id, id);

CREATE TRIGGER resource_types_validate_translations BEFORE INSERT OR UPDATE OF translations ON public.resource_types
    FOR EACH ROW EXECUTE FUNCTION public.validate_multilingual_entity_translations();
CREATE TRIGGER resource_fields_validate_translations BEFORE INSERT OR UPDATE OF translations ON public.resource_type_fields
    FOR EACH ROW EXECUTE FUNCTION public.validate_multilingual_entity_translations();
CREATE TRIGGER resource_choices_validate_translations BEFORE INSERT OR UPDATE OF translations ON public.resource_field_choices
    FOR EACH ROW EXECUTE FUNCTION public.validate_multilingual_entity_translations();
CREATE TRIGGER resource_types_bump_version BEFORE UPDATE ON public.resource_types
    FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();
CREATE TRIGGER resource_fields_bump_version BEFORE UPDATE ON public.resource_type_fields
    FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();
CREATE TRIGGER resource_choices_bump_version BEFORE UPDATE ON public.resource_field_choices
    FOR EACH ROW EXECUTE FUNCTION public.bump_entity_version();

CREATE TABLE public.resource_type_values (
    kind text NOT NULL,
    resource_id bigint NOT NULL,
    type_id bigint NOT NULL,
    field_id bigint NOT NULL,
    data_type text NOT NULL,
    text_capacity integer NOT NULL,
    value public.resource_field_literal NOT NULL,
    choice_id bigint GENERATED ALWAYS AS ((value).choice_id) STORED,
    PRIMARY KEY (kind, resource_id, field_id),
    CHECK (public.resource_field_valid(data_type, text_capacity, false, value)),
    FOREIGN KEY (kind, type_id, field_id, data_type)
        REFERENCES public.resource_type_fields (kind, type_id, id, data_type),
    -- A shorter limit must also fit every stored value. The cascading update
    -- and its CHECK are atomic with the definition edit, including concurrent inserts.
    FOREIGN KEY (field_id, text_capacity)
        REFERENCES public.resource_type_fields (id, text_capacity) ON UPDATE CASCADE,
    FOREIGN KEY (field_id, choice_id) REFERENCES public.resource_field_choices (field_id, id)
) PARTITION BY LIST (kind);
CREATE TABLE public.aggregation_type_values PARTITION OF public.resource_type_values FOR VALUES IN ('aggregation');
CREATE TABLE public.record_type_values PARTITION OF public.resource_type_values FOR VALUES IN ('record');
ALTER TABLE public.aggregation_type_values ADD FOREIGN KEY (resource_id, type_id)
    REFERENCES public.aggregations (id, type_id) ON DELETE CASCADE;
ALTER TABLE public.record_type_values ADD FOREIGN KEY (resource_id, type_id)
    REFERENCES public.records (id, type_id) ON DELETE CASCADE;
CREATE INDEX resource_type_values_by_field ON public.resource_type_values (field_id, choice_id);

-- Decode one submitted JSON literal once, before persistence. Exact decimal
-- strings and JSON numbers both enter numeric directly, without a float round trip.
CREATE FUNCTION public.resource_field_decode(data_type text, input jsonb) RETURNS public.resource_field_literal
LANGUAGE plpgsql STABLE STRICT AS $$
DECLARE
    result public.resource_field_literal;
    scalar text := input #>> '{}';
    shape text := jsonb_typeof(input);
BEGIN
    IF shape = 'null' THEN RETURN NULL; END IF;
    CASE
        WHEN data_type = 'text' AND shape = 'string' THEN result.text_value := scalar;
        WHEN data_type = 'integer' AND shape = 'number' AND scalar ~ '^-?[0-9]+$' THEN
            result.integer_value := scalar::bigint;
        WHEN data_type = 'decimal' AND shape IN ('number','string')
             AND scalar ~ '^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$' THEN
            result.decimal_value := scalar::numeric;
        WHEN data_type = 'boolean' AND shape = 'boolean' THEN result.boolean_value := scalar::boolean;
        WHEN data_type = 'date' AND shape = 'string' AND scalar ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
            result.date_value := scalar::date;
        WHEN data_type = 'datetime' AND shape = 'string'
             AND scalar ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt ][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]+)?)?([Zz]|[+-][0-9]{2}(:?[0-9]{2})?)$' THEN
            result.datetime_value := scalar::timestamptz;
        WHEN data_type = 'single_choice' AND shape = 'number' AND scalar ~ '^[0-9]+$' THEN
            result.choice_id := scalar::bigint;
        ELSE RAISE EXCEPTION 'Invalid % literal', data_type USING ERRCODE = '22023';
    END CASE;
    RETURN result;
END $$;

-- Resolve the complete proposed value set for a metadata save. This function
-- has no write or authorization side effects. A new resource has a NULL ID.
CREATE FUNCTION public.resolve_resource_type_values(p_kind text, p_resource_id bigint, p_type_id bigint, submitted jsonb)
RETURNS TABLE(field_id bigint, data_type text, text_capacity integer, value public.resource_field_literal)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    current_type bigint;
    field record;
BEGIN
    IF p_kind IS NULL OR p_kind NOT IN ('record','aggregation') OR jsonb_typeof(submitted) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'Invalid resource kind or field map' USING ERRCODE = '22023';
    END IF;
    IF p_resource_id IS NOT NULL THEN
        IF p_kind = 'record' THEN SELECT r.type_id INTO STRICT current_type FROM public.records r WHERE r.id = p_resource_id;
        ELSE SELECT a.type_id INTO STRICT current_type FROM public.aggregations a WHERE a.id = p_resource_id;
        END IF;
    END IF;
    IF p_type_id IS NOT NULL AND NOT EXISTS (
        SELECT FROM public.resource_types t WHERE (t.kind, t.id) = (p_kind, p_type_id)
    ) THEN RAISE EXCEPTION 'Unknown % type %', p_kind, p_type_id USING ERRCODE = '23503'; END IF;
    IF EXISTS (
        SELECT FROM jsonb_object_keys(submitted) AS supplied(key) WHERE NOT EXISTS (
            SELECT FROM public.resource_type_fields f
            WHERE (f.kind, f.type_id) = (p_kind, p_type_id) AND f.id::text = supplied.key)
    ) THEN RAISE EXCEPTION 'Field outside selected type' USING ERRCODE = '22023'; END IF;

    FOR field IN
        SELECT f.*, v.value AS previous FROM public.resource_type_fields f
        LEFT JOIN public.resource_type_values v ON (v.kind, v.resource_id, v.field_id) = (f.kind, p_resource_id, f.id)
        WHERE (f.kind, f.type_id) = (p_kind, p_type_id) ORDER BY f.display_order, f.id
    LOOP
        field_id := field.id;
        data_type := field.data_type;
        text_capacity := field.text_capacity;
        value := CASE WHEN submitted ? field.id::text THEN public.resource_field_decode(data_type, submitted -> field.id::text)
                      WHEN current_type IS DISTINCT FROM p_type_id THEN field.default_value ELSE field.previous END;
        IF NOT public.resource_field_valid(data_type, field.max_length, field.required, value) THEN
            RAISE EXCEPTION 'Invalid value for field %', field.id USING ERRCODE = '23514';
        END IF;
        IF value.choice_id IS NOT NULL AND NOT EXISTS (
            SELECT FROM public.resource_field_choices c WHERE (c.field_id, c.id) = (field.id, value.choice_id)
        ) THEN RAISE EXCEPTION 'Unknown choice for field %', field.id USING ERRCODE = '23503'; END IF;
        IF value IS DISTINCT FROM NULL THEN RETURN NEXT; END IF;
    END LOOP;
END $$;

INSERT INTO public.schema_migrations(version) VALUES ('119_resource_types');
COMMIT;
