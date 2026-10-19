"""Atomic Manager approval; report storage retries never replay execution.

The caller commits approval before generating its report on a fresh transaction.
All reviewed values/tokens are server snapshots; clients cannot choose a subset.
"""
from uuid import UUID,uuid5,NAMESPACE_URL

from fastapi import HTTPException

from .commands import execute_command
from . import artifacts,documents


def preview(c,task_id,acting_role_id):
    with c.transaction():
        return c.execute('SELECT disposition_private.approval_preview(%s,%s) result',(task_id,acting_role_id)).fetchone()['result']


def approve(c,*,task_id,expected_version,task_version,membership_token,proposals_token,
            overall_reason=None,acting_role_id,command_id: UUID,reason=None):
    # Approval has its own protected endpoint. Ordinary review decisions remain
    # unable to approve or apply a partial proposal selection.
    payload=dict(task_id=task_id,expected_version=expected_version,task_version=task_version,
                 membership_token=membership_token,proposals_token=proposals_token,overall_reason=overall_reason,approval=True)
    return execute_command(c,command_id=command_id,operation='review_decide',payload=payload,
        acting_role_id=acting_role_id,reason=(reason or '').strip() or (overall_reason or '').strip() or 'Approve the complete reviewed proposal set',
        apply=lambda x:x.execute('SELECT disposition_private.approve_proposals(%s,%s,%s,%s,%s,%s) result',
          (task_id,expected_version,task_version,membership_token,proposals_token,overall_reason)).fetchone()['result'])


def execution(c,job_id,round_id,acting_role_id):
    artifacts.require_workspace(c,job_id)
    if not c.execute("SELECT disposition_private.person_role(current_user_id(),%s) AND disposition_private.review_role(%s,'records_manager_review',%s) allowed",(acting_role_id,job_id,acting_role_id)).fetchone()['allowed']:
        raise HTTPException(403,detail={'code':'disposition_manager_role_required'})
    row=c.execute('SELECT * FROM disposition_review_rounds WHERE id=%s AND job_id=%s AND approval_execution IS NOT NULL',(round_id,job_id)).fetchone()
    if not row:raise HTTPException(404,detail={'code':'disposition_approval_unavailable'})
    if not c.execute("SELECT current_user_can_view_event_resource('disposition_review_round',%s,NULL,to_jsonb(r)) allowed FROM disposition_review_rounds r WHERE id=%s",(round_id,round_id)).fetchone()['allowed']:
        raise HTTPException(403,detail={'code':'disposition_resource_access_required'})
    return row


def report_snapshot(row,generated_at=None):
    data=row['approval_execution'];job=data['job_snapshot']
    fields={'job.id':row['job_id'],'job.number':job['job_number'],'job.type':job['job_type'],
       'job.owner':job['owner_name'],'job.officer':job['assignee_name'],'job.created_at':job['date_created'],
       'generated_at':generated_at or data['executed_at'],'review.round':row['round_number'],
       'execution.manager':data['approving_user_name']+' · '+data['acting_role_name'],
       'execution.reference':data['command_id'],'membership.checksum':documents.checksum(data['post_membership'])}
    proposals=[]
    for p in data['results']:
        effect=p['effect'];removed=sorted({str(e['governing_root_id']) for e in effect['effects'] if e['effect_type'] in ('unit_removed','cascading_unit_removed')})
        target=p['current_values'].get('record') if p['target_record_id'] is not None else p['current_values']
        target_code=target.get('record_number') if p['target_record_id'] is not None else target.get('aggregation_number')
        proposals.append({'proposal.id':p['id'],'proposal.action':p['proposal_type'].replace('_',' ').title(),
           'proposal.target':str(target_code or p['target_record_id'] or p['target_aggregation_id'])+' · '+target.get('title',''),
           'proposal.proposer':p['proposer_name']+' · '+p['proposer_role'],
           'proposal.result':p['proposal_state'].title(),'proposal.executor':fields['execution.manager'],
           'proposal.reason':effect['reason_used']+' · '+effect['reason_source'].title(),
           'proposal.removed_units':', '.join(removed) or '—',
           'proposal.history':f"disposition_review_proposal:{p['id']}"})
    return {'fields':fields,'proposals':proposals,'source':data}


def generate_report(c,*,job_id,round_id,acting_role_id,settings,preview=None,connection_factory=None):
    row=execution(c,job_id,round_id,acting_role_id)
    # Serialize only report creation for this immutable round, across API
    # instances. This holds no job/workflow lock while rendering or staging.
    c.execute("SELECT pg_advisory_xact_lock(7358,hashtext(%s))",(f'{job_id}:{round_id}',))
    prior=c.execute("SELECT id FROM disposition_job_documents WHERE job_id=%s AND review_round=%s AND document_type='proposal_execution_report' AND provenance->>'approval_round_id'=%s",(job_id,row['round_number'],str(round_id))).fetchone()
    if prior:
        return artifacts.document(c,job_id,prior['id'])
    destination=preview or artifacts.destination(c,job_id,'proposal_execution_report')
    result=documents.generate(c,job_id=job_id,expected_version=c.execute('SELECT version FROM disposition_jobs WHERE id=%s',(job_id,)).fetchone()['version'],
       kind='proposal_execution_report',snapshot=report_snapshot(row,c.execute('SELECT clock_timestamp() at').fetchone()['at'].isoformat()),command_id=uuid5(NAMESPACE_URL,f'wathiq:proposal-execution-report:{job_id}:{round_id}'),
       acting_role_id=acting_role_id,reason='Store the approved proposal execution report',preview=destination,settings=settings,
       connection_factory=connection_factory,review_round=row['round_number'],approval_round_id=round_id)
    return result


def effects(c,job_id,*,limit,offset):
    artifacts.require_workspace(c,job_id)
    source=' FROM disposition_proposal_effects e JOIN disposition_review_proposals p ON p.id=e.proposal_id WHERE p.job_id=%s'
    total=c.execute('SELECT count(*) n'+source,(job_id,)).fetchone()['n']
    rows=c.execute('SELECT e.*,disposition_private.proposal_visible(to_jsonb(p)) AND current_user_can_view_aggregation(e.governing_root_id) visible'+source+' ORDER BY e.id LIMIT %s OFFSET %s',(job_id,limit,offset)).fetchall()
    for i,row in enumerate(rows):
        if not row.pop('visible'):rows[i]={'id':row['id'],'redacted':True}
        else:row['redacted']=False
    return {'items':rows,'total':total}
