"""Job-scoped candidates remain advisory; existing commands recheck admission."""
from datetime import datetime,timezone
from uuid import uuid4
import pytest
from fastapi import HTTPException
from backend.services.api.disposition import queries
from backend.services.api.disposition.eligibility import worker_actor,evaluate_root
from backend.services.api.tests.test_disposition_membership import db,actor,setup,ready,admit,kwargs,job_version
from backend.services.api.tests.test_disposition_eligibility import make_hold
from backend.services.api.tests.test_disposition_foundation import version
from backend.services.api.tests.test_disposition_workflow import person,role,seeded,submit,task,act


def candidates(c,job,**params):
    return queries.eligibility(c,limit=25,offset=0,job_id=job['id'],**params)


def move_owner(c,root,owner):
    c.execute('UPDATE aggregations SET date_closed=NULL WHERE id=%s',(root,))
    c.execute("SELECT set_config('app.ownership_correction_authorized','authorized',true)")
    c.execute('UPDATE aggregations SET owning_org_unit_id=%s WHERE id=%s',(owner,root))
    c.execute("SELECT set_config('app.ownership_correction_authorized','',true)")
    c.execute("UPDATE aggregations SET date_closed='2020-01-01' WHERE id=%s",(root,))
    worker_actor(c);evaluate_root(c,root);actor(c)


def test_scope_excludes_other_action_owner_protections_open_and_active_job(client):
    with db() as c:
        job=setup(c)
        child=c.execute("INSERT INTO org_units(code,name,parent_org_unit_id) VALUES('child','Child',1) RETURNING id").fetchone()['id']
        grandchild=c.execute("INSERT INTO org_units(code,name,parent_org_unit_id) VALUES('grand','Grandchild',%s) RETURNING id",(child,)).fetchone()['id']
        outside=c.execute("INSERT INTO org_units(code,name) VALUES('outside','Other unit') RETURNING id").fetchone()['id']
        same,*_=ready(c);descendant,*_=ready(c);move_owner(c,descendant,grandchild)
        foreign,*_=ready(c);move_owner(c,foreign,outside)
        transfer,*_=ready(c,'transfer_to_external_archive')
        opened,*_=ready(c,closed=None)
        vital,*_=ready(c)
        c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)")
        c.execute('UPDATE aggregations SET is_vital=true WHERE id=%s',(vital,))
        c.execute("SELECT set_config('app.vital_status_change_authorized','',true)")
        held,*_=ready(c);make_hold(c,'aggregation',held)
        admitted,*_=ready(c);admit(c,job['id'],[admitted])
        result=candidates(c,job)
        assert {r['id'] for r in result['items']}=={same,descendant}
        assert result['total']==2 and result['scope']['id']==job['id']
        assert result['scope']['version']==job_version(c,job['id'])
        # Caller-controlled filters can narrow this scope, never broaden it.
        assert not candidates(c,job,owner=outside,active_job=None)['items']
        assert not candidates(c,job,status=3,vital=None,held=None)['items']
        assert not candidates(c,job,active_job=True)['items']
        assert candidates(c,job,owner=grandchild)['total']==1
        # The standalone listing remains general, including protected/other-unit roots.
        general=queries.eligibility(c,limit=100,offset=0)
        assert {foreign,transfer,vital,held} <= {r['id'] for r in general['items']}


def test_search_paging_dates_and_relationship_warning_without_related_identities(client):
    with db() as c:
        job=setup(c);roots=[ready(c)[0] for _ in range(4)]
        for i,root in enumerate(roots):
            c.execute('UPDATE aggregations SET date_closed=NULL WHERE id=%s',(root,))
            c.execute('UPDATE aggregations SET title=%s WHERE id=%s',(f'Picker candidate {i}',root))
            c.execute("UPDATE aggregations SET date_closed='2020-01-01' WHERE id=%s",(root,))
            worker_actor(c);evaluate_root(c,root);actor(c)
        kind=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' AND is_active LIMIT 1").fetchone()['id']
        c.execute('INSERT INTO aggregation_relationships(source_id,target_id,relationship_type_id) VALUES(%s,%s,%s)',(roots[0],roots[1],kind))
        result=candidates(c,job,query='candidate',sort='id')
        assert result['total']==4
        linked=next(r for r in result['items'] if r['id']==roots[0])
        assert linked['selectable'] and linked['relationships_block_final']
        assert not {'source_id','target_id','relationship_id','related_aggregation_id'} & linked.keys()
        assert candidates(c,job,query='candidate 3')['items'][0]['id']==roots[3]
        number=c.execute('SELECT aggregation_number FROM aggregations WHERE id=%s',(roots[2],)).fetchone()['aggregation_number']
        assert candidates(c,job,query=number)['total']==1
        page=queries.eligibility(c,job_id=job['id'],query='candidate',limit=2,offset=2,sort='id')
        assert [r['id'] for r in page['items']]==roots[2:] and page['total']==4
        assert not candidates(c,job,due_from=datetime(2100,1,1,tzinfo=timezone.utc))['items']


@pytest.mark.parametrize('hidden',['actor','preparer'])
def test_current_actor_and_delegated_preparer_clearance_are_both_required(client,hidden):
    with db() as c:
        actor(c);c.execute("UPDATE roles SET profile_id=(SELECT id FROM profiles WHERE code='INFO_GOV_MGR') WHERE id=1")
        officer=person(c,'Assigned Officer');role(c,'assigned-officer','INFO_GOV_OFFICER',user=officer)
        job=setup(c,assigned=officer);root,*_=ready(c)
        high=c.execute("INSERT INTO security_levels(level_number,code,name,prevents_disposition) SELECT max(level_number)+1,%s,%s,false FROM security_levels RETURNING id",('PICK-'+uuid4().hex,'Picker protected '+uuid4().hex)).fetchone()['id']
        if hidden=='preparer':c.execute('UPDATE roles SET security_level_id=%s WHERE id=1',(high,))
        c.execute("SELECT set_config('app.security_level_change_authorized','authorized',true)")
        c.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s',(high,root))
        assert candidates(c,job)['total']==0
        c.execute('UPDATE roles SET security_level_id=%s WHERE id=1 OR code=%s',(high,'assigned-officer'))
        assert candidates(c,job)['items'][0]['id']==root


def test_candidate_read_requires_current_addition_rights_and_claim(client):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,'simplified');extra,*_=ready(c)
        other=person(c,'Second eligible Manager')
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,mgr))
        assert candidates(c,job)['total']==1
        submit(c,job['id'])
        with pytest.raises(HTTPException) as error:candidates(c,job)
        assert error.value.status_code==403
        t=task(c,job['id']);act(c,t,'claim',t['destination_role_id'])
        assert candidates(c,job)['items'][0]['id']==extra


def test_http_scope_and_late_blocker_preserve_per_item_addition_results(client):
    from backend.services.api.disposition import membership
    with db() as c:
        job=setup(c);first,*_=ready(c);second,*_=ready(c)
        snapshots=[{'root_id':r,'expected_version':version(c,r)} for r in (first,second)]
    response=client.get('/api/v1/disposition/eligibility',params={'job_id':job['id'],'limit':1})
    assert response.status_code==200,response.text
    assert response.json()['total']==2 and len(response.json()['items'])==1
    assert response.json()['scope']['job_number']==job['job_number']
    assert client.get('/api/v1/disposition/eligibility',params={'job_id':0}).status_code==422
    with db() as c:
        actor(c);make_hold(c,'aggregation',second)
        assert candidates(c,job)['total']==1
        result=membership.add_many(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),items=snapshots))
        assert result['items'][0]['success']
        assert not result['items'][1]['success']
        assert result['items'][1]['code'] in ('disposition_admission_blocked','disposition_stale_version')
        assert not candidates(c,job)['items']


@pytest.mark.parametrize('kind,action',[('permanent_transfer','transfer_to_external_archive'),
    ('selective_transfer','selective_preservation'),('local_archives','retain_as_local_archives')])
def test_other_disposition_jobs_keep_their_matching_action_scope(client,kind,action):
    with db() as c:
        job=setup(c,kind);matching,*_=ready(c,action);other,*_=ready(c)
        assert {r['id'] for r in candidates(c,job)['items']}=={matching}
