"""Read-only counts cover the complete saved set and queued edits, without approval."""
from uuid import uuid4
import pytest
from backend.services.api.disposition import approval
from backend.services.api.tests.test_disposition_approval import manager,reach_manager,approve
from backend.services.api.tests.test_disposition_review import db,save,create,payloads,task
from backend.services.api.tests.test_disposition_membership import job_version


def summary(c,job,mgr,changes=None):
    t=task(c,job['id'])
    return approval.confirmation(c,task_id=t['id'],acting_role_id=mgr,expected_version=job_version(c,job['id']),task_version=t['version'],changes=changes or [])


def snapshot(c):
    return [c.execute('SELECT jsonb_agg(to_jsonb(t) ORDER BY id) data FROM '+table+' t').fetchone()['data'] for table in ('disposition_jobs','disposition_tasks','disposition_review_proposals','disposition_review_notes','disposition_review_decisions','disposition_job_memberships','event_history')]


def test_counts_all_saved_and_pending_changes_without_saving_or_executing(client):
    with db() as c:
        job,root,mgr=manager(c)
        changes=payloads(c,root)
        saved=save(c,job,changes=[changes[1],changes[5],changes[6]])['changes']
        reach_manager(c,job,'standard')
        before=snapshot(c)
        pending=[dict(action='withdraw',proposal_id=saved[0]['id'],expected_version=1,reason='Do not mark vital'),create(c,root,'local_retention_override',dict(current_period_years=2,intermediate_period_years=3,final_disposition='destruction',instructions='Draft rule'))]
        result=summary(c,job,mgr,pending)
        assert result['proposal_count']==3
        assert result['proposal_counts']=={'local_retention_override':1,'remove_aggregation_relationship':1,'remove_record_relationship':1}
        assert result['next_step']=='conditional'
        assert snapshot(c)==before


@pytest.mark.parametrize('route',['standard','records_manager_only'])
def test_certain_empty_outcome_matches_actual_approval_and_route(client,route):
    with db() as c:
        job,root,mgr=manager(c,route)
        from backend.services.api.tests.test_disposition_review import officer
        save(c,job,acting=mgr if route=='records_manager_only' else officer(c),changes=[create(c,root)])
        reach_manager(c,job,route)
        result=summary(c,job,mgr)
        assert result['next_step']=='empty' and result['proposal_count']==1
        assert result['empty_return_stage']==('manager_preparation' if route=='records_manager_only' else 'officer_correction')
        assert approve(c,job,mgr,overall_reason='Approve this job' if route=='records_manager_only' else None)['remaining_units']==0


def test_relationship_removals_and_zero_proposals_keep_request_path(client):
    with db() as c:
        job,root,mgr=manager(c)
        changes=payloads(c,root)
        save(c,job,changes=[changes[5],changes[6]])
        reach_manager(c,job,'standard')
        result=summary(c,job,mgr)
        assert result['proposal_count']==2 and result['next_step']=='request'
        p=c.execute("SELECT * FROM disposition_review_proposals WHERE proposal_type='remove_aggregation_relationship'").fetchone()
        revise=dict(action='revise',proposal_id=p['id'],expected_version=p['version'],target_version=p['current_values']['aggregation_version'],proposed_values=p['proposed_values'],reason='Revised draft')
        assert summary(c,job,mgr,[revise])['proposal_count']==2
        assert summary(c,job,mgr,[dict(action='withdraw',proposal_id=r['id'],expected_version=r['version']) for r in c.execute('SELECT id,version FROM disposition_review_proposals').fetchall()])['proposal_count']==0


def test_summary_http_is_read_only_and_rejects_stale_unauthorized_or_unbounded_requests(client):
    with db() as c:
        job,root,mgr=manager(c);reach_manager(c,job,'standard');t=task(c,job['id'])
        body=dict(acting_role_id=mgr,task_version=t['version'],changes=[])
        version=job_version(c,job['id']);before=snapshot(c)
    url=f"/api/v1/disposition/tasks/{t['id']}/approval-summary"
    headers={'If-Match':str(version),'X-CSRF-Token':client.cookies.get('erms_csrf')}
    response=client.post(url,json=body,headers=headers)
    assert response.status_code==200,response.text
    assert response.json()['proposal_count']==0 and response.json()['next_step']=='request'
    with db() as c:assert snapshot(c)==before
    assert client.post(url,json=body,headers={**headers,'If-Match':str(version-1)}).status_code==409
    assert client.post(url,json={**body,'acting_role_id':1},headers=headers).status_code==403
    assert client.post(url,json={**body,'changes':[{}]*101},headers=headers).status_code==422
