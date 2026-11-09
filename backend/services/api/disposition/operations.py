"""Durable disposition operations, independent of HTTP and browser lifetimes.

Purpose-built endpoints enqueue explicitly approved handlers. New disposition
processes can reuse these checkpoints/status/worker locks, without introducing
an administrator-defined workflow engine or generic mutation endpoint. No cache.
"""
import logging
from uuid import uuid5
from fastapi import HTTPException
from psycopg.types.json import Jsonb
from . import approval, artifacts, external
from .commands import execute_command
from .completion import identity as _identity

def identity(c,user,*,consistent=False):
    if consistent:c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
    if user is None:
        c.execute("SELECT set_config('app.user_id','',true),set_config('app.actor_type','automated_process',true),set_config('app.event_source','scheduled_job',true)")
    else:_identity(c,user)


APPROVAL='approve_proposals'
PENDING="released_at IS NULL AND (state IN ('queued','running') OR state='failed' AND result IS NOT NULL)"


def public(row):
    if not row:return None
    allowed={'job_id','round_id','review_round','job_version','task_id','workflow_stage','remaining_units',
             'report_status','request_status','report_document_id','request_document_id'}
    return dict(operation_id=str(row['id']),job_id=row['job_id'],task_id=row['task_id'],operation=row['operation'],
        state=row['state'],phase=row['phase'],approval_committed=row['result'] is not None,
        last_error_code=row['last_error_code']) | {k:v for k,v in (row['outcome'] or {}).items() if k in allowed}


def latest(c,job_id):
    return c.execute('SELECT * FROM disposition_private.operation_work WHERE job_id=%s AND released_at IS NULL ORDER BY requested_at DESC,id DESC LIMIT 1',(job_id,)).fetchone()


def progress(c,job_id):
    artifacts.require_workspace(c,job_id)
    return public(latest(c,job_id))


def request_approval(c,*,task_id,expected_version,task_version,membership_token,proposals_token,overall_reason,
                     acting_role_id,command_id,reason=None):
    task=c.execute('SELECT job_id FROM disposition_tasks WHERE id=%s',(task_id,)).fetchone()
    if not task:raise HTTPException(404,detail={'code':'disposition_review_task_unavailable'})
    external.require_manager(c,task['job_id'],acting_role_id)
    payload=dict(expected_version=expected_version,task_version=task_version,membership_token=membership_token,
                 proposals_token=proposals_token,overall_reason=overall_reason)
    # Per-request identity lock avoids a global workflow mutex for acceptance.
    c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('disposition-request/'+str(command_id),))
    prior=c.execute('SELECT *,requested_by_user_id=current_user_id() AS own FROM disposition_private.operation_work WHERE id=%s',(command_id,)).fetchone()
    if prior:
        if not prior['own'] or prior['acting_role_id']!=acting_role_id or prior['task_id']!=task_id or prior['payload']!=payload:
            raise HTTPException(409,detail={'code':'disposition_command_conflict'})
        return public(prior)
    if c.execute('SELECT disposition_private.operation_pending(%s) busy',(task['job_id'],)).fetchone()['busy']:
        raise HTTPException(409,detail={'code':'disposition_operation_in_progress'})
    # Serialize only this job's acceptance, without doing application/rendering.
    c.execute('SELECT id FROM disposition_jobs WHERE id=%s FOR UPDATE',(task['job_id'],))
    if c.execute('SELECT disposition_private.operation_pending(%s) busy',(task['job_id'],)).fetchone()['busy']:
        raise HTTPException(409,detail={'code':'disposition_operation_in_progress'})
    c.execute('SELECT disposition_private.require_task_actor(%s,%s,true)',(task_id,acting_role_id))
    current=c.execute('SELECT j.version AS job_version,t.version AS task_version,t.workflow_stage FROM disposition_jobs j JOIN disposition_tasks t ON t.job_id=j.id WHERE t.id=%s',(task_id,)).fetchone()
    if current['job_version']!=expected_version or current['task_version']!=task_version:
        raise HTTPException(409,detail={'code':'disposition_stale_version'})
    if current['workflow_stage'] not in ('records_manager_review','manager_preparation','manager_correction'):
        raise HTTPException(403,detail={'code':'disposition_manager_role_required'})
    row=c.execute('''INSERT INTO disposition_private.operation_work(id,job_id,task_id,operation,requested_by_user_id,acting_role_id,
      execution_id,completion_id,payload,state,phase)
      VALUES(%s,%s,%s,%s,current_user_id(),%s,%s,%s,%s,'queued','applying') RETURNING *''',
      (command_id,task['job_id'],task_id,APPROVAL,acting_role_id,uuid5(command_id,'apply'),uuid5(command_id,'finish'),Jsonb(payload))).fetchone()
    c.execute("SELECT append_domain_event('disposition_job',%s,'DISPOSITION_OPERATION_REQUESTED',jsonb_build_object('operation_id',%s::text,'operation',%s::text))",(task['job_id'],str(command_id),APPROVAL))
    return public(row)


def retry_documents(c,*,job_id,acting_role_id,command_id,reason=None):
    external.require_manager(c,job_id,acting_role_id)
    def apply(x):
        row=x.execute('SELECT * FROM disposition_private.operation_work WHERE job_id=%s AND '+PENDING+' FOR UPDATE',(job_id,)).fetchone()
        if not row or row['result'] is None:raise HTTPException(409,detail={'code':'disposition_approval_unavailable'})
        x.execute('SELECT disposition_private.require_task_actor(%s,%s,true)',(row['task_id'],acting_role_id))
        if row['state']=='failed':
            x.execute("UPDATE disposition_private.operation_work SET state='queued',phase='documents',last_error_code=NULL,finished_at=NULL,notification_pending=true WHERE id=%s",(row['id'],))
            # Retry storage/routing uses the current assigned Manager; original
            # approval and request attribution remain immutable.
            x.execute('UPDATE disposition_private.operation_work SET run_as_user_id=current_user_id(),run_as_role_id=%s WHERE id=%s',(acting_role_id,row['id']))
            x.execute("SELECT append_domain_event('disposition_job',%s,'DISPOSITION_DOCUMENTS_RETRY_REQUESTED',jsonb_build_object('operation_id',%s::text))",(job_id,str(row['id'])))
        return progress(x,job_id)
    return execute_command(c,command_id=command_id,operation='review_decide',payload={'job_id':job_id,'action':'retry_approval_documents'},
        acting_role_id=acting_role_id,reason='Retry saved approval documents',apply=apply)


def _finish(c,work,request_document):
    from . import workflow
    role=work.get('run_as_role_id') or work['acting_role_id']
    c.execute('SELECT disposition_private.require_task_actor(%s,%s,true)',(work['task_id'],role))
    job=external.require_manager(c,work['job_id'],role)
    c.execute("UPDATE disposition_tasks SET task_state=CASE WHEN id=%s THEN 'completed' ELSE 'cancelled' END WHERE job_id=%s AND task_state IN ('open','claimed')",(work['task_id'],work['job_id']))
    result=work['result']
    if result['remaining_units']:
        outcome=c.execute('SELECT disposition_private.activate_request(%s,%s,%s,%s) result',(job['id'],result['round_id'],request_document['request_document_id'],job['version'])).fetchone()['result']
    else:
        if job['review_route']=='records_manager_only':
            c.execute('''INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,review_round,destination_user_id)
              VALUES(%s,%s,%s,%s,%s)''',(job['id'],'preparation' if job['workflow_stage']=='manager_preparation' else 'correction',job['workflow_stage'],result['review_round'],job['assigned_user_id']))
        else:workflow.route_correction(c,job_id=job['id'])
        outcome={'job_id':job['id'],'request_status':'not_required'}
    return {**result,**outcome,'report_status':'available'}


def _approval(c,work,factory):
    from ..application_settings import load_snapshot
    if work['result'] is None:
        if work['requested_by_user_id'] is None or work['acting_role_id'] is None:raise HTTPException(403,detail={'code':'disposition_manager_role_required'})
        identity(c,work['requested_by_user_id'],consistent=True)
        p=work['payload']
        result=approval.approve(c,task_id=work['task_id'],expected_version=p['expected_version'],task_version=p['task_version'],membership_token=p['membership_token'],proposals_token=p['proposals_token'],overall_reason=p['overall_reason'],acting_role_id=work['acting_role_id'],command_id=work['execution_id'])
        c.execute("UPDATE disposition_private.operation_work SET result=%s,phase='documents' WHERE id=%s",(Jsonb(result),work['id']))
        c.commit()  # Effect transaction and its durable checkpoint commit together.
        work['result']=result
    role=work.get('run_as_role_id') or work['acting_role_id']
    user=work.get('run_as_user_id') or work['requested_by_user_id']
    if user is None or role is None:raise HTTPException(403,detail={'code':'disposition_manager_role_required'})
    identity(c,user)
    report=approval.generate_report(c,job_id=work['job_id'],round_id=work['result']['round_id'],acting_role_id=role,settings=load_snapshot(c),connection_factory=factory)
    c.commit()
    identity(c,user)
    request=external.generate_request(c,job_id=work['job_id'],round_id=work['result']['round_id'],acting_role_id=role,settings=load_snapshot(c),connection_factory=factory,activate=False) if work['result']['remaining_units'] else None
    c.commit()
    identity(c,user,consistent=True)
    outcome=execute_command(c,command_id=work['completion_id'],operation='review_decide',payload={'job_id':work['job_id'],'operation_id':str(work['id'])},acting_role_id=role,
        reason='Finish approved changes with saved documents',apply=lambda x:_finish(x,work,request))
    outcome['report_document_id']=report['id']
    c.execute("UPDATE disposition_private.operation_work SET state='succeeded',phase='ready',outcome=%s,finished_at=clock_timestamp(),last_error_code=NULL WHERE id=%s",(Jsonb(outcome),work['id']))
    _outcome(c,work,'DISPOSITION_OPERATION_READY')
    c.commit()


def _outcome(c,work,operation):
    c.execute("SELECT append_domain_event('disposition_job',%s,%s,jsonb_build_object('operation_id',%s::text))",(work['job_id'],operation,str(work['id'])))
    from .notifications import publish_operation_outcomes
    try:
        with c.transaction():
            if publish_operation_outcomes(c,work['id']):
                c.execute('UPDATE disposition_private.operation_work SET notification_pending=false WHERE id=%s',(work['id'],))
    except Exception:logging.getLogger(__name__).exception('Disposition operation notification remains unavailable')


# Deliberate handler registry: future approved long operations use the same
# durable lifecycle and worker mutex, with their own authorization/atomicity.
HANDLERS={APPROVAL:_approval}


def process_one(factory):
    with factory() as c:
        work=None
        try:
            rows=c.execute("SELECT * FROM disposition_private.operation_work WHERE state IN ('queued','running') ORDER BY requested_at,id LIMIT 100").fetchall()
            for row in rows:
                if not c.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) yes',('disposition-operation/'+str(row['id']),)).fetchone()['yes']:continue
                work=c.execute("SELECT * FROM disposition_private.operation_work WHERE id=%s AND state IN ('queued','running') FOR UPDATE",(row['id'],)).fetchone()
                if work:break
                c.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',('disposition-operation/'+str(row['id']),))
            else:return False
            c.execute("UPDATE disposition_private.operation_work SET state='running',started_at=coalesce(started_at,clock_timestamp()),attempt_count=attempt_count+1 WHERE id=%s",(work['id'],));c.commit()
            # Reclaiming an interrupted handler uses the same execution identity;
            # committed effects and document checkpoints are never replayed.
            HANDLERS[work['operation']](c,work,factory)
            return True
        except Exception as error:
            c.rollback()
            if work is None:raise
            logging.getLogger(__name__).exception('Background disposition operation requires attention')
            code=error.detail.get('code') if isinstance(error,HTTPException) and isinstance(error.detail,dict) else getattr(getattr(error,'diag',None),'message_primary',None)
            safe=code if isinstance(code,str) and code.startswith('disposition_') and code.replace('_','').isalnum() else 'disposition_operation_failed'
            identity(c,work.get('run_as_user_id') or work['requested_by_user_id'],consistent=True)
            c.execute("UPDATE disposition_private.operation_work SET state='failed',last_error_code=%s,finished_at=clock_timestamp() WHERE id=%s",(safe,work['id']))
            _outcome(c,work,'DISPOSITION_OPERATION_FAILED');c.commit();return True
        finally:
            c.rollback()
            if work:
                c.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',('disposition-operation/'+str(work['id']),));c.commit()


def _notify_one(factory):
    """Retry a durable terminal notification without rerunning business work."""
    from .notifications import OPERATION_OUTCOME,publish_operation_outcomes
    with factory() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
        if not c.execute('SELECT 1 FROM system_notification_producers WHERE producer_code=%s AND active_configuration_version_id IS NOT NULL',(OPERATION_OUTCOME,)).fetchone():return False
        work=c.execute("SELECT * FROM disposition_private.operation_work WHERE state IN ('succeeded','failed') AND notification_pending ORDER BY requested_at,id LIMIT 1 FOR UPDATE SKIP LOCKED").fetchone()
        if not work:return False
        identity(c,work['requested_by_user_id'])
        if publish_operation_outcomes(c,work['id']):
            c.execute('UPDATE disposition_private.operation_work SET notification_pending=false WHERE id=%s',(work['id'],))
        return True


def notify_one(factory):
    try:return _notify_one(factory)
    except Exception:
        logging.getLogger(__name__).exception('Disposition outcome notification will be retried')
        return False
