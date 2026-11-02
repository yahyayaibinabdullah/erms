"""Protected termination/recovery projections; no destruction or result cache."""
from fastapi import HTTPException
from .commands import execute_command
from . import queries


def preview(c,job_id):
    return c.execute('SELECT disposition_private.recovery_preview(%s) result',(job_id,)).fetchone()['result']


def resolve(c,*,job_id,target_status,root_id=None,root_version=None,confirmed=False,affected_count=None,scope_token=None,acting_role_id,command_id,reason):
    payload=dict(job_id=job_id,target_status=target_status,root_id=root_id,root_version=root_version,confirmed=confirmed,affected_count=affected_count,scope_token=scope_token)
    return execute_command(c,command_id=command_id,operation='resolve_partial',payload=payload,acting_role_id=acting_role_id,reason=reason,
      apply=lambda x:x.execute('SELECT disposition_private.resolve_partial(%s,%s,%s,%s,%s,%s,%s) result',(job_id,root_id,root_version,target_status,confirmed,affected_count,scope_token)).fetchone()['result'])


def view(c,job):
    manager=c.execute('SELECT disposition_private.can_manage() allowed').fetchone()['allowed']
    physical=c.execute('SELECT EXISTS(SELECT 1 FROM disposition_physical_confirmations WHERE job_id=%s) yes',(job['id'],)).fetchone()['yes']
    partial=c.execute('SELECT count(*) count,coalesce(bool_and(disposition_private.recovery_unit_visible(root_id)),true) visible FROM disposition_private.recovery_roots(%s)',(job['id'],)).fetchone()
    stale=False
    if physical and job['lifecycle_state']=='active':
        stale=not c.execute('SELECT disposition_private.request_approval_current(%s,id) allowed FROM disposition_review_rounds WHERE job_id=%s AND round_number=%s',(job['id'],job['id'],job['current_review_round'])).fetchone()['allowed']
    return {'can_terminate':bool(manager and job['lifecycle_state']=='active'),'physical_confirmed':physical,'correction_requires_termination':bool(physical and job['lifecycle_state']=='active' and stale),
      'partial_count':partial['count'] if manager and partial['visible'] else None,'can_resolve_bulk':bool(manager and partial['visible'] and partial['count']),'roles':queries.context(c)['roles'] if manager else []}
