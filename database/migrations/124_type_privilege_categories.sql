BEGIN;
SELECT set_config('app.event_source', 'migration', true),
       set_config('app.change_reason', 'Group type administration privileges by resource kind', true);

UPDATE public.privileges AS p
SET category = target.category
FROM (VALUES ('aggregations.administer', 'aggregation'),
             ('records.administer', 'record')) AS target(code, category)
WHERE p.code = target.code AND p.category IS DISTINCT FROM target.category;

INSERT INTO public.schema_migrations(version) VALUES ('124_type_privilege_categories');
COMMIT;
