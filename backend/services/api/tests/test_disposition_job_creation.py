"""System numbering and creation authorization; disposable database only."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from backend.services.api.disposition import membership as service
from backend.services.api.tests.test_disposition_membership import db,actor,kwargs,ensure_officer


def create(c,kind='destruction',**extra):
    return service.create_job(c,**{**kwargs(job_type=kind,owning_org_unit_id=1 if kind=='destruction' else None), 'reason':'',**extra})


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
def test_both_profiles_create_all_types_without_becoming_preparers(client,route,profile):
    with db() as c, c.transaction(force_rollback=True):
        actor(c);ensure_officer(c)
        from backend.services.api.tests.test_disposition_workflow import set_route
        set_route(c,route)
        c.execute("DELETE FROM user_role_assignments WHERE user_id=1 AND role_id<>1")
        c.execute("UPDATE roles SET profile_id=(SELECT id FROM profiles WHERE code=%s) WHERE id=1",(profile,))
        for kind in ('destruction','permanent_transfer','selective_transfer','local_archives'):
            job=create(c,kind)
            assert job['assigned_user_id'] is None
            if kind=='destruction':assert job['review_route']==route


def test_http_creation_without_reason_and_manual_number_rejected(client):
    with db() as c:actor(c);ensure_officer(c)
    payload={'command_id':str(uuid4()),'acting_role_id':1,'job_type':'destruction','owning_org_unit_id':1}
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
