BEGIN;

LOCK TABLE system_notification_producers IN EXCLUSIVE MODE;

DO $$
DECLARE
    wording record;
    producer system_notification_producers%ROWTYPE;
    previous system_notification_configuration_versions%ROWTYPE;
    canonical_contract jsonb;
    configuration_id uuid;
    administrator_id bigint;
    migration_version constant text := '117_disposition_notification_job_numbers';
    reason constant text := 'Show the user-facing job number in disposition notifications';
    correlation uuid := gen_random_uuid();
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = migration_version) THEN
        RETURN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '116_disposition_notification_defaults') THEN
        RAISE EXCEPTION 'Apply migration 116 before migration 117';
    END IF;

    FOR wording IN
        SELECT * FROM (VALUES
            ('completion_outcome', 'current_eligible_managers',
             '{"job_id":{"type":"integer","max_length":1000}}'::jsonb,
             '<p>Open Job details for destruction job {job_number} to check the outcome. If Wathiq could not generate or save the destruction certificate, open Current task for recovery instructions.</p>',
             '<p>افتح «تفاصيل العملية» لعملية الإتلاف رقم {job_number} للاطلاع على النتيجة. إذا تعذّر على وثق إنشاء شهادة الإتلاف أو حفظها، فافتح «المهمة الحالية» للاطلاع على خطوات المعالجة.</p>'),
            ('destruction_outcome', 'current_eligible_managers',
             '{"run_id":{"type":"integer","max_length":1000}}'::jsonb,
             '<p>Open Job details for job {job_number} and check Current task or History for the digital destruction result and any next steps.</p>',
             '<p>افتح «تفاصيل العملية» للعملية رقم {job_number} وراجع «المهمة الحالية» أو «السجل» للاطلاع على نتيجة الإتلاف الرقمي وأي خطوات تالية.</p>'),
            ('operation_outcome', 'requesting_managers',
             '{"job_id":{"type":"integer","max_length":1000},"operation_id":{"type":"text","max_length":1000}}'::jsonb,
             '<p>Background processing for job {job_number} has ended. Open Job details to review the result and any next steps.</p>',
             '<p>انتهت المعالجة في الخلفية للعملية رقم {job_number}. افتح «تفاصيل العملية» للاطلاع على النتيجة وأي خطوات تالية.</p>'),
            ('task_assigned', 'current_eligible_task_recipients',
             '{"task_id":{"type":"integer","max_length":1000}}'::jsonb,
             '<p>A disposition task for job {job_number} is available to you. Open the task from this message or go to My tasks to review the required action and claim it if needed.</p>',
             '<p>لديك مهمة تصرف متاحة للعملية رقم {job_number}. افتح المهمة من هذه الرسالة أو انتقل إلى «مهامي» لمعرفة الإجراء المطلوب واستلم المهمة عند الحاجة.</p>')
        ) AS defaults(event_type, audience_mode, placeholders, body_en, body_ar)
        ORDER BY event_type
    LOOP
        SELECT * INTO producer FROM system_notification_producers
        WHERE producer_code = 'disposition.' || wording.event_type;

        canonical_contract := jsonb_build_object('placeholders', wording.placeholders,
            'audience_modes', jsonb_build_array(wording.audience_mode),
            'resource_link_kinds', '[]'::jsonb, 'resource_configuration', NULL);
        IF NOT FOUND OR producer.feature_code <> 'disposition' OR producer.event_type <> wording.event_type
            OR producer.required_for_business_commit OR NOT (
                (producer.contract_version = 1 AND producer.contract_definition = canonical_contract)
                OR (producer.contract_version = 2 AND producer.contract_definition = jsonb_set(
                    canonical_contract, '{placeholders,job_number}', '{"type":"text","max_length":1000}'::jsonb))
            ) THEN
            RAISE EXCEPTION 'Incompatible disposition notification contract for disposition.%', wording.event_type;
        END IF;

        IF producer.contract_version = 1 THEN
            UPDATE system_notification_producers SET contract_version = 2,
                contract_definition = jsonb_set(contract_definition, '{placeholders,job_number}',
                    '{"type":"text","max_length":1000}'::jsonb)
            WHERE producer_code = producer.producer_code;
        END IF;

        -- The placeholder is additive. Republish only deployment-owned wording.
        SELECT * INTO previous FROM system_notification_configuration_versions
        WHERE id = producer.active_configuration_version_id;
        IF NOT FOUND OR EXISTS (
            SELECT 1 FROM system_notification_configuration_versions
            WHERE producer_code = producer.producer_code AND version > previous.version
        ) OR NOT EXISTS (
            SELECT 1 FROM event_history AS event
            WHERE event.entity_type = 'system_notification' AND event.operation = 'NOTIFICATION_CONFIGURATION_ACTIVATED'
                AND event.metadata->>'producer_code' = producer.producer_code
                AND event.metadata->>'configuration_version_id' = previous.id::text
                AND ((event.source = 'migration' AND event.metadata->>'migration_version' = '116_disposition_notification_defaults')
                    OR (event.source = 'cli' AND event.reason = 'Use the linked Wathiq workspace instead of internal identifiers in notifications'))
        ) THEN
            CONTINUE;
        END IF;

        IF administrator_id IS NULL THEN
            administrator_id := current_user_id();
            IF NOT EXISTS (
                SELECT 1 FROM users WHERE id = administrator_id AND status = 'active' AND account_type = 'person'
                    AND user_has_global_privilege(id, 'messaging.notifications.administer')
            ) THEN
                RAISE EXCEPTION 'Set app.user_id to the approving notification administrator before applying migration 117';
            END IF;
        END IF;

        configuration_id := gen_random_uuid();
        INSERT INTO system_notification_configuration_versions
            (id, producer_code, version, enabled, subject_template, body_template_rich_text, priority,
             audience_mode, resource_presentation, operational_owner, change_reason, created_by_user_id)
        VALUES (configuration_id, producer.producer_code, previous.version + 1, previous.enabled,
            previous.subject_template, wording.body_en, previous.priority, previous.audience_mode,
            previous.resource_presentation, previous.operational_owner, reason, administrator_id);

        INSERT INTO system_notification_configuration_translations
            (configuration_version_id, language_tag, subject_template, body_template_rich_text,
             review_status, reviewed_by_user_id, reviewed_at)
        SELECT configuration_id, template.language_tag, template.subject_template,
            CASE template.language_tag WHEN 'en' THEN wording.body_en ELSE wording.body_ar END,
            'published', administrator_id, CURRENT_TIMESTAMP
        FROM system_notification_configuration_translations AS template
        WHERE template.configuration_version_id = previous.id AND template.language_tag IN ('en', 'ar');

        UPDATE system_notification_producers SET active_configuration_version_id = configuration_id
        WHERE producer_code = producer.producer_code;

        INSERT INTO event_history
            (entity_type, entity_id, operation, actor_user_id, actor_type, source, reason, correlation_id, metadata, changed_fields)
        SELECT 'system_notification', 0, event.operation, administrator_id, 'user', 'migration', reason, correlation,
            jsonb_build_object('producer_code', producer.producer_code, 'configuration_version_id', configuration_id,
                'migration_version', migration_version, 'changed_fields', event.changed_fields),
            event.changed_fields
        FROM (VALUES
            ('NOTIFICATION_CONFIGURATION_SAVED', ARRAY['templates']),
            ('NOTIFICATION_CONFIGURATION_ACTIVATED', ARRAY['active_configuration_version_id'])
        ) AS event(operation, changed_fields);
    END LOOP;
END $$;

INSERT INTO schema_migrations(version) VALUES ('117_disposition_notification_job_numbers') ON CONFLICT DO NOTHING;
COMMIT;
