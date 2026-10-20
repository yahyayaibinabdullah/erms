"""Durable digital execution; public requests never run deletion inline.

The release boundary is closed until storage cleanup and retained-record guards
are verified. Workers use a session mutex and one atomic PostgreSQL unit per
transaction. All displayed failures are allow-listed codes, never raw errors.
"""
from uuid import uuid4
from .commands import execute_command
from .external import require_manager


def request(c,*,task_id,expected_version,task_version,confirmed,acting_role_id,command_id,reason=None):
    job=c.execute('SELECT job_id FROM disposition_tasks WHERE id=%s',(task_id,)).fetchone()
    if not job:
        from fastapi import HTTPException
        raise HTTPException(404,detail={'code':'disposition_review_task_unavailable'})
    require_manager(c,job['job_id'],acting_role_id)
    return execute_command(c,command_id=command_id,operation='final_complete',
      payload=dict(job_id=job['job_id'],task_id=task_id,expected_version=expected_version,task_version=task_version,confirmed=confirmed),
      acting_role_id=acting_role_id,reason='Request authorized digital destruction',
      apply=lambda x:x.execute('SELECT disposition_private.request_digital(%s,%s,%s,%s) result',(task_id,expected_version,task_version,confirmed)).fetchone()['result'])


def progress(c,job_id):
    from .artifacts import require_workspace
    require_workspace(c,job_id)
    return c.execute('''SELECT r.id AS run_id,r.run_number,r.state,r.total_units,r.completed_units,r.failed_units,r.last_error_code,
      (SELECT count(*) FROM disposition_destruction_run_units u WHERE u.run_id=r.id AND u.state='queued') queued_units,
      (SELECT count(*) FROM disposition_destruction_run_units u WHERE u.run_id=r.id AND u.state='running') running_units,
      (SELECT count(*) FROM disposition_job_memberships m JOIN aggregations a ON a.id=m.root_aggregation_id WHERE m.job_id=r.job_id AND a.disposition_status=10 AND m.membership_state IN ('active','completed_history')) overall_completed_units,
      (SELECT count(*) FROM disposition_job_memberships m WHERE m.job_id=r.job_id AND m.membership_state IN ('active','completed_history')) overall_total_units
      FROM disposition_destruction_runs r WHERE r.job_id=%s ORDER BY r.run_number DESC LIMIT 1''',(job_id,)).fetchone()


def _context(c,run,root=None,token=None,mode='claim'):
    c.execute('INSERT INTO disposition_private.destruction_context VALUES(txid_current(),pg_backend_pid(),NULL,%s,%s,%s,%s)',(run,root,token,mode))


def _clear(c):c.execute('DELETE FROM disposition_private.destruction_context WHERE transaction_id=txid_current()')


def _fail(c,run,root,code='disposition_digital_interrupted'):
    current=c.execute('SELECT state FROM disposition_destruction_runs WHERE id=%s FOR UPDATE',(run,)).fetchone()
    if not current or current['state'] not in ('queued','running'):return
    _context(c,run,root,mode='fail')
    c.execute("UPDATE disposition_destruction_run_units SET state='failed',finished_at=clock_timestamp(),last_error_code=%s,last_error_message='Digital destruction requires authorized action.' WHERE run_id=%s AND state='running'",(code,run))
    c.execute("UPDATE disposition_destruction_runs SET state='failed',finished_at=clock_timestamp(),failed_units=(SELECT count(*) FROM disposition_destruction_run_units WHERE run_id=%s AND state='failed'),last_error_code=%s,last_error_message='Digital destruction requires authorized action.' WHERE id=%s AND state IN ('queued','running')",(run,code,run))
    c.execute("SELECT set_config('app.user_id','',true),set_config('app.actor_type','automated_process',true),set_config('app.actor_name','Digital destruction worker',true),set_config('app.event_source','scheduled_job',true)")
    c.execute("SELECT append_domain_event('disposition_job',(SELECT job_id FROM disposition_destruction_runs WHERE id=%s),'DIGITAL_DESTRUCTION_FAILED',jsonb_build_object('run_id',%s::bigint,'error_code',%s::text))",(run,run,code))
    from .notifications import publish_destruction_outcomes
    try:
        with c.transaction():publish_destruction_outcomes(c,run)
    except Exception:
        # Failed notification delivery cannot erase the durable failure record.
        # Its optional producer can be repaired before an explicit retry.
        pass
    _clear(c)


def claim(c):
    """Caller keeps this connection until releasing the returned session lock.

    A running unit with no surviving mutex owner is an interrupted execution.
    Persist failure instead of silently resuming it without a Manager retry.
    """
    c.execute('SELECT pg_advisory_xact_lock(7357,1)')
    runs=c.execute("SELECT * FROM disposition_destruction_runs WHERE state IN ('queued','running') ORDER BY id LIMIT 100 FOR UPDATE SKIP LOCKED").fetchall()
    for run in runs:
        key='destruction-run/'+str(run['id'])
        if not c.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) yes',(key,)).fetchone()['yes']:continue
        running=c.execute("SELECT root_id FROM disposition_destruction_run_units WHERE run_id=%s AND state='running' LIMIT 1",(run['id'],)).fetchone()
        if running:
            _fail(c,run['id'],running['root_id']);release(c,run['id']);continue
        unit=c.execute("SELECT * FROM disposition_destruction_run_units WHERE run_id=%s AND state='queued' ORDER BY id LIMIT 1 FOR UPDATE",(run['id'],)).fetchone()
        if not unit:release(c,run['id']);continue
        token=uuid4();_context(c,run['id'],unit['root_id'],token)
        c.execute("UPDATE disposition_destruction_runs SET state='running',started_at=coalesce(started_at,clock_timestamp()) WHERE id=%s",(run['id'],))
        c.execute("UPDATE disposition_destruction_run_units SET state='running',started_at=clock_timestamp(),attempt_count=attempt_count+1,claim_token=%s WHERE id=%s",(token,unit['id']))
        c.execute('''INSERT INTO disposition_destruction_manifest_items(job_id,root_id,resource_kind,resource_id,medium,run_id)
          SELECT %s,%s,'aggregation',id,medium,%s FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(%s))
          ON CONFLICT DO NOTHING''',(run['job_id'],unit['root_id'],run['id'],unit['root_id']))
        c.execute('''INSERT INTO disposition_destruction_manifest_items(job_id,root_id,resource_kind,resource_id,record_id,medium,run_id)
          SELECT %s,%s,'record',id,id,medium,%s FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(%s))
          ON CONFLICT DO NOTHING''',(run['job_id'],unit['root_id'],run['id'],unit['root_id']))
        c.execute('''INSERT INTO disposition_destruction_manifest_items(job_id,root_id,resource_kind,resource_id,record_id,source_component_id,source_content_set_id,checksum_algo,checksum_value,size_in_bytes,medium,run_id)
          SELECT %s,%s,'component',d.id,r.id,d.id,s.id,coalesce(s.checksum_algo,d.checksum_algo),coalesce(s.checksum_value,d.checksum_value),coalesce(s.size_in_bytes,d.size_in_bytes),r.medium,%s
          FROM digital_components d JOIN records r ON r.id=d.record_id LEFT JOIN digital_component_content_sets s ON s.digital_component_id=d.id
          WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(%s)) ON CONFLICT DO NOTHING''',(run['job_id'],unit['root_id'],run['id'],unit['root_id']))
        c.execute("UPDATE disposition_destruction_manifest_items SET run_id=%s WHERE job_id=%s AND root_id=%s AND destruction_state='queued'",(run['id'],run['job_id'],unit['root_id']))
        _clear(c)
        return {**run,'root_id':unit['root_id'],'unit_id':unit['id'],'claim_token':token}
    return None


def release(c,run_id):c.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',('destruction-run/'+str(run_id),))


SAFE_ERRORS=frozenset(('disposition_task_claim_required','disposition_task_ineligible','disposition_digital_interrupted','disposition_digital_scope_changed','disposition_digital_blocked','disposition_physical_recovery_required','disposition_processing_cleanup_required','disposition_storage_backend_unsupported','disposition_authorization_required','disposition_manager_role_required','disposition_resource_access_required','disposition_inactive_job','disposition_digital_stage_invalid','disposition_approval_invalidated','disposition_assignee_not_authorized','disposition_removal_required'))


def execute_unit(c,unit,*,event_source='scheduled_job'):
    # A worker acts for the actual authenticated requester and rechecks that
    # person's present authority; no service account is recorded as executor.
    c.execute("SELECT set_config('app.user_id',%s,true),set_config('app.actor_type','user',true),set_config('app.event_source',%s,true)",(str(unit['requested_by_user_id']),event_source))
    return execute_command(c,command_id=uuid4(),operation='final_complete',payload={'job_id':unit['job_id'],'run_id':unit['id'],'root_id':unit['root_id']},acting_role_id=unit['acting_role_id'],reason='Execute confirmed digital destruction',
      apply=lambda x:x.execute('SELECT disposition_private.finish_digital_unit(%s,%s,%s) result',(unit['id'],unit['root_id'],unit['claim_token'])).fetchone()['result'])


def process_one(factory,*,event_source='scheduled_job'):
    # Dedicated connection: the session mutex survives the claim commit and is
    # always released before returning the connection to a pool.
    with factory() as c:
        unit=None
        try:
            # Acquire the policy mutex before opening a consistent snapshot.
            # Otherwise a hold/security change committed while we waited for
            # an advisory lock could be invisible to SERIALIZABLE reads.
            c.execute('SELECT pg_advisory_lock(7357,1)');c.commit()
            c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
            unit=claim(c);c.commit()
            if not unit:return False
            try:
                c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
                execute_unit(c,unit,event_source=event_source);c.commit()
            except Exception as error:
                c.rollback()
                c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
                code=getattr(getattr(error,'diag',None),'message_primary',None)
                code=code if code in SAFE_ERRORS else 'disposition_digital_storage_failed'
                _fail(c,unit['id'],unit['root_id'],code);c.commit()
            return True
        finally:
            if unit:release(c,unit['id']);c.commit()
            c.execute('SELECT pg_advisory_unlock(7357,1)');c.commit()


def view(c,job):
    if job['job_type']!='destruction':return None
    return {'progress':progress(c,job['id'])}


def retained(c,kind,identity,*,audit=False):
    from fastapi import HTTPException
    if kind=='digital_component':
        item=c.execute('SELECT record_id FROM disposition_destruction_manifest_items WHERE source_component_id=%s LIMIT 1',(identity,)).fetchone()
        if not item:raise HTTPException(404,detail={'code':'disposition_retained_unavailable'})
        kind,identity='record',item['record_id']
    row=c.execute('SELECT * FROM disposition_retained_records WHERE resource_kind=%s AND resource_id=%s AND disposition_private.retained_access(resource_kind,resource_id,%s)',(kind,identity,audit)).fetchone()
    if not row:raise HTTPException(404,detail={'code':'disposition_retained_unavailable'})
    row['manifest_count']=c.execute('SELECT count(*) n FROM disposition_destruction_manifest_items WHERE job_id=%s AND root_id=%s',(row['job_id'],row['root_id'])).fetchone()['n']
    return row


def retained_page(c,job_id,*,root_id=None,limit=25,offset=0,sort='resource_id',descending=False):
    from .queries import require_manager
    from fastapi import HTTPException
    require_manager(c)
    orders={'resource_id':'resource_id','resource_kind':'resource_kind','medium':'medium','destroyed_at':'destroyed_at'}
    if sort not in orders:raise HTTPException(422,detail={'code':'disposition_command_failed'})
    source=' FROM disposition_retained_records WHERE job_id=%s AND (%s::bigint IS NULL OR root_id=%s) AND disposition_private.retained_access(resource_kind,resource_id,false)'
    params=(job_id,root_id,root_id)
    total=c.execute('SELECT count(*) n'+source,params).fetchone()['n']
    rows=c.execute('SELECT resource_kind,resource_id,root_id,medium,destroyed_at,executor_name'+source+' ORDER BY '+orders[sort]+(' DESC' if descending else ' ASC')+',resource_kind,resource_id LIMIT %s OFFSET %s',(*params,limit,offset)).fetchall()
    return {'total':total,'items':rows}


def manifest_page(c,job_id,*,root_id,limit=25,offset=0,sort='id',descending=False):
    from fastapi import HTTPException
    try:retained(c,'aggregation',root_id)
    except HTTPException as error:
        if error.status_code!=404:raise
        retained(c,'aggregation',root_id,audit=True)
    if sort not in ('id','resource_kind','resource_id','medium','size_in_bytes','checksum_value','destruction_state'):raise HTTPException(422,detail={'code':'disposition_command_failed'})
    source=' FROM disposition_destruction_manifest_items WHERE job_id=%s AND root_id=%s'
    params=(job_id,root_id)
    return {'total':c.execute('SELECT count(*) n'+source,params).fetchone()['n'],'items':c.execute('SELECT *'+source+' ORDER BY '+sort+(' DESC' if descending else ' ASC')+',id LIMIT %s OFFSET %s',(*params,limit,offset)).fetchall()}
