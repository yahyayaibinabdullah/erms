"""Saved destruction review work and stage decisions; no proposal execution.

Callers own a consistent transaction. The SQL gates independently enforce task,
claim, type, scope, actor, access, version, history and no-execution boundaries.
Operational projections are uncached and server-paginated.
"""
from uuid import UUID
from psycopg.types.json import Jsonb
from fastapi import HTTPException

from .commands import execute_command
from .artifacts import require_workspace


def save(c, *, task_id, expected_version, task_version, changes, review_notes=None,
         note_version=None, overall_reason=None, acting_role_id, command_id: UUID,
         reason='Save destruction review work'):
    payload=dict(task_id=task_id,expected_version=expected_version,task_version=task_version,
                 changes=changes,review_notes=review_notes,note_version=note_version,overall_reason=overall_reason)
    return execute_command(c,command_id=command_id,operation='review_save',payload=payload,
      acting_role_id=acting_role_id,reason=reason,apply=lambda x:x.execute(
        'SELECT disposition_private.save_review_work(%s,%s,%s,%s,%s,%s,%s) result',
        (task_id,expected_version,task_version,Jsonb(changes),review_notes,note_version,overall_reason)).fetchone()['result'])


def submit(c, *, task_id, expected_version, task_version, overall_reason,
           acting_role_id, command_id: UUID, reason=None):
    if not overall_reason or not overall_reason.strip():
        raise HTTPException(422,detail={'code':'disposition_submission_reason_required'})
    payload=dict(task_id=task_id,expected_version=expected_version,task_version=task_version,overall_reason=overall_reason)
    return execute_command(c,command_id=command_id,operation='review_submit',payload=payload,
      acting_role_id=acting_role_id,reason=overall_reason,apply=lambda x:x.execute(
        'SELECT disposition_private.submit_review_work(%s,%s,%s,%s) result',
        (task_id,expected_version,task_version,overall_reason)).fetchone()['result'])


def decide(c, *, task_id, expected_version, task_version, decision, decision_reason='',
           acting_role_id, command_id: UUID, reason=None):
    payload=dict(task_id=task_id,expected_version=expected_version,task_version=task_version,
                 decision=decision,decision_reason=decision_reason)
    return execute_command(c,command_id=command_id,operation='review_decide',payload=payload,
      acting_role_id=acting_role_id,reason=decision_reason.strip() or ('Return review for correction' if decision=='rejected' else 'Complete authorized review'),
      apply=lambda x:x.execute('SELECT disposition_private.decide_review_work(%s,%s,%s,%s,%s) result',
        (task_id,expected_version,task_version,decision,decision_reason)).fetchone()['result'])


def page(c, job_id, *, limit, offset, review_round=None, state=None, root_id=None):
    require_workspace(c,job_id)
    clauses=['p.job_id=%s'];params=[job_id]
    if review_round is not None:clauses.append('p.review_round=%s');params.append(review_round)
    else:clauses.append('p.review_round=disposition_private.review_round_for_work(p.job_id)')
    if state:clauses.append('p.proposal_state=%s');params.append(state)
    if root_id is not None:clauses.append('p.governing_root_id=%s');params.append(root_id)
    source=' FROM disposition_review_proposals p LEFT JOIN users proposer ON proposer.id=p.proposer_user_id LEFT JOIN roles proposer_role ON proposer_role.id=p.proposer_role_id LEFT JOIN users editor ON editor.id=p.last_revised_by_user_id LEFT JOIN roles editor_role ON editor_role.id=p.last_revised_role_id WHERE '+' AND '.join(clauses)
    total=c.execute('SELECT count(*) total'+source,params).fetchone()['total']
    rows=c.execute("""SELECT p.*,proposer.name AS proposer_name,proposer_role.name AS proposer_role_name,editor.name AS editor_name,editor_role.name AS editor_role_name,
        (SELECT name FROM security_levels WHERE id=(p.current_values->>'security_level_id')::bigint) AS current_security_name,
        (SELECT forward_name FROM relationship_types WHERE id=(p.current_values#>>'{relationship,relationship_type_id}')::bigint) AS relationship_type_name,
        CASE WHEN p.current_values#>>'{relationship,resource_kind}'='record' THEN (SELECT record_number||' · '||title FROM records WHERE id=(p.current_values#>>'{relationship,source_id}')::bigint) ELSE (SELECT aggregation_number||' · '||title FROM aggregations WHERE id=(p.current_values#>>'{relationship,source_id}')::bigint) END AS relationship_source_label,
        CASE WHEN p.current_values#>>'{relationship,resource_kind}'='record' THEN (SELECT record_number||' · '||title FROM records WHERE id=(p.current_values#>>'{relationship,target_id}')::bigint) ELSE (SELECT aggregation_number||' · '||title FROM aggregations WHERE id=(p.current_values#>>'{relationship,target_id}')::bigint) END AS relationship_target_label,
        EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=p.job_id AND m.root_aggregation_id=p.governing_root_id AND m.membership_state='active') AS in_current_membership,disposition_private.proposal_visible(to_jsonb(p)) visible"""+source+' ORDER BY p.governing_root_id,p.target_aggregation_id,p.target_record_id,p.proposal_type,p.id LIMIT %s OFFSET %s',[*params,limit,offset]).fetchall()
    for i,row in enumerate(rows):
        if not row.pop('visible'):
            rows[i]={'id':row['id'],'version':row['version'],'redacted':True}
        else:
            row['redacted']=False
    return {'items':rows,'total':total}


def work(c, task_id):
    task=c.execute('SELECT * FROM disposition_tasks WHERE id=%s',(task_id,)).fetchone()
    if not task:raise HTTPException(404,detail={'code':'disposition_review_task_unavailable'})
    require_workspace(c,task['job_id'])
    if not c.execute('SELECT disposition_private.task_eligible(current_user_id(),%s) allowed',(task_id,)).fetchone()['allowed']:
        raise HTTPException(403,detail={'code':'disposition_task_ineligible'})
    job=c.execute('SELECT version,current_review_round,review_route,workflow_stage FROM disposition_jobs WHERE id=%s',(task['job_id'],)).fetchone()
    own=c.execute('SELECT * FROM disposition_review_notes WHERE task_id=%s AND author_user_id=current_user_id()',(task_id,)).fetchone()
    return {'job_id':task['job_id'],'job_version':job['version'],'task_id':task_id,'task_version':task['version'],
      'task_state':task['task_state'],'workflow_stage':job['workflow_stage'],'review_route':job['review_route'],
      'review_round':max(1,job['current_review_round']),'overall_reason':task['draft_overall_reason'],
      'own_notes':own,'submission_reason':(c.execute('SELECT submission_reason FROM disposition_review_rounds WHERE job_id=%s AND round_number=%s',(task['job_id'],job['current_review_round'])).fetchone() or {}).get('submission_reason')}


def notes(c, job_id, *, limit, offset):
    require_workspace(c,job_id)
    visible=c.execute("SELECT current_user_can_view_event_resource('disposition_job',%s,NULL,NULL) allowed",(job_id,)).fetchone()['allowed']
    total=c.execute('SELECT count(*) total FROM disposition_review_notes WHERE job_id=%s',(job_id,)).fetchone()['total']
    rows=c.execute('SELECT n.*,u.name AS author_name,r.name AS role_name FROM disposition_review_notes n JOIN users u ON u.id=n.author_user_id JOIN roles r ON r.id=n.acting_role_id WHERE n.job_id=%s ORDER BY n.review_round,n.workflow_stage,n.id LIMIT %s OFFSET %s',(job_id,limit,offset)).fetchall()
    if not visible:rows=[{'id':r['id'],'version':r['version'],'redacted':True} for r in rows]
    return {'items':rows,'total':total}


def candidates(c, task_id, *, acting_role_id, kind, query='', selected=None):
    c.execute('SELECT disposition_private.require_task_actor(%s,%s,true)',(task_id,acting_role_id))
    if selected is None and len(query.strip())<2:return {'items':[]}
    match='%'+query.strip()+'%'
    if kind=='holds':
        rows=c.execute('''SELECT h.id,h.code,h.name,h.version FROM holds h WHERE disposition_private.hold_visible(h.id)
          AND ((%s::bigint IS NOT NULL AND h.id=%s) OR (%s::bigint IS NULL AND (h.code ILIKE %s OR h.name ILIKE %s))) ORDER BY h.code,h.id LIMIT 25''',(selected,selected,selected,match,match)).fetchall()
    elif kind in ('aggregations','records'):
        table='aggregations' if kind=='aggregations' else 'records';identity='aggregation' if kind=='aggregations' else 'record'
        rows=c.execute(f'''SELECT id,{identity}_number AS code,title AS name,version FROM {table}
          WHERE current_user_can_view_{identity}(id) AND ((%s::bigint IS NOT NULL AND id=%s) OR (%s::bigint IS NULL AND ({identity}_number ILIKE %s OR title ILIKE %s))) ORDER BY {identity}_number,id LIMIT 25''',(selected,selected,selected,match,match)).fetchall()
    elif kind=='security_levels':
        rows=c.execute('''SELECT id,code,name,version,level_number FROM security_levels WHERE prevents_disposition
          AND ((%s::bigint IS NOT NULL AND id=%s) OR (%s::bigint IS NULL AND (code ILIKE %s OR name ILIKE %s))) ORDER BY level_number,id LIMIT 25''',(selected,selected,selected,match,match)).fetchall()
    elif kind=='relationship_types':
        rows=c.execute('''SELECT id,code,forward_name AS name,reverse_name,is_symmetric,version FROM relationship_types WHERE resource_kind='aggregation' AND is_active
          AND ((%s::bigint IS NOT NULL AND id=%s) OR (%s::bigint IS NULL AND (code ILIKE %s OR forward_name ILIKE %s OR reverse_name ILIKE %s))) ORDER BY code,id LIMIT 25''',(selected,selected,selected,match,match,match)).fetchall()
    else:raise HTTPException(404,detail='candidate type not found')
    return {'items':rows}


def rounds(c, job_id, *, limit, offset, decisions=False, summary=False):
    require_workspace(c,job_id)
    table='disposition_review_decisions' if decisions else 'disposition_review_rounds'
    entity='disposition_review_decision' if decisions else 'disposition_review_round'
    total=c.execute(f'SELECT count(*) total FROM {table} WHERE job_id=%s',(job_id,)).fetchone()['total']
    projection="r.*"
    if summary and not decisions:
        projection="r.id,r.round_number,r.started_at,r.completed_at,r.invalidated_at,r.invalidation_reason,r.submission_reason,jsonb_array_length(r.membership_snapshot) AS root_count,(r.approval_execution IS NOT NULL) AS approved"
    elif summary:
        projection="r.id,r.review_stage,r.reason,r.decision,r.decided_at,u.name AS actor_name,role.name AS role_name"
    joins=" LEFT JOIN users u ON u.id=r.actor_user_id LEFT JOIN roles role ON role.id=r.acting_role_id" if decisions and summary else ""
    rows=c.execute(f"""SELECT {projection},current_user_can_view_event_resource(%s,r.id,NULL,to_jsonb(r)) visible
        FROM {table} r{joins} WHERE r.job_id=%s ORDER BY r.id DESC LIMIT %s OFFSET %s""",(entity,job_id,limit,offset)).fetchall()
    for i,row in enumerate(rows):
        if not row.pop('visible'):rows[i]={'id':row['id'],'redacted':True}
        else:row['redacted']=False
    return {'items':rows,'total':total}
