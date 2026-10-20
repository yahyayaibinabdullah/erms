"""Recoverable certificate-only completion; no operation here repeats deletion.

Rendering and staging occur before the final, fresh authorization transaction.
The saved certificate, completion, download task and history commit together.
Only private worker checkpoints survive failure. There is no process cache.
"""
from io import BytesIO
from uuid import uuid4, uuid5

from fastapi import HTTPException, UploadFile
from psycopg.types.json import Jsonb
from starlette.datastructures import Headers

from ..application_settings import load_snapshot
from ..content_storage import stage_governed_upload
from . import artifacts, documents, document_snapshots, external
from .commands import execute_command

KIND = 'digital_destruction_certificate'


def identity(c, user, source='scheduled_job'):
    c.execute("SELECT set_config('app.user_id',%s,true),set_config('app.actor_type','user',true),set_config('app.event_source',%s,true)", (str(user),source))


def snapshot(c, job_id):
    """Use permanent proof, never removed content or a browser-supplied snapshot."""
    proof = c.execute('''SELECT resource_kind,resource_id,root_id,medium,destroyed_at,
      executor_user_id,executor_name,final_event_id FROM disposition_retained_records
      WHERE job_id=%s ORDER BY resource_kind,resource_id''', (job_id,)).fetchall()
    if not proof:
        raise HTTPException(409, detail={'code': 'disposition_completion_unfinished'})
    source = [{**r, 'destroyed_at': r['destroyed_at'].isoformat()} for r in proof]
    roots = sorted({r['root_id'] for r in proof})
    at = max(r['destroyed_at'] for r in proof).isoformat()
    job = c.execute('SELECT * FROM disposition_jobs WHERE id=%s', (job_id,)).fetchone()
    approval = c.execute('''SELECT a.request_document_id,d.checksum FROM disposition_external_approvals a
      JOIN disposition_review_rounds r ON r.id=a.round_id JOIN disposition_job_documents d ON d.id=a.request_document_id
      WHERE a.job_id=%s AND a.decision='approved' AND r.round_number=%s''', (job_id, job['current_review_round'])).fetchone()
    if not approval:
        raise HTTPException(409, detail={'code': 'disposition_approval_invalidated'})
    physical = c.execute('SELECT id,certificate_reference,confirmed_at,confirmed_by_user_id FROM disposition_physical_confirmations WHERE job_id=%s', (job_id,)).fetchone()
    physical_value = ('لا ينطبق / Not applicable' if not physical else
                      f"{physical['certificate_reference']} · {physical['confirmed_at'].isoformat()} · user #{physical['confirmed_by_user_id']}")
    source_value = {'proof': source, 'job_id': job_id, 'destruction_number': job['destruction_number'],
                    'approved_request_id': approval['request_document_id'], 'approved_request_checksum': approval['checksum'],
                    'physical_confirmation_id': physical['id'] if physical else None}
    counts = document_snapshots.counts([r for r in proof if r['resource_kind'] == 'aggregation'],
                                     [r for r in proof if r['resource_kind'] == 'record'], len(roots))
    generation = c.execute('SELECT started_at FROM disposition_private.completion_work WHERE job_id=%s', (job_id,)).fetchone()
    if not generation or not generation['started_at']:
        raise HTTPException(409, detail={'code': 'disposition_completion_unfinished'})
    # Destruction time and actor remain the immutable outcome. Generation time
    # identifies this certificate attempt, which may be days after destruction.
    return {'source': source_value, 'fields': {
        **document_snapshots.job_fields(c, job_id, generation['started_at'].isoformat()),
        'external.destruction_number': job['destruction_number'],
        'approved_request.reference': f"#{approval['request_document_id']}",
        'completed_at': at, 'execution.manager': '; '.join(sorted({f"{r['executor_name']} (#{r['executor_user_id']})" for r in proof})),
        'execution.scope': '; '.join(f"aggregation #{root}" for root in roots),
        **{'counts.' + k: v for k, v in counts.items()},
        'physical.confirmation': physical_value, 'integrity.value': documents.checksum(source_value)}}


def retry(c, *, job_id, task_id, task_version, expected_version, acting_role_id, command_id, reason=None):
    external.require_manager(c, job_id, acting_role_id)
    def apply(x):
        x.execute('SELECT disposition_private.check_completion(%s,%s,%s)', (job_id, task_id, acting_role_id))
        versions = x.execute('SELECT j.version AS job_version,t.version AS task_version FROM disposition_jobs j JOIN disposition_tasks t ON t.job_id=j.id WHERE j.id=%s AND t.id=%s', (job_id, task_id)).fetchone()
        if not versions or (versions['job_version'], versions['task_version']) != (expected_version, task_version):
            raise HTTPException(409, detail={'code': 'disposition_stale_task'})
        row = x.execute("UPDATE disposition_private.completion_work SET state='queued',request_id=%s,task_id=%s,requested_by_user_id=current_user_id(),acting_role_id=%s,requested_at=clock_timestamp(),started_at=NULL,finished_at=NULL,claim_token=NULL,last_error_code=NULL WHERE job_id=%s AND state='failed' RETURNING job_id,state", (command_id, task_id, acting_role_id, job_id)).fetchone()
        if not row:
            raise HTTPException(409, detail={'code': 'disposition_certificate_retry_unavailable'})
        x.execute("SELECT append_domain_event('disposition_job',%s,'DIGITAL_CERTIFICATE_RETRY_REQUESTED',jsonb_build_object('job_id',%s::bigint,'task_id',%s::bigint))", (job_id, job_id, task_id))
        return row
    return execute_command(c, command_id=command_id, operation='final_complete', payload=dict(job_id=job_id, task_id=task_id, task_version=task_version, expected_version=expected_version), acting_role_id=acting_role_id, reason='Retry certificate generation and storage only', apply=apply)


def view(c, job):
    if job['job_type'] != 'destruction':
        return None
    artifacts.require_workspace(c, job['id'])
    work = c.execute('SELECT state,last_error_code FROM disposition_private.completion_work WHERE job_id=%s', (job['id'],)).fetchone()
    # Access to certificate metadata and bytes remains intersected with normal
    # record permissions; workspace access alone never reveals the attachment.
    certificate = c.execute('''SELECT d.id,d.record_id,d.digital_component_id,c.file_name,
      current_user_can_record_component_operation(d.record_id,'record.component.download','record.component.download') AS can_download
      FROM disposition_job_documents d JOIN digital_components c ON c.id=d.digital_component_id
      WHERE d.job_id=%s AND d.document_type='digital_destruction_certificate'
      AND current_user_can_view_record(d.record_id) AND current_user_can_list_record_components(d.record_id)''', (job['id'],)).fetchone()
    return {'progress': work, 'certificate': certificate,
            'destination': artifacts.public_destination(c, job['id'], KIND) if work and work['state'] == 'failed' else None,
            'completed': job['lifecycle_state'] == 'completed'}


def downloaded(c, job_id, document_id):
    """Record the Manager's actual authorized download; completion preceded it."""
    row = c.execute("SELECT t.id,r.id AS role_id FROM disposition_tasks t JOIN roles r ON disposition_private.task_eligible(current_user_id(),t.id,r.id) WHERE t.job_id=%s AND t.task_type='certificate_download' AND t.task_state='open' ORDER BY r.id LIMIT 1", (job_id,)).fetchone()
    if not row:
        return
    return execute_command(c, command_id=uuid4(), operation='task_complete', payload=dict(job_id=job_id, task_id=row['id'], document_id=document_id), acting_role_id=row['role_id'], reason='Download saved digital destruction certificate', apply=lambda x: x.execute('SELECT disposition_private.finish_certificate_download(%s,%s) result', (job_id, document_id)).fetchone()['result'])


def fail(c, job_id, code, source='scheduled_job'):
    row = c.execute("UPDATE disposition_private.completion_work SET state='failed',finished_at=clock_timestamp(),last_error_code=%s WHERE job_id=%s AND state IN ('queued','running') RETURNING job_id", (code, job_id)).fetchone()
    if not row:
        return
    c.execute("SELECT set_config('app.user_id','',true),set_config('app.actor_type','automated_process',true),set_config('app.actor_name','Certificate worker',true),set_config('app.event_source',%s,true)",(source,))
    c.execute("SELECT append_domain_event('disposition_job',%s,'DIGITAL_CERTIFICATE_FAILED',%s)", (job_id, Jsonb({'job_id': job_id, 'error_code': code})))
    try:
        from .notifications import publish_completion_outcomes
        with c.transaction():
            publish_completion_outcomes(c, job_id)
    except Exception:
        pass  # Notification failure must not erase the durable failure record.


def process_one(factory,*,event_source='scheduled_job'):
    """One certificate, with a dedicated session mutex across rendering/commit."""
    with factory() as c:
        work = None
        try:
            rows = c.execute("SELECT * FROM disposition_private.completion_work WHERE state IN ('queued','running') ORDER BY job_id LIMIT 100").fetchall()
            for row in rows:
                if not c.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) yes', ('completion/' + str(row['job_id']),)).fetchone()['yes']:
                    continue
                work = c.execute("SELECT * FROM disposition_private.completion_work WHERE job_id=%s AND state IN ('queued','running') FOR UPDATE", (row['job_id'],)).fetchone()
                if not work:
                    c.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', ('completion/' + str(row['job_id']),))
                    continue
                if work['state'] == 'running':
                    c.commit();c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
                    fail(c, work['job_id'], 'disposition_certificate_interrupted',event_source);c.commit()
                    return True
                work['claim_token'] = uuid4()
                c.execute("UPDATE disposition_private.completion_work SET state='running',claim_token=%s,started_at=clock_timestamp() WHERE job_id=%s", (work['claim_token'], work['job_id']))
                c.commit()
                break
            else:
                return False
            try:
                identity(c, work['requested_by_user_id'],event_source)
                external.require_manager(c, work['job_id'], work['acting_role_id'])
                c.execute('SELECT disposition_private.check_completion(%s,%s,%s)', (work['job_id'], work['task_id'], work['acting_role_id']))
                captured = snapshot(c, work['job_id'])
                destination = artifacts.destination(c, work['job_id'], KIND)
                if not destination['ready']:
                    raise HTTPException(409, detail={'code': destination['warning']})
                revision = documents.current(c, KIND)
                settings = load_snapshot(c)
                c.commit()
                pdf, rendered = documents.engine.render(revision['content'], KIND, captured, settings)
                provenance = {'template_revision': revision['reference'], 'template_checksum': revision['checksum'],
                              'template_type': KIND, 'template_filename': revision['original_filename'],
                              'snapshot': captured, 'snapshot_checksum': documents.checksum(captured),
                              'completion_request_id': str(work['request_id']), **rendered}
                upload = UploadFile(BytesIO(pdf), filename=f'{KIND}-{work["job_id"]}.pdf', headers=Headers({'content-type': 'application/pdf'}))
                with stage_governed_upload(upload, settings, connection_factory=factory) as staged:
                    # Obtain the concurrency boundary before the transaction's
                    # consistent snapshot, just as digital execution does.
                    c.execute('SELECT pg_advisory_lock(7357,1)');c.commit()
                    c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
                    identity(c, work['requested_by_user_id'],event_source)
                    def save(x):
                        x.execute('SELECT disposition_private.activate_certificate(%s,%s,%s)', (work['job_id'], work['request_id'], work['claim_token']))
                        if snapshot(x, work['job_id']) != captured:
                            raise HTTPException(409, detail={'code': 'disposition_certificate_snapshot_changed'})
                        result = artifacts.save(x, job_id=work['job_id'], document_type=KIND, staged=staged,
                                                preview=artifacts.destination_token(destination), template_version=revision['reference'], provenance=provenance)
                        x.execute('DELETE FROM disposition_private.completion_context WHERE transaction_id=txid_current()')
                        return result
                    document = execute_command(c, command_id=uuid5(work['request_id'], 'certificate'), operation='document_save', payload={'job_id': work['job_id'], 'completion_request_id': str(work['request_id'])}, acting_role_id=work['acting_role_id'], reason='Store digital destruction certificate', apply=save)
                    execute_command(c, command_id=uuid5(work['request_id'], 'complete'), operation='final_complete', payload={'job_id': work['job_id'], 'certificate_document_id': document['id']}, acting_role_id=work['acting_role_id'], reason='Complete destruction with saved certificate', apply=lambda x: x.execute('SELECT disposition_private.finish_destruction_job(%s,%s) result', (work['job_id'], document['id'])).fetchone()['result'])
                    c.commit()
            except Exception as error:
                c.rollback()
                c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
                code = (error.detail or {}).get('code') if isinstance(error, HTTPException) else getattr(getattr(error, 'diag', None), 'message_primary', None)
                safe = {'disposition_destination_unset', 'disposition_destination_open_root_missing', 'disposition_destination_changed', 'disposition_manager_role_required', 'disposition_task_ineligible', 'disposition_task_claim_required', 'disposition_resource_access_required', 'disposition_certificate_snapshot_changed'}
                fail(c, work['job_id'], code if code in safe else 'disposition_certificate_generation_failed',event_source);c.commit()
            return True
        finally:
            c.rollback()
            if work:
                c.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', ('completion/' + str(work['job_id']),))
            c.execute('SELECT pg_advisory_unlock(7357,1)');c.commit()
