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


def report_snapshot(row,generated_at=None,*,c,settings=None):
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
    from .report_presentation import enrich
    if settings is None:
        from ..application_settings import load_snapshot
        settings=load_snapshot(c)
    return enrich(c,row,{'fields':fields,'proposals':proposals,'source':data},settings)


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
       kind='proposal_execution_report',snapshot=report_snapshot(row,c.execute('SELECT clock_timestamp() at').fetchone()['at'].isoformat(),c=c,settings=settings),command_id=uuid5(NAMESPACE_URL,f'wathiq:proposal-execution-report:{job_id}:{round_id}'),
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


def confirmation(c, *, task_id, acting_role_id, expected_version, task_version, changes):
    """Read-only hypothetical summary; cancellation never saves queued review work."""
    from collections import Counter
    from .commands import StaleVersion
    result = preview(c, task_id, acting_role_id)
    if result['job_version'] != expected_version or result['task_version'] != task_version:
        raise StaleVersion()
    task = c.execute('SELECT job_id FROM disposition_tasks WHERE id=%s', (task_id,)).fetchone()
    job_id = task['job_id']
    job = c.execute('SELECT review_route,workflow_stage FROM disposition_jobs WHERE id=%s', (job_id,)).fetchone()
    rows = c.execute('''SELECT p.id,p.version,p.governing_root_id,p.target_aggregation_id,p.target_record_id,
        p.proposal_type,p.proposed_values,p.current_values,p.reason FROM disposition_review_proposals p
        JOIN disposition_job_memberships m ON m.job_id=p.job_id AND m.root_aggregation_id=p.governing_root_id AND m.membership_state='active'
        WHERE p.job_id=%s AND p.review_round=disposition_private.review_round_for_work(%s) AND p.proposal_state='active' ''', (job_id,job_id)).fetchall()
    proposals = {p['id']: dict(p) for p in rows}
    for index, change in enumerate(changes):
        action = change['action']
        if action == 'create':
            proposal = {**change, 'id': -(index+1), 'version': 1}
        else:
            proposal = proposals.get(change['proposal_id'])
            if not proposal or proposal['version'] != change['expected_version']:
                raise HTTPException(409, detail={'code':'disposition_stale_proposal'})
            proposal = {**proposal, 'version': proposal['version']+1}
        if action == 'withdraw':
            allowed = c.execute('SELECT current_user_can_view_aggregation(%s) AND (%s::bigint IS NULL OR current_user_can_view_record(%s)) allowed', (proposal['target_aggregation_id'], proposal['target_record_id'], proposal['target_record_id'])).fetchone()['allowed']
            if not allowed:
                raise HTTPException(403, detail={'code':'disposition_resource_access_required'})
            del proposals[proposal['id']]
            continue
        if action == 'revise':
            proposal.update(proposed_values=change['proposed_values'], reason=change.get('reason'))
        from psycopg.types.json import Jsonb
        facts = c.execute('SELECT disposition_private.proposal_facts(%s,%s,%s,%s,%s,%s,%s) facts',
            (job_id, proposal['governing_root_id'], proposal['target_aggregation_id'], proposal.get('target_record_id'), proposal['proposal_type'], Jsonb(proposal['proposed_values']), proposal.get('reason'))).fetchone()['facts']
        target_version = facts['record']['version'] if proposal.get('target_record_id') else facts['aggregation_version']
        if target_version != change['target_version']:
            raise HTTPException(409, detail={'code':'disposition_stale_target'})
        proposal['current_values'] = facts
        proposals[proposal['id']] = proposal
    counts = Counter(p['proposal_type'] for p in proposals.values())
    roots = {r['root_aggregation_id'] for r in c.execute("SELECT root_aggregation_id FROM disposition_job_memberships WHERE job_id=%s AND membership_state='active'", (job_id,)).fetchall()}
    # These effects certainly remove their governing units on successful approval.
    # Retention, holds and new links can depend on live policy/cascading links;
    # do not promise an exact surviving count for those cases.
    removed = {p['governing_root_id'] for p in proposals.values() if p['proposal_type']=='blocking_security' or p['proposal_type']=='make_vital' and not p['current_values'].get('is_vital')}
    outcome = 'empty' if roots and roots <= removed else 'request' if set(counts) <= {'remove_aggregation_relationship','remove_record_relationship'} else 'conditional'
    return {**result, 'proposal_count':sum(counts.values()), 'proposal_counts':dict(sorted(counts.items())), 'next_step':outcome,
            'empty_return_stage':job['workflow_stage'] if job['review_route']=='records_manager_only' else 'officer_correction'}
