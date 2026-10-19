"""Organization-wide immutable templates and private snapshot PDF generation.

There is deliberately no public 'generate any document' action. Approval,
execution and preparation services own their snapshot and transaction boundary.
No job state is changed here. There is no content/authorization/result cache.
"""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from functools import cache

from fastapi import HTTPException,UploadFile
from psycopg.types.json import Jsonb
from starlette.datastructures import Headers

from ..content_storage import stage_governed_upload
from ..continuity_lock import acquire_continuity_shared_lock
from . import artifacts,template_engine as engine
from .commands import execute_command,lock_job
from .template_contract import CONTRACTS

DEFAULTS=Path(__file__).resolve().parents[4]/'templates/disposition/destruction'
METADATA='id,document_type,revision_number,original_filename,checksum,uploaded_by_user_id,acting_role_id,actor_type,uploaded_from_job_id,uploaded_at'


def checksum(value):
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def roles(c):
    return c.execute('''SELECT r.id,r.name FROM roles r
      WHERE disposition_private.can_revise_template(r.id) ORDER BY r.id''').fetchall()


def require_access(c,job_id,role=None):
    job=artifacts.require_workspace(c,job_id)
    allowed=roles(c)
    if job['job_type']!='destruction' or not allowed or role is not None and not any(r['id']==role for r in allowed):
        engine.invalid('disposition_template_forbidden',403)
    return job


@cache
def _default_bytes(kind):
    # Process-scoped immutable packaged assets, keyed by the four fixed types.
    # A deployment/restart invalidates it; runtime uploads never alter defaults.
    # Failures are not cached. No identity, locale or authorized data is cached.
    if kind not in CONTRACTS:engine.invalid('disposition_document_type_invalid')
    name=CONTRACTS[kind].filename;content=(DEFAULTS/name).read_bytes();digest=sha256(content).hexdigest()
    manifest=json.loads((DEFAULTS/'defaults.json').read_text())
    if manifest.get(name)!=digest:engine.invalid('disposition_template_invalid',409)
    return content,digest


def default(kind):
    content,digest=_default_bytes(kind);name=CONTRACTS[kind].filename
    return dict(id=None,document_type=kind,revision_number=0,reference='default.v1:'+digest,
      original_filename=name,checksum=digest,content=content,uploaded_by_user_id=None,acting_role_id=None,
      actor_type=None,uploaded_at=None,source='repository')


def current(c,kind,*,include_content=True):
    if kind not in CONTRACTS:engine.invalid('disposition_document_type_invalid')
    row=c.execute('SELECT '+METADATA+(',content' if include_content else '')+' FROM disposition_template_revisions WHERE document_type=%s ORDER BY revision_number DESC LIMIT 1',(kind,)).fetchone()
    if not row:return default(kind)
    return dict(row,reference='revision:'+str(row['id'])+':'+row['checksum'],source='upload')


def public(row):
    return {k:v for k,v in row.items() if k!='content'}


def catalogue(c,job_id):
    require_access(c,job_id)
    # Four fixed template types, not a growing collection.
    rows=c.execute('SELECT DISTINCT ON(document_type) '+METADATA+' FROM disposition_template_revisions ORDER BY document_type,revision_number DESC').fetchall()
    by_kind={r['document_type']:dict(r,reference='revision:'+str(r['id'])+':'+r['checksum'],source='upload') for r in rows}
    return {'items':[by_kind[kind] if kind in by_kind else public(default(kind)) for kind in CONTRACTS],'roles':roles(c)}


def history(c,job_id,kind,*,limit,offset,sort='revision_number',descending=True):
    require_access(c,job_id)
    if kind not in CONTRACTS:engine.invalid('disposition_document_type_invalid')
    total=c.execute('SELECT count(*) n FROM disposition_template_revisions WHERE document_type=%s',(kind,)).fetchone()['n']+1
    orders={'revision_number':'revision_number','original_filename':'original_filename','uploaded_at':'uploaded_at'}
    if sort not in orders:engine.invalid('disposition_template_invalid')
    base=default(kind)
    rows=c.execute('''SELECT * FROM (SELECT t.id,t.document_type,t.revision_number,t.original_filename,t.checksum,t.uploaded_by_user_id,
      t.acting_role_id,t.actor_type,t.uploaded_at,u.name AS uploader,r.name AS acting_role
      FROM disposition_template_revisions t JOIN users u ON u.id=t.uploaded_by_user_id JOIN roles r ON r.id=t.acting_role_id
      WHERE t.document_type=%s UNION ALL SELECT NULL::bigint,%s,0,%s,%s,NULL::bigint,NULL::bigint,NULL::text,
      NULL::timestamptz,NULL::text,NULL::text) history ORDER BY '''+orders[sort]+(' DESC' if descending else ' ASC')+' NULLS LAST,id DESC LIMIT %s OFFSET %s',
      (kind,kind,base['original_filename'],base['checksum'],limit,offset)).fetchall()
    items=[dict(row,reference='revision:'+str(row['id'])+':'+row['checksum'],source='upload') if row['id'] else public(base) for row in rows]
    return {'items':items,'total':total}


def download(c,job_id,kind,reference=None):
    require_access(c,job_id)
    if reference is None:return current(c,kind)
    if reference.startswith('default.v1:'):
        row=default(kind)
    else:
        row=c.execute('SELECT * FROM disposition_template_revisions WHERE document_type=%s AND id::text=%s',
          (kind,reference.split(':')[1] if reference.startswith('revision:') and len(reference.split(':'))==3 else '')).fetchone()
        if not row:engine.invalid('disposition_template_unavailable',404)
        row=dict(row,reference='revision:'+str(row['id'])+':'+row['checksum'],content=bytes(row['content']))
    if row['reference']!=reference:engine.invalid('disposition_template_unavailable',404)
    return row


def revise(c,*,job_id,kind,expected_reference,command_id,acting_role_id,reason,content,filename,settings):
    require_access(c,job_id,acting_role_id)
    if Path(filename).suffix.lower()!='.docx':engine.invalid()
    engine.validate(content,kind,settings['MAX_RENDITION_SIZE_BYTES'])
    digest=sha256(content).hexdigest();name=Path(filename.replace('\\','/')).name
    payload=dict(template_upload=True,job_id=job_id,kind=kind,expected_reference=expected_reference,checksum=digest,filename=name)
    def apply(c):
        if current(c,kind,include_content=False)['reference']!=expected_reference:engine.invalid('disposition_template_stale',409)
        revision=c.execute('''INSERT INTO disposition_template_revisions(document_type,revision_number,original_filename,
          content,checksum,uploaded_by_user_id,acting_role_id,uploaded_from_job_id)
          VALUES(%s,(SELECT coalesce(max(revision_number),0)+1 FROM disposition_template_revisions WHERE document_type=%s),
          %s,%s,%s,current_user_id(),%s,%s) RETURNING id,revision_number''',(kind,kind,name,content,digest,acting_role_id,job_id)).fetchone()
        return dict(revision,reference='revision:'+str(revision['id'])+':'+digest)
    return execute_command(c,command_id=command_id,operation='document_save',payload=payload,
      acting_role_id=acting_role_id,reason=reason,apply=apply)


def generate(c,*,job_id,expected_version,kind,snapshot,command_id,acting_role_id,reason,preview,settings,connection_factory=None,review_round=None,approval_round_id=None):
    """Render an action-owned snapshot and save once, retaining its exact input.

    Render/stage before workflow locks. Retried committed generations bypass
    rendering and retain the original template even if another upload became
    current. The caller owns the outer commit; a later failure rolls back the
    artifact and receipt together. Later phases supply the action-specific
    approval/execution gates and never accept snapshot data from the browser.
    """
    job=require_access(c,job_id,acting_role_id)
    if kind not in CONTRACTS:engine.invalid('disposition_document_type_invalid')
    engine.snapshot_values(kind,snapshot)
    if str(snapshot['fields']['job.id'])!=str(job_id):engine.invalid('disposition_document_snapshot_invalid')
    token=preview if isinstance(preview,str) else artifacts.destination_token(preview)
    payload=dict(template_generation=True,job_id=job_id,expected_version=expected_version,kind=kind,snapshot=snapshot,preview=token)
    if approval_round_id is not None:payload.update(approval_round_id=approval_round_id,review_round=review_round)
    prior=c.execute('SELECT result FROM disposition_private.command_receipts WHERE command_id=%s',(command_id,)).fetchone()
    if prior:
        result=execute_command(c,command_id=command_id,operation='document_save',payload=payload,acting_role_id=acting_role_id,reason=reason,
          apply=lambda c:engine.invalid('disposition_command_conflict',409))
        artifacts.document(c,job_id,result['id']);return result
    revision=current(c,kind)
    pdf,rendered=engine.render(revision['content'],kind,snapshot,settings)
    provenance={'template_revision':revision['reference'],'template_checksum':revision['checksum'],
      'template_type':kind,'template_filename':revision['original_filename'],'snapshot':snapshot,
      'snapshot_checksum':checksum(snapshot),'generation_key':str(command_id),**rendered}
    if approval_round_id is not None:provenance['approval_round_id']=approval_round_id
    upload=UploadFile(BytesIO(pdf),filename=f"{kind}-{job_id}.pdf",headers=Headers({'content-type':'application/pdf'}))
    with stage_governed_upload(upload,settings,connection_factory=connection_factory) as staged:
        def apply(c):
            lock_job(c,job_id,expected_version)
            return artifacts.save(c,job_id=job_id,document_type=kind,staged=staged,preview=token,
              template_version=revision['reference'],provenance=provenance,review_round=review_round)
        acquire_continuity_shared_lock(c)
        result=execute_command(c,command_id=command_id,operation='document_save',payload=payload,
          acting_role_id=acting_role_id,reason=reason,apply=apply)
    artifacts.document(c,job_id,result['id']);return result
