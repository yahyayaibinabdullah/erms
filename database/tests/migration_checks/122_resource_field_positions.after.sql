SELECT count(*)=2 AND bool_and(names=ARRAY['First tie','Second tie','Last'] AND positions=ARRAY[1,2,3])
FROM (SELECT f.kind, array_agg(f.name ORDER BY f.display_order) AS names,
             array_agg(f.display_order ORDER BY f.display_order) AS positions
      FROM public.resource_type_fields f JOIN public.resource_types t ON (t.kind,t.id)=(f.kind,f.type_id)
      WHERE t.name='Order 122' GROUP BY f.kind) AS migrated;
