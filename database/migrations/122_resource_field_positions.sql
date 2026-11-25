BEGIN;
SELECT set_config('app.event_source','migration',true),
       set_config('app.change_reason','Assign unique positions in existing field display order',true);
LOCK TABLE public.resource_types, public.resource_type_fields IN SHARE ROW EXCLUSIVE MODE;
WITH positions AS (
    SELECT id, row_number() OVER (PARTITION BY kind,type_id ORDER BY display_order,id) AS position
    FROM public.resource_type_fields
), changed AS (
    UPDATE public.resource_type_fields f SET display_order=p.position
    FROM positions p WHERE f.id=p.id AND f.display_order<>p.position
    RETURNING f.kind,f.type_id
)
UPDATE public.resource_types t SET name=t.name
WHERE (t.kind,t.id) IN (SELECT kind,type_id FROM changed);

ALTER TABLE public.resource_type_fields
    ADD CONSTRAINT resource_field_position_positive CHECK (display_order >= 1),
    ADD CONSTRAINT resource_field_position_unique UNIQUE (kind,type_id,display_order) DEFERRABLE;
INSERT INTO public.schema_migrations(version) VALUES ('122_resource_field_positions');
COMMIT;
