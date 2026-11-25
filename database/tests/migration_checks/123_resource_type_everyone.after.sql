SELECT NOT EXISTS (SELECT FROM public.resource_type_role_grants WHERE role_id IS NULL)
   AND EXISTS (SELECT FROM pg_index WHERE indexrelid='public.resource_type_principal_unique'::regclass
               AND indisunique AND indnullsnotdistinct AND indisvalid);
