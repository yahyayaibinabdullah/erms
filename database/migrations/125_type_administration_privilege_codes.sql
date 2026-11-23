BEGIN;
SELECT set_config('app.event_source', 'migration', true),
       set_config('app.actor_type', 'automated_process', true),
       set_config('app.change_reason', 'Rename the two type administration privileges and their translation keys', true);

DO $$
DECLARE
    old_code text;
    new_code text;
    old_key text;
    new_key text;
    suffix text;
    catalogue_changed boolean := false;
BEGIN
    FOR old_code, new_code IN VALUES
        ('aggregations.administer', 'aggregation_types.administer'),
        ('records.administer', 'record_types.administer')
    LOOP
        UPDATE public.privileges SET code = new_code, category = 'administration'
        WHERE code = old_code;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Missing privilege %', old_code;
        END IF;

        FOREACH suffix IN ARRAY ARRAY['name', 'description'] LOOP
            old_key := 'privilege.' || old_code || '.' || suffix;
            new_key := 'privilege.' || new_code || '.' || suffix;
            INSERT INTO public.ui_message_definitions
                (message_key, context_group, default_text, semantic_meaning, common_locations,
                 translator_guidance, grammatical_role, parameter_schema, rendered_example, is_html)
            SELECT new_key, 'privilege.' || new_code, default_text,
                   replace(semantic_meaning, old_code, new_code), common_locations,
                   translator_guidance, grammatical_role, parameter_schema, rendered_example, is_html
            FROM public.ui_message_definitions WHERE message_key = old_key
            ON CONFLICT (message_key) DO NOTHING;

            -- Preserve wording, publication and review provenance in every language.
            -- An early catalogue sync can already have supplied a source-copy draft.
            INSERT INTO public.ui_message_translations AS target
                (message_key, language_tag, translated_text, published_text, status, origin,
                 generation_metadata, needs_review, updated_by_user_id, reviewed_by_user_id,
                 date_reviewed, published_by_user_id, date_published, date_created, date_updated, version)
            SELECT new_key, language_tag, translated_text, published_text, status, origin,
                   generation_metadata, needs_review, updated_by_user_id, reviewed_by_user_id,
                   date_reviewed, published_by_user_id, date_published, date_created, date_updated, version
            FROM public.ui_message_translations WHERE message_key = old_key
            ON CONFLICT (message_key, language_tag) DO UPDATE SET
                (translated_text, published_text, status, origin, generation_metadata, needs_review,
                 updated_by_user_id, reviewed_by_user_id, date_reviewed, published_by_user_id, date_published) =
                (EXCLUDED.translated_text, EXCLUDED.published_text, EXCLUDED.status, EXCLUDED.origin,
                 EXCLUDED.generation_metadata, EXCLUDED.needs_review, EXCLUDED.updated_by_user_id,
                 EXCLUDED.reviewed_by_user_id, EXCLUDED.date_reviewed, EXCLUDED.published_by_user_id,
                 EXCLUDED.date_published)
            WHERE target.origin = 'source_copy' AND target.status = 'draft'
              AND target.reviewed_by_user_id IS NULL AND target.published_text IS NULL;

            UPDATE public.ui_message_definitions SET is_deprecated = true WHERE message_key = old_key;
            catalogue_changed := catalogue_changed OR FOUND;
        END LOOP;
    END LOOP;
    IF catalogue_changed THEN
        UPDATE public.supported_languages SET catalogue_revision = catalogue_revision + 1;
    END IF;
END
$$;

INSERT INTO public.schema_migrations(version) VALUES ('125_type_administration_privilege_codes');
COMMIT;
