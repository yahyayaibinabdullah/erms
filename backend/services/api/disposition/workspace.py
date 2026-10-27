"""Uncached, bounded destruction workspace projections under current authority."""
from fastapi import HTTPException
from .artifacts import require_workspace
from . import queries
from ..entity_localization import localized_projection

PREPARATION=('officer_preparation','officer_correction','manager_preparation','manager_correction')
REVIEWS=('file_administrator_review','unit_manager_review','records_manager_review')


def read(c, job_id, task_id=None, language_tag='en'):
    job=queries.job(c,job_id,language_tag)
    require_workspace(c,job_id)
    params=[job_id]
    where="t.job_id=%s AND (disposition_private.task_eligible(current_user_id(),t.id) OR EXISTS(SELECT 1 FROM user_role_assignments a WHERE a.user_id=current_user_id() AND disposition_private.task_manager(t.id,a.role_id)))"
    if task_id is None:where+=" AND t.task_state IN ('open','claimed')"
    if task_id is not None:where+=' AND t.id=%s';params.append(task_id)
    task=c.execute('''SELECT t.*,d.translations AS direct_assignee_translations,q.translations AS role_queue_translations,u.translations AS claimant_translations,d.name AS direct_assignee,q.name AS role_queue,u.name AS claimant,
        t.claimed_by_user_id=current_user_id() AS own_claim
        FROM disposition_tasks t LEFT JOIN users d ON d.id=t.destination_user_id
        LEFT JOIN roles q ON q.id=t.destination_role_id LEFT JOIN users u ON u.id=t.claimed_by_user_id
        WHERE '''+where+' ORDER BY disposition_private.task_eligible(current_user_id(),t.id) DESC,(t.claimed_by_user_id=current_user_id()) DESC NULLS LAST,t.id LIMIT 1',params).fetchone()
    if task_id is not None and not task:raise HTTPException(404,detail={'code':'disposition_review_task_unavailable'})
    roles=[];actions=[];management_roles=[]
    if task:
        for field in ('direct_assignee','role_queue','claimant'):
            task[field]=localized_projection({'name':task[field],'translations':task.pop(field+'_translations')},language_tag,'name')['name']
        roles=c.execute('''SELECT DISTINCT r.id,r.name FROM roles r JOIN user_role_assignments a ON a.role_id=r.id
            WHERE a.user_id=current_user_id() AND disposition_private.task_eligible(current_user_id(),%s,r.id) ORDER BY r.id''',(task['id'],)).fetchall()
        management_roles=c.execute('SELECT DISTINCT r.id,r.name FROM roles r JOIN user_role_assignments a ON a.role_id=r.id WHERE a.user_id=current_user_id() AND disposition_private.task_manager(%s,r.id) ORDER BY r.id',(task['id'],)).fetchall()
        current=bool(roles) and task['task_state'] in ('open','claimed') and task['workflow_stage']==job['workflow_stage'] and job['lifecycle_state']=='active'
        queue=task['destination_role_id'] is not None
        working=current and (not queue or task['task_state']=='claimed' and task['own_claim'])
        if current and queue and task['task_state']=='open':actions.append('claim')
        if queue and task['task_state'] in ('open','claimed') and task['workflow_stage']==job['workflow_stage'] and (management_roles or current and task['own_claim']):
            actions.append('reassign')
            if task['task_state']=='claimed':actions.append('release')
        if working and job['workflow_stage'] in (*PREPARATION,*REVIEWS):
            actions.extend(('save','propose'))
            if job['workflow_stage'] in PREPARATION:
                actions.append('approve' if job['review_route']=='records_manager_only' else 'submit')
            elif job['workflow_stage']=='file_administrator_review':actions.append('complete_review')
            elif job['workflow_stage']=='unit_manager_review':actions.extend(('complete_review','reject'))
            else:actions.extend(('approve','reject'))
    skip=c.execute("SELECT metadata->>'file_administrator_skipped' AS skipped FROM event_history WHERE entity_type='disposition_job' AND entity_id=%s AND operation='TASK_ROUTED' AND metadata->>'workflow_stage' IN ('file_administrator_review','unit_manager_review') ORDER BY id DESC LIMIT 1",(job_id,)).fetchone()
    job['file_administrator_skipped']=bool(skip and skip['skipped']=='true')
    manager=c.execute('SELECT disposition_private.can_manage() allowed').fetchone()['allowed']
    from .workflow import action_indicator_sql
    indicators=action_indicator_sql()
    job['action_required']=dict(c.execute('SELECT '+','.join('('+expression+') AS '+key for key,expression in indicators.items())+' FROM disposition_jobs j WHERE j.id=%s',(job_id,)).fetchone())
    job['assignment_editable']=manager and job['lifecycle_state']=='active'
    job['owner_editable']=manager and job['owner_editable']
    from . import external
    external_view=external.view(c,job) if job['job_type']=='destruction' else None
    if task and current and working and job['workflow_stage']=='external_approval_pending' and external_view and external_view['approval_current']:
        actions.append('external_decide')
    from . import email
    email_view=email.controls(c,job_id) if job['job_type']=='destruction' else None
    from . import physical
    physical_view=physical.view(c,job) if job['job_type']=='destruction' else None
    if task and current and working and physical_view and task['task_type']=='physical_destruction':actions.extend(('check_physical_work','confirm_physical'))
    from . import recovery
    recovery_view=recovery.view(c,job)
    from . import destruction
    destruction_view=destruction.view(c,job)
    from . import completion
    completion_view=completion.view(c,job)
    if task and current and working and task['task_type']=='digital_destruction' and destruction_view and (not destruction_view['progress'] or destruction_view['progress']['state']=='failed'):actions.append('destroy_digital')
    if task and current and working and destruction_view and completion_view and completion_view['progress'] and completion_view['progress']['state']=='failed':actions.append('retry_certificate')
    if task and roles and task['task_type']=='certificate_download' and task['task_state'] in ('open','claimed') and completion_view and completion_view.get('certificate'):actions.append('complete_certificate')
    return {'completion':completion_view,'destruction':destruction_view,'recovery':recovery_view,'physical':physical_view,'email':email_view,'job':job,'task':task,'roles':roles,'actions':actions,'management_roles':queries.context(c)['roles'] if manager else [],'task_management_roles':management_roles,'external':external_view}


def targets(c, task_id, *, acting_role_id, root_id, kind, query='', selected=None):
    """Scope proposal targets to the selected current complete disposition unit."""
    c.execute('SELECT disposition_private.require_task_actor(%s,%s,true)',(task_id,acting_role_id))
    scope=c.execute('''SELECT 1 FROM disposition_job_memberships m JOIN disposition_tasks t ON t.job_id=m.job_id
        WHERE t.id=%s AND m.root_aggregation_id=%s AND m.membership_state='active'
        AND current_user_can_view_aggregation(m.root_aggregation_id)''',(task_id,root_id)).fetchone()
    if not scope:raise HTTPException(404,detail={'code':'disposition_resource_access_required'})
    if selected is None and len(query.strip())<2:return {'items':[]}
    table='aggregations' if kind=='aggregations' else 'records'
    singular='aggregation' if kind=='aggregations' else 'record'
    scope_id='r.id' if kind=='aggregations' else 'r.aggregation_id'
    return {'items':c.execute(f'''SELECT r.id,r.{singular}_number AS code,r.title AS name,r.version,
        {'r.id' if kind=='aggregations' else 'r.aggregation_id'} AS aggregation_id
        FROM {table} r WHERE {scope_id} IN (SELECT id FROM disposition_private.unit_ids(%s))
        AND current_user_can_view_{singular}(r.id)
        AND ((%s::bigint IS NOT NULL AND r.id=%s) OR (%s::bigint IS NULL AND (r.{singular}_number ILIKE %s OR r.title ILIKE %s)))
        ORDER BY r.{singular}_number,r.id LIMIT 25''',(root_id,selected,selected,selected,'%'+query.strip()+'%','%'+query.strip()+'%')).fetchall()}


def assignment_candidates(c,task_id,*,acting_role_id,kind,query='',selected=None):
    c.execute("SELECT disposition_private.require_task_command(%s,%s,'task_reassign')",(task_id,acting_role_id))
    task=c.execute('''SELECT t.*,disposition_private.task_manager(t.id,%s) AS manager,
        t.claimed_by_user_id=current_user_id() AS own_claim FROM disposition_tasks t
        JOIN disposition_jobs j ON j.id=t.job_id WHERE t.id=%s AND t.destination_role_id IS NOT NULL
        AND t.task_state IN ('open','claimed') AND t.workflow_stage=j.workflow_stage AND j.lifecycle_state='active' ''',(acting_role_id,task_id)).fetchone()
    if not task or not (task['manager'] or task['own_claim']):raise HTTPException(403,detail={'code':'disposition_task_ineligible'})
    if selected is None and len(query.strip())<2:return {'items':[]}
    match='%'+query.strip()+'%'
    if kind=='users':
        rows=c.execute('''SELECT u.id,u.name,u.email FROM users u WHERE disposition_private.task_eligible(u.id,%s,%s)
            AND ((%s::bigint IS NOT NULL AND u.id=%s) OR (%s::bigint IS NULL AND (u.name ILIKE %s OR u.email ILIKE %s)))
            ORDER BY u.name,u.id LIMIT 25''',(task_id,task['destination_role_id'],selected,selected,selected,match,match)).fetchall()
    elif kind=='roles':
        rows=c.execute('''SELECT r.id,r.name,r.code FROM roles r WHERE disposition_private.review_role(%s,%s,r.id)
            AND (%s OR r.id=%s) AND EXISTS(SELECT 1 FROM users u WHERE disposition_private.person_role(u.id,r.id) AND disposition_private.can_review_content(u.id,%s))
            AND ((%s::bigint IS NOT NULL AND r.id=%s) OR (%s::bigint IS NULL AND (r.name ILIKE %s OR r.code ILIKE %s)))
            ORDER BY r.name,r.id LIMIT 25''',(task['job_id'],task['workflow_stage'],task['manager'],task['destination_role_id'],task['job_id'],selected,selected,selected,match,match)).fetchall()
    else:raise HTTPException(404)
    return {'items':rows}


def review_history(c,job_id,*,kind,identity,limit,offset,language_tag='en'):
    require_workspace(c,job_id)
    table,entity={'proposal':('disposition_review_proposals','disposition_review_proposal'),'note':('disposition_review_notes','disposition_review_note')}[kind]
    if not c.execute(f'SELECT 1 FROM {table} WHERE id=%s AND job_id=%s',(identity,job_id)).fetchone():raise HTTPException(404)
    source=' FROM event_history raw JOIN authorized_event_history e ON e.id=raw.id WHERE raw.entity_type=%s AND raw.entity_id=%s'
    total=c.execute('SELECT count(*) AS total'+source,(entity,identity)).fetchone()['total']
    from .history_display import enrich
    rows=c.execute('SELECT e.*'+source+' ORDER BY e.id DESC LIMIT %s OFFSET %s',(entity,identity,limit,offset)).fetchall()
    return {'total':total,'items':enrich(c,rows,language_tag)}
