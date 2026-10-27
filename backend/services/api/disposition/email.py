"""Durable, exact-version external email; no workflow transitions or auto resend."""
import hashlib
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr,make_msgid,formatdate
from uuid import uuid4
from fastapi import HTTPException
from psycopg.types.json import Jsonb
from ..application_settings import capture_email_settings,load_snapshot
from ..application_settings_registry import SettingsInvalid
from ..application_settings_secret import decrypt,encrypt
from . import artifacts
from .eligibility import worker_actor as eligibility_actor


def worker_actor(c):
    eligibility_actor(c)
    c.execute("SELECT set_config('app.actor_name','Disposition communications service',true)")


def allowed(c,job_id,document_id,role_id):
    return c.execute('SELECT disposition_private.can_email(current_user_id(),%s,%s,%s) allowed',(job_id,document_id,role_id)).fetchone()['allowed']


def enqueue(c,*,job_id,document_id,acting_role_id,command_id,expected_recipient=None,reason=None,connection_factory=None):
    document=artifacts.document(c,job_id,document_id)
    prior=c.execute('SELECT id,recipient FROM disposition_email_attempts WHERE command_id=%s',(command_id,)).fetchone()
    if prior:
        if expected_recipient!=prior['recipient']:raise HTTPException(409,detail={'code':'disposition_command_conflict'})
        identity=c.execute("SELECT disposition_private.create_email_attempt(%s,%s,%s,%s,'{}',NULL,NULL,NULL) id",(command_id,job_id,document_id,acting_role_id)).fetchone()['id']
        return {'attempt_id':identity}
    if not allowed(c,job_id,document_id,acting_role_id):raise HTTPException(403,detail={'code':'disposition_email_not_authorized'})
    try:settings=capture_email_settings(decrypt_secret=decrypt,connection_factory=connection_factory)
    except SettingsInvalid:raise HTTPException(409,detail={'code':'disposition_email_configuration'}) from None
    if settings.recipient!=expected_recipient:raise HTTPException(409,detail={'code':'disposition_email_recipient_changed'})
    # No password enters public rows, audit, logs or a response; the immutable
    # transport snapshot retains an encrypted credential until its outcome.
    database_id=str(load_snapshot(c).database_id)
    secret=encrypt(settings.password.get_secret_value(),database_id).encode() if settings.password else None
    configuration=settings.safe_values()
    configuration['body']=request_body(c,job_id,document,current_settings=load_snapshot(c))
    identity=c.execute('SELECT disposition_private.create_email_attempt(%s,%s,%s,%s,%s,%s,%s,%s) id',
      (command_id,job_id,document_id,acting_role_id,Jsonb(configuration),database_id,secret,make_msgid(domain='wathiq.invalid'))).fetchone()['id']
    return {'attempt_id':identity}


def request_body(c,job_id,document,*,current_settings,actor_user_id=None):
    """Capture correspondence wording at deliberate send, independent of worker identity."""
    if document['document_type']!='destruction_request':return ''
    from ..entity_localization import preferred_language_for_user
    from .document_snapshots import bilingual,request_organization
    language='bilingual' if current_settings['DISPOSITION_REQUEST_LANGUAGE']=='arabic_first_bilingual' else preferred_language_for_user(
        c,actor_user_id if actor_user_id is not None else c.execute('SELECT current_user_id() id').fetchone()['id'])
    manager=c.execute("""SELECT u.name,u.translations,o.name unit_name,o.translations unit_translations
        FROM disposition_review_rounds rr
        JOIN users u ON u.id=(rr.approval_execution->>'approving_user_id')::bigint
        JOIN roles r ON r.id=(rr.approval_execution->>'acting_role_id')::bigint
        JOIN org_units o ON o.id=r.org_unit_id
        WHERE rr.job_id=%s AND rr.round_number=%s""",(job_id,document['review_round'])).fetchone()
    if not manager:raise ValueError('Missing approving Records Manager')
    def block(tag):
        name=bilingual(manager,language=tag)
        unit=bilingual({'name':manager['unit_name'],'translations':manager['unit_translations']},language=tag)
        organization=request_organization(c,job_id,current_settings,tag)['organization.name']
        authority=current_settings['DISPOSITION_EXTERNAL_AUTHORITY_NAME']
        if tag.split('-')[0]=='ar':
            return f"إلى {authority}،\nيرجى التكرم بالاطلاع على إستمارة الإتلاف المرفقة للموافقة عليها.\n\nوتفضلوا بقبول فائق الاحترام والتقدير،\n{name}\n{unit}\n{organization}"
        return f"To {authority},\nPlease find attached a Request for Destruction Form for your approval.\n\nYours faithfully,\n{name}\n{unit}\n{organization}"
    return block('ar')+'\n\n'+block('en') if language=='bilingual' else block(language)


def page(c,job_id,*,limit,offset,sort='requested_at',descending=True):
    artifacts.require_workspace(c,job_id)
    order={'requested_at':'a.requested_at','status':'a.status','recipient':'a.recipient'}.get(sort,'a.requested_at')
    source=''' FROM disposition_email_attempts a JOIN disposition_job_documents d ON d.id=a.document_id
       JOIN digital_components dc ON dc.id=d.digital_component_id JOIN users u ON u.id=a.actor_user_id JOIN roles r ON r.id=a.acting_role_id
       WHERE a.job_id=%s AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id)'''
    total=c.execute('SELECT count(*) total'+source,(job_id,)).fetchone()['total']
    rows=c.execute('''SELECT a.id,a.document_id,d.review_round,dc.file_name,a.recipient,a.sender,u.name actor,r.name role,a.actor_type,
       a.requested_at,a.outcome_at,a.status,a.message_id,a.server_message_id,a.error_code,a.smtp_code'''+source+f" ORDER BY {order} {'DESC' if descending else 'ASC'},a.id DESC LIMIT %s OFFSET %s",(job_id,limit,offset)).fetchall()
    return {'items':rows,'total':total}


def controls(c,job_id):
    artifacts.require_workspace(c,job_id)
    roles=c.execute('''SELECT r.id,r.name FROM roles r WHERE disposition_private.person_role(current_user_id(),r.id)
       AND (EXISTS(SELECT 1 FROM profiles p WHERE p.id=r.profile_id AND p.code IN ('INFO_GOV_OFFICER','INFO_GOV_MGR'))) ORDER BY r.id''').fetchall()
    # Only the currently awaiting request and available digital certificates.
    docs=c.execute("""SELECT d.id,dc.file_name,d.document_type,array(SELECT selected.id FROM unnest(%s::bigint[]) selected(id) WHERE disposition_private.can_email(current_user_id(),d.job_id,d.id,selected.id) ORDER BY selected.id) role_ids
       FROM disposition_job_documents d JOIN digital_components dc ON dc.id=d.digital_component_id WHERE d.job_id=%s
       AND d.document_type IN ('destruction_request','digital_destruction_certificate') AND d.document_state='available'
       AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id)
       ORDER BY d.id DESC LIMIT 25""",([r['id'] for r in roles],job_id)).fetchall()
    return {'recipient':load_snapshot(c)['DISPOSITION_EXTERNAL_AUTHORITY_EMAIL'],'documents':[d for d in docs if d['role_ids']],'roles':roles}


def smtp_send(settings,message,*,tls_context=None):
    """A 250 DATA response proves SMTP acceptance, never inbox arrival.

    Connection/auth/envelope refusal is a definite failure. A lost connection
    after DATA starts is uncertain and is never retried automatically.
    """
    mail=None;data_started=False
    try:
        context=tls_context or ssl.create_default_context()
        if not context.check_hostname or context.verify_mode!=ssl.CERT_REQUIRED:return ('failed','disposition_email_configuration',None,None)
        if settings['security']=='implicit_tls':
            mail=smtplib.SMTP_SSL(settings['host'],settings['port'],timeout=settings['timeout_seconds'],context=context);mail.ehlo()
        elif settings['security']=='starttls':
            mail=smtplib.SMTP(settings['host'],settings['port'],timeout=settings['timeout_seconds']);mail.ehlo();mail.starttls(context=context);mail.ehlo()
        else:return ('failed','disposition_email_configuration',None,None)
        if settings['authentication_enabled']:mail.login(settings['username'],settings['password'])
        code,_=mail.mail(settings['sender_email'])
        if code!=250:return ('failed','disposition_email_failed',code,None)
        code,_=mail.rcpt(settings['recipient'])
        if code not in (250,251):return ('failed','disposition_email_failed',code,None)
        data_started=True;code,response=mail.data(message.as_bytes())
        if code!=250:return ('failed','disposition_email_failed',code,None)
        # Only a bounded queue identifier, never raw server response/error text.
        found=re.search(rb'(?i)queued as ([A-Za-z0-9_-]{1,100})(?:\s|$)',response)
        return ('smtp_accepted',None,code,found.group(1).decode() if found else None)
    except smtplib.SMTPResponseException as error:
        return ('failed','disposition_email_failed',error.smtp_code,None)
    except (OSError,smtplib.SMTPException,ValueError):
        return ('unknown','disposition_email_unknown',None,None) if data_started else ('failed','disposition_email_failed',None,None)
    finally:
        if mail:
            # A failed QUIT cannot turn an already accepted DATA into a failure.
            try:mail.close()
            except OSError:pass


def process_one(connection_factory,*,transport=smtp_send):
    token=uuid4()
    with connection_factory() as c:
        worker_actor(c);identity=c.execute('SELECT disposition_private.claim_email(%s) id',(token,)).fetchone()['id']
    if identity is None:return False
    outcome=('failed','disposition_email_failed',None,None)
    try:
        with connection_factory() as c:
            worker_actor(c)
            row=c.execute('''SELECT a.*,p.*,d.document_type,d.review_round,d.checksum_algo,dc.file_name FROM disposition_email_attempts a JOIN disposition_private.email_payloads p ON p.attempt_id=a.id
                JOIN disposition_job_documents d ON d.id=a.document_id JOIN digital_components dc ON dc.id=d.digital_component_id WHERE a.id=%s''',(identity,)).fetchone()
            if not c.execute('SELECT disposition_private.can_email(%s,%s,%s,%s) allowed',(row['actor_user_id'],row['job_id'],row['document_id'],row['acting_role_id'])).fetchone()['allowed']:
                outcome=('failed','disposition_email_not_authorized',None,None)
            else:
                # Immutable saved content-set identity, not a freshly generated PDF.
                content=b''.join(bytes(x['content']) for x in c.execute('SELECT content FROM digital_component_blobs WHERE content_set_id=%s ORDER BY segment_no',(row['content_set_id'],)).fetchall())
                if not content or hashlib.new(row['checksum_algo'],content).hexdigest()!=row['checksum']:raise ValueError('Unavailable saved artifact')
                settings=dict(row['configuration']);settings['password']=decrypt(bytes(row['encrypted_password']),row['database_id']).get_secret_value() if row['encrypted_password'] else None
                message=EmailMessage();message['To']=row['recipient'];message['From']=formataddr((settings.get('sender_name') or '',row['sender']));message['Message-ID']=row['message_id'];message['Date']=formatdate(usegmt=True)
                if settings.get('reply_to'):message['Reply-To']=settings['reply_to']
                message['Subject']='Request for Destruction Form' if row['document_type']=='destruction_request' else 'Certificate of Destruction (Digital)'
                message.set_content(settings['body'] if 'body' in settings else request_body(c,row['job_id'],row,current_settings=load_snapshot(c),actor_user_id=row['actor_user_id']));message.add_attachment(content,maintype='application',subtype='pdf',filename=row['file_name'])
                outcome=None
        # No DB transaction/lock is held across network I/O.
        if outcome is None:outcome=transport(settings,message)
    except SettingsInvalid:outcome=('failed','disposition_email_configuration',None,None)
    except ValueError:outcome=('failed','disposition_document_unavailable',None,None)
    except Exception:
        # A surprising transport exception cannot prove that mail was refused.
        outcome=('unknown','disposition_email_unknown',None,None)
    with connection_factory() as c:
        worker_actor(c);c.execute('SELECT disposition_private.finish_email(%s,%s,%s,%s,%s,%s)',(identity,token,*outcome))
    return True
