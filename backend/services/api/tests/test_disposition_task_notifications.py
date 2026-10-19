"""Phase 13 task events use existing durable messaging, not a new outbox."""
from pathlib import Path
from uuid import uuid4

import pytest

from backend.services.api.disposition import membership,notifications
from backend.services.api.messaging import notification_registry as registry
from backend.services.api.messaging import notification_configuration as config
from backend.services.api.tests.test_disposition_membership import actor,db,setup,kwargs

ROOT=Path(__file__).resolve().parents[4]


def configure(c,enabled=True):
    c.execute((ROOT/'database/seeds/disposition-notification-producers.sql').read_text())
    # The seed contains an explicit COMMIT, so reopen the consistent snapshot
    # required by the canonical messaging service before activation/business work.
    c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE');actor(c)
    payload=config.Configuration(expected_version=0,enabled=enabled,
      audience_mode='current_eligible_task_recipients',operational_owner='Disposable acceptance',
      templates=[config.Template(language_tag=tag,subject_template=subject,
        body_template_rich_text=body,review_status='published') for tag,subject,body in [
          ('en','Disposition task assigned','<p>Disposition task {task_id} is available.</p>'),
          ('ar','إسناد مهمة التصرف النهائي','<p>مهمة التصرف النهائي {task_id} متاحة.</p>')]])
    version=config.save(c,1,notifications.ASSIGNED,payload,'Configure disposable task producer')
    config.activate(c,1,notifications.ASSIGNED,version['id'],config.Expected(expected_version=version['version']),'Activate disposable task producer')


def test_feature_seed_contract_matches_registry_and_remains_optional(client):
    with db() as c:
        c.execute((ROOT/'database/seeds/disposition-notification-producers.sql').read_text())
        row=c.execute('SELECT * FROM system_notification_producers WHERE producer_code=%s',(notifications.ASSIGNED,)).fetchone()
        assert row['contract_definition']==notifications.definitions()[0].contract()
        assert row['required_for_business_commit'] is False and row['active_configuration_version_id'] is None
        assert notifications.ASSIGNED in {d.producer_code for d in registry.application_definitions()}


@pytest.mark.parametrize('enabled',[True,False])
def test_task_creation_message_atomic_exact_retry_and_disable(client,monkeypatch,enabled):
    monkeypatch.setattr(registry,'registry',registry.NotificationRegistry(registry.application_definitions()))
    with db() as c:
        configure(c,enabled)
        # Existing helper provides the required actual Officer, separately from
        # the administrator's acting management role.
        job=setup(c)
        count=c.execute('SELECT count(*) n FROM message_request_receipts WHERE producer_code=%s',(notifications.ASSIGNED,)).fetchone()['n']
        assert count==int(enabled)
        if enabled:
            receipt=c.execute('SELECT * FROM message_request_receipts WHERE producer_code=%s',(notifications.ASSIGNED,)).fetchone()
            assert receipt['source_event_id'].isdigit()
        key=uuid4();values={**kwargs(),'command_id':key}
        job2=membership.create_job(c,**values,job_number='Exact notification retry',job_type='destruction',owning_org_unit_id=1,assigned_user_id=1)
        assert membership.create_job(c,**values,job_number='Exact notification retry',job_type='destruction',owning_org_unit_id=1,assigned_user_id=1)==job2
        assert c.execute('SELECT count(*) n FROM message_request_receipts WHERE producer_code=%s',(notifications.ASSIGNED,)).fetchone()['n']==2*int(enabled)


def test_enabled_notification_failure_rolls_back_job_task_receipt_and_events(client,monkeypatch):
    monkeypatch.setattr(registry,'registry',registry.NotificationRegistry(registry.application_definitions()))
    with db() as c:
        configure(c);setup(c)
        counts={t:c.execute('SELECT count(*) n FROM '+t).fetchone()['n'] for t in ['disposition_jobs','disposition_tasks','event_history','disposition_private.command_receipts','message_request_receipts']}
        def fail(**kwargs):raise RuntimeError('Synthetic notification failure')
        monkeypatch.setattr(notifications,'emit_system_notification',fail)
        with pytest.raises(RuntimeError,match='Synthetic notification failure'):
            membership.create_job(c,**kwargs(),job_number='Rolled back',job_type='destruction',owning_org_unit_id=1,assigned_user_id=1)
        assert counts=={t:c.execute('SELECT count(*) n FROM '+t).fetchone()['n'] for t in counts}


def test_notification_snapshot_is_sealed_after_commit_even_with_command_savepoints(client,monkeypatch):
    import psycopg
    monkeypatch.setattr(registry,'registry',registry.NotificationRegistry(registry.application_definitions()))
    with db() as c:
        configure(c);setup(c)
        envelope=c.execute('SELECT result_envelope_id FROM message_request_receipts WHERE producer_code=%s',(notifications.ASSIGNED,)).fetchone()['result_envelope_id']
        c.commit();actor(c)
        with pytest.raises(psycopg.Error,match='message_snapshot_already_committed'):
            with c.transaction():
                c.execute("INSERT INTO message_envelope_localizations(envelope_id,language_tag,subject,body_rich_text,direction) VALUES(%s,'en','Changed','<p>Changed</p>','ltr')",(envelope,))


def test_http_creation_uses_consistent_transaction_with_enabled_producer(client,monkeypatch):
    monkeypatch.setattr(registry,'registry',registry.NotificationRegistry(registry.application_definitions()))
    with db() as c:
        configure(c);setup(c)
    response=client.post('/api/v1/disposition/jobs',json={'command_id':str(uuid4()),'acting_role_id':1,
      'job_number':'Enabled notification API creation','job_type':'destruction','owning_org_unit_id':1,'assigned_user_id':1},
      headers={'X-CSRF-Token':client.cookies.get('erms_csrf'),'X-Change-Reason':'Prepare new destruction job'})
    assert response.status_code==201,response.text
    with db() as c:
        assert c.execute('SELECT count(*) n FROM message_request_receipts WHERE producer_code=%s',(notifications.ASSIGNED,)).fetchone()['n']==2
