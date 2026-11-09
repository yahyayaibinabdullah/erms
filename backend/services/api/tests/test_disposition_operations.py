"""Long disposition work is durable, atomic and independent of HTTP lifetimes."""
from uuid import uuid4
import pytest
from backend.services.api.disposition import operations,approval,documents,workspace,workflow
from backend.services.api.tests.test_disposition_approval import manager,reach_manager
from backend.services.api.tests.test_disposition_review import db,task,save,create
from backend.services.api.tests.test_disposition_membership import actor
from backend.services.api.tests.test_disposition_artifacts import configure,root as destination_root
from tools.preview_disposition import preview_pdf



def configure_outcome_notification(c):
    from pathlib import Path
    from backend.services.api.disposition import notifications
    from backend.services.api.messaging import notification_configuration as config
    c.execute((Path(__file__).parents[4]/'database/seeds/disposition-notification-producers.sql').read_text());c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE');actor(c)
    configuration=config.Configuration(expected_version=0,enabled=True,audience_mode='requesting_managers',operational_owner='Disposable background approval verification',templates=[config.Template(language_tag=tag,subject_template=subject,body_template_rich_text=body,review_status='published') for tag,subject,body in [('en','Disposition processing outcome','<p>Open job {job_id} to review its processing outcome.</p>'),('ar','نتيجة معالجة التصرف','<p>افتح العملية {job_id} لمراجعة نتيجة المعالجة.</p>')]])
    saved=config.save(c,1,notifications.OPERATION_OUTCOME,configuration,'Configure disposable background outcome')
    config.activate(c,1,notifications.OPERATION_OUTCOME,saved['id'],config.Expected(expected_version=saved['version']),'Activate disposable background outcome');c.commit()

def queued(c,route='simplified',empty=False,enqueue=True):
    job,root,mgr=manager(c,route);configure(c);destination_root(c)
    if empty:save(c,job,acting=mgr if route=='records_manager_only' else None,changes=[create(c,root)])
    reach_manager(c,job,route);t=task(c,job['id']);p=approval.preview(c,t['id'],mgr)
    args=dict(task_id=t['id'],expected_version=p['job_version'],task_version=p['task_version'],membership_token=p['membership_token'],proposals_token=p['proposals_token'],overall_reason=None,acting_role_id=mgr,command_id=uuid4())
    out=operations.request_approval(c,**args) if enqueue else None
    return job,root,mgr,args,out


@pytest.mark.parametrize('route',['standard','simplified','records_manager_only'])
@pytest.mark.parametrize('empty',[False,True])
def test_acceptance_is_durable_and_worker_routes_only_after_documents(client,monkeypatch,route,empty):
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{'renderer':'test'}))
    with db() as c:
        actor(c);job,root,mgr,args,out=queued(c,route,empty)
        assert out['state']=='queued' and operations.request_approval(c,**args)==out
        assert task(c,job['id'])['task_state'] in ('open','claimed')
        inbox=workflow.tasks(c,limit=25,offset=0,sort='digital_state',job_id=job['id'])
        assert inbox['items'][0]['operation_progress']['state']=='queued'
        assert not c.execute('SELECT 1 FROM disposition_proposal_effects').fetchone()
        c.commit()
    assert operations.process_one(db)
    with db() as c:
        actor(c);progress=operations.progress(c,job['id'])
        assert progress['state']=='succeeded',progress
        assert progress['report_status']=='available'
        assert progress['request_status']==('not_required' if empty else 'available')
        assert task(c,job['id'])['id']!=args['task_id']
        assert task(c,job['id'])['task_type']==('preparation' if route=='records_manager_only' else 'correction') if empty else task(c,job['id'])['task_type']=='external_approval'
        assert operations.request_approval(c,**args)['state']=='succeeded'
        assert c.execute('SELECT count(*) n FROM disposition_private.operation_work').fetchone()['n']==1
    assert not operations.process_one(db)


def test_document_failure_retains_task_and_retry_does_not_reapply(client,monkeypatch):
    with db() as c:
        actor(c);job,root,mgr,args,out=queued(c,empty=True);c.commit()
    monkeypatch.setattr(documents.engine,'render',lambda *a:(_ for _ in ()).throw(RuntimeError('Renderer unavailable')))
    assert operations.process_one(db)
    with db() as c:
        actor(c);p=operations.progress(c,job['id']);assert p['state']=='failed' and p['approval_committed']
        assert task(c,job['id'])['id']==args['task_id']
        count=c.execute('SELECT count(*) n FROM disposition_proposal_effects').fetchone()['n'];assert count>0
        w=workspace.read(c,job['id']);assert 'approve' not in w['actions'] and 'retry_approval_documents' in w['actions']
        c.execute('UPDATE disposition_private.operation_work SET notification_pending=false WHERE id=%s',(args['command_id'],))
        retry_id=uuid4();accepted=operations.retry_documents(c,job_id=job['id'],acting_role_id=mgr,command_id=retry_id);c.commit()
        assert c.execute('SELECT notification_pending FROM disposition_private.operation_work WHERE id=%s',(args['command_id'],)).fetchone()['notification_pending']
    assert operations.process_one(db)  # The deliberately unavailable renderer fails again.
    with db() as c:
        actor(c)
        assert operations.retry_documents(c,job_id=job['id'],acting_role_id=mgr,command_id=retry_id)==accepted
        assert operations.progress(c,job['id'])['state']=='failed'  # Lost-response retry does not start another attempt.
        operations.retry_documents(c,job_id=job['id'],acting_role_id=mgr,command_id=uuid4());c.commit()
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{}))
    assert operations.process_one(db)
    with db() as c:
        actor(c);assert operations.progress(c,job['id'])['state']=='succeeded'
        assert c.execute('SELECT count(*) n FROM disposition_proposal_effects').fetchone()['n']==count


def test_task_progress_sort_uses_latest_success_instead_of_older_failure(client,monkeypatch):
    from fastapi import HTTPException
    from backend.services.api.tests.test_disposition_membership import setup,ready,admit
    with db() as c:
        actor(c);job,root,mgr,args,out=queued(c);c.commit()
    original=approval.approve
    def unavailable(*a,**kw):raise HTTPException(409,detail={'code':'disposition_approval_stale'})
    monkeypatch.setattr(approval,'approve',unavailable)
    assert operations.process_one(db)
    monkeypatch.setattr(approval,'approve',original)
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{}))
    with db() as c:
        actor(c)
        operations.request_approval(c,**{**args,'command_id':uuid4()})
        other=setup(c);other_root,*_=ready(c);admit(c,other['id'],[other_root]);reach_manager(c,other,'simplified')
        t=task(c,other['id']);p=approval.preview(c,t['id'],mgr)
        operations.request_approval(c,task_id=t['id'],expected_version=p['job_version'],task_version=p['task_version'],
            membership_token=p['membership_token'],proposals_token=p['proposals_token'],overall_reason=None,acting_role_id=mgr,command_id=uuid4())
        c.commit()
    assert operations.process_one(db)
    with db() as c:
        actor(c)
        assert operations.progress(c,job['id'])['state']=='succeeded'
        assert operations.progress(c,other['id'])['state']=='queued'
        ascending=workflow.tasks(c,limit=25,offset=0,sort='digital_state')['items']
        descending=workflow.tasks(c,limit=25,offset=0,sort='digital_state',descending=True)['items']
        assert [r['job_id'] for r in ascending]==[other['id'],job['id']]
        assert [r['job_id'] for r in descending]==[job['id'],other['id']]
        assert ascending[1]['operation_progress']['state']=='succeeded'


@pytest.mark.parametrize('change',['version','authority'])
def test_worker_rechecks_current_facts_and_applies_nothing_on_failure(client,monkeypatch,change):
    with db() as c:
        actor(c);job,root,mgr,args,out=queued(c,empty=True)
        if change=='version':c.execute('UPDATE aggregation_retention_rules SET current_period_years=current_period_years+1 WHERE aggregation_id=%s',(root,))
        else:c.execute('DELETE FROM user_role_assignments WHERE user_id=1 AND role_id=%s',(mgr,))
        c.commit()
    assert operations.process_one(db)
    with db() as c:
        actor(c);status=operations.progress(c,job['id']);assert status['state']=='failed' and not status['approval_committed']
        assert not c.execute('SELECT is_vital FROM aggregations WHERE id=%s',(root,)).fetchone()['is_vital']
        assert not c.execute('SELECT 1 FROM disposition_proposal_effects').fetchone()
        assert task(c,job['id'])['id']==args['task_id']
        assert not c.execute('SELECT disposition_private.operation_pending(%s) busy',(job['id'],)).fetchone()['busy']


def test_duplicate_request_conflicts_and_pending_job_is_readable_but_frozen(client):
    import psycopg
    from fastapi import HTTPException
    with db() as c:
        actor(c);job,root,mgr,args,out=queued(c)
        with pytest.raises(HTTPException) as err:operations.request_approval(c,**{**args,'command_id':uuid4()})
        assert err.value.detail['code']=='disposition_operation_in_progress'
        with pytest.raises(HTTPException) as err:operations.request_approval(c,**{**args,'overall_reason':'Different confirmation'})
        assert err.value.detail['code']=='disposition_command_conflict'
        w=workspace.read(c,job['id']);assert w['operation']['state']=='queued' and not w['actions']
        assert not w['job']['membership_addable'] and not w['job']['assignment_editable']
        with pytest.raises(psycopg.Error,match='disposition_operation_in_progress'),c.transaction():
            save(c,job,acting=mgr,changes=[create(c,root)])
        c.commit()


@pytest.mark.parametrize('committed',[False,True])
def test_interrupted_worker_resumes_from_checkpoint_without_reapplying(client,monkeypatch,committed):
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{}))
    with db() as c:
        actor(c);job,root,mgr,args,out=queued(c,empty=True)
        c.execute("UPDATE disposition_private.operation_work SET state='running',attempt_count=1 WHERE id=%s",(args['command_id'],));c.commit()
    if committed:
        original=approval.generate_report
        monkeypatch.setattr(approval,'generate_report',lambda *a,**kw:(_ for _ in ()).throw(SystemExit('simulated process termination')))
        with pytest.raises(SystemExit):operations.process_one(db)
        with db() as c:
            actor(c);assert operations.progress(c,job['id'])['approval_committed']
            count=c.execute('SELECT count(*) n FROM disposition_proposal_effects').fetchone()['n'];assert count>0
        monkeypatch.setattr(approval,'generate_report',original)
    assert operations.process_one(db)
    with db() as c:
        actor(c);p=operations.progress(c,job['id']);assert p['state']=='succeeded'
        assert c.execute('SELECT count(*) n FROM disposition_proposal_effects').fetchone()['n']==(count if committed else 3)
        assert c.execute("SELECT count(*) n FROM disposition_job_documents WHERE document_type='proposal_execution_report'").fetchone()['n']==1


def test_http_acceptance_does_not_call_renderer_and_status_survives_new_client_read(client,monkeypatch):
    from uuid import UUID
    with db() as c:
        actor(c);job,root,mgr,args,out=queued(c,enqueue=False);c.commit()
    def unexpected(*a,**kw):raise AssertionError('HTTP acceptance must not render documents')
    monkeypatch.setattr(documents.engine,'render',unexpected)
    payload={k:v for k,v in args.items() if k not in ('expected_version','task_id')};payload['command_id']=str(payload['command_id'])
    headers={'If-Match':str(args['expected_version']),'X-CSRF-Token':client.cookies.get('erms_csrf')}
    url=f"/api/v1/disposition/tasks/{args['task_id']}/approve-proposals"
    response=client.post(url,json=payload,headers=headers);assert response.status_code==202,response.text
    assert response.json()['state']=='queued' and UUID(response.json()['operation_id'])==args['command_id']
    assert client.post(url,json=payload,headers=headers).json()==response.json()
    status=client.get(f"/api/v1/disposition/jobs/{job['id']}/operation-progress")
    assert status.status_code==200 and status.json()==response.json()


def test_two_workers_cannot_duplicate_processing_and_task_stays_open_during_render(client,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    entered=Event();finish=Event()
    def render(*args):
        entered.set();assert finish.wait(15);return preview_pdf(),{}
    monkeypatch.setattr(documents.engine,'render',render)
    with db() as c:
        actor(c);job,root,mgr,args,out=queued(c,empty=True);c.commit()
    with ThreadPoolExecutor(max_workers=2) as workers:
        pending=workers.submit(operations.process_one,db)
        try:
            assert entered.wait(10)
            assert workers.submit(operations.process_one,db).result(timeout=3) is False
            with db() as c:
                actor(c);value=operations.progress(c,job['id'])
                assert value['state']=='running' and value['phase']=='documents' and value['approval_committed']
                assert task(c,job['id'])['id']==args['task_id']
                assert not c.execute("SELECT 1 FROM disposition_tasks WHERE job_id=%s AND task_type='external_approval'",(job['id'],)).fetchone()
                # Other jobs remain writable while this job's rendering is slow.
                from backend.services.api.disposition import membership
                from backend.services.api.tests.test_disposition_membership import kwargs
                other=membership.create_job(c,**kwargs(job_type='destruction',owning_org_unit_id=1,assigned_user_id=1))
                assert other['id']!=job['id']
        finally:finish.set()
        assert pending.result(timeout=15)
    with db() as c:
        actor(c);assert operations.progress(c,job['id'])['state']=='succeeded'
        assert c.execute('SELECT attempt_count FROM disposition_private.operation_work WHERE job_id=%s',(job['id'],)).fetchone()['attempt_count']==1


def test_outcome_notification_deduplicates_and_links_to_currently_accessible_job(client,monkeypatch):
    from pathlib import Path
    from backend.services.api.disposition import notifications
    from backend.services.api.messaging import notification_configuration as config,reading
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{}))
    with db() as c:
        actor(c);job,root,mgr,args,out=queued(c);c.commit()
        configure_outcome_notification(c)
    assert operations.process_one(db)
    with db() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE');actor(c)
        assert c.execute("SELECT count(*) n FROM message_envelopes WHERE system_producer_code=%s",(notifications.OPERATION_OUTCOME,)).fetchone()['n']==1
        notifications.publish_operation_outcomes(c,args['command_id'])
        assert c.execute("SELECT count(*) n FROM message_envelopes WHERE system_producer_code=%s",(notifications.OPERATION_OUTCOME,)).fetchone()['n']==1
        delivery=c.execute('SELECT id FROM message_deliveries ORDER BY id LIMIT 1').fetchone()['id']
        shown=reading.delivery(c,1,delivery)
        assert shown['disposition_job']==job['id']
        c.execute("DELETE FROM user_role_assignments WHERE user_id=1 AND role_id=%s",(mgr,))
        assert not reading.delivery(c,1,delivery).get('disposition_job')


def test_invalidated_approval_can_renew_review_after_document_failure(client,monkeypatch):
    from backend.services.api.disposition import external
    from backend.services.api.tests.test_disposition_membership import job_version
    with db() as c:
        actor(c);job,root,mgr,args,out=queued(c);c.commit()
    monkeypatch.setattr(documents.engine,'render',lambda *a:(_ for _ in ()).throw(RuntimeError('Temporary document failure')))
    assert operations.process_one(db)
    with db() as c:
        actor(c);row=operations.latest(c,job['id']);assert row['result'] and row['state']=='failed'
        c.execute('UPDATE aggregation_retention_rules SET current_period_years=current_period_years+1 WHERE aggregation_id=%s',(root,))
        assert not c.execute('SELECT disposition_private.request_approval_current(%s,%s) yes',(job['id'],row['result']['round_id'])).fetchone()['yes']
        assert workspace.read(c,job['id'])['external']['can_renew']
        external.renew(c,job_id=job['id'],round_id=row['result']['round_id'],expected_version=job_version(c,job['id']),acting_role_id=mgr,command_id=uuid4())
        assert not c.execute('SELECT disposition_private.operation_pending(%s) busy',(job['id'],)).fetchone()['busy']
        assert task(c,job['id'])['workflow_stage']=='officer_correction'
        assert operations.latest(c,job['id']) is None


def test_notification_failure_retries_without_repeating_business_work(client,monkeypatch):
    from backend.services.api.disposition import notifications
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{}))
    with db() as c:
        actor(c);job,root,mgr,args,out=queued(c,empty=True);c.commit()
    with db() as c:configure_outcome_notification(c)
    original=notifications.publish_operation_outcomes
    monkeypatch.setattr(notifications,'publish_operation_outcomes',lambda *a:(_ for _ in ()).throw(RuntimeError('Temporary messaging interruption')))
    assert operations.process_one(db)
    with db() as c:
        actor(c);row=operations.latest(c,job['id']);assert row['state']=='succeeded' and row['notification_pending']
        count=c.execute('SELECT count(*) n FROM disposition_proposal_effects').fetchone()['n']
    monkeypatch.setattr(notifications,'publish_operation_outcomes',original)
    assert operations.notify_one(db)
    with db() as c:
        actor(c);assert not operations.latest(c,job['id'])['notification_pending']
        assert c.execute('SELECT count(*) n FROM disposition_proposal_effects').fetchone()['n']==count
        assert c.execute("SELECT count(*) n FROM message_envelopes WHERE system_producer_code=%s",(notifications.OPERATION_OUTCOME,)).fetchone()['n']==1
    assert not operations.notify_one(db)
    assert not operations.process_one(db)
