"""Live remaining-review checks and the explicitly retained File Administrator skip."""
from copy import deepcopy
import re
import subprocess
import psycopg
import pytest
from backend.services.api.disposition import queries
from backend.services.api.tests.test_disposition_workflow import seeded,submit,task,actor,job_version
from backend.services.api.tests.test_disposition_review import save,claim,decide
from backend.services.api.tests.test_disposition_membership import db


def facts(c,job):
    return queries.job(c,job['id'])['review_setup']


def snapshot(c,job):
    return [c.execute(f'SELECT jsonb_agg(to_jsonb(x) ORDER BY id) v FROM {table} x WHERE '+('id=%s' if table=='disposition_jobs' else 'job_id=%s'),(job['id'],)).fetchone()['v'] for table in ('disposition_jobs','disposition_tasks','disposition_review_rounds','disposition_review_proposals')]


@pytest.mark.parametrize('missing',['file_administrator','unit_manager','both'])
def test_existing_preparation_live_warning_blocks_submit_atomically_but_save_and_repair_work(client,missing):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True)
        roles=[fa] if missing=='file_administrator' else [um] if missing=='unit_manager' else [fa,um]
        c.execute('DELETE FROM user_role_assignments WHERE role_id=ANY(%s)',(roles,))
        expected={'file_administrator_missing':missing in ('file_administrator','both'),'unit_manager_missing':missing in ('unit_manager','both')}
        assert facts(c,job)==expected
        rows=queries.jobs(c,limit=1,offset=0)['items'];assert len(rows)==1 and rows[0]['review_setup']==expected
        # Saving comments remains legal; reviewer configuration grants no new authority.
        save(c,job,overall_reason='Saved while awaiting System Administrator')
        before=snapshot(c,job)
        code='reviewers' if missing=='both' else missing
        with pytest.raises(psycopg.Error,match='disposition_'+code+'_required'):
            submit(c,job['id'])
        assert snapshot(c,job)==before
        for role in roles:c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(1,%s)',(role,))
        assert not any(facts(c,job).values())
        assert submit(c,job['id'])['workflow_stage']=='file_administrator_review'


@pytest.mark.parametrize('problem',['unset','empty','expired','future'])
def test_unit_manager_missing_blocks_even_when_file_administrator_would_be_skipped(client,problem):
    with db() as c:
        job,root,um,fa,mgr=seeded(c)
        if problem=='unset':c.execute('UPDATE org_units SET managing_role_id=NULL WHERE id=1')
        elif problem=='empty':c.execute('DELETE FROM user_role_assignments WHERE role_id=%s',(um,))
        elif problem=='expired':c.execute("UPDATE user_role_assignments SET valid_from=CURRENT_TIMESTAMP-interval '2 days',valid_until=CURRENT_TIMESTAMP-interval '1 day' WHERE role_id=%s",(um,))
        else:c.execute("UPDATE user_role_assignments SET valid_from=CURRENT_TIMESTAMP+interval '1 day' WHERE role_id=%s",(um,))
        assert facts(c,job)=={'file_administrator_missing':False,'unit_manager_missing':True}
        with pytest.raises(psycopg.Error,match='disposition_unit_manager_required'):submit(c,job['id'])


def test_removed_designation_before_routing_keeps_existing_skip_and_skip_history(client):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True)
        c.execute('UPDATE org_units SET file_administrator_role_id=NULL WHERE id=1')
        assert not any(facts(c,job).values())
        result=submit(c,job['id'])
        assert result['workflow_stage']=='unit_manager_review' and result['file_administrator_skipped']
        assert not c.execute("SELECT 1 FROM disposition_tasks WHERE job_id=%s AND workflow_stage='file_administrator_review'",(job['id'],)).fetchone()
        assert c.execute("SELECT metadata FROM event_history WHERE entity_type='disposition_job' AND entity_id=%s AND operation='TASK_ROUTED' ORDER BY id DESC LIMIT 1",(job['id'],)).fetchone()['metadata']['file_administrator_skipped']


def test_current_file_administrator_task_is_not_silently_rerouted_if_designation_removed(client):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True);submit(c,job['id'])
        current=deepcopy(task(c,job['id']))
        c.execute('UPDATE org_units SET file_administrator_role_id=NULL WHERE id=1')
        assert facts(c,job)=={'file_administrator_missing':True,'unit_manager_missing':False}
        assert task(c,job['id'])==current
        with pytest.raises(psycopg.Error):decide(c,job)
        assert task(c,job['id'])==current
        c.execute('UPDATE org_units SET file_administrator_role_id=%s WHERE id=1',(fa,))
        assert not any(facts(c,job).values())
        decide(c,job)
        assert task(c,job['id'])['workflow_stage']=='unit_manager_review'


def test_only_remaining_reviews_are_checked_and_rejection_still_saves_correction(client):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True);submit(c,job['id']);decide(c,job)
        c.execute('UPDATE org_units SET file_administrator_role_id=NULL WHERE id=1')
        assert not any(facts(c,job).values())
        # A missing future/current reviewer must not prevent returning work for correction.
        c.execute('UPDATE org_units SET managing_role_id=NULL WHERE id=1')
        assert facts(c,job)['unit_manager_missing']
        # Restore current role so task authority remains valid, but remove its other
        # assignees only after approval routing reaches the next stage.
        c.execute('UPDATE org_units SET managing_role_id=%s WHERE id=1',(um,))
        decide(c,job)
        assert task(c,job['id'])['workflow_stage']=='records_manager_review'
        c.execute('UPDATE org_units SET managing_role_id=NULL WHERE id=1')
        assert not any(facts(c,job).values())
        decide(c,job,decision='rejected',reason='Please correct the review')
        assert facts(c,job)=={'file_administrator_missing':False,'unit_manager_missing':True}


@pytest.mark.parametrize('route',['simplified','records_manager_only'])
def test_other_routes_do_not_warn_about_standard_reviewers(client,route):
    with db() as c:
        job,*_=seeded(c,route)
        c.execute('UPDATE org_units SET file_administrator_role_id=NULL,managing_role_id=NULL WHERE id=1')
        assert not any(facts(c,job).values())


def test_routing_function_is_unchanged_by_readiness_migration(client):
    # The user expressly retained the existing no-designation skip.
    source=subprocess.check_output(['git','show','HEAD:database/schema.sql'],text=True)
    expected=re.search(r'CREATE FUNCTION disposition_private.route_review\(.*?AS \$\$(.*?)\$\$;',source,re.S).group(1).strip()
    with db() as c:
        actual=c.execute("SELECT prosrc FROM pg_proc WHERE oid='disposition_private.route_review(bigint,text)'::regprocedure").fetchone()['prosrc'].strip()
        assert actual==expected


def test_file_administrator_can_save_but_not_complete_when_future_manager_is_missing(client):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True);submit(c,job['id'])
        c.execute('UPDATE org_units SET managing_role_id=NULL WHERE id=1')
        assert facts(c,job)['unit_manager_missing']
        save(c,job,review_notes='Work retained without a Unit Manager',note_version=0)
        before=snapshot(c,job)
        with pytest.raises(psycopg.Error,match='disposition_unit_manager_required'):decide(c,job)
        assert snapshot(c,job)==before
        assert task(c,job['id'])['workflow_stage']=='file_administrator_review'
        assert c.execute('SELECT review_notes FROM disposition_review_notes WHERE task_id=%s',(task(c,job['id'])['id'],)).fetchone()['review_notes']=='Work retained without a Unit Manager'


@pytest.mark.parametrize('kind',['permanent_transfer','selective_transfer','local_archives'])
def test_other_job_types_are_excluded(client,kind):
    from backend.services.api.tests.test_disposition_membership import setup
    with db() as c:
        job=setup(c,kind)
        assert not any(facts(c,job).values())


def test_terminated_job_does_not_warn_about_remaining_reviewers(client):
    from backend.services.api.disposition import membership
    from backend.services.api.tests.test_disposition_membership import kwargs
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True)
        membership.terminate_job(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),confirmed=True))
        c.execute('UPDATE org_units SET file_administrator_role_id=NULL,managing_role_id=NULL WHERE id=1')
        assert not any(facts(c,job).values())
