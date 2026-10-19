"""Physical preparation snapshots and gated, atomic offline confirmations.

No operation destroys content. The immutable SQL release boundary remains
closed until recovery and completion pass. No environment flag bypasses it.
"""
from uuid import uuid5
from fastapi import HTTPException
from . import artifacts,documents,document_snapshots,external
from .commands import execute_command


def invalid(code,status=409):raise HTTPException(status,detail={'code':code})


def generate_report(c,*,job_id,expected_version,command_id,acting_role_id,settings,preview=None,connection_factory=None,automatic=False,reason=None):
    job=documents.require_access(c,job_id,acting_role_id)
    if not automatic:external.require_manager(c,job_id,acting_role_id)
    # Serializes only this report's versions. Resource/workflow locks follow rendering.
    c.execute('SELECT pg_advisory_xact_lock(7364,hashtext(%s))',(str(job_id),))
    prior=c.execute('SELECT payload,result FROM disposition_private.command_receipts WHERE command_id=%s',(command_id,)).fetchone()
    if prior:
        payload=prior['payload'];snapshot=payload.get('snapshot',{})
    else:
        if job['lifecycle_state']!='active' or job['workflow_stage']!='physical_destruction' or c.execute('SELECT 1 FROM disposition_physical_confirmations WHERE job_id=%s',(job_id,)).fetchone():invalid('disposition_physical_stage_invalid')
        version=c.execute("SELECT count(*)+1 n FROM disposition_job_documents WHERE job_id=%s AND document_type='physical_preparation_report'",(job_id,)).fetchone()['n']
        at=c.execute('SELECT clock_timestamp() at').fetchone()['at'].isoformat()
        snapshot=document_snapshots.preparation_snapshot(c,job_id,report_version=version,generated_at=at)
    def recheck(x):
        x.execute('SELECT disposition_private.lock_request_facts(%s)',(job_id,))
        if document_snapshots.capture(x,job_id)!=snapshot['source']:invalid('disposition_physical_report_stale')
        if x.execute('SELECT 1 FROM disposition_physical_confirmations WHERE job_id=%s',(job_id,)).fetchone():invalid('disposition_physical_stage_invalid')
    return documents.generate(c,job_id=job_id,expected_version=expected_version,kind='physical_preparation_report',snapshot=snapshot,command_id=command_id,acting_role_id=acting_role_id,
      reason='Store physical destruction preparation report',preview=preview or (prior['payload']['preview'] if prior else artifacts.destination(c,job_id,'physical_preparation_report')),
      settings=settings,connection_factory=connection_factory,review_round=job['current_review_round'],before_save=recheck)


def check_work(c,*,task_id,expected_version,task_version,acting_role_id,command_id,reason=None):
    # Never replay a previously successful safety check over changed blockers.
    scope=c.execute('SELECT disposition_private.check_physical_work(%s,%s,%s,%s) scope',(task_id,expected_version,task_version,acting_role_id)).fetchone()['scope']
    def apply(x):
        job=x.execute('SELECT job_id FROM disposition_tasks WHERE id=%s',(task_id,)).fetchone()['job_id']
        from psycopg.types.json import Jsonb
        x.execute("SELECT append_domain_event('disposition_job',%s,'PHYSICAL_WORK_CHECKED',%s)",(job,Jsonb({'physical_scope':scope,'acting_role_id':acting_role_id})))
        return {'job_id':job,'physical_scope':scope,'authorized':True}
    return execute_command(c,command_id=command_id,operation='review_decide',payload=dict(task_id=task_id,expected_version=expected_version,task_version=task_version),acting_role_id=acting_role_id,reason='Check current blockers before offline physical work',apply=apply)


def confirm(c,*,task_id,expected_version,task_version,successful,certificate_reference,staged,preview,acting_role_id,command_id,reason=None):
    if successful is not True or not str(certificate_reference or '').strip():invalid('disposition_physical_required',422)
    t=c.execute("SELECT * FROM disposition_tasks WHERE id=%s AND task_type='physical_destruction'",(task_id,)).fetchone()
    if not t:invalid('disposition_physical_stage_invalid')
    external.require_manager(c,t['job_id'],acting_role_id)
    prior=c.execute('SELECT result FROM disposition_private.command_receipts WHERE command_id=%s',(command_id,)).fetchone()
    payload=dict(task_id=task_id,expected_version=expected_version,task_version=task_version,successful=successful,certificate_reference=certificate_reference,
      checksum=staged.checksum_value,size=staged.size_in_bytes,file_name=staged.file_name,mime_type=staged.mime_type,preview=preview)
    with c.transaction():
        if not prior:
            c.execute('SELECT disposition_private.check_physical_work(%s,%s,%s,%s)',(task_id,expected_version,task_version,acting_role_id))
        certificate=None
        if not prior:
            certificate=artifacts.register(c,job_id=t['job_id'],expected_version=expected_version,document_type='physical_destruction_certificate',command_id=uuid5(command_id,'certificate'),acting_role_id=acting_role_id,
              reason='Store completed physical destruction certificate',staged=staged,preview=preview,provenance={'physical_command_id':str(command_id),'certificate_reference':certificate_reference})
        result=execute_command(c,command_id=command_id,operation='review_decide',payload=payload,acting_role_id=acting_role_id,reason='Confirm successful offline physical destruction',
          apply=lambda x:x.execute('SELECT disposition_private.confirm_physical(%s,%s,%s,%s,%s,%s) result',(task_id,expected_version,task_version,successful,certificate_reference,certificate['id'])).fetchone()['result'])
        artifacts.document(c,t['job_id'],result['certificate_document_id']);return result


def view(c,job):
    if job['workflow_stage'] not in ('physical_destruction','digital_destruction') and not c.execute('SELECT 1 FROM disposition_physical_confirmations WHERE job_id=%s',(job['id'],)).fetchone():return None
    roles=[r for r in documents.roles(c) if c.execute("SELECT disposition_private.person_role(current_user_id(),%s) AND disposition_private.review_role(%s,'records_manager_review',%s) AND disposition_private.can_review_content(current_user_id(),%s) allowed",(r['id'],job['id'],r['id'],job['id'])).fetchone()['allowed']]
    latest=c.execute("SELECT d.id,d.record_id,d.digital_component_id,d.provenance#>>'{snapshot,fields,report.version}' AS report_version,c.file_name,current_user_can_record_component_operation(d.record_id,'record.component.view','record.component.view') AS can_preview,current_user_can_record_component_operation(d.record_id,'record.component.download','record.component.download') AS can_download FROM disposition_job_documents d JOIN digital_components c ON c.id=d.digital_component_id WHERE d.job_id=%s AND d.document_type='physical_preparation_report' AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id) ORDER BY d.id DESC LIMIT 1",(job['id'],)).fetchone()
    confirmation=c.execute("SELECT p.* FROM disposition_physical_confirmations p WHERE p.job_id=%s AND current_user_can_view_event_resource('disposition_job',p.job_id,NULL,to_jsonb(p))",(job['id'],)).fetchone()
    released=c.execute('SELECT disposition_private.physical_execution_released() allowed').fetchone()['allowed']
    required=job['workflow_stage']=='physical_destruction' or bool(latest or confirmation) or bool(c.execute("SELECT 1 FROM disposition_tasks WHERE job_id=%s AND task_type='physical_destruction' LIMIT 1",(job['id'],)).fetchone())
    return {'physical_required':required,'report':latest,'confirmation':confirmation,'manager_roles':roles,'released':released,'can_generate':bool(roles and job['lifecycle_state']=='active' and job['workflow_stage']=='physical_destruction' and not confirmation)}
