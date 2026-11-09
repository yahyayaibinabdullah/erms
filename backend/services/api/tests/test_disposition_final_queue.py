"""Final certificate handover; only the disposable database runner may run this."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from backend.services.api.disposition import completion,workflow,workspace
from backend.services.api.disposition.eligibility import worker_actor
from backend.services.api.disposition.destruction_worker import run_pass
from backend.services.api.tests.test_disposition_completion import ready,guarded_fixture
from backend.services.api.tests.test_disposition_membership import db,actor,job_version
from backend.services.api.tests.test_disposition_review import task
from backend.services.api.tests.test_disposition_workflow import person,role

ROOT=Path(__file__).resolve().parents[4]
MIGRATION=ROOT/'database/migrations/106_final_certificate_task_queue.sql'


def finished(monkeypatch):
    job,root,mgr=ready(monkeypatch)
    assert run_pass(db,1)=={'units_processed':1,'certificates_processed':1,'operations_processed':0}
    return job,root,mgr


def command(c,t,mgr,action,**extra):
    return workflow.task_command(c,task_id=t['id'],expected_version=t['version'],acting_role_id=mgr,
      reason='Final certificate task handover',command_id=uuid4(),action=action,**extra)


def evidence(c,job):
    return {name:c.execute(query,(job,)).fetchall() for name,query in {
      'proof':'SELECT to_jsonb(p) FROM disposition_retained_records p WHERE job_id=%s ORDER BY resource_kind,resource_id',
      'certificate':"SELECT to_jsonb(d) FROM disposition_job_documents d WHERE job_id=%s AND document_type='digital_destruction_certificate' ORDER BY id",
      'components':"SELECT to_jsonb(c) FROM digital_components c JOIN disposition_job_documents d ON d.digital_component_id=c.id WHERE d.job_id=%s AND d.document_type='digital_destruction_certificate' ORDER BY c.id",
      'runs':'SELECT to_jsonb(r) FROM disposition_destruction_runs r WHERE job_id=%s ORDER BY id',
    }.items()}


def complete(c,job,t,mgr):
    return completion.complete_task(c,job_id=job,task_id=t['id'],task_version=t['version'],
      expected_version=job_version(c,job),acting_role_id=mgr,command_id=uuid4())


def test_final_task_handover_moves_inboxes_and_preserves_evidence_and_executor(client,monkeypatch):
    job,root,mgr=finished(monkeypatch)
    with db() as c:
        actor(c);t=task(c,job['id']);before=evidence(c,job['id'])
        assert t['destination_user_id'] is None and t['destination_role_id']==mgr
        assert t['task_state']=='claimed' and t['claimed_by_user_id']==1 and t['claimed_at']
        assert {'release','reassign','complete_certificate'}<=set(workspace.read(c,job['id'])['actions'])
        other=person(c);c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,mgr))
        args=dict(task_id=t['id'],expected_version=t['version'],acting_role_id=mgr,reason='Final task handover',command_id=uuid4(),action='reassign',assigned_user_id=other)
        moved=workflow.task_command(c,**args);assert workflow.task_command(c,**args)==moved
        assert workflow.tasks(c,limit=25,offset=0,job_id=job['id'])['total']==0
        assert 'complete_certificate' not in workspace.read(c,job['id'])['actions']
        with pytest.raises(psycopg.Error,match='disposition_task_claim_required'),c.transaction():complete(c,job['id'],moved,mgr)
        actor(c,other)
        assert workflow.tasks(c,limit=25,offset=0,job_id=job['id'])['total']==1
        assert 'complete_certificate' in workspace.read(c,job['id'])['actions']
        assert complete(c,job['id'],moved,mgr)['lifecycle_state']=='completed'
        assert evidence(c,job['id'])==before
        final=c.execute('SELECT * FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()
        assert final['completed_by_user_id']==1  # Destruction executor stays attributed.
        assert c.execute('SELECT completed_by_user_id FROM disposition_tasks WHERE id=%s',(t['id'],)).fetchone()['completed_by_user_id']==other
        assert workflow.tasks(c,limit=25,offset=0,job_id=job['id'])['total']==0


def test_final_task_release_requires_claim_before_completion_and_keeps_certificate(client,monkeypatch):
    job,root,mgr=finished(monkeypatch)
    with db() as c:
        actor(c);before=evidence(c,job['id']);released=command(c,task(c,job['id']),mgr,'release')
        assert released['task_state']=='open' and released['claimed_by_user_id'] is None
        assert 'claim' in workspace.read(c,job['id'])['actions']
        assert 'complete_certificate' not in workspace.read(c,job['id'])['actions']
        assert workflow.tasks(c,limit=25,offset=0,job_id=job['id'])['total']==1
        with pytest.raises(psycopg.Error,match='disposition_task_claim_required'),c.transaction():complete(c,job['id'],released,mgr)
        claimed=command(c,released,mgr,'claim')
        assert claimed['claimed_by_user_id']==1
        assert complete(c,job['id'],claimed,mgr)['lifecycle_state']=='completed'
        assert evidence(c,job['id'])==before


def test_final_queue_candidates_recheck_clearance_membership_and_manager_profile(client,monkeypatch):
    job,root,mgr=finished(monkeypatch)
    with db() as c:
        actor(c);t=task(c,job['id']);other=person(c)
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,mgr))
        assert workspace.assignment_candidates(c,t['id'],acting_role_id=mgr,kind='users',selected=other)['items']
        high=c.execute("INSERT INTO security_levels(level_number,code,name,prevents_disposition) SELECT max(level_number)+1,%s,'Final certificate clearance',false FROM security_levels RETURNING id",('FINAL-'+uuid4().hex,)).fetchone()['id']
        c.execute('UPDATE roles SET security_level_id=%s WHERE id=1',(high,))
        c.execute("SELECT set_config('app.security_level_change_authorized','authorized',true)")
        c.execute("UPDATE aggregations SET security_level_id=%s WHERE id=(SELECT r.aggregation_id FROM disposition_job_documents d JOIN records r ON r.id=d.record_id WHERE d.job_id=%s AND d.document_type='digital_destruction_certificate')",(high,job['id']))
        c.execute("UPDATE records SET security_level_id=%s WHERE id=(SELECT record_id FROM disposition_job_documents WHERE job_id=%s AND document_type='digital_destruction_certificate')",(high,job['id']))
        assert not workspace.assignment_candidates(c,t['id'],acting_role_id=mgr,kind='users',selected=other)['items']
        with pytest.raises(psycopg.Error,match='disposition_task_ineligible'),c.transaction():command(c,t,mgr,'reassign',assigned_user_id=other)
        role(c,'final-officer','INFO_GOV_OFFICER',user=other)
        c.execute('DELETE FROM user_role_assignments WHERE user_id=%s AND role_id=%s',(other,mgr))
        assert not workspace.assignment_candidates(c,t['id'],acting_role_id=mgr,kind='users',selected=other)['items']


def test_final_claim_eligibility_loss_returns_to_queue_without_reassigning_it(client,monkeypatch):
    job,root,mgr=finished(monkeypatch)
    with db() as c:
        actor(c);t=task(c,job['id']);before=evidence(c,job['id'])
        c.execute('DELETE FROM user_role_assignments WHERE user_id=1 AND role_id=%s',(mgr,))
        assert workflow.tasks(c,limit=25,offset=0,job_id=job['id'])['total']==0
        worker_actor(c);assert workflow.reconcile_claims(c)['released']==[t['id']]
        current=task(c,job['id']);assert current['task_state']=='open' and current['claimed_by_user_id'] is None
        assert evidence(c,job['id'])==before


def test_final_queue_can_be_retargeted_to_another_manager_role(client,monkeypatch):
    job,root,mgr=finished(monkeypatch)
    with db() as c:
        actor(c);other=person(c);second=role(c,'second-final-manager','INFO_GOV_MGR',user=other)
        moved=command(c,task(c,job['id']),mgr,'reassign',destination_role_id=second)
        assert moved['destination_role_id']==second and moved['task_state']=='open'
        actor(c,other);claimed=command(c,moved,second,'claim')
        assert complete(c,job['id'],claimed,second)['lifecycle_state']=='completed'


def test_final_queue_simultaneous_claims_have_one_winner(client,monkeypatch):
    job,root,mgr=finished(monkeypatch)
    with db() as c:
        actor(c);other=person(c);c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,mgr))
        released=command(c,task(c,job['id']),mgr,'release')
    def claim(user):
        try:
            with db() as c:actor(c,user);return command(c,released,mgr,'claim')
        except psycopg.Error as error:return error.sqlstate
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(claim,[1,other]))
    assert sum(isinstance(result,dict) for result in results)==1
    with db() as c:assert task(c,job['id'])['task_state']=='claimed'


@pytest.mark.parametrize('state',['unfinished','completed','assignee_ineligible'])
def test_upgrade_converts_only_unfinished_direct_tasks_once_without_touching_evidence(client,monkeypatch,state):
    # Install the historical creation primitive, then perform real destruction.
    with db() as c:c.execute((ROOT/'database/migrations/091_explicit_certificate_task_completion.sql').read_text(),prepare=False)
    job,root,mgr=finished(monkeypatch)
    with db() as c:
        actor(c);prior=task(c,job['id']);assert prior['destination_user_id']==1 and prior['task_state']=='open'
        if state=='completed':complete(c,job['id'],prior,mgr)
        if state=='assignee_ineligible':c.execute('DELETE FROM user_role_assignments WHERE user_id=1 AND role_id=%s',(mgr,))
        prior=c.execute('SELECT * FROM disposition_tasks WHERE id=%s',(prior['id'],)).fetchone()
        before=evidence(c,job['id'])
        c.execute(MIGRATION.read_text(),prepare=False)
        current=c.execute('SELECT * FROM disposition_tasks WHERE id=%s',(prior['id'],)).fetchone()
        events=c.execute('SELECT count(*) n FROM event_history').fetchone()['n']
        c.execute(MIGRATION.read_text(),prepare=False)
        assert c.execute('SELECT count(*) n FROM event_history').fetchone()['n']==events
        assert evidence(c,job['id'])==before
        if state=='completed':assert current==prior
        else:
            assert current['id']==prior['id'] and current['date_created']==prior['date_created']
            assert current['destination_user_id'] is None and current['destination_role_id']==mgr
            assert current['task_state']==('open' if state=='assignee_ineligible' else 'claimed')
            assert current['claimed_by_user_id']==(None if state=='assignee_ineligible' else 1)
            assert current['version']==prior['version']+1
            assert c.execute("SELECT count(*) n FROM event_history WHERE entity_type='disposition_task' AND entity_id=%s AND source='migration'",(prior['id'],)).fetchone()['n']==1
