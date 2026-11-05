"""System numbering and creation authorization; disposable database only."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from backend.services.api.disposition import membership as service
from backend.services.api.tests.test_disposition_membership import db,actor,kwargs,ensure_officer,configured_creation_roles


def create(c,kind='destruction',**extra):
    with configured_creation_roles(c,extra.get('owning_org_unit_id',1),kind):
        return service.create_job(c,**{**kwargs(job_type=kind,owning_org_unit_id=1 if kind=='destruction' else None), 'reason':'','assigned_user_id':1,**extra})


def test_automatic_numbers_retry_existing_numbers_and_rollback(client):
    with db() as c:
        actor(c);ensure_officer(c)
        year=c.execute("SELECT extract(year FROM CURRENT_TIMESTAMP AT TIME ZONE (SELECT value#>>'{}' FROM application_settings WHERE key='DEFAULT_WORKING_TIMEZONE'))::integer y").fetchone()['y']
        old=create(c,job_number=f'DT-{year}-7')
        key=uuid4();first=create(c,command_id=key)
        assert first['job_number']==f'DT-{year}-8'
        assert create(c,command_id=key)==first
        with c.transaction(force_rollback=True):
            assert create(c)['job_number']==f'DT-{year}-9'
        assert create(c)['job_number']==f'DT-{year}-9'
        for kind,prefix in [('permanent_transfer','PT'),('selective_transfer','ST'),('local_archives','LA')]:
            assert create(c,kind)['job_number']==f'{prefix}-{year}-1'
        assert c.execute('SELECT job_number FROM disposition_jobs WHERE id=%s',(old['id'],)).fetchone()['job_number']==old['job_number']
        c.execute("INSERT INTO disposition_private.job_number_counters VALUES('destruction',%s,99)",(year-1,))
        assert create(c)['job_number']==f'DT-{year}-10'


@pytest.mark.parametrize('route',['standard','simplified','records_manager_only'])
@pytest.mark.parametrize('profile',['INFO_GOV_MGR','INFO_GOV_OFFICER'])
def test_both_profiles_create_all_types_with_required_eligible_preparer(client,route,profile):
    with db() as c, c.transaction(force_rollback=True):
        actor(c);ensure_officer(c)
        from backend.services.api.tests.test_disposition_workflow import set_route
        set_route(c,route)
        c.execute("DELETE FROM user_role_assignments WHERE user_id=1 AND role_id<>1")
        c.execute("UPDATE roles SET profile_id=(SELECT id FROM profiles WHERE code=%s) WHERE id=1",(profile,))
        if route=='records_manager_only' and profile=='INFO_GOV_OFFICER':
            from backend.services.api.tests.test_disposition_workflow import person,role
            preparer=person(c,'Manager preparer');role(c,'manager-preparer','INFO_GOV_MGR',user=preparer)
        else:preparer=1
        for kind in ('destruction','permanent_transfer','selective_transfer','local_archives'):
            job=create(c,kind,assigned_user_id=preparer)
            assert job['assigned_user_id']==preparer
            if kind=='destruction':assert job['review_route']==route


def test_http_creation_without_reason_and_manual_number_rejected(client):
    with db() as c:
        actor(c);ensure_officer(c)
        from backend.services.api.tests.test_disposition_owner_readiness import configure
        configure(c)
    payload={'command_id':str(uuid4()),'acting_role_id':1,'job_type':'destruction','owning_org_unit_id':1,'assigned_user_id':1}
    response=client.post('/api/v1/disposition/jobs',json=payload)
    assert response.status_code==201,response.text
    assert response.json()['job_number'].startswith('DT-')
    assert client.post('/api/v1/disposition/jobs',json=payload).json()==response.json()
    assert client.post('/api/v1/disposition/jobs',json={**payload,'job_number':'MANUAL'}).status_code==422


def test_concurrent_auto_number_allocation(client):
    with db() as c:actor(c);ensure_officer(c)
    def run(_):
        with db() as c:
            actor(c)
            return create(c)['job_number']
    with ThreadPoolExecutor(max_workers=2) as pool:
        numbers=list(pool.map(run,range(2)))
    assert len(set(numbers))==2
    serials=sorted(int(n.rsplit('-',1)[1]) for n in numbers)
    assert serials[1]==serials[0]+1


@pytest.mark.parametrize('kind',['destruction','permanent_transfer','selective_transfer','local_archives'])
def test_preparer_is_required_by_http_and_database_without_consuming_job_number(client,kind):
    import psycopg
    with db() as c:
        actor(c);ensure_officer(c)
        before=c.execute('SELECT count(*) n FROM disposition_jobs').fetchone()['n']
        counters=c.execute('SELECT * FROM disposition_private.job_number_counters ORDER BY job_type,number_year').fetchall()
        with pytest.raises(psycopg.Error,match='disposition_assignment_required'):
            create(c,kind,assigned_user_id=None)
        assert c.execute('SELECT count(*) n FROM disposition_jobs').fetchone()['n']==before
        assert c.execute('SELECT * FROM disposition_private.job_number_counters ORDER BY job_type,number_year').fetchall()==counters
        assert create(c,kind)['assigned_user_id']==1
    payload={'command_id':str(uuid4()),'acting_role_id':1,'job_type':kind,'owning_org_unit_id':1 if kind=='destruction' else None}
    for invalid in (payload,{**payload,'assigned_user_id':None}):
        assert client.post('/api/v1/disposition/jobs',json=invalid).status_code==422


@pytest.mark.parametrize('route',['standard','simplified'])
def test_manager_can_prepare_and_submit_without_changing_review_route(client,route):
    from backend.services.api.tests.test_disposition_workflow import set_route,role,task
    from backend.services.api.tests.test_disposition_membership import ready,admit
    from backend.services.api.disposition import workspace
    with db() as c:
        actor(c);set_route(c,route)
        c.execute("UPDATE roles SET profile_id=(SELECT id FROM profiles WHERE code='INFO_GOV_MGR') WHERE id=1")
        unit_manager=role(c,'unit-manager')
        c.execute('UPDATE org_units SET managing_role_id=%s WHERE id=1',(unit_manager,))
        job=create(c);actor(c);root,*_=ready(c)
        assert admit(c,job['id'],[root])['items'][0]['success']
        t=task(c,job['id'])
        assert t['destination_user_id']==1 and t['workflow_stage']=='officer_preparation'
        assert c.execute('SELECT disposition_private.task_eligible(1,%s,1) allowed',(t['id'],)).fetchone()['allowed']
        assert 'submit' in workspace.read(c,job['id'])['actions']
        from backend.services.api.disposition import proposals
        proposals.submit(c,task_id=t['id'],expected_version=c.execute('SELECT version FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()['version'],task_version=t['version'],overall_reason='Prepared by the Records Manager',acting_role_id=1,command_id=uuid4())
        assert task(c,job['id'])['workflow_stage']==('unit_manager_review' if route=='standard' else 'records_manager_review')
        from backend.services.api.disposition.certificate_presentation import participants
        current=c.execute('SELECT * FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()
        assert not any('Records Officer' in row['participant.role'] for row in participants(c,current,[],'en'))


def test_manager_can_admit_for_assigned_officer_without_taking_over_preparation(client):
    from backend.services.api.tests.test_disposition_workflow import person,role,task
    from backend.services.api.tests.test_disposition_membership import ready,admit
    from backend.services.api.disposition import queries,workspace
    with db() as c:
        actor(c);c.execute("UPDATE roles SET profile_id=(SELECT id FROM profiles WHERE code='INFO_GOV_MGR') WHERE id=1")
        officer=person(c,'Assigned Officer');officer_role=role(c,'assigned-officer','INFO_GOV_OFFICER',user=officer)
        job=create(c,assigned_user_id=officer);actor(c);root,*_=ready(c)
        assert queries.job_selection_compatibility(c,[job['id']],[root])[job['id']] is None
        view=queries.job(c,job['id']);assert view['membership_addable'] and not view['membership_editable']
        assert view['membership_add_role_id']==1
        assert admit(c,job['id'],[root])['items'][0]['success']
        t=task(c,job['id']);assert t['destination_user_id']==officer and t['task_state']=='open'
        assert c.execute('SELECT assigned_user_id FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()['assigned_user_id']==officer
        assert not workspace.read(c,job['id'])['actions']
        actor(c,officer)
        assert c.execute('SELECT disposition_private.task_eligible(%s,%s,%s) allowed',(officer,t['id'],officer_role)).fetchone()['allowed']


def test_delegated_manager_admission_rechecks_officer_clearance(client):
    from backend.services.api.tests.test_disposition_workflow import person,role
    from backend.services.api.tests.test_disposition_membership import ready,admit
    with db() as c:
        actor(c);c.execute("UPDATE roles SET profile_id=(SELECT id FROM profiles WHERE code='INFO_GOV_MGR') WHERE id=1")
        officer=person(c,'Low clearance Officer');role(c,'low-clearance-officer','INFO_GOV_OFFICER',user=officer)
        job=create(c,assigned_user_id=officer);actor(c);root,*_=ready(c)
        high=c.execute("INSERT INTO security_levels(level_number,code,name,description,prevents_disposition) SELECT max(level_number)+1,'PREPARER-HIGH','Higher clearance','Disposable preparer security test',false FROM security_levels RETURNING id").fetchone()['id']
        c.execute('UPDATE roles SET security_level_id=%s WHERE id=1',(high,))
        c.execute("SELECT set_config('app.security_level_change_authorized','authorized',true)")
        c.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s',(high,root))
        assert not c.execute('SELECT user_can_view_aggregation(%s,%s) allowed',(officer,root)).fetchone()['allowed']
        assert admit(c,job['id'],[root])['items'][0]['code']=='disposition_assignee_access_required'
        assert not c.execute('SELECT 1 FROM disposition_job_memberships WHERE job_id=%s',(job['id'],)).fetchone()
