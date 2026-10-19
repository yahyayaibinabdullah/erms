"""Destruction routing and shared task commands.

Routing entry points are private action-service primitives. Phase 14 owns the
submission/decision gates; clients cannot choose stages or complete arbitrary
tasks. There is no result/identity cache. Every operation uses current database
roles, designations, clearance and resource access, including committed retries.
"""
from uuid import uuid4

from fastapi import HTTPException
from .commands import execute_command


def task_command(c, *, task_id, expected_version, acting_role_id, reason,
                 command_id, action, assigned_user_id=None, destination_role_id=None):
    if action not in ('claim', 'release', 'reassign'):
        raise ValueError('Unsupported shared task action')
    payload = dict(task_id=task_id, expected_version=expected_version)
    if action == 'reassign':
        payload['assigned_user_id'] = assigned_user_id
        payload['destination_role_id'] = destination_role_id
    def apply(connection):
        if action == 'claim':
            connection.execute('SELECT disposition_private.claim_task(%s,%s)', (task_id, expected_version))
            return connection.execute('SELECT to_jsonb(t) result FROM disposition_tasks t WHERE id=%s', (task_id,)).fetchone()['result']
        parameters = (task_id, expected_version, assigned_user_id, destination_role_id) if action == 'reassign' else (task_id, expected_version)
        placeholders = ','.join(['%s'] * len(parameters))
        return connection.execute(f'SELECT disposition_private.{action}_task({placeholders}) result', parameters).fetchone()['result']
    return execute_command(c, command_id=command_id, operation='task_'+action,
                           payload=payload, acting_role_id=acting_role_id, reason=reason,
                           apply=apply)


def start_review(c, *, job_id, expected_version):
    """Internal: invoke only inside a fully validated review_submit command."""
    return c.execute('SELECT disposition_private.start_review(%s,%s) result', (job_id, expected_version)).fetchone()['result']


def route_review(c, *, job_id, stage):
    """Internal: action service persists the stage decision in the SAME command."""
    return c.execute('SELECT disposition_private.route_review(%s,%s) result', (job_id, stage)).fetchone()['result']


def route_correction(c, *, job_id):
    c.execute('SELECT disposition_private.route_correction(%s)', (job_id,))


def reconcile_claims(c, *, limit=100, after_id=0):
    """Bounded worker pass; caller supplies automated actor and owns commit.

    Claim/complete gates independently reject ineligible actors immediately,
    before this pass runs. No saved work or review decision is rewritten.
    """
    if type(limit) is not int or not 1 <= limit <= 1000 or type(after_id) is not int or after_id < 0:
        raise ValueError('Invalid task reconciliation bounds')
    rows = c.execute("""SELECT id FROM disposition_tasks WHERE id>%s AND task_state='claimed'
      AND destination_role_id IS NOT NULL ORDER BY id LIMIT %s""", (after_id, limit)).fetchall()
    changed = []
    for row in rows:
        command_id=uuid4()
        result = c.execute('SELECT disposition_private.reconcile_task(%s,%s) result', (row['id'], command_id)).fetchone()['result']
        if result['changed']:
            from .notifications import publish_command_tasks
            publish_command_tasks(c,command_id)
            changed.append(row['id'])
    return {'released': changed, 'next_after_id': rows[-1]['id'] if len(rows) == limit else 0}


def action_indicator_sql():
    """The same current action-required facts in inbox and workspace header."""
    return {
        'blocked':"EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=j.id AND m.membership_state='active' AND (EXISTS(SELECT 1 FROM disposition_private.protection_blockers(m.root_aggregation_id)) OR EXISTS(SELECT 1 FROM disposition_private.relationship_scope(m.root_aggregation_id) WHERE blocks_final)))",
        'removal_required':"EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=j.id AND m.membership_state='active' AND (m.removal_required OR EXISTS(SELECT 1 FROM disposition_review_proposals p WHERE p.job_id=m.job_id AND p.governing_root_id=m.root_aggregation_id AND p.review_round=disposition_private.review_round_for_work(m.job_id) AND p.proposal_type='remove_from_job' AND p.proposal_state='active')))",
        'failed_reports':"EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.job_id=j.id AND d.document_state='failed') OR EXISTS(SELECT 1 FROM disposition_review_rounds r WHERE r.job_id=j.id AND r.approval_execution IS NOT NULL AND NOT EXISTS(SELECT 1 FROM disposition_job_documents d WHERE d.job_id=j.id AND d.provenance->>'approval_round_id'=r.id::text AND d.document_state='available'))"}


def tasks(c, *, limit, offset, sort='received', descending=False, state=None, job_id=None, query='', stage=None, task_type=None, indicator=None, min_priority=None, min_roots=None, has_claimant=None):
    """Current destination/claimant with no inaccessible resource identifiers.

    Phase 16 consumes this server-paginated projection for its task inbox. A
    background pass returns lost claims to queues; current eligibility is also
    checked here so a stale assignment never provides task or content access.
    """
    root_count="(SELECT count(*) FROM disposition_job_memberships m WHERE m.job_id=j.id AND m.membership_state='active')"
    indicators=action_indicator_sql()
    orders = {'job_type':'j.job_type','age':'t.date_created','id': 't.id', 'received': 't.date_created', 'priority': 't.priority',
              'task_type': 't.task_type', 'job_number': 'j.job_number',
              'owner': 'o.name', 'workflow_stage': 't.workflow_stage', 'state': 't.task_state', 'direct_assignee':'direct.name', 'role_queue':'queue.name', 'claimant':'claimant.name', 'root_count':"(SELECT count(*) FROM disposition_job_memberships m WHERE m.job_id=j.id AND m.membership_state='active')"}
    if sort not in orders:
        raise HTTPException(422, detail='invalid sort')
    if sort=='age':descending=not descending
    clauses = ["t.task_state IN ('open','claimed')", "disposition_private.task_eligible(current_user_id(),t.id)"]
    params = []
    if query.strip():
        clauses.append('(j.job_number ILIKE %s OR o.name ILIKE %s OR direct.name ILIKE %s OR queue.name ILIKE %s OR claimant.name ILIKE %s)')
        params.extend(['%'+query.strip()+'%']*5)
    for field,value in (('workflow_stage',stage),('task_type',task_type)):
        if value is not None:clauses.append('t.'+field+'=%s');params.append(value)
    if indicator is not None:
        if indicator not in indicators:raise HTTPException(422,detail='invalid indicator')
        clauses.append('('+indicators[indicator]+')')
    if min_priority is not None:clauses.append('t.priority>=%s');params.append(min_priority)
    if min_roots is not None:clauses.append(root_count+'>=%s');params.append(min_roots)
    if has_claimant is not None:clauses.append('(t.claimed_by_user_id IS NOT NULL)=%s');params.append(has_claimant)
    if state is not None:
        clauses.append('t.task_state=%s'); params.append(state)
    if job_id is not None:
        clauses.append('t.job_id=%s'); params.append(job_id)
    source = ''' FROM disposition_tasks t JOIN disposition_jobs j ON j.id=t.job_id
      LEFT JOIN org_units o ON o.id=j.owning_org_unit_id
      LEFT JOIN users direct ON direct.id=t.destination_user_id
      LEFT JOIN users claimant ON claimant.id=t.claimed_by_user_id
      LEFT JOIN roles queue ON queue.id=t.destination_role_id WHERE ''' + ' AND '.join(clauses)
    total = c.execute('SELECT count(*) total'+source, params).fetchone()['total']
    rows = c.execute('''SELECT ('''+indicators['blocked']+''') AS blocked,('''+indicators['failed_reports']+''') AS failed_reports,('''+indicators['removal_required']+''') AS action_removal_required,t.*,j.job_number,j.job_type,j.review_route,j.owning_org_unit_id,o.name AS owner,
      direct.name AS direct_assignee,queue.name AS role_queue,claimant.name AS claimant,
      extract(epoch FROM (CURRENT_TIMESTAMP-t.date_created))::bigint AS age_seconds,
      (SELECT count(*) FROM disposition_job_memberships m WHERE m.job_id=j.id AND m.membership_state='active') AS root_count,
      EXISTS(SELECT 1 FROM disposition_job_memberships m WHERE m.job_id=j.id AND m.membership_state='active' AND m.removal_required) AS removal_required,
      ARRAY(SELECT DISTINCT r.id FROM roles r JOIN user_role_assignments a ON a.role_id=r.id AND a.user_id=current_user_id() WHERE disposition_private.task_eligible(current_user_id(),t.id,r.id) ORDER BY r.id) AS acting_role_ids
      '''+source+' ORDER BY '+orders[sort]+(' DESC' if descending else ' ASC')+',t.id LIMIT %s OFFSET %s', [*params, limit, offset]).fetchall()
    return {'items': rows, 'total': total}
