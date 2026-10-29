"""Simplified review additions keep task authority and submitted-unit integrity."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import psycopg
import pytest
import os
from backend.services.api.disposition import membership,queries,approval,workspace
from backend.services.api.tests.test_disposition_review import seeded,submit,claim,decide,save,create,task
from backend.services.api.tests.test_disposition_approval import approve,reach_manager
from backend.services.api.tests.test_disposition_membership import db,actor,ready,job_version,member,version
from backend.services.api.tests.test_disposition_workflow import person,set_route,act
from backend.services.api.tests.test_disposition_eligibility import make_hold,statuses


def add(c,job,root,mgr,**extra):
    return membership.add_many(c,job_id=job['id'],expected_version=job_version(c,job['id']),
        items=[{'root_id':root,'expected_version':version(c,root)}],acting_role_id=mgr,
        reason='',command_id=uuid4(),**extra)


def test_manager_addition_preserves_work_round_and_submission_then_approves_complete_new_set(client):
    with db() as c:
        job,original,_,_,mgr=seeded(c,'simplified');new,*_=ready(c)
        reach_manager(c,job,'simplified');t=task(c,job['id'])
        save(c,job,acting=mgr,review_notes='Manager saved review comments',note_version=0)
        t=task(c,job['id'])
        before=c.execute('SELECT * FROM disposition_review_rounds WHERE job_id=%s',(job['id'],)).fetchone()
        preview=approval.preview(c,t['id'],mgr)
        info=queries.job(c,job['id'])
        assert info['membership_addable'] and not info['membership_editable']
        assert info['membership_add_role_id']==mgr
        assert queries.job_selection_compatibility(c,[job['id']],[new])=={job['id']:None}
        # Saved per-job route, not the current organization default, controls this exception.
        set_route(c,'standard')
        payload=dict(job_id=job['id'],expected_version=job_version(c,job['id']),items=[{'root_id':new,'expected_version':version(c,new)}],acting_role_id=mgr,reason='',command_id=uuid4())
        result=membership.add_many(c,**payload)
        assert result['items'][0]['success']
        assert membership.add_many(c,**payload)==result
        assert statuses(c,new)==[6]*4 and member(c,new)['added_by_user_id']==1
        assert c.execute('SELECT * FROM disposition_review_rounds WHERE job_id=%s',(job['id'],)).fetchone()==before
        assert task(c,job['id'])['id']==t['id'] and task(c,job['id'])['version']==t['version']
        assert c.execute('SELECT review_notes FROM disposition_review_notes WHERE task_id=%s',(t['id'],)).fetchone()['review_notes']=='Manager saved review comments'
        with pytest.raises(psycopg.Error,match='disposition_stale_version'),c.transaction():
            approval.approve(c,task_id=t['id'],expected_version=preview['job_version'],task_version=preview['task_version'],membership_token=preview['membership_token'],proposals_token=preview['proposals_token'],acting_role_id=mgr,command_id=uuid4())
        # Newly added members also participate in proposal authorization/execution.
        save(c,job,acting=mgr,changes=[create(c,new)])
        result=approve(c,job,mgr)
        assert result['remaining_units']==1 and member(c,new) is None and member(c,original)
        row=c.execute('SELECT * FROM disposition_review_rounds WHERE job_id=%s',(job['id'],)).fetchone()
        assert row['membership_snapshot']==before['membership_snapshot']
        reviewed=row['approval_execution']['reviewed_membership']
        assert {r['root_id'] for r in reviewed}=={original,new}
        assert c.execute('SELECT membership_snapshot FROM disposition_review_decisions WHERE job_id=%s ORDER BY id DESC LIMIT 1',(job['id'],)).fetchone()['membership_snapshot']==reviewed
        assert not queries.job(c,job['id'])['membership_addable']


@pytest.mark.parametrize('case',['standard','wrong_role','unclaimed','another_claim'])
def test_review_addition_requires_saved_simplified_route_and_current_claim_role(client,case):
    with db() as c:
        route='standard' if case=='standard' else 'simplified'
        job,original,_,_,mgr=seeded(c,route);new,*_=ready(c)
        other=person(c)
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s),(%s,1)',(other,mgr,other))
        submit(c,job)
        if route=='standard':claim(c,job);decide(c,job);set_route(c,'simplified')
        if case!='unclaimed':claim(c,job)
        if case=='another_claim':actor(c,other)
        assert not c.execute('SELECT disposition_private.can_add_review_members(%s,%s) allowed',(job['id'],1 if case=='wrong_role' else mgr)).fetchone()['allowed']
        result=add(c,job,new,1 if case=='wrong_role' else mgr)
        assert not result['items'][0]['success'] and member(c,new) is None
        assert statuses(c,new)==[2]*4 and member(c,original)
        if case!='wrong_role':
            assert not queries.job(c,job['id'])['membership_addable']
            assert queries.job_selection_compatibility(c,[job['id']],[new])[job['id']]=='disposition_membership_stage_invalid'


def test_manager_cannot_remove_during_review_and_cannot_bypass_admission_protections(client):
    with db() as c:
        job,original,_,_,mgr=seeded(c,'simplified');new,*_=ready(c)
        make_hold(c,'aggregation',new)
        reach_manager(c,job,'simplified')
        assert add(c,job,new,mgr)['items'][0]['code']=='disposition_admission_blocked'
        m=member(c,original)
        with pytest.raises(psycopg.Error,match='disposition_membership_stage_invalid'),c.transaction():
            membership.remove_member(c,membership_id=m['id'],expected_version=m['version'],root_version=version(c,original),acting_role_id=mgr,reason='Review does not grant immediate removal',command_id=uuid4())
        assert member(c,original) and not member(c,new)


def test_adding_units_does_not_waive_exact_snapshot_for_original_units(client):
    with db() as c:
        job,original,_,_,mgr=seeded(c,'simplified');new,*_=ready(c)
        reach_manager(c,job,'simplified');assert add(c,job,new,mgr)['items'][0]['success']
        actor(c)
        c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)")
        c.execute('UPDATE aggregations SET is_vital=true WHERE id=%s',(original,))
        with pytest.raises(psycopg.Error,match='disposition_review_snapshot_stale'),c.transaction():approve(c,job,mgr)
        assert task(c,job['id'])['workflow_stage']=='records_manager_review'
        assert not c.execute('SELECT 1 FROM disposition_review_decisions WHERE job_id=%s',(job['id'],)).fetchone()


def test_concurrent_additions_use_current_job_version(client):
    with db() as c:
        job,original,_,_,mgr=seeded(c,'simplified');roots=[ready(c)[0] for _ in range(2)]
        reach_manager(c,job,'simplified');v=job_version(c,job['id']);versions={r:version(c,r) for r in roots}
    def perform(root):
        try:
            with db() as c:
                actor(c)
                return membership.add_many(c,job_id=job['id'],expected_version=v,items=[{'root_id':root,'expected_version':versions[root]}],acting_role_id=mgr,reason='',command_id=uuid4())
        except psycopg.Error as error:return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(perform,roots))
    assert sum(isinstance(r,dict) and r['items'][0]['success'] for r in results)==1
    assert any('disposition_stale_version' in r for r in results if isinstance(r,str))
    with db() as c:
        actor(c)
        assert c.execute("SELECT count(*) n FROM disposition_job_memberships WHERE job_id=%s AND membership_state='active'",(job['id'],)).fetchone()['n']==2


def test_http_addition_uses_claimed_role_and_returns_fresh_workspace(client):
    with db() as c:
        job,original,_,_,mgr=seeded(c,'simplified');new,*_=ready(c)
        reach_manager(c,job,'simplified');v=job_version(c,job['id']);rv=version(c,new)
    response=client.post(f"/api/v1/disposition/jobs/{job['id']}/memberships",headers={'If-Match':str(v)},json={'command_id':str(uuid4()),'acting_role_id':mgr,'items':[{'root_id':new,'expected_version':rv}]})
    assert response.status_code==200,response.text
    assert response.json()['items'][0]['success']
    result=client.get(f"/api/v1/disposition/jobs/{job['id']}/workspace").json()
    assert result['job']['version']>v and result['job']['membership_add_role_id']==mgr
    assert 'approve' in result['actions'] and result['job']['membership_addable']


def test_migration_is_idempotent_and_does_not_modify_existing_work(client):
    from pathlib import Path
    with db() as c:
        job,original,_,_,mgr=seeded(c,'simplified');reach_manager(c,job,'simplified')
        before=c.execute('SELECT to_jsonb(j) value FROM disposition_jobs j WHERE id=%s',(job['id'],)).fetchone()
        for _ in range(2):c.execute(Path('database/migrations/094_simplified_review_additions.sql').read_text(),prepare=False)
        actor(c)
        assert c.execute('SELECT to_jsonb(j) value FROM disposition_jobs j WHERE id=%s',(job['id'],)).fetchone()==before
        assert queries.job(c,job['id'])['membership_addable']


@pytest.mark.skipif(not os.environ.get('ERMS_TEST_DEFERRED_MIGRATIONS'),reason='Requires the pinned populated upgrade runner')
def test_populated_upgrade_preserves_review_work_then_allows_addition(client):
    from pathlib import Path
    with db() as c:
        job,original,_,_,mgr=seeded(c,'simplified');new,*_=ready(c)
        reach_manager(c,job,'simplified')
        save(c,job,acting=mgr,review_notes='Saved before upgrade',note_version=0,changes=[create(c,original)])
        assert add(c,job,new,mgr)['items'][0]['code']=='disposition_membership_stage_invalid'
        before={table:c.execute(f'SELECT to_jsonb(t) value FROM {table} t WHERE job_id=%s ORDER BY id',(job['id'],)).fetchall() for table in ('disposition_tasks','disposition_review_rounds','disposition_review_proposals','disposition_review_notes','disposition_job_memberships')}
        c.commit()
        for _ in range(2):
            for path in os.environ['ERMS_TEST_DEFERRED_MIGRATIONS'].split(os.pathsep):c.execute(Path(path).read_text(),prepare=False)
        actor(c)
        for table,rows in before.items():assert c.execute(f'SELECT to_jsonb(t) value FROM {table} t WHERE job_id=%s ORDER BY id',(job['id'],)).fetchall()==rows
        assert add(c,job,new,mgr)['items'][0]['success']
        assert approve(c,job,mgr)['remaining_units']==1
