SELECT set_config('app.event_source','seeding',true),
       set_config('app.change_reason','Exercise migration of a curated Arabic privilege label',true);
INSERT INTO public.ui_message_definitions
    (message_key, context_group, default_text, semantic_meaning, common_locations,
     translator_guidance, grammatical_role, rendered_example)
VALUES ('privilege.records.administer.name', 'privilege.records.administer',
        'Administer record types', 'Friendly name of records.administer', '["Role details"]',
        'Keep the privilege code unchanged', 'label', 'Administer record types');
INSERT INTO public.ui_message_translations
    (message_key, language_tag, translated_text, published_text, status, origin)
VALUES ('privilege.records.administer.name', 'ar', 'إدارة أنواع الوثائق',
        'إدارة أنواع الوثائق', 'published', 'manual');
