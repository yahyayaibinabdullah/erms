"""Automatic review responsibility preserves the live authorization boundary."""
import pytest
from backend.services.api.tests.test_disposition_workflow import seeded,submit,task,person,role
from backend.services.api.tests.test_disposition_membership import db
from backend.services.api.disposition import workflow,proposals
from backend.services.api.disposition.eligibility import worker_actor


@pytest.mark.parametrize('route,fa',[('standard',True),('standard',False),('simplified',False)])
def test_single_reviewer_is_ready_without_claim_and_recipient_is_person(client,route,fa):
    with db() as c:
        job,*_=seeded(c,route,fa=fa)
        result=submit(c,job['id']);t=task(c,job['id'])
        assert t['destination_role_id'] and t['destination_user_id'] is None
        assert t['task_state']=='claimed' and t['claimed_by_user_id']==1 and t['claimed_at']
        assert c.execute('SELECT disposition_private.task_eligible(1,%s) ok',(t['id'],)).fetchone()['ok']
        result['job_id']=job['id']
        assert all(x['kind']=='person' for x in proposals.submission_recipients(c,result,'en'))


@pytest.mark.parametrize('other_state',['eligible','inactive','expired','future','no_access'])
def test_counts_only_currently_eligible_people(client,other_state):
    with db() as c:
        job,root,um,*_=seeded(c)
        other=person(c)
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,um))
        if other_state=='inactive':c.execute("UPDATE users SET date_deactivated=CURRENT_TIMESTAMP WHERE id=%s",(other,))
        elif other_state=='expired':c.execute("UPDATE user_role_assignments SET valid_from=CURRENT_TIMESTAMP-interval '2 days',valid_until=CURRENT_TIMESTAMP-interval '1 day' WHERE user_id=%s",(other,))
        elif other_state=='future':c.execute("UPDATE user_role_assignments SET valid_from=CURRENT_TIMESTAMP+interval '1 day' WHERE user_id=%s",(other,))
        elif other_state=='no_access':
            from uuid import uuid4
            level=c.execute("INSERT INTO security_levels(level_number,code,name,prevents_disposition) SELECT max(level_number)+1,%s,'Restricted review',false FROM security_levels RETURNING id",(uuid4().hex,)).fetchone()['id']
            c.execute('UPDATE roles SET security_level_id=%s WHERE id=1',(level,))
            c.execute("SELECT set_config('app.security_level_change_authorized','authorized',true)")
            c.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s',(level,root))
            assert not c.execute('SELECT disposition_private.can_review_content(%s,%s) ok',(other,job['id'])).fetchone()['ok']
        submit(c,job['id']);t=task(c,job['id'])
        if other_state=='eligible':
            assert t['task_state']=='open' and t['claimed_by_user_id'] is None
        else:
            assert t['task_state']=='claimed' and t['claimed_by_user_id']==1


def test_lost_role_blocks_work_then_worker_returns_to_queue_without_reassigning(client):
    with db() as c:
        job,root,um,*_=seeded(c);submit(c,job['id']);t=task(c,job['id'])
        assert t['claimed_by_user_id']==1
        c.execute('DELETE FROM user_role_assignments WHERE user_id=1 AND role_id=%s',(um,))
        assert not c.execute('SELECT disposition_private.task_eligible(1,%s) ok',(t['id'],)).fetchone()['ok']
        c.commit()
        worker_actor(c)
        result=workflow.reconcile_claims(c)
        assert t['id'] in result['released']
        current=task(c,job['id'])
        assert current['task_state']=='open' and current['claimed_by_user_id'] is None
        assert current['destination_role_id']==um


@pytest.mark.parametrize('loss',['clearance','access','inactive','expired'])
def test_auto_assignee_losing_authority_returns_to_manual_queue(client,loss):
    from uuid import uuid4
    with db() as c:
        job,root,um,fa,*_=seeded(c,fa=True)
        other=person(c)
        c.execute('DELETE FROM user_role_assignments WHERE role_id=%s',(fa,))
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,fa))
        submit(c,job['id']);t=task(c,job['id'])
        assert t['claimed_by_user_id']==other
        if loss=='clearance':
            high=c.execute("INSERT INTO security_levels(level_number,code,name,prevents_disposition) SELECT max(level_number)+1,%s,'New clearance',false FROM security_levels RETURNING id",(uuid4().hex,)).fetchone()['id']
            c.execute('UPDATE roles SET security_level_id=%s WHERE id=1',(high,))
            c.execute("SELECT set_config('app.security_level_change_authorized','authorized',true)")
            c.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s',(high,root))
        elif loss=='access':
            role(c,'read-only-auto','READ_ONLY',user=None)
            c.execute("UPDATE roles SET profile_id=(SELECT id FROM profiles WHERE code='READ_ONLY'),is_information_governance=false WHERE id=%s",(fa,))
        elif loss=='inactive':c.execute('UPDATE users SET date_deactivated=CURRENT_TIMESTAMP WHERE id=%s',(other,))
        else:c.execute('DELETE FROM user_role_assignments WHERE role_id=%s AND user_id=%s',(fa,other))
        assert not c.execute('SELECT disposition_private.task_eligible(%s,%s) ok',(other,t['id'])).fetchone()['ok']
        worker_actor(c);assert t['id'] in workflow.reconcile_claims(c)['released']
        t=task(c,job['id']);assert t['task_state']=='open' and t['claimed_by_user_id'] is None and t['destination_role_id']==fa


def test_upgrade_preserves_existing_tasks_and_applies_only_to_new_routes(client):
    from pathlib import Path
    with db() as c:
        c.execute('DROP TRIGGER disposition_single_reviewer ON disposition_tasks')
        c.execute('DROP FUNCTION disposition_private.assign_single_reviewer()')
        job,*_=seeded(c);submit(c,job['id']);before=task(c,job['id'])
        assert before['task_state']=='open'
        c.execute((Path(__file__).resolve().parents[4]/'database/migrations/083_single_eligible_reviewer.sql').read_text())
        assert task(c,job['id'])==before
        body=c.execute("SELECT pg_get_functiondef('disposition_private.assign_single_reviewer()'::regprocedure) body").fetchone()['body']
        assert 'can_review_content' in body and 'person_role' in body


@pytest.mark.parametrize('same_person',[True,False])
def test_manager_stage_counts_distinct_people_across_roles_and_has_one_claimant(client,same_person):
    with db() as c:
        job,*_=seeded(c,'simplified')
        other=1 if same_person else person(c)
        role(c,'extra-manager','INFO_GOV_MGR',user=other)
        submit(c,job['id'])
        rows=c.execute("SELECT * FROM disposition_tasks WHERE job_id=%s AND workflow_stage='records_manager_review'",(job['id'],)).fetchall()
        assert len(rows)==2
        assert sum(t['task_state']=='claimed' for t in rows)==int(same_person)
