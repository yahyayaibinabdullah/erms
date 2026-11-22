-- Both type administration privileges must reach all three built-in profiles.
SELECT count(*) = 6
FROM public.profile_privileges grants
JOIN public.privileges privilege ON privilege.id = grants.privilege_id
JOIN public.profiles profile ON profile.id = grants.profile_id
WHERE privilege.code IN ('aggregations.administer', 'records.administer')
  AND profile.code IN ('ALL_PRIVS', 'INFO_GOV_MGR', 'INFO_GOV_OFFICER');
