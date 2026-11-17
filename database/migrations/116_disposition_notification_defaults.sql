BEGIN;

-- Serialize with Notification Administration, which locks the producer before saving.
LOCK TABLE system_notification_producers IN EXCLUSIVE MODE;

DO $$
DECLARE
    defaults record;
    producer system_notification_producers%ROWTYPE;
    contract jsonb;
    administrator_id bigint;
    configuration_id uuid;
    migration_version constant text := '116_disposition_notification_defaults';
    reason constant text := 'Install bilingual defaults for previously unconfigured disposition notifications';
    correlation uuid := gen_random_uuid();
BEGIN
    FOR defaults IN
        SELECT * FROM (VALUES
            ('completion_outcome', 'Destruction completion or certificate failure',
             'current_eligible_managers', '{"job_id":{"type":"integer","max_length":1000}}'::jsonb,
             'Destruction job status update',
             '<p>Open Job details in Wathiq to check the outcome. If Wathiq could not generate or save the destruction certificate, open Current task for recovery instructions.</p>',
             'تحديث حالة عملية الإتلاف',
             '<p>افتح «تفاصيل العملية» في وثق للاطلاع على النتيجة. إذا تعذّر على وثق إنشاء شهادة الإتلاف أو حفظها، فافتح «المهمة الحالية» للاطلاع على خطوات المعالجة.</p>'),
            ('destruction_outcome', 'Digital destruction outcome',
             'current_eligible_managers', '{"run_id":{"type":"integer","max_length":1000}}'::jsonb,
             'Digital destruction result available',
             '<p>Open Job details in Wathiq and check Current task or History for the digital destruction result and any next steps.</p>',
             'نتيجة الإتلاف الرقمي متاحة',
             '<p>افتح «تفاصيل العملية» في وثق وراجع «المهمة الحالية» أو «السجل» للاطلاع على نتيجة الإتلاف الرقمي وأي خطوات تالية.</p>'),
            ('eligibility_reminder', 'Destruction eligibility reminder',
             'current_governance_person', '{"recipient_id":{"type":"integer","max_length":1000},"scheduled_interval":{"type":"text","max_length":1000}}'::jsonb,
             'Aggregations eligible for destruction',
             '<p>Some aggregations are eligible for destruction. In Wathiq, open Disposition eligibility and select Eligible for destruction to review the aggregations you can access and any blockers.</p>',
             'ملفات مؤهلة للإتلاف',
             '<p>توجد ملفات مؤهلة للإتلاف. افتح «أهلية التصرف» في وثق واختر «مؤهل للإتلاف» لمراجعة الملفات التي يمكنك الوصول إليها وأي عوائق أمام إتلافها.</p>'),
            ('operation_outcome', 'Background disposition processing outcome',
             'requesting_managers', '{"job_id":{"type":"integer","max_length":1000},"operation_id":{"type":"text","max_length":1000}}'::jsonb,
             'Background disposition processing result',
             '<p>Background processing has ended. Open Job details in Wathiq to review the result and any next steps.</p>',
             'نتيجة المعالجة في الخلفية لعملية التصرف',
             '<p>انتهت المعالجة في الخلفية. افتح «تفاصيل العملية» في وثق للاطلاع على النتيجة وأي خطوات تالية.</p>'),
            ('task_assigned', 'Disposition task assigned',
             'current_eligible_task_recipients', '{"task_id":{"type":"integer","max_length":1000}}'::jsonb,
             'Disposition task available',
             '<p>A disposition task is available to you. Open it from this message or go to My tasks in Wathiq to review the required action and claim the task if needed.</p>',
             'مهمة تصرف متاحة',
             '<p>لديك مهمة تصرف متاحة. افتح المهمة من هذه الرسالة أو انتقل إلى «مهامي» في وثق لمعرفة الإجراء المطلوب واستلم المهمة عند الحاجة.</p>')
        ) AS template(event_type, producer_name, audience_mode, placeholders, subject_en, body_en, subject_ar, body_ar)
        CROSS JOIN LATERAL (SELECT 'disposition.' || template.event_type AS producer_code) AS identity
        ORDER BY producer_code
    LOOP
        SELECT * INTO producer FROM system_notification_producers WHERE producer_code = defaults.producer_code;
        IF producer.active_configuration_version_id IS NOT NULL OR EXISTS (
            SELECT 1 FROM system_notification_configuration_versions WHERE producer_code = defaults.producer_code
        ) THEN
            CONTINUE;
        END IF;

        IF administrator_id IS NULL THEN
            administrator_id := current_user_id();
            IF NOT EXISTS (
                SELECT 1 FROM users
                WHERE id = administrator_id AND status = 'active' AND account_type = 'person'
                    AND user_has_global_privilege(id, 'messaging.notifications.administer')
            ) THEN
                RAISE EXCEPTION 'Set app.user_id to the approving notification administrator before applying migration 116';
            END IF;
            IF (SELECT count(*) FROM supported_languages WHERE language_tag IN ('en', 'ar')) <> 2
                OR EXISTS (SELECT 1 FROM supported_languages WHERE is_enabled AND language_tag NOT IN ('en', 'ar')) THEN
                RAISE EXCEPTION 'Migration 116 requires English and Arabic to be registered and covers only those languages';
            END IF;
        END IF;

        contract := jsonb_build_object('placeholders', defaults.placeholders,
            'audience_modes', jsonb_build_array(defaults.audience_mode),
            'resource_link_kinds', '[]'::jsonb, 'resource_configuration', NULL);
        IF producer.producer_code IS NULL THEN
            INSERT INTO system_notification_producers
                (producer_code, feature_code, event_type, required_for_business_commit, contract_version, contract_definition, name)
            VALUES (defaults.producer_code, 'disposition', defaults.event_type, false, 1, contract, defaults.producer_name);
        ELSIF producer.feature_code <> 'disposition' OR producer.event_type <> defaults.event_type
            OR producer.required_for_business_commit OR NOT (
                (producer.contract_version = 1 AND producer.contract_definition = contract)
                OR (defaults.event_type <> 'eligibility_reminder' AND producer.contract_version = 2
                    AND producer.contract_definition = jsonb_set(contract, '{placeholders,job_number}',
                        '{"type":"text","max_length":1000}'::jsonb))
            ) THEN
            RAISE EXCEPTION 'Incompatible disposition notification contract for %', defaults.producer_code;
        END IF;

        configuration_id := gen_random_uuid();
        INSERT INTO system_notification_configuration_versions
            (id, producer_code, version, enabled, subject_template, body_template_rich_text, audience_mode,
             resource_presentation, operational_owner, change_reason, created_by_user_id)
        VALUES (configuration_id, defaults.producer_code, 1, true, defaults.subject_en, defaults.body_en,
            defaults.audience_mode, '{}'::jsonb, 'Information Governance', reason, administrator_id);

        INSERT INTO system_notification_configuration_translations
            (configuration_version_id, language_tag, subject_template, body_template_rich_text,
             review_status, reviewed_by_user_id, reviewed_at)
        VALUES (configuration_id, 'en', defaults.subject_en, defaults.body_en, 'published', administrator_id, CURRENT_TIMESTAMP),
               (configuration_id, 'ar', defaults.subject_ar, defaults.body_ar, 'published', administrator_id, CURRENT_TIMESTAMP);

        UPDATE system_notification_producers SET active_configuration_version_id = configuration_id
        WHERE producer_code = defaults.producer_code;

        INSERT INTO event_history
            (entity_type, entity_id, operation, actor_user_id, actor_type, source, reason, correlation_id, metadata, changed_fields)
        SELECT 'system_notification', 0, event.operation, administrator_id, 'user', 'migration', reason, correlation,
            jsonb_build_object('producer_code', defaults.producer_code, 'configuration_version_id', configuration_id,
                'migration_version', migration_version, 'changed_fields', event.changed_fields),
            event.changed_fields
        FROM (VALUES
            ('NOTIFICATION_CONFIGURATION_SAVED', ARRAY['enabled', 'priority', 'audience', 'templates', 'resource_presentation', 'operational_owner']),
            ('NOTIFICATION_CONFIGURATION_ACTIVATED', ARRAY['active_configuration_version_id'])
        ) AS event(operation, changed_fields);
    END LOOP;
END $$;

INSERT INTO schema_migrations(version) VALUES ('116_disposition_notification_defaults') ON CONFLICT DO NOTHING;
COMMIT;
