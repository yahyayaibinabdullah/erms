from pathlib import Path

import psycopg
import pytest

from backend.services.api.disposition import notifications
from backend.services.api.messaging import notification_configuration as config
from backend.services.api.tests.test_disposition_membership import db
from backend.services.api.tests.test_disposition_task_notifications import configure


MIGRATIONS = Path(__file__).resolve().parents[4] / 'database/migrations'
DEFAULTS = (MIGRATIONS / '116_disposition_notification_defaults.sql').read_text()
JOB_NUMBERS = (MIGRATIONS / '117_disposition_notification_job_numbers.sql').read_text()


@pytest.mark.parametrize('existing_configuration', [False, True])
def test_disposition_defaults_migration(client, existing_configuration):
    with db() as c:
        # The disposable suite shares its migration ledger between test cases.
        c.execute("DELETE FROM schema_migrations WHERE version IN ('116_disposition_notification_defaults', '117_disposition_notification_job_numbers')")
        c.commit()
        preserved = None
        if existing_configuration:
            configure(c, enabled=False)
            preserved = config.state(c, notifications.ASSIGNED)['active_configuration_version_id']
            c.commit()

        c.autocommit = True
        with pytest.raises(psycopg.errors.RaiseException, match='approving notification administrator'):
            c.execute(DEFAULTS)
        c.execute('ROLLBACK')

        c.execute("SELECT set_config('app.user_id', '1', false)")
        c.execute(DEFAULTS)
        c.execute(JOB_NUMBERS)
        c.execute(JOB_NUMBERS)

        for definition in notifications.definitions():
            code = definition.producer_code
            _, producer = config.verify_contract(c, code)
            identity = producer['active_configuration_version_id']
            version = config.load_version(c, code, identity)
            assert not producer['required_for_business_commit']
            if preserved and code == notifications.ASSIGNED:
                assert identity == preserved
                assert version['version'] == 1
                assert not version['enabled']
                continue

            assert version['enabled']
            assert config.coverage(c, version)
            templates, _ = config.validate_configuration(c, definition, config.configuration_from_row(version))
            variants = config.render(c, definition, templates, definition.sample_context, config.enabled_languages(c))
            assert {variant['direction'] for variant in variants} == {'ltr', 'rtl'}
            assert len({variant['subject'] for variant in variants}) == 2
            job_specific = 'job_number' in definition.placeholders
            assert version['version'] == (2 if job_specific else 1)
            assert config.state(c, code)['latest_version'] == version['version']
            if job_specific:
                assert all(definition.sample_context['job_number'] in v['body_rich_text'] for v in variants)
            for template in templates.values():
                assert not config.fields(template.subject_template, definition.placeholders)
                assert dict(config.fields(template.body_template_rich_text, definition.placeholders)) == (
                    {'job_number': 1} if job_specific else {}
                )

        events = c.execute("SELECT operation, actor_user_id FROM event_history WHERE source='migration' AND entity_type='system_notification'").fetchall()
        assert len(events) == (14 if preserved else 18)
        assert {event['actor_user_id'] for event in events} == {1}
        assert {event['operation'] for event in events} == {
            'NOTIFICATION_CONFIGURATION_SAVED', 'NOTIFICATION_CONFIGURATION_ACTIVATED',
        }
        assert not c.execute('SELECT 1 FROM message_envelopes LIMIT 1').fetchone()
