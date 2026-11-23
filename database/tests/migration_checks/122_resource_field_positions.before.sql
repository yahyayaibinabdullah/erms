SELECT set_config('app.event_source','seeding',true);
INSERT INTO public.resource_types(kind,name) VALUES ('record','Order 122'),('aggregation','Order 122');
INSERT INTO public.resource_type_fields(kind,type_id,name,data_type,display_order)
SELECT kind,id,entry.name,'integer',entry.position FROM public.resource_types
CROSS JOIN (VALUES ('First tie',1),('Second tie',1),('Last',7)) entry(name,position)
WHERE resource_types.name='Order 122' ORDER BY id,entry.position,entry.name;
