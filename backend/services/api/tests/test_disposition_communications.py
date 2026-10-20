"""Phase 18 synthetic transport and reminder acceptance; disposable DB only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from uuid import uuid4
import json,smtplib,ssl
import pytest
from cryptography.fernet import Fernet
from backend.services.api.disposition import email,reminders,documents
from backend.services.api.tests.test_disposition_external import prepared,generate
from backend.services.api.tests.test_disposition_membership import db,actor,ready
from backend.services.api.tests.test_disposition_review import officer
from backend.services.api.tests.test_disposition_workflow import person,role
from backend.services.api.application_settings import apply_changes
from backend.services.api.application_settings_registry import GROUPS
from backend.services.api.application_settings_routes import SettingChange
from backend.services.api.application_settings_secret import encrypt
from backend.services.api.messaging import notification_configuration as config,notification_registry as registry
from tools.preview_disposition import preview_pdf


def settings(c,values):
    keys=set(values)
    for group in GROUPS.values():
        if keys&group:keys|=group
    changes=[]
    for key in sorted(keys):
        value={'key':key,'expected_version':c.execute('SELECT version FROM application_settings WHERE key=%s',(key,)).fetchone()['version']}
        if key in values:value['secret_value' if key=='SMTP_PASSWORD' else 'value']=values[key]
        changes.append(SettingChange(**value))
    apply_changes(c,changes,'Configure disposable communications',encrypt_secret=encrypt)


def smtp(c,recipient='archives@test.invalid',auth=False):
    settings(c,{'DISPOSITION_EXTERNAL_AUTHORITY_EMAIL':recipient,'SMTP_HOST':'smtp.test.invalid','SMTP_SECURITY':'starttls','SMTP_PORT':587,'SMTP_AUTH_ENABLED':auth,'SMTP_USERNAME':'transport-user' if auth else None,'SMTP_PASSWORD':'NEVER-LOG-THIS-PASSWORD' if auth else None,'SMTP_SENDER_EMAIL':'wathiq@test.invalid'})


def request(c,monkeypatch,route='simplified'):
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{}))
    job,root,mgr,rid=prepared(c,route);result=generate(c,job,mgr,rid);smtp(c);c.commit();actor(c)
    return job,result['request_document_id'],mgr if route=='records_manager_only' else officer(c)


def enqueue(c,job,doc,rid,key=None,recipient='archives@test.invalid'):
    return email.enqueue(c,job_id=job['id'],document_id=doc,acting_role_id=rid,command_id=key or uuid4(),expected_recipient=recipient,connection_factory=db)


@pytest.fixture(autouse=True)
def communications_state(client,monkeypatch):
    monkeypatch.setenv('APPLICATION_SETTINGS_ENCRYPTION_KEY',Fernet.generate_key().decode())
    monkeypatch.setattr(registry,'registry',registry.NotificationRegistry(registry.application_definitions()))
    with db() as c:c.execute('TRUNCATE disposition_private.reminder_schedule,disposition_private.reminder_checkpoints')


@pytest.mark.parametrize('route',['standard','simplified','records_manager_only'])
def test_exact_saved_attachment_fresh_settings_retry_resend_and_no_workflow_change(client,monkeypatch,route):
    captured=[]
    with db() as c:
        job,doc,rid=request(c,monkeypatch,route);smtp(c,auth=True);c.commit();actor(c)
        before=c.execute('SELECT to_jsonb(j) value FROM disposition_jobs j WHERE id=%s',(job['id'],)).fetchone()['value']
        key=uuid4();first=enqueue(c,job,doc,rid,key);c.commit();actor(c)
        assert enqueue(c,job,doc,rid,key)==first
        smtp(c,recipient='changed@test.invalid');c.commit();actor(c)
        assert enqueue(c,job,doc,rid,key)==first
        second=enqueue(c,job,doc,rid,recipient='changed@test.invalid');assert second!=first
    def transport(cfg,message):captured.append((cfg,message));return ('smtp_accepted',None,250,'QUEUE_123')
    assert email.process_one(db,transport=transport) and email.process_one(db,transport=transport)
    assert not email.process_one(db,transport=transport)
    assert [cfg['recipient'] for cfg,_ in captured]==['archives@test.invalid','changed@test.invalid']
    assert captured[0][0]['password']=='NEVER-LOG-THIS-PASSWORD'
    assert list(captured[0][1].iter_attachments())[0].get_payload(decode=True)==preview_pdf()
    with db() as c:
        actor(c);history=email.page(c,job['id'],limit=1,offset=0);assert history['total']==2 and len(history['items'])==1
        assert history['items'][0]['status']=='smtp_accepted' and history['items'][0]['actor_type']=='user'
        assert 'NEVER-LOG' not in json.dumps(history,default=str)
        assert not c.execute('SELECT 1 FROM disposition_private.email_payloads WHERE encrypted_password IS NOT NULL').fetchone()
        assert c.execute('SELECT to_jsonb(j) value FROM disposition_jobs j WHERE id=%s',(job['id'],)).fetchone()['value']==before
        assert 'NEVER-LOG' not in str(c.execute("SELECT metadata FROM event_history WHERE operation LIKE 'DISPOSITION_EMAIL_%'").fetchall())


@pytest.mark.parametrize('status',['failed','unknown'])
def test_failure_unknown_persist_without_automatic_resend(client,monkeypatch,status):
    with db() as c:job,doc,rid=request(c,monkeypatch);enqueue(c,job,doc,rid)
    calls=[]
    assert email.process_one(db,transport=lambda *a:(calls.append(1) or (status,'disposition_email_'+status,None,None)))
    assert not email.process_one(db,transport=lambda *a:pytest.fail('Must not auto resend'))
    with db() as c:assert c.execute('SELECT status FROM disposition_email_attempts').fetchone()['status']==status
    assert len(calls)==1


def test_missing_configuration_and_changed_recipient_create_no_attempt(client,monkeypatch):
    with db() as c:
        job,doc,rid=request(c,monkeypatch)
        with pytest.raises(Exception,match='disposition_email_recipient_changed'):enqueue(c,job,doc,rid,recipient='stale@test.invalid')
        settings(c,{'SMTP_HOST':None});c.commit();actor(c)
        with pytest.raises(Exception,match='disposition_email_configuration'):enqueue(c,job,doc,rid)
        assert not c.execute('SELECT 1 FROM disposition_email_attempts').fetchone()


def test_revoked_task_actor_sql_protection_and_worker_recheck(client,monkeypatch):
    with db() as c:
        job,doc,rid=request(c,monkeypatch);enqueue(c,job,doc,rid)
        other=person(c);actor(c,user=other)
        with pytest.raises(Exception):enqueue(c,job,doc,rid)
        actor(c)
        with pytest.raises(Exception,match='disposition_communication_protected'):
            with c.transaction():c.execute("UPDATE disposition_email_attempts SET recipient='bypass@test.invalid'")
        c.execute('DELETE FROM user_role_assignments WHERE user_id=1 AND role_id=%s',(rid,))
    assert email.process_one(db,transport=lambda *a:pytest.fail('Revoked role must not transmit'))
    with db() as c:assert c.execute('SELECT error_code FROM disposition_email_attempts').fetchone()['error_code']=='disposition_email_not_authorized'


def test_concurrent_workers_send_once_and_orphan_is_unknown(client,monkeypatch):
    with db() as c:job,doc,rid=request(c,monkeypatch);enqueue(c,job,doc,rid)
    calls=[]
    def transport(*args):calls.append(1);return ('smtp_accepted',None,250,None)
    with ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:email.process_one(db,transport=transport),range(2)))
    assert len(calls)==1
    with db() as c:
        actor(c);enqueue(c,job,doc,rid)
        from backend.services.api.disposition.eligibility import worker_actor
        worker_actor(c);assert c.execute('SELECT disposition_private.claim_email(%s) id',(uuid4(),)).fetchone()['id']
        # Controlled clock fixture only: age the committed claim, never use a
        # persistent database or ask the transport to repeat uncertain work.
        c.execute('ALTER TABLE disposition_private.email_payloads DISABLE TRIGGER USER');c.execute("UPDATE disposition_private.email_payloads SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE encrypted_password IS NULL AND worker_token IS NOT NULL");c.execute('ALTER TABLE disposition_private.email_payloads ENABLE TRIGGER USER')
    assert not email.process_one(db,transport=lambda *a:pytest.fail('No replay of orphan'))
    with db() as c:assert c.execute("SELECT count(*) n FROM disposition_email_attempts WHERE status='unknown'").fetchone()['n']==1


@pytest.mark.parametrize('security',['starttls','implicit_tls'])
@pytest.mark.parametrize('failure',[None,'auth','data_refused','data_lost','connect'])
def test_verified_tls_and_truthful_smtp_outcomes(monkeypatch,security,failure):
    calls=[]
    class Mail:
        def __init__(self,*args,**kw):
            self.greeted=False;calls.append(('connect',kw));
            if failure=='connect':raise TimeoutError('secret connection failure')
        def ehlo(self):self.greeted=True
        def starttls(self,**kw):calls.append(('tls',kw))
        def login(self,*args):
            if failure=='auth':raise smtplib.SMTPAuthenticationError(535,b'NEVER-LOG-SECRET')
        def mail(self,*args):
            assert self.greeted,'SMTP envelope requires EHLO on both TLS paths'
            return 250,b'ok'
        def rcpt(self,*args):return 250,b'ok'
        def data(self,*args):
            if failure=='data_refused':raise smtplib.SMTPDataError(550,b'NEVER-LOG-SECRET')
            if failure=='data_lost':raise smtplib.SMTPServerDisconnected('NEVER-LOG-SECRET')
            return 250,b'queued as QUEUE_1'
        def close(self):pass
    monkeypatch.setattr(smtplib,'SMTP',Mail);monkeypatch.setattr(smtplib,'SMTP_SSL',Mail)
    from email.message import EmailMessage
    outcome=email.smtp_send({'host':'synthetic','port':465,'security':security,'authentication_enabled':True,'username':'synthetic','password':'private','timeout_seconds':30,'sender_email':'a@test.invalid','recipient':'b@test.invalid'},EmailMessage())
    assert outcome[0]==('smtp_accepted' if failure is None else 'unknown' if failure=='data_lost' else 'failed')
    assert 'NEVER-LOG' not in str(outcome)
    contexts=[kw['context'] for _,kw in calls if 'context' in kw]
    assert contexts or failure=='connect' and security=='starttls'
    assert all(context.check_hostname and context.verify_mode==ssl.CERT_REQUIRED for context in contexts)


def configure_reminder(c,enabled=True):
    from backend.services.api.tests.test_disposition_foundation import ensure_officer
    ensure_officer(c)
    from pathlib import Path
    c.execute((Path(__file__).parents[4]/'database/seeds/disposition-notification-producers.sql').read_text());c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE');actor(c)
    version=c.execute('SELECT COALESCE(max(version),0) v FROM system_notification_configuration_versions WHERE producer_code=%s',(reminders.CODE,)).fetchone()['v']
    payload=config.Configuration(expected_version=version,enabled=enabled,audience_mode='current_governance_person',operational_owner='Disposable reminder test',templates=[config.Template(language_tag=tag,subject_template=subject,body_template_rich_text=body,review_status='published') for tag,subject,body in [('en','Destruction eligibility','<p>Aggregations are eligible for destruction.</p>'),('ar','أهلية الإتلاف','<p>توجد ملفات مؤهلة للإتلاف.</p>')]])
    saved=config.save(c,1,reminders.CODE,payload,'Configure reminder acceptance');config.activate(c,1,reminders.CODE,saved['id'],config.Expected(expected_version=saved['version']),'Activate reminder acceptance')


T0=datetime(2024,8,31,12,tzinfo=timezone.utc)
DUE=datetime(2025,2,28,12,tzinfo=timezone.utc)


def test_calendar_anchor_clamps_without_drift_and_no_historical_interval_changes(client,monkeypatch):
    assert reminders.add_months(T0,6)==DUE
    assert reminders.add_months(T0,12).day==31
    with db() as c:actor(c);ready(c);configure_reminder(c)
    assert reminders.run_batch(db,now=T0)['sent']==0
    assert reminders.run_batch(db,now=DUE.replace(hour=11))['sent']==0
    first=reminders.run_batch(db,now=DUE);assert first['sent']==1
    assert reminders.run_batch(db,now=DUE)['sent']==0
    with db() as c:actor(c);settings(c,{'DISPOSITION_DESTRUCTION_REMINDER_MONTHS':1})
    assert reminders.run_batch(db,now=DUE)['rescheduled']
    assert reminders.run_batch(db,now=DUE)['sent']==0


def test_reminders_current_people_both_profiles_dedupe_privacy_and_purge_independence(client):
    with db() as c:
        actor(c);ready(c);role(c,'dual-manager','INFO_GOV_MGR')
        other=person(c);role(c,'other-mgr','INFO_GOV_MGR',user=other)
        inactive=person(c);role(c,'inactive-ig','INFO_GOV_OFFICER',user=inactive);c.execute("UPDATE users SET date_deactivated=CURRENT_TIMESTAMP WHERE id=%s",(inactive,))
        configure_reminder(c)
    reminders.run_batch(db,now=T0)
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:reminders.run_batch(db,now=DUE,limit=1),range(2)))
    while reminders.run_batch(db,now=DUE,limit=1).get('more'):pass
    with db() as c:
        points=c.execute('SELECT * FROM disposition_private.reminder_checkpoints').fetchall();assert {p['recipient_user_id'] for p in points}=={1,other} and len(points)==2
        receipts=c.execute('SELECT * FROM message_request_receipts WHERE producer_code=%s',(reminders.CODE,)).fetchall();assert len(receipts)==2
        assert not any('aggregation' in str(p).lower() for p in points)
        # Purge-independent schedule/checkpoint identity: exercise the real
        # notification receipt's purged-result projection without deleting any
        # governed test evidence or weakening production constraints.
    inbox=client.get('/api/v1/messages/inbox');assert inbox.status_code==200,inbox.text
    own=inbox.json()['items'][0]
    detail=client.get('/api/v1/messages/inbox/'+str(own['id']));assert detail.status_code==200,detail.text
    assert detail.json()['disposition_eligibility'] is True
    from backend.services.api.tests.test_messaging_phase5 import age
    from backend.services.api.messaging.retention import purge_group
    ids=[str(r['result_envelope_id']) for r in receipts]
    age(ids,100)
    for receipt in receipts:
        with db() as c:assert purge_group(c,receipt['result_envelope_id'])==1
    with db() as c:
        assert len(c.execute('SELECT * FROM disposition_private.reminder_checkpoints').fetchall())==2
        c.execute('UPDATE disposition_private.reminder_schedule SET interval_index=1,recipient_after=0')
    assert reminders.run_batch(db,now=DUE)['sent']==0


@pytest.mark.parametrize('enabled,eligible',[(False,True),(True,False)])
def test_disabled_or_no_eligible_work_sends_nothing(client,enabled,eligible):
    with db() as c:
        actor(c)
        if eligible:ready(c)
        configure_reminder(c,enabled)
    reminders.run_batch(db,now=T0);assert reminders.run_batch(db,now=DUE)['sent']==0
    with db() as c:assert not c.execute('SELECT 1 FROM disposition_private.reminder_checkpoints').fetchone()


def test_http_enqueue_idempotence_bounded_history_and_received_task_closure(client,monkeypatch):
    from backend.services.api.tests.test_disposition_external import decision
    with db() as c:job,doc,rid=request(c,monkeypatch)
    payload={'command_id':str(uuid4()),'acting_role_id':rid,'expected_recipient':'archives@test.invalid'}
    path=f"/api/v1/disposition/jobs/{job['id']}/documents/{doc}/email"
    first=client.post(path,json=payload);assert first.status_code==202,first.text
    assert client.post(path,json=payload).json()==first.json()
    assert client.post(path,json={**payload,'expected_recipient':'changed@test.invalid'}).status_code==409
    projection=client.get(f"/api/v1/disposition/jobs/{job['id']}/workspace");assert projection.status_code==200,projection.text
    assert projection.json()['email']['documents'][0]['id']==doc
    assert email.process_one(db,transport=lambda *a:('smtp_accepted',None,250,None))
    with db() as c:actor(c);decision(c,job,number='COMM-18')
    assert client.post(path,json={**payload,'command_id':str(uuid4())}).status_code==403
    assert client.post(path,json=payload).json()==first.json()
    page=client.get(f"/api/v1/disposition/jobs/{job['id']}/email-attempts?limit=1&offset=0&sort=status");assert page.status_code==200,page.text
    assert page.json()['total']==1 and page.json()['items'][0]['status']=='smtp_accepted'
    assert 'configuration' not in page.json()['items'][0]
    assert client.get(f"/api/v1/disposition/jobs/{job['id']}/email-attempts?limit=101").status_code==422


def test_certificate_shared_sender_after_completion_requires_actual_manager(client,monkeypatch):
    from backend.services.api.tests.test_disposition_destruction import prepared as digital_prepared,request as destroy_request
    from backend.services.api.disposition.destruction_worker import run_pass
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{}))
    with db() as c:
        job,root,manager_role=digital_prepared(c,monkeypatch)
        officer_role=officer(c);smtp(c);destroy_request(c,job,manager_role)
    assert run_pass(db,1)=={'units_processed':1,'certificates_processed':1}
    with db() as c:
        actor(c)
        cert=c.execute("SELECT id FROM disposition_job_documents WHERE job_id=%s AND document_type='digital_destruction_certificate'",(job['id'],)).fetchone()
        assert c.execute('SELECT lifecycle_state FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()['lifecycle_state']=='completed'
        with pytest.raises(Exception,match='disposition_email_not_authorized'):enqueue(c,job,cert['id'],officer_role)
        first=enqueue(c,job,cert['id'],manager_role);second=enqueue(c,job,cert['id'],manager_role);assert first!=second
        before=c.execute('SELECT to_jsonb(j) value FROM disposition_jobs j WHERE id=%s',(job['id'],)).fetchone()['value']
    captured=[]
    assert email.process_one(db,transport=lambda cfg,msg:(captured.append(msg) or ('smtp_accepted',None,250,None)))
    assert list(captured[0].iter_attachments())[0].get_payload(decode=True)==preview_pdf()
    with db() as c:
        actor(c);assert c.execute('SELECT to_jsonb(j) value FROM disposition_jobs j WHERE id=%s',(job['id'],)).fetchone()['value']==before


def test_changed_approved_facts_prevent_sending_stale_request(client,monkeypatch):
    with db() as c:
        job,doc,rid=request(c,monkeypatch)
        c.execute('UPDATE aggregation_retention_rules SET current_period_years=current_period_years+1 WHERE aggregation_id IN(SELECT root_aggregation_id FROM disposition_job_memberships WHERE job_id=%s)',(job['id'],));c.commit();actor(c)
        with pytest.raises(Exception,match='disposition_email_not_authorized'):enqueue(c,job,doc,rid)
