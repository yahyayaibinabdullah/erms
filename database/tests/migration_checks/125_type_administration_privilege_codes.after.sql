SELECT (SELECT count(*) = 2 FROM public.privileges
        WHERE code IN ('aggregation_types.administer','record_types.administer')
          AND category = 'administration')
   AND NOT EXISTS (SELECT FROM public.privileges WHERE code IN ('aggregations.administer','records.administer'))
   AND (SELECT count(*) = 6 FROM public.profile_privileges g
        JOIN public.profiles p ON p.id = g.profile_id
        JOIN public.privileges v ON v.id = g.privilege_id
        WHERE p.code IN ('INFO_GOV_MGR','INFO_GOV_OFFICER','ALL_PRIVS')
          AND v.code IN ('aggregation_types.administer','record_types.administer'))
   AND NOT EXISTS (
       SELECT FROM public.ui_message_translations old
       JOIN public.ui_message_definitions d USING (message_key)
       LEFT JOIN public.ui_message_translations renamed
         ON renamed.message_key = 'privilege.record_types.administer.name'
        AND renamed.language_tag = old.language_tag
       WHERE old.message_key = 'privilege.records.administer.name'
         AND (NOT d.is_deprecated OR renamed.message_key IS NULL OR
              (to_jsonb(old) - 'message_key') <> (to_jsonb(renamed) - 'message_key'))
   );
