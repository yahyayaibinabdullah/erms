"""Approved request snapshots and atomic received external decisions.

PDF rendering/staging precedes workflow locks. Number/evidence/decision/task/
history commit together. Request/report retries never execute proposals again.
No email or physical/digital execution is implemented here.
"""
from uuid import uuid5,NAMESPACE_URL
from fastapi import HTTPException
from . import artifacts,documents,document_snapshots
from .commands import execute_command


def invalid(code,status=409):raise HTTPException(status,detail={'code':code})


def require_manager(c,job_id,acting_role_id):
    job=artifacts.require_workspace(c,job_id)
    allowed=c.execute("SELECT disposition_private.person_role(current_user_id(),%s) AND disposition_private.review_role(%s,'records_manager_review',%s) AND disposition_private.can_review_content(current_user_id(),%s) allowed",(acting_role_id,job_id,acting_role_id,job_id)).fetchone()['allowed']
    if not allowed:invalid('disposition_manager_role_required',403)
    return job


def round_row(c,job_id,round_id):
    row=c.execute('SELECT * FROM disposition_review_rounds WHERE id=%s AND job_id=%s AND approval_execution IS NOT NULL',(round_id,job_id)).fetchone()
    if not row:invalid('disposition_approval_unavailable',404)
    return row


def summaries(c,job,round_id):
    rows=c.execute('''SELECT d.review_stage,d.decision,d.reason,d.decided_at,u.name,r.name AS role FROM disposition_review_decisions d
      JOIN users u ON u.id=d.actor_user_id JOIN roles r ON r.id=d.acting_role_id WHERE d.round_id=%s ORDER BY d.id''',(round_id,)).fetchall()
    result={}
    for key,stage in [('file_administrator','file_administrator_review'),('unit_manager','unit_manager_review'),('records_manager','records_manager_review')]:
        matches=[d for d in rows if d['review_stage']==stage or key=='records_manager' and d['review_stage'] in ('manager_preparation','manager_correction')]
        result[key]='; '.join(f"{d['name']} · {d['role']} · {d['decision']} · {d['decided_at'].isoformat()} · {d['reason']}" for d in matches) if matches else ('تم تجاوز المرحلة وفق مسار المراجعة المحفوظ / Skipped under saved review route' if key!='records_manager' else '')
    return result


def generate_request(c,*,job_id,round_id,acting_role_id,settings,preview=None,connection_factory=None):
    job=require_manager(c,job_id,acting_role_id);rr=round_row(c,job_id,round_id)
    # Per-round generation mutex, not a workflow/resource lock during rendering.
    c.execute('SELECT pg_advisory_xact_lock(7360,hashtext(%s))',(f'{job_id}:{round_id}',))
    prior=c.execute("SELECT id FROM disposition_job_documents WHERE job_id=%s AND document_type='destruction_request' AND provenance->>'approval_round_id'=%s",(job_id,str(round_id))).fetchone()
    if prior:
        artifacts.document(c,job_id,prior['id'])
        return {'request_status':'available','request_document_id':prior['id'],'job_id':job_id,'round_id':round_id}
    if job['lifecycle_state']!='active' or job['current_review_round']!=rr['round_number'] or job['workflow_stage'] not in ('records_manager_review','manager_preparation','manager_correction'):invalid('disposition_request_stage_invalid')
    if not c.execute('SELECT disposition_private.request_approval_current(%s,%s) allowed',(job_id,round_id)).fetchone()['allowed']:invalid('disposition_approval_invalidated')
    facts=c.execute('SELECT disposition_private.request_facts(%s) facts',(job_id,)).fetchone()['facts']
    at=c.execute('SELECT clock_timestamp() at').fetchone()['at'].isoformat()
    source=facts['source'];count=document_snapshots.counts(source['aggregations'],source['records'],len(source['roots']))
    snapshot={'source':{'approved_facts':facts},'fields':{**document_snapshots.job_fields(c,job_id,at),
      'authority.name':settings['DISPOSITION_EXTERNAL_AUTHORITY_NAME'],**{'counts.'+k:v for k,v in count.items()},
      **{'review.'+k:v for k,v in summaries(c,job,round_id).items()},'review.round':rr['round_number'],'form.version':rr['round_number'],
      'membership.checksum':documents.checksum(facts)},'groups':document_snapshots.request_groups(source)}
    key=uuid5(NAMESPACE_URL,f'wathiq:destruction-request:{job_id}:{round_id}')
    destination=preview or artifacts.destination(c,job_id,'destruction_request')
    with c.transaction():
        result=documents.generate(c,job_id=job_id,expected_version=job['version'],kind='destruction_request',snapshot=snapshot,
          command_id=key,acting_role_id=acting_role_id,reason='Store the approved Request for Destruction Form',preview=destination,settings=settings,
          connection_factory=connection_factory,review_round=rr['round_number'],approval_round_id=round_id)
        return execute_command(c,command_id=uuid5(key,'activate'),operation='review_decide',payload={'job_id':job_id,'round_id':round_id,'request_document_id':result['id']},acting_role_id=acting_role_id,
          reason='Generate the approved request and assign the external decision task',
          apply=lambda x:x.execute('SELECT disposition_private.activate_request(%s,%s,%s,%s) result',(job_id,round_id,result['id'],job['version'])).fetchone()['result'])


def require_external_task(c,task_id,acting_role_id,*,working=True):
    c.execute('SELECT disposition_private.require_task_actor(%s,%s,%s)',(task_id,acting_role_id,working))
    t=c.execute("SELECT t.*,j.version AS job_version FROM disposition_tasks t JOIN disposition_jobs j ON j.id=t.job_id WHERE t.id=%s AND t.task_type='external_approval'",(task_id,)).fetchone()
    if not t:invalid('disposition_external_request_mismatch')
    artifacts.document(c,t['job_id'],t['request_document_id'])
    return t


def decide(c,*,task_id,expected_version,task_version,request_document_id,decision,correction_notes,destruction_number,
           staged,preview,acting_role_id,command_id,reason=None):
    if decision not in ('approved','rejected'):invalid('disposition_external_decision_invalid',422)
    if decision=='rejected' and not str(correction_notes or '').strip():invalid('disposition_external_notes_required',422)
    if decision=='approved' and (not isinstance(destruction_number,str) or not destruction_number.strip() or len(destruction_number)>20):invalid('disposition_destruction_number_invalid',422)
    # Existing receipts authorize exact committed retries even after task closure.
    prior=c.execute('SELECT result FROM disposition_private.command_receipts WHERE command_id=%s',(command_id,)).fetchone()
    t=require_external_task(c,task_id,acting_role_id,working=not bool(prior))
    kind='external_approval_letter' if decision=='approved' else 'external_rejection_letter'
    reason='Record external approval' if decision=='approved' else correction_notes.strip()
    payload=dict(task_id=task_id,expected_version=expected_version,task_version=task_version,request_document_id=request_document_id,
      decision=decision,correction_notes=correction_notes,destruction_number=destruction_number,checksum=staged.checksum_value,
      size=staged.size_in_bytes,file_name=staged.file_name,mime_type=staged.mime_type,preview=preview)
    # The evidence command and outcome command are savepoints in ONE outer
    # transaction; any outcome/number/task/audit failure removes the evidence too.
    with c.transaction():
        if not prior:
            c.execute('SELECT pg_advisory_xact_lock(7357,1)')
            if t['version']!=task_version or t['job_version']!=expected_version:invalid('disposition_stale_task')
            if t['request_document_id']!=request_document_id:invalid('disposition_external_request_mismatch')
        letter=None
        if not prior:
            letter=artifacts.register(c,job_id=t['job_id'],expected_version=expected_version,document_type=kind,
              command_id=uuid5(command_id,'letter'),acting_role_id=acting_role_id,reason=reason,staged=staged,preview=preview,
              provenance={'request_document_id':request_document_id,'external_command_id':str(command_id)})
        def apply(x):
            return x.execute('SELECT disposition_private.record_external_decision(%s,%s,%s,%s,%s,%s,%s,%s) result',
              (task_id,expected_version,task_version,request_document_id,decision,correction_notes,destruction_number,letter['id'])).fetchone()['result']
        result=execute_command(c,command_id=command_id,operation='review_decide',payload=payload,acting_role_id=acting_role_id,reason=reason,apply=apply)
        artifacts.document(c,t['job_id'],result['letter_document_id'])
        return result


def renew(c,*,job_id,round_id,expected_version,acting_role_id,command_id,reason=None):
    return execute_command(c,command_id=command_id,operation='review_decide',payload={'job_id':job_id,'round_id':round_id,'expected_version':expected_version,'decision':'rejected','invalidation':True},acting_role_id=acting_role_id,
      reason='Approved job facts changed; renew the complete saved review route',apply=lambda x:x.execute('SELECT disposition_private.renew_external_review(%s,%s,%s) result',(job_id,round_id,expected_version)).fetchone()['result'])


def view(c,job):
    rr=c.execute('SELECT id,approval_execution IS NOT NULL AS approved,invalidated_at FROM disposition_review_rounds WHERE job_id=%s AND round_number=%s',(job['id'],job['current_review_round'])).fetchone()
    if not rr or not rr['approved'] or rr['invalidated_at']:return None
    roles=c.execute("""SELECT r.id,r.name,p.code AS profile_code FROM roles r JOIN profiles p ON p.id=r.profile_id
      WHERE r.is_information_governance AND disposition_private.person_role(current_user_id(),r.id)
      AND disposition_private.can_review_content(current_user_id(),%s) AND EXISTS(SELECT 1 FROM profile_privileges pp JOIN privileges v ON v.id=pp.privilege_id WHERE pp.profile_id=r.profile_id AND v.code='disposition.jobs.manage')
      AND (p.code='INFO_GOV_MGR' OR p.code='INFO_GOV_OFFICER' AND current_user_id()=%s AND %s<>'records_manager_only') ORDER BY r.id""",(job['id'],job['assigned_user_id'],job['review_route'])).fetchall()
    current=c.execute('SELECT disposition_private.request_approval_current(%s,%s) allowed',(job['id'],rr['id'])).fetchone()['allowed']
    req=c.execute("""SELECT d.id,d.record_id,d.digital_component_id,c.file_name,current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id) AS visible FROM disposition_job_documents d JOIN digital_components c ON c.id=d.digital_component_id
      WHERE d.job_id=%s AND d.document_type='destruction_request' AND d.provenance->>'approval_round_id'=%s""",(job['id'],str(rr['id']))).fetchone()
    manager_roles=[r for r in roles if r['profile_code']=='INFO_GOV_MGR']
    received=c.execute('SELECT * FROM disposition_external_approvals WHERE job_id=%s AND round_id=%s ORDER BY id DESC LIMIT 1',(job['id'],rr['id'])).fetchone()
    visible_received=bool(received and c.execute("SELECT current_user_can_view_event_resource('disposition_job',job_id,NULL,to_jsonb(a)) allowed FROM disposition_external_approvals a WHERE id=%s",(received['id'],)).fetchone()['allowed'])
    failure=c.execute("SELECT metadata->>'code' code FROM event_history WHERE entity_type='disposition_job' AND entity_id=%s AND operation='DESTRUCTION_REQUEST_PENDING' AND metadata->>'round_id'=%s ORDER BY id DESC LIMIT 1",(job['id'],str(rr['id']))).fetchone() if not req else None
    stage=job['workflow_stage'];active=job['lifecycle_state']=='active'
    return {'round_id':rr['id'],'approval_current':current,'request':{k:v for k,v in req.items() if k!='visible'} if req and req['visible'] else None,
      'received_decision':received['decision'] if visible_received else None,'generation_error':failure['code'] if failure else None,
      'can_generate':bool(active and manager_roles and not req and stage in ('records_manager_review','manager_preparation','manager_correction') and current),
      'can_renew':bool(active and roles and not current and stage in ('records_manager_review','manager_preparation','manager_correction','external_approval_pending')),
      'manager_roles':manager_roles,'renew_roles':roles}


def history(c,job_id,*,limit,offset,sort='recorded_at',descending=True):
    artifacts.require_workspace(c,job_id)
    orders={'recorded_at':'a.recorded_at','decision':'a.decision','review_round':'d.review_round','destruction_number':'a.destruction_number'}
    if sort not in orders:invalid('disposition_external_decision_invalid',422)
    rows=c.execute('''SELECT a.*,u.name AS actor,r.name AS role,d.review_round,rc.file_name AS request_name,lc.file_name AS letter_name,
      current_user_can_view_event_resource('disposition_job',a.job_id,NULL,to_jsonb(a)) AS visible
      FROM disposition_external_approvals a JOIN users u ON u.id=a.recorded_by_user_id JOIN roles r ON r.id=a.acting_role_id JOIN disposition_job_documents d ON d.id=a.request_document_id
      JOIN digital_components rc ON rc.id=d.digital_component_id JOIN disposition_job_documents letter ON letter.id=COALESCE(a.approval_letter_document_id,a.rejection_letter_document_id)
      JOIN digital_components lc ON lc.id=letter.digital_component_id
      WHERE a.job_id=%s ORDER BY '''+orders[sort]+(' DESC' if descending else ' ASC')+',a.id DESC LIMIT %s OFFSET %s',(job_id,limit,offset)).fetchall()
    for i,row in enumerate(rows):
        if not row.pop('visible'):rows[i]={'id':row['id'],'redacted':True}
        else:row['redacted']=False
    return {'items':rows,'total':c.execute('SELECT count(*) n FROM disposition_external_approvals WHERE job_id=%s',(job_id,)).fetchone()['n']}
