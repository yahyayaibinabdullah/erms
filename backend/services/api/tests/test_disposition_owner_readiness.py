"""Standard creation gates use live role configuration/assignments, never fixtures' bypasses."""
from uuid import uuid4
import psycopg
import pytest
from backend.services.api.disposition import membership,queries
from backend.services.api.tests.test_disposition_membership import db,actor,kwargs,ensure_officer
from backend.services.api.tests.test_disposition_workflow import role,person,set_route


def create(c,owner=1):
    return membership.create_job(c,**kwargs(job_type='destruction',owning_org_unit_id=owner,assigned_user_id=1))


def configure(c,owner=1,fa_owner=None):
    fa=role(c,'ready-fa-'+str(uuid4()),owner=fa_owner or owner)
    manager=role(c,'ready-manager-'+str(uuid4()),owner=owner)
    c.execute('UPDATE org_units SET file_administrator_role_id=%s WHERE id=%s',(fa,fa_owner or owner))
    c.execute('UPDATE org_units SET managing_role_id=%s WHERE id=%s',(manager,owner))
    return fa,manager


@pytest.mark.parametrize('problem',['both_missing','fa_missing','manager_missing','fa_empty','manager_empty','future','expired','inactive_person','inactive_role','inactive_ancestor','nearest_empty'])
def test_standard_creation_rejects_unready_roles_without_partial_writes(client,problem):
    with db() as c:
        actor(c);ensure_officer(c)
        fa,manager=configure(c)
        owner=1
        if problem=='both_missing':c.execute('UPDATE org_units SET file_administrator_role_id=NULL,managing_role_id=NULL WHERE id=1')
        elif problem=='fa_missing':c.execute('UPDATE org_units SET file_administrator_role_id=NULL WHERE id=1')
        elif problem=='manager_missing':c.execute('UPDATE org_units SET managing_role_id=NULL WHERE id=1')
        elif problem in ('fa_empty','manager_empty'):c.execute('DELETE FROM user_role_assignments WHERE role_id=%s',(fa if problem=='fa_empty' else manager,))
        elif problem=='future':c.execute("UPDATE user_role_assignments SET valid_from=CURRENT_TIMESTAMP+interval '1 day' WHERE role_id=%s",(fa,))
        elif problem=='expired':c.execute("UPDATE user_role_assignments SET valid_from=CURRENT_TIMESTAMP-interval '2 days',valid_until=CURRENT_TIMESTAMP-interval '1 day' WHERE role_id=%s",(fa,))
        elif problem=='inactive_person':
            other=person(c);c.execute('UPDATE user_role_assignments SET user_id=%s WHERE role_id=%s',(other,fa));c.execute('UPDATE users SET date_suspended=CURRENT_TIMESTAMP WHERE id=%s',(other,))
        elif problem=='inactive_role':c.execute('UPDATE roles SET date_deactivated=CURRENT_TIMESTAMP WHERE id=%s',(manager,))
        elif problem=='inactive_ancestor':
            parent=c.execute("INSERT INTO org_units(code,name,parent_org_unit_id) VALUES('READY_PARENT','Parent',1) RETURNING id").fetchone()['id']
            owner=c.execute("INSERT INTO org_units(code,name,parent_org_unit_id) VALUES('READY_CHILD','Child',%s) RETURNING id",(parent,)).fetchone()['id']
            configure(c,owner,fa_owner=parent)
            c.execute('UPDATE org_units SET date_deactivated=CURRENT_TIMESTAMP WHERE id=%s',(parent,))
        elif problem=='nearest_empty':
            owner=c.execute("INSERT INTO org_units(code,name,parent_org_unit_id) VALUES('READY_CHILD','Child',1) RETURNING id").fetchone()['id']
            local_fa,_=configure(c,owner);c.execute('DELETE FROM user_role_assignments WHERE role_id=%s',(local_fa,))
        before=c.execute("SELECT (SELECT count(*) FROM disposition_jobs) jobs,(SELECT count(*) FROM disposition_tasks) tasks,(SELECT count(*) FROM event_history) events,(SELECT count(*) FROM disposition_private.command_receipts) receipts,(SELECT count(*) FROM disposition_private.job_number_counters) counters").fetchone()
        with pytest.raises(psycopg.Error,match='disposition_(reviewers|file_administrator|unit_manager)_required'):
            with c.transaction():create(c,owner)
        after=c.execute("SELECT (SELECT count(*) FROM disposition_jobs) jobs,(SELECT count(*) FROM disposition_tasks) tasks,(SELECT count(*) FROM event_history) events,(SELECT count(*) FROM disposition_private.command_receipts) receipts,(SELECT count(*) FROM disposition_private.job_number_counters) counters").fetchone()
        assert after==before


def test_inherited_staffed_file_admin_and_direct_staffed_manager_allow_creation(client):
    with db() as c:
        actor(c);ensure_officer(c)
        owner=c.execute("INSERT INTO org_units(code,name,parent_org_unit_id) VALUES('READY_CHILD','Child',1) RETURNING id").fetchone()['id']
        configure(c,owner,fa_owner=1)
        setup=queries.owner_review_setup(c,[owner])[owner]
        assert all(setup.values())
        job=create(c,owner)
        assert job['review_route']=='standard'
        # This requirement is a creation gate: an existing job remains readable
        # after configuration changes; submission/routing retain their live checks.
        c.execute('UPDATE org_units SET managing_role_id=NULL WHERE id=%s',(owner,))
        assert queries.job(c,job['id'])['id']==job['id']


@pytest.mark.parametrize('route',['simplified','records_manager_only'])
def test_other_routes_do_not_require_file_admin_or_unit_manager(client,route):
    with db() as c:
        actor(c);ensure_officer(c);set_route(c,route)
        if route=='records_manager_only':role(c,'ready-records-manager','INFO_GOV_MGR')
        assert create(c)['review_route']==route


def test_http_rechecks_configuration_instead_of_trusting_selector_preview(client):
    with db() as c:
        actor(c);ensure_officer(c);configure(c)
        assert all(queries.selector(c,'owners',selected=1)['items'][0]['review_role_setup'].values())
        c.execute('UPDATE org_units SET managing_role_id=NULL WHERE id=1')
    response=client.post('/api/v1/disposition/jobs',json={'command_id':str(uuid4()),'acting_role_id':1,'job_type':'destruction','owning_org_unit_id':1,'assigned_user_id':1})
    assert response.status_code==409,response.text
    assert response.json()['detail']['code']=='disposition_unit_manager_required'


def test_canonical_and_upgrade_install_the_same_readiness_functions_and_trigger(client):
    import re
    from pathlib import Path
    source=(Path(__file__).resolve().parents[4]/'database/schema.sql').read_text()
    with db() as c:
        for name in ('owner_review_setup','require_standard_owner_roles','job_review_setup','require_progress'):
            body=re.search(r'CREATE FUNCTION disposition_private\.'+name+r'\(.*?AS \$\$(.*?)\$\$;',source,re.S).group(1).strip()
            actual=c.execute("SELECT prosrc FROM pg_proc WHERE oid=%s::regprocedure",('disposition_private.'+name+('(bigint)' if name in ('owner_review_setup','job_review_setup','require_progress') else '()'),)).fetchone()['prosrc'].strip()
            assert actual==body
        trigger=c.execute("SELECT pg_get_triggerdef(oid) definition FROM pg_trigger WHERE tgname='disposition_standard_owner_roles'").fetchone()['definition']
        assert 'BEFORE INSERT ON public.disposition_jobs' in trigger
        assert c.execute("SELECT 1 FROM schema_migrations WHERE version='104_remaining_review_readiness'").fetchone()
