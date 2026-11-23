SELECT count(*) = 2
FROM public.privileges
WHERE (code, category) IN (('aggregations.administer', 'aggregation'),
                           ('records.administer', 'record'));
