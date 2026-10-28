"""SMTP Test Send uses a temporary recipient and fresh saved configuration."""
import smtplib
import ssl
from email import policy
from email.parser import BytesParser

from cryptography.fernet import Fernet
import pytest

from backend.services.api.disposition import email as transport
from backend.services.api.tests.test_application_settings import db, items, save_smtp
from backend.services.api.tests.test_phase7_mutation_authorization import _grant_principal, _login_as_phase7

PATH = '/api/v1/application-settings/test-send'


def configure(client, **changes):
    values = dict(SMTP_HOST='smtp.test.invalid', SMTP_SECURITY='implicit_tls',
                  SMTP_AUTH_ENABLED=False, SMTP_SENDER_EMAIL='sender@test.invalid',
                  SMTP_SENDER_NAME='Wathiq test', SMTP_REPLY_TO_EMAIL='reply@test.invalid')
    values.update(changes)
    response=save_smtp(client,values=values)
    assert response.status_code==200,response.text


def test_recipient_is_temporary_saved_settings_are_fresh_and_no_settings_history_is_written(client,monkeypatch):
    configure(client)
    before=items(client)
    with db() as c:
        history=c.execute("SELECT count(*) n FROM event_history WHERE entity_type='application_setting'").fetchone()['n']
    calls=[]
    def send(settings,message):
        calls.append((dict(settings),message))
        return 'smtp_accepted',None,250,'IGNORED-QUEUE-ID'
    monkeypatch.setattr(transport,'smtp_send',send)
    response=client.post(PATH,json={'recipient':' recipient@test.invalid '})
    assert response.status_code==200,response.text
    assert response.json()=={'outcome':'smtp_accepted','smtp_code':250}
    settings,message=calls[0]
    assert settings['recipient']=='recipient@test.invalid' and settings['port']==465
    assert settings['sender_email']=='sender@test.invalid' and settings['reply_to']=='reply@test.invalid'
    assert message['To']=='recipient@test.invalid' and message['Reply-To']=='reply@test.invalid'
    assert message['Message-ID'] and message['Date'] and 'SMTP test' in message['Subject']
    assert not message.is_multipart() and 'اختبار' in message.get_content()
    assert not list(message.iter_attachments())
    assert items(client)==before and before['DISPOSITION_EXTERNAL_AUTHORITY_EMAIL']['value'] is None
    with db() as c:
        assert c.execute("SELECT count(*) n FROM event_history WHERE entity_type='application_setting'").fetchone()['n']==history
        assert c.execute('SELECT count(*) n FROM disposition_email_attempts').fetchone()['n']==0
    configure(client,SMTP_HOST='fresh.test.invalid',SMTP_SECURITY='starttls',SMTP_PORT=587)
    assert client.post(PATH,json={'recipient':'second@test.invalid'}).status_code==200
    assert calls[-1][0]['host']=='fresh.test.invalid' and calls[-1][0]['port']==587
    assert calls[-1][0]['recipient']=='second@test.invalid' and len(calls)==2


def test_missing_settings_invalid_addresses_and_unapproved_payloads_never_send(client,monkeypatch):
    calls=[]
    monkeypatch.setattr(transport,'smtp_send',lambda *args:calls.append(args))
    missing=client.post(PATH,json={'recipient':'recipient@test.invalid'})
    assert missing.status_code==409 and missing.json()['detail']['code']=='smtp_test_configuration'
    for recipient in ['', 'not-email', 'a@test.invalid,b@test.invalid','a@test.invalid\r\nBcc: b@test.invalid', 'a'*321]:
        assert client.post(PATH,json={'recipient':recipient}).status_code==422
    for extra in ('host','password','subject','body','attachments'):
        assert client.post(PATH,json={'recipient':'a@test.invalid',extra:'not permitted'}).status_code==422
    assert not calls


def test_settings_privilege_is_required_before_send(client,monkeypatch):
    calls=[];monkeypatch.setattr(transport,'smtp_send',lambda *args:calls.append(args))
    _grant_principal({'aggregation.view'});_login_as_phase7(client)
    assert client.post(PATH,json={'recipient':'recipient@test.invalid'}).status_code==403
    assert not calls


@pytest.mark.parametrize('security',['starttls','implicit_tls'])
def test_tls_credentials_sender_and_fixed_message_use_existing_transport(client,monkeypatch,security,caplog):
    monkeypatch.setenv('APPLICATION_SETTINGS_ENCRYPTION_KEY',Fernet.generate_key().decode())
    configure(client,SMTP_SECURITY=security)
    assert save_smtp(client,password='SMTP-SECRET-NEVER-EXPOSE',values={'SMTP_AUTH_ENABLED':True,'SMTP_USERNAME':'synthetic-user'}).status_code==200
    calls=[]
    class Mail:
        def __init__(self,host,port,**options):calls.append(('connect',host,port,options))
        def ehlo(self):calls.append(('ehlo',))
        def starttls(self,**options):calls.append(('tls',options))
        def login(self,username,password):assert (username,password)==('synthetic-user','SMTP-SECRET-NEVER-EXPOSE')
        def mail(self,address):assert address=='sender@test.invalid';return 250,b'ok'
        def rcpt(self,address):assert address=='recipient@test.invalid';return 250,b'ok'
        def data(self,data):
            message=BytesParser(policy=policy.default).parsebytes(data)
            assert 'اختبار' in message.get_content() and not list(message.iter_attachments())
            return 250,b'queued as TEST-QUEUE-1'
        def close(self):pass
    monkeypatch.setattr(smtplib,'SMTP',Mail);monkeypatch.setattr(smtplib,'SMTP_SSL',Mail)
    response=client.post(PATH,json={'recipient':'recipient@test.invalid'})
    assert response.json()=={'outcome':'smtp_accepted','smtp_code':250}
    contexts=[call[-1]['context'] for call in calls if call[0] in {'connect','tls'} and 'context' in call[-1]]
    assert contexts and all(c.check_hostname and c.verify_mode==ssl.CERT_REQUIRED for c in contexts)
    assert len([c for c in calls if c[0]=='ehlo'])==(2 if security=='starttls' else 1)
    assert 'SMTP-SECRET-NEVER-EXPOSE' not in response.text+caplog.text
    assert 'TEST-QUEUE' not in response.text


@pytest.mark.parametrize('failure,expected', [('connect','failed'),('tls','failed'),('auth','failed'),('data_refused','failed'),('data_lost','unknown')])
def test_send_failure_is_secret_safe_truthful_and_never_retried(client,monkeypatch,failure,expected,caplog):
    configure(client,SMTP_SECURITY='starttls')
    calls=[]
    class Mail:
        def __init__(self,*args,**kwargs):
            calls.append('connect')
            if failure=='connect':raise TimeoutError('PRIVATE-SERVER-DETAIL')
        def ehlo(self):pass
        def starttls(self,**kwargs):
            if failure=='tls':raise ssl.SSLCertVerificationError('PRIVATE-SERVER-DETAIL')
            if failure=='auth':raise smtplib.SMTPAuthenticationError(535,b'PRIVATE-SERVER-DETAIL')
        def mail(self,*args):return 250,b'ok'
        def rcpt(self,*args):return 250,b'ok'
        def data(self,*args):
            if failure=='data_refused':raise smtplib.SMTPDataError(550,b'PRIVATE-SERVER-DETAIL')
            raise smtplib.SMTPServerDisconnected('PRIVATE-SERVER-DETAIL')
        def close(self):pass
    monkeypatch.setattr(smtplib,'SMTP',Mail)
    response=client.post(PATH,json={'recipient':'recipient@test.invalid'})
    assert response.status_code==200 and response.json()['outcome']==expected
    assert calls==['connect'] and 'PRIVATE-SERVER-DETAIL' not in response.text+caplog.text
