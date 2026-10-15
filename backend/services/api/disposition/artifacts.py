"""Governed artifact storage and append-only evidence corrections.

No generic upload endpoint can create an external decision or confirmation.
Action services call save() inside their command/transaction; the correction
endpoint only appends to a pre-existing uploaded-evidence chain. Every request
uses current DB policy/settings, with no result or authorization cache.
"""
import hashlib
import json

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from ..content_storage import configured_storage, GovernedUpload
from ..crud import create_row
from ..continuity_lock import acquire_continuity_shared_lock
from ..resource_authorization import require_resource_operation, require_component_operation
from .commands import execute_command, lock_job

UPLOADED = {'external_rejection_letter', 'external_approval_letter', 'physical_destruction_certificate'}
REPORTS = {'destruction_request', 'proposal_execution_report', 'physical_preparation_report'}
TYPES = UPLOADED | REPORTS | {'digital_destruction_certificate'}
SETTINGS = ['DISPOSITION_CLASSIFICATION_SCHEME_ID', 'DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID',
            'DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID']


def require_workspace(c, job_id):
    """IG managers or actual current/past task recipients, with content gates later.

    A task association grants only workspace context, never record visibility.
    This also supports FA/UM preview once their action phases create the tasks.
    """
    row = c.execute('''SELECT j.* FROM disposition_jobs j JOIN users requester ON requester.id=current_user_id()
     AND requester.status='active' AND requester.account_type='person' WHERE j.id=%s AND (
     disposition_private.can_manage() OR EXISTS(SELECT 1 FROM disposition_tasks t
      WHERE t.job_id=j.id AND (t.destination_user_id=current_user_id() OR
       EXISTS(SELECT 1 FROM user_role_assignments a WHERE a.role_id=t.destination_role_id
        AND a.user_id=current_user_id() AND role_effectively_active(a.role_id)
        AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)))))''',(job_id,)).fetchone()
    if row is None:
        raise HTTPException(404,detail={'code':'disposition_document_unavailable'})
    return row


def correction_roles(c, job_id):
    return c.execute('''SELECT r.id,r.name FROM roles r
     WHERE disposition_private.can_correct_evidence(%s,r.id) ORDER BY r.id''',(job_id,)).fetchall()


def _visible_destination(c, values):
    if not values or not values.get('aggregation_id'):
        return None
    root = c.execute('''SELECT a.id,a.aggregation_number,a.title,cl.code AS classification_code,
     cl.title AS classification_title,s.code AS scheme_code,s.title AS scheme_title
     FROM aggregations a JOIN classifications cl ON cl.id=%s
     JOIN classification_schemes s ON s.id=%s
     WHERE a.id=%s AND current_user_can_view_aggregation(a.id)''',(values['classification_id'],values.get('scheme_id',values.get('classification_scheme_id')),values['aggregation_id'])).fetchone()
    return root


def destination(c, job_id, document_type, *, locked=False):
    if document_type not in TYPES:
        raise HTTPException(422,detail={'code':'disposition_document_type_invalid'})
    # The preview is advisory. save() locks settings and independently resolves
    # again, and rejects an obsolete preview so a changed warning is seen first.
    if locked:
        current = c.execute('SELECT * FROM disposition_private.artifact_destination(%s)',(document_type,)).fetchone()
    else:
        current = c.execute('''WITH settings AS (
         SELECT (max(value#>>'{}') FILTER(WHERE key='DISPOSITION_CLASSIFICATION_SCHEME_ID'))::bigint scheme_id,
         (max(value#>>'{}') FILTER(WHERE key=%s))::bigint classification_id
         FROM application_settings WHERE key=ANY(%s))
         SELECT s.*,a.id AS aggregation_id FROM settings s LEFT JOIN LATERAL
          (SELECT id FROM aggregations WHERE classification_id=s.classification_id
           AND parent_aggregation_id IS NULL AND date_closed IS NULL
           ORDER BY date_opened DESC,id DESC LIMIT 1) a ON true''',
         ('DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID' if document_type in REPORTS else 'DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID',SETTINGS)).fetchone()
    category = list(REPORTS) if document_type in REPORTS else list(UPLOADED | {'digital_destruction_certificate'})
    previous = c.execute('''SELECT classification_scheme_id AS scheme_id,classification_id,aggregation_id
     FROM disposition_job_documents WHERE job_id=%s AND document_type=ANY(%s)
     AND document_state='available' AND (classification_scheme_id,classification_id) IS DISTINCT FROM (%s::bigint,%s::bigint) ORDER BY id DESC LIMIT 1''',(job_id,category,current['scheme_id'],current['classification_id'])).fetchone()
    changed = bool(previous and (previous['scheme_id'],previous['classification_id']) !=
                   (current['scheme_id'],current['classification_id']))
    ready = bool(current['scheme_id'] and current['classification_id'] and current['aggregation_id'])
    return {**current,'ready':ready,'changed':changed,
            'destination':_visible_destination(c,current),'previous_destination':_visible_destination(c,previous) if changed else None,
            'warning':None if ready else ('disposition_destination_unset' if not current['scheme_id'] or not current['classification_id'] else 'disposition_destination_open_root_missing')}


def destination_token(values):
    """Concurrency fingerprint, not an authorization token."""
    return hashlib.sha256(json.dumps({k:values[k] for k in ('scheme_id','classification_id','aggregation_id')},sort_keys=True).encode()).hexdigest()


def public_destination(c, job_id, document_type):
    require_workspace(c,job_id)
    result=destination(c,job_id,document_type)
    return {k:result[k] for k in ('ready','changed','destination','previous_destination','warning')} | {'token':destination_token(result)}


def document(c, job_id, document_id):
    require_workspace(c,job_id)
    row = c.execute('''SELECT d.*,c.file_name,c.mime_type FROM disposition_job_documents d
     JOIN digital_components c ON c.id=d.digital_component_id
     WHERE d.job_id=%s AND d.id=%s AND current_user_can_view_record(d.record_id)
     AND current_user_can_list_record_components(d.record_id)''',(job_id,document_id)).fetchone()
    if not row:
        raise HTTPException(404,detail={'code':'disposition_document_unavailable'})
    return row


def page(c, job_id, *, limit, offset, sort='id', descending=True):
    require_workspace(c,job_id)
    source = ''' FROM disposition_job_documents d JOIN digital_components c ON c.id=d.digital_component_id
     WHERE d.job_id=%s AND current_user_can_view_record(d.record_id)
     AND current_user_can_list_record_components(d.record_id)'''
    orders={'id':'d.id','file_name':'c.file_name','type_label':'d.document_type','evidence_version':'d.evidence_version','created_label':'d.date_created'}
    if sort not in orders:raise HTTPException(422,detail={'code':'disposition_document_type_invalid'})
    total=c.execute('SELECT count(*) total'+source,(job_id,)).fetchone()['total']
    rows=c.execute('''SELECT d.*,c.file_name,c.mime_type,
     NOT EXISTS(SELECT 1 FROM disposition_job_documents next WHERE next.supersedes_document_id=d.id) AS is_current,
     current_user_can_record_component_operation(d.record_id,'record.component.view','record.component.view') AS can_preview,
     current_user_can_record_component_operation(d.record_id,'record.component.download','record.component.download') AS can_download'''+source+
     ' ORDER BY '+orders[sort]+(' DESC' if descending else ' ASC')+',d.id DESC LIMIT %s OFFSET %s',(job_id,limit,offset)).fetchall()
    roles=correction_roles(c,job_id)
    for row in rows:
        row['can_correct']=bool(roles) and row['can_preview'] and row['origin']=='uploaded' and row['is_current'] and row['document_state']=='available'
    return {'items':rows,'total':total,'correction_roles':roles}


def save(c, *, job_id, document_type, staged: GovernedUpload, preview, supersedes=None,
         template_version=None, provenance=None):
    """Private action primitive; caller's command saves outcome/history together.

    Staging is committed separately and invisible. All governed resources, link,
    checksum, version and history become visible together, or all roll back.
    No workflow stage, original decision or confirmation is changed here.
    """
    acquire_continuity_shared_lock(c)
    c.execute('SELECT disposition_private.require_command()')
    job=c.execute('SELECT * FROM disposition_jobs WHERE id=%s FOR UPDATE',(job_id,)).fetchone()
    if not job or job['job_type']!='destruction':
        raise HTTPException(409,detail={'code':'disposition_document_type_invalid'})
    current=destination(c,job_id,document_type,locked=True)
    if (isinstance(preview,str) and destination_token(current)!=preview) or (isinstance(preview,dict) and any(current[key] != preview.get(key) for key in ('scheme_id','classification_id','aggregation_id'))):
        raise HTTPException(409,detail={'code':'disposition_destination_changed'})
    role=c.execute('''SELECT r.acting_role_id FROM disposition_private.command_context x
     JOIN disposition_private.command_receipts r USING(command_id) WHERE x.transaction_id=txid_current()''').fetchone()['acting_role_id']
    prior=None
    if supersedes:
        prior=document(c,job_id,supersedes)
        require_component_operation(c,prior['digital_component_id'],'record.component.view','record.component.view')
        if prior['origin']!='uploaded' or document_type not in UPLOADED:
            raise HTTPException(409,detail={'code':'disposition_generated_correction_forbidden'})
        if not c.execute('SELECT disposition_private.can_correct_evidence(%s,%s) allowed',(job_id,role)).fetchone()['allowed']:
            raise HTTPException(403,detail={'code':'disposition_evidence_correction_forbidden'})
    parent=require_resource_operation(c,'aggregation',current['aggregation_id'],'record.create','aggregation.add_record')
    if parent['medium'] not in ('digital','mixed'):
        raise HTTPException(409,detail={'code':'disposition_destination_digital_required'})
    # Role is a currently verified command role, rather than a client-selected
    # ACL bypass. Standard ownership/security/creator-ACL triggers still run.
    c.execute("SELECT set_config('app.creator_acl_role_id',%s,true)",(str(role),))
    serial=c.execute("SELECT nextval(pg_get_serial_sequence('records','id')) AS id").fetchone()['id']
    record=create_row(c,'records',dict(id=serial,aggregation_id=parent['id'],record_number=f'DISP-{job_id}-{serial}',
      title=staged.file_name,medium='digital',security_level_id=parent['security_level_id']))
    component=create_row(c,'digital_components',dict(record_id=record['id'],component_order=1,
      file_name=staged.file_name,mime_type=staged.mime_type,size_in_bytes=staged.size_in_bytes,
      checksum_algo='sha256',checksum_value=staged.checksum_value,storage_backend='postgresql',content_status='available'))
    configured_storage().promote_draft(c,staged.component_id,component['id'])
    c.execute("SELECT append_domain_event('digital_component',%s,'CONTENT_UPLOADED',%s)",(component['id'],Jsonb({'file_name':staged.file_name,'mime_type':staged.mime_type,'size_in_bytes':staged.size_in_bytes,'checksum_algo':'sha256','checksum_value':staged.checksum_value,'workflow':'disposition'})))
    new=c.execute('''INSERT INTO disposition_job_documents(job_id,document_type,document_state,review_round,
     record_id,digital_component_id,created_by_user_id,checksum_algo,checksum,template_version,origin,
     supersedes_document_id,evidence_version,classification_scheme_id,classification_id,aggregation_id,acting_role_id,provenance)
     VALUES(%s,%s,'available',%s,%s,%s,current_user_id(),'sha256',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
     (job_id,document_type,prior['review_round'] if prior else (job['current_review_round'] or None),record['id'],component['id'],
      staged.checksum_value,template_version,'uploaded' if document_type in UPLOADED else 'generated',supersedes,
      prior['evidence_version']+1 if prior else 1,current['scheme_id'],current['classification_id'],parent['id'],role,Jsonb(provenance or {}))).fetchone()
    metadata={'job_id':job_id,'acting_role_id':role,'evidence_type':document_type,
              'previous_document_id':prior['id'] if prior else None,'previous_evidence_version':prior['evidence_version'] if prior else None,'previous_record_id':prior['record_id'] if prior else None,
              'document_id':new['id'],'record_id':record['id'],'digital_component_id':component['id'],
              'evidence_version':new['evidence_version'],'review_round':new['review_round'],
              'scheme_id':current['scheme_id'],'classification_id':current['classification_id'],'aggregation_id':parent['id'],
              'checksum_algo':'sha256','checksum':staged.checksum_value}
    c.execute("SELECT append_domain_event('disposition_job_document',%s,%s,%s)",(new['id'],'EVIDENCE_CORRECTED' if prior else 'ARTIFACT_SAVED',Jsonb(metadata)))
    return {'id':new['id'],'record_id':record['id'],'digital_component_id':component['id'],'evidence_version':new['evidence_version']}


def correct(c, *, job_id, document_id, expected_version, command_id, acting_role_id, reason,
            staged: GovernedUpload, preview):
    # Recheck correction-specific access even for a committed retry; the command
    # kernel's general manage check alone does not authorize this operation.
    old=document(c,job_id,document_id)
    if not c.execute("SELECT current_user_can_record_component_operation(%s,'record.component.view','record.component.view') allowed",(old['record_id'],)).fetchone()['allowed']:
        raise HTTPException(403,detail={'code':'disposition_resource_access_required'})
    if old['origin']!='uploaded':
        raise HTTPException(409,detail={'code':'disposition_generated_correction_forbidden'})
    if not c.execute('SELECT disposition_private.can_correct_evidence(%s,%s) allowed',(job_id,acting_role_id)).fetchone()['allowed']:
        raise HTTPException(403,detail={'code':'disposition_evidence_correction_forbidden'})
    payload=dict(job_id=job_id,document_id=document_id,expected_version=expected_version,
                 checksum=staged.checksum_value,size=staged.size_in_bytes,file_name=staged.file_name,mime_type=staged.mime_type,preview=preview)
    def apply(c):
        lock_job(c,job_id,expected_version)
        return save(c,job_id=job_id,document_type=old['document_type'],staged=staged,preview=preview,supersedes=document_id)
    acquire_continuity_shared_lock(c)
    result=execute_command(c,command_id=command_id,operation='document_save',payload=payload,
                           acting_role_id=acting_role_id,reason=reason,apply=apply)
    document(c,job_id,result['id'])
    return result


def register(c, *, job_id, expected_version, document_type, command_id, acting_role_id,
             reason, staged: GovernedUpload, preview, template_version=None, provenance=None):
    """Private action-service entry point; never an unrestricted HTTP upload.

    An action service may call this and its outcome command on the same outer
    connection/transaction. Neither result may be committed on its own by that
    caller. The receipt binds file content and every storage/provenance input.
    """
    token=preview if isinstance(preview,str) else destination_token(preview)
    payload=dict(job_id=job_id,expected_version=expected_version,document_type=document_type,
                 checksum=staged.checksum_value,size=staged.size_in_bytes,file_name=staged.file_name,
                 mime_type=staged.mime_type,preview=token,template_version=template_version,provenance=provenance or {})
    def apply(c):
        lock_job(c,job_id,expected_version)
        return save(c,job_id=job_id,document_type=document_type,staged=staged,preview=token,
                    template_version=template_version,provenance=provenance)
    acquire_continuity_shared_lock(c)
    result=execute_command(c,command_id=command_id,operation='document_save',payload=payload,
                           acting_role_id=acting_role_id,reason=reason,apply=apply)
    document(c,job_id,result['id'])
    return result
