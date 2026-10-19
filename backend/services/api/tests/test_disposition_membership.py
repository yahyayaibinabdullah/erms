"""Phase 9 command, current authorization, recalculation and rollback acceptance.

conftest rejects persistent databases before API startup. The runner creates a
new database and drops it after every invocation, including failed runs.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from uuid import uuid4
import os

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from backend.services.api.disposition import membership as service
from backend.services.api.disposition.eligibility import evaluate_root,worker_actor
from backend.services.api.tests.test_disposition_foundation import actor as foundation_actor,command,ensure_officer,version
from backend.services.api.tests.test_disposition_eligibility import unit,make_hold,statuses,wait_for_waiter

ROOT=Path(__file__).resolve().parents[4]


def actor(c,user=1):
    foundation_actor(c,user=user)
    c.execute("SELECT set_config('app.change_reason','Phase 9 policy and membership acceptance',true)")


def db(): return psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row)


def kwargs(**values):
    return dict(acting_role_id=1,reason='Authorized Phase 9 acceptance reason',command_id=uuid4(),**values)


def setup(c,kind='destruction',assigned=1,owner=1):
    actor(c);ensure_officer(c)
    return service.create_job(c,**kwargs(job_number=str(uuid4()),job_type=kind,owning_org_unit_id=owner if kind=='destruction' else None,assigned_user_id=assigned))


def ready(c,action='destruction',*,closed='2020-01-01T00:00:00Z'):
    root,*rest=unit(c,closed=None)
    # A local rule keeps this test unit's policy independent of all other units.
    c.execute("INSERT INTO aggregation_retention_rules(aggregation_id,current_period_years,intermediate_period_years,final_disposition,justification) VALUES(%s,5,0,%s,'Specific test policy')",(root,action))
    if closed is not None:c.execute('UPDATE aggregations SET date_closed=%s WHERE id=%s',(closed,root))
    worker_actor(c);evaluate_root(c,root);actor(c)
    return root,*rest


def job_version(c,job):return c.execute('SELECT version FROM disposition_jobs WHERE id=%s',(job,)).fetchone()['version']


def admit(c,job,roots):
    return service.add_many(c,**kwargs(job_id=job,expected_version=job_version(c,job),items=[{'root_id':root,'expected_version':version(c,root)} for root in roots]))


def member(c,root):return c.execute("SELECT * FROM disposition_job_memberships WHERE root_aggregation_id=%s AND membership_state='active'",(root,)).fetchone()


def remove(c,root):
    m=member(c,root)
    return service.remove_member(c,**kwargs(membership_id=m['id'],expected_version=m['version'],root_version=version(c,root)))


def rule_change(c,root,*,years=0,action='destruction'):
    c.execute('UPDATE aggregation_retention_rules SET current_period_years=%s,final_disposition=%s WHERE aggregation_id=%s',(years,action,root))


@pytest.mark.parametrize('kind,action,pending',[
 ('destruction','destruction',6),('permanent_transfer','transfer_to_external_archive',7),
 ('selective_transfer','selective_preservation',8),('local_archives','retain_as_local_archives',9)])
def test_all_actions_create_admit_remove_and_readd_preserve_each_episode(client,kind,action,pending):
    with db() as c:
        job=setup(c,kind);root,*_=ready(c,action)
        first=admit(c,job['id'],[root]); assert first['items'][0]['success']
        assert statuses(c,root)==[pending]*4
        remove(c,root); assert statuses(c,root)==[pending-4]*4
        second=admit(c,job['id'],[root]); assert second['items'][0]['success']
        assert first['items'][0]['membership_id']!=second['items'][0]['membership_id']
        assert [r['membership_state'] for r in c.execute('SELECT membership_state FROM disposition_job_memberships ORDER BY id')]==['removed','active']
        assert c.execute("SELECT count(*) n FROM event_history WHERE entity_type='disposition_job_membership' AND operation='MEMBERSHIP_ADD'").fetchone()['n']==2


def test_empty_unassigned_job_rejects_admission_then_assignment_enables_it(client):
    with db() as c:
        job=setup(c,assigned=None);root,*_=ready(c)
        assert not admit(c,job['id'],[root])['items'][0]['success']
        assigned=service.assign_job(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),assigned_user_id=1))
        assert assigned['assigned_user_id']==1 and admit(c,job['id'],[root])['items'][0]['success']
        with pytest.raises(psycopg.Error):
            service.assign_job(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),assigned_user_id=None))


@pytest.mark.parametrize('reason',['','   '])
def test_every_command_requires_reason_and_rejected_command_leaves_no_receipt(client,reason):
    with db() as c:
        actor(c);ensure_officer(c)
        with pytest.raises(psycopg.Error,match='disposition_reason_required'):
            service.create_job(c,**{**kwargs(job_number='NO-REASON',job_type='destruction',owning_org_unit_id=1),'reason':reason})
        assert not c.execute('SELECT 1 FROM disposition_jobs').fetchone()
        assert not c.execute('SELECT 1 FROM disposition_private.command_receipts').fetchone()


def test_multi_add_keeps_success_and_rolls_back_stale_blocked_wrong_type_and_hidden_items(client):
    with db() as c:
        job=setup(c);good,*_=ready(c);bad,child,*_=ready(c);wrong,*_=ready(c,'retain_as_local_archives');stale,*_=ready(c)
        c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)");c.execute('UPDATE aggregations SET is_vital=true WHERE id=%s',(child,))
        items=[{'root_id':good,'expected_version':version(c,good)},{'root_id':bad,'expected_version':version(c,bad)},
               {'root_id':wrong,'expected_version':version(c,wrong)},{'root_id':stale,'expected_version':version(c,stale)-1},
               {'root_id':999999,'expected_version':1}]
        options=kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),items=items)
        result=service.add_many(c,**options)
        assert [i['success'] for i in result['items']]==[True,False,False,False,False]
        assert [i.get('code') for i in result['items'][1:]]==['disposition_admission_blocked','disposition_job_type_status_mismatch','disposition_stale_version','disposition_resource_access_required']
        assert service.add_many(c,**options)==result
        assert statuses(c,good)==[6]*4 and statuses(c,bad)==[2]*4 and member(c,bad) is None
        assert len(c.execute('SELECT * FROM disposition_job_memberships').fetchall())==1


@pytest.mark.parametrize('kind',['root_vital','descendant_vital','record_vital','security','hold_root','hold_inherited','hold_record'])
def test_current_protections_reject_admission_and_acceleration_without_changing_unit(client,kind):
    with db() as c:
        job=setup(c);root,child,leaf,record=ready(c)
        with c.transaction(force_rollback=True):
            if kind.endswith('vital'):
                c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)")
                table='records' if kind=='record_vital' else 'aggregations';target=root if kind=='root_vital' else record if kind=='record_vital' else child
                c.execute(f'UPDATE {table} SET is_vital=true WHERE id=%s',(target,))
            elif kind=='security':c.execute('UPDATE security_levels SET prevents_disposition=true WHERE id=(SELECT security_level_id FROM records WHERE id=%s)',(record,))
            else:make_hold(c,'record' if kind=='hold_record' else 'aggregation',record if kind=='hold_record' else child if kind=='hold_inherited' else root)
            result=admit(c,job['id'],[root]);assert result['items'][0]['code']=='disposition_admission_blocked'
            assert statuses(c,root)==[2]*4 and member(c,root) is None
            # Reopening obeys preserve-state holds; use policy recalculation to
            # make status 1 without weakening those existing metadata guards.
            rule_change(c,root,years=100)
            assert statuses(c,root)==[1]*4
            with pytest.raises(psycopg.Error,match='disposition_admission_blocked'):
                service.accelerate(c,**kwargs(root_id=root,expected_version=version(c,root)))
            assert statuses(c,root)==[1]*4


@pytest.mark.parametrize('closed',[None,'2025-01-01T00:00:00Z'])
@pytest.mark.parametrize('action,status',[('destruction',2),('transfer_to_external_archive',3),('selective_preservation',4),('retain_as_local_archives',5)])
def test_acceleration_uses_effective_action_including_open_root_and_saves_reason_dates(client,closed,action,status):
    with db() as c:
        setup(c);root,*_=ready(c,action,closed=closed)
        assert statuses(c,root)==[1]*4
        result=service.accelerate(c,**kwargs(root_id=root,expected_version=version(c,root)))
        assert result['status']==status and statuses(c,root)==[status]*4
        event=c.execute("SELECT * FROM event_history WHERE operation='DISPOSITION_ACCELERATED' AND entity_id=%s",(root,)).fetchone()
        assert event['actor_user_id']==1 and event['reason']=='Authorized Phase 9 acceptance reason'
        assert event['metadata']['rule_snapshot']['final_disposition']==action
        assert (event['metadata']['calculated_disposition_at'] is None)==(closed is None)
        if closed is None:assert not admit(c,c.execute('SELECT id FROM disposition_jobs').fetchone()['id'],[root])['items'][0]['success']


def test_outside_relationships_allow_acceleration_and_admission(client):
    with db() as c:
        job=setup(c);root,*_=ready(c,closed='2025-01-01');other,*_=ready(c)
        typ=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' LIMIT 1").fetchone()['id']
        c.execute('INSERT INTO aggregation_relationships(source_id,target_id,relationship_type_id) VALUES(%s,%s,%s)',(root,other,typ))
        service.accelerate(c,**kwargs(root_id=root,expected_version=version(c,root)))
        assert admit(c,job['id'],[root])['items'][0]['success']
        assert c.execute('SELECT count(*) n FROM disposition_private.relationship_scope(%s) WHERE blocks_final',(root,)).fetchone()['n']==1


def test_simultaneous_jobs_cannot_admit_the_same_root(client):
    with db() as c:
        one=setup(c);two=setup(c);root,*_=ready(c);v=version(c,root)
    def attempt(job):
        with db() as c:
            actor(c)
            return service.add_many(c,**kwargs(job_id=job['id'],expected_version=job['version'],items=[{'root_id':root,'expected_version':v}]))
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,[one,two]))
    assert sum(r['items'][0]['success'] for r in results)==1
    with db() as c:assert c.execute("SELECT count(*) n FROM disposition_job_memberships WHERE membership_state='active'").fetchone()['n']==1


@pytest.mark.parametrize('years,action,status,required',[(0,'destruction',6,False),(100,'destruction',1,True),(0,'retain_as_local_archives',5,True)])
def test_rule_change_is_atomic_preserves_matching_pending_or_requires_explicit_removal(client,years,action,status,required):
    with db() as c:
        job=setup(c);root,*_=ready(c);admit(c,job['id'],[root]);before=member(c,root)
        rule_change(c,root,years=years,action=action)
        after=member(c,root);assert after['id']==before['id'] and after['removal_required'] is required
        assert statuses(c,root)==[status]*4
        if required:
            with pytest.raises(psycopg.Error,match='disposition_removal_required'):
                command(c,'review_submit',lambda c:(c.execute("UPDATE disposition_jobs SET workflow_stage='records_manager_review' WHERE id=%s",(job['id'],)) and {}))
            remove(c,root);assert statuses(c,root)==[status]*4
            assert c.execute('SELECT membership_state FROM disposition_job_memberships WHERE id=%s',(before['id'],)).fetchone()['membership_state']=='removed'
        else:c.execute('SELECT disposition_private.require_progress(%s)',(job['id'],))
        event=c.execute("SELECT metadata FROM event_history WHERE operation='DISPOSITION_RECALCULATED' AND entity_type='aggregation' AND entity_id=%s ORDER BY id DESC LIMIT 1",(root,)).fetchone()['metadata']
        assert event['new_status']==status and event['removal_required'] is required
        assert event['old_evaluation']['rule_snapshot']['final_disposition']=='destruction'


def test_reopen_reclose_keeps_removal_required_and_removal_at_status_one_then_worker_can_evaluate(client):
    with db() as c:
        job=setup(c);root,*_=ready(c);admit(c,job['id'],[root]);old_member=member(c,root)['id']
        c.execute('UPDATE aggregations SET date_closed=NULL WHERE id=%s',(root,));assert statuses(c,root)==[1]*4
        assert member(c,root)['removal_required_reason']=='reopened'
        c.execute("UPDATE aggregations SET date_closed='2020-01-01' WHERE id=%s",(root,))
        worker_actor(c);assert not evaluate_root(c,root)['changed'];actor(c)
        remove(c,root);assert statuses(c,root)==[1]*4
        worker_actor(c);assert evaluate_root(c,root)['changed'];actor(c)
        assert statuses(c,root)==[2]*4
        assert c.execute('SELECT membership_state FROM disposition_job_memberships WHERE id=%s',(old_member,)).fetchone()['membership_state']=='removed'
        assert c.execute("SELECT count(*) n FROM event_history WHERE operation='DISPOSITION_REOPENED' AND entity_id=%s",(root,)).fetchone()['n']==1


def hierarchy(c):
    branch=c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(1,'POLICY','Policy branch',false) RETURNING id").fetchone()['id']
    c.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES(%s,5,0,'destruction')",(branch,))
    child=c.execute("INSERT INTO classifications(classification_scheme_id,parent_classification_id,code,title,is_terminal) VALUES(1,%s,'LEAF','Leaf',true) RETURNING id",(branch,)).fetchone()['id']
    return branch,child


def test_classification_inherited_policy_change_recalculates_and_local_override_is_isolated(client):
    with db() as c:
        job=setup(c);branch,cls=hierarchy(c);root,*_=unit(c)
        c.execute('UPDATE aggregations SET classification_id=%s WHERE id=%s',(cls,root))
        assert statuses(c,root)==[2]*4
        admit(c,job['id'],[root]);local,*_=ready(c)
        c.execute("UPDATE classification_retention_rules SET final_disposition='retain_as_local_archives' WHERE classification_id=%s",(branch,))
        assert statuses(c,root)==[5]*4 and member(c,root)['removal_required']
        assert statuses(c,local)==[2]*4


def test_unchanged_inherited_rule_preserves_acceleration_and_membership_without_status_event(client):
    with db() as c:
        job=setup(c);branch,cls=hierarchy(c)
        middle=c.execute("INSERT INTO classifications(classification_scheme_id,parent_classification_id,code,title,is_terminal) VALUES(1,%s,'MIDDLE','Middle',false) RETURNING id",(branch,)).fetchone()['id']
        root,*_=unit(c,closed='2025-01-01');c.execute('UPDATE aggregations SET classification_id=%s WHERE id=%s',(cls,root))
        service.accelerate(c,**kwargs(root_id=root,expected_version=version(c,root)));admit(c,job['id'],[root]);before=member(c,root)
        events=c.execute('SELECT count(*) n FROM event_history WHERE entity_type=\'aggregation\' AND entity_id=%s',(root,)).fetchone()['n']
        c.execute('UPDATE classifications SET parent_classification_id=%s WHERE id=%s',(middle,cls))
        assert statuses(c,root)==[6]*4 and member(c,root)==before
        assert c.execute('SELECT count(*) n FROM event_history WHERE entity_type=\'aggregation\' AND entity_id=%s',(root,)).fetchone()['n']==events


def test_changed_classification_hierarchy_recalculates_all_affected_units_as_one_operation(client):
    with db() as c:
        setup(c);branch,cls=hierarchy(c)
        other=c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(1,'OTHER','Other policy',false) RETURNING id").fetchone()['id']
        c.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES(%s,0,0,'retain_as_local_archives')",(other,))
        roots=[]
        for _ in range(2):
            root,*_=unit(c);c.execute('UPDATE aggregations SET classification_id=%s WHERE id=%s',(cls,root));roots.append(root)
        c.execute('UPDATE classifications SET parent_classification_id=%s WHERE id=%s',(other,cls))
        assert all(statuses(c,r)==[5]*4 for r in roots)


def test_deleting_local_override_recalculates_back_to_inherited_rule(client):
    with db() as c:
        setup(c);root,*_=ready(c,'retain_as_local_archives');assert statuses(c,root)==[5]*4
        c.execute('DELETE FROM aggregation_retention_rules WHERE aggregation_id=%s',(root,))
        assert statuses(c,root)==[2]*4
        e=c.execute("SELECT metadata FROM event_history WHERE operation='DISPOSITION_RECALCULATED' AND entity_type='aggregation' AND entity_id=%s ORDER BY id DESC LIMIT 1",(root,)).fetchone()['metadata']
        assert e['old_evaluation']['rule_snapshot']['rule_source']=='aggregation' and e['new_evaluation']['rule_snapshot']['rule_source']=='classification'


def test_policy_authority_does_not_require_disposition_privilege_or_resource_visibility(client):
    with db() as c:
        job=setup(c);root,*_=ready(c);admit(c,job['id'],[root])
        user=c.execute("INSERT INTO users(name,email) VALUES('Policy administrator','policy@fixture.invalid') RETURNING id").fetchone()['id']
        role=c.execute("INSERT INTO roles(org_unit_id,code,name,profile_id,is_information_governance) SELECT 1,'policy-admin','Policy administrator',id,false FROM profiles WHERE code='SYS_ADMIN' RETURNING id").fetchone()['id']
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(user,role));actor(c,user=user)
        assert not c.execute('SELECT current_user_can_view_aggregation(%s) visible',(root,)).fetchone()['visible']
        rule_change(c,root,years=100)
        assert statuses(c,root)==[1]*4 and member(c,root)['removal_required']
        assert c.execute("SELECT actor_user_id FROM event_history WHERE operation='DISPOSITION_RECALCULATED' AND entity_type='aggregation' AND entity_id=%s ORDER BY id DESC LIMIT 1",(root,)).fetchone()['actor_user_id']==user


def test_disposition_authority_alone_cannot_change_retention_policy(client):
    with db() as c:
        setup(c);root,*_=ready(c)
        role=c.execute("SELECT id FROM roles WHERE code='fixture-records-officer'").fetchone()['id']
        user=c.execute("INSERT INTO users(name,email) VALUES('Officer','officer@fixture.invalid') RETURNING id").fetchone()['id']
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(user,role));actor(c,user=user)
        with c.transaction(force_rollback=True):
            c.execute("DELETE FROM profile_privileges WHERE profile_id=(SELECT profile_id FROM roles WHERE id=%s) AND privilege_id=(SELECT id FROM privileges WHERE code='classifications.administer')",(role,))
            with pytest.raises(psycopg.Error,match='disposition_retention_authorization_required'):
                with c.transaction():rule_change(c,root,years=100)
            assert statuses(c,root)==[2]*4


def test_recalculation_failure_rolls_back_policy_every_descendant_job_flag_and_events(client):
    with db() as c:
        job=setup(c);root,child,leaf,record=ready(c);admit(c,job['id'],[root]);before=member(c,root)
        c.execute(f"CREATE FUNCTION fail_phase9() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.id={record} AND NEW.disposition_status<>OLD.disposition_status THEN RAISE EXCEPTION 'Injected descendant failure'; END IF; RETURN NEW; END $$")
        c.execute('CREATE TRIGGER fail_phase9 BEFORE UPDATE ON records FOR EACH ROW EXECUTE FUNCTION fail_phase9()')
        try:
            count=c.execute('SELECT count(*) n FROM event_history').fetchone()['n']
            with pytest.raises(psycopg.Error,match='Injected descendant failure'):
                with c.transaction():rule_change(c,root,years=100)
            assert statuses(c,root)==[6]*4 and member(c,root)==before
            assert c.execute('SELECT current_period_years FROM aggregation_retention_rules WHERE aggregation_id=%s',(root,)).fetchone()['current_period_years']==5
            assert c.execute('SELECT count(*) n FROM event_history').fetchone()['n']==count
            assert not c.execute('SELECT 1 FROM disposition_private.recalculation_context').fetchone()
        finally:c.execute('DROP TRIGGER fail_phase9 ON records');c.execute('DROP FUNCTION fail_phase9()')


def test_termination_requires_confirmation_preserves_memberships_and_allows_new_job(client):
    with db() as c:
        job=setup(c);root,*_=ready(c);admit(c,job['id'],[root]);old=member(c,root)['id']
        with pytest.raises(psycopg.Error,match='disposition_confirmation_required'):
            service.terminate_job(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),confirmed=False))
        options=kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),confirmed=True)
        result=service.terminate_job(c,**options);assert result['lifecycle_state']=='terminated'
        assert service.terminate_job(c,**options)==result and statuses(c,root)==[2]*4
        assert c.execute('SELECT membership_state FROM disposition_job_memberships WHERE id=%s',(old,)).fetchone()['membership_state']=='terminated_history'
        new=setup(c);assert admit(c,new['id'],[root])['items'][0]['success']


def test_forged_context_or_unprotected_membership_cannot_bypass_guards(client):
    with db() as c:
        job=setup(c);root,*_=ready(c)
        c.execute("SELECT set_config('app.disposition_recalculation','authorized',true),set_config('app.disposition_authorized','authorized',true)")
        with pytest.raises(psycopg.Error,match='disposition_protected_operation_required'):
            with c.transaction():c.execute('INSERT INTO disposition_job_memberships(job_id,root_aggregation_id,added_by_user_id) VALUES(%s,%s,1)',(job['id'],root))
        with pytest.raises(psycopg.Error,match='disposition_protected_operation_required'):
            with c.transaction():c.execute('UPDATE aggregations SET disposition_status=6 WHERE id=%s',(root,))
        assert statuses(c,root)==[2]*4


def test_current_policy_change_waits_then_admission_rechecks_new_blocking_state(client):
    with db() as c:job=setup(c);root,*_=ready(c);v=version(c,root)
    q=Queue()
    def add():
        with db() as c:
            actor(c);q.put(c.info.backend_pid)
            return service.add_many(c,**kwargs(job_id=job['id'],expected_version=job['version'],items=[{'root_id':root,'expected_version':v}]))
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db() as c:
            actor(c);rule_change(c,root,years=100)
            future=pool.submit(add);wait_for_waiter(c,q.get(timeout=5));c.commit()
        result=future.result(timeout=10)
    assert not result['items'][0]['success']
    with db() as c:assert statuses(c,root)==[1]*4 and member(c,root) is None


def test_api_command_contract_retries_versions_reason_confirmation_and_no_raw_crud(client):
    with db() as c:actor(c);ensure_officer(c);root,*_=ready(c)
    data={'command_id':str(uuid4()),'acting_role_id':1,'job_number':'API-9','job_type':'destruction','owning_org_unit_id':1,'assigned_user_id':1}
    headers={'X-Change-Reason':'API membership acceptance'}
    assert client.post('/api/v1/disposition/jobs',json=data).status_code==422
    created=client.post('/api/v1/disposition/jobs',json=data,headers=headers);assert created.status_code==201,created.text
    assert client.post('/api/v1/disposition/jobs',json=data,headers=headers).json()==created.json()
    job=created.json();items={'command_id':str(uuid4()),'acting_role_id':1,'items':[{'root_id':root,'expected_version':version_from_db(root)}]}
    url=f'/api/v1/disposition/jobs/{job["id"]}/memberships'
    assert client.post(url,json=items,headers=headers).status_code==428
    added=client.post(url,json=items,headers={**headers,'If-Match':str(job['version'])});assert added.status_code==200 and added.json()['items'][0]['success'],added.text
    assert client.post(url,json=items,headers={**headers,'If-Match':str(job['version'])}).json()==added.json()
    assert client.patch(f'/api/v1/disposition_jobs/{job["id"]}',json={'lifecycle_state':'completed'}).status_code in (404,405)


def version_from_db(root):
    with db() as c:return version(c,root)


def test_canonical_and_independent_membership_migration_match_exactly(client):
    marker='-- Disposition membership and atomic recalculation (055).\n'
    assert (ROOT/'database/schema.sql').read_text().split(marker,1)[1].split('\n-- Disposition governed artifacts (056).',1)[0]==(ROOT/'database/migrations/055_disposition_membership.sql').read_text()
