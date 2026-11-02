"""Phase 9 race, access, stage, rollback and endpoint integration boundaries."""
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from uuid import uuid4
import time

import psycopg
import pytest

from backend.services.api.disposition import membership as service
from backend.services.api.tests.test_disposition_membership import (
    actor,db,setup,ready,admit,member,remove,kwargs,job_version,rule_change,
)
from backend.services.api.tests.test_disposition_foundation import command,version,ensure_officer
from backend.services.api.tests.test_disposition_eligibility import statuses,make_hold,wait_for_waiter


def candidate(c,*,clearance=None,profile='INFO_GOV_OFFICER',governance=True):
    user=c.execute('INSERT INTO users(name,email) VALUES(%s,%s) RETURNING id',('Candidate',str(uuid4())+'@fixture.invalid')).fetchone()['id']
    role=c.execute('INSERT INTO roles(org_unit_id,code,name,profile_id,is_information_governance,security_level_id) SELECT 1,%s,\'Candidate role\',id,%s,COALESCE(%s,lowest_security_level_id()) FROM profiles WHERE code=%s RETURNING id',(str(uuid4()),governance,clearance,profile)).fetchone()['id']
    c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(user,role))
    return user,role


def test_assignment_and_admission_require_assignee_current_clearance_and_do_not_grant_access(client):
    with db() as c:
        job=setup(c);root,*_=ready(c)
        high=c.execute("INSERT INTO security_levels(level_number,code,name,description,prevents_disposition) SELECT max(level_number)+1,'PHASE9','Phase 9 clearance test','Disposable acceptance policy',false FROM security_levels RETURNING id").fetchone()['id']
        # Give only the acting administrator higher clearance, never the candidate.
        c.execute('UPDATE roles SET security_level_id=%s WHERE id=1',(high,))
        c.execute("SELECT set_config('app.security_level_change_authorized','authorized',true)")
        c.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s',(high,root))
        user,role=candidate(c)
        assert not c.execute('SELECT user_can_view_aggregation(%s,%s) allowed',(user,root)).fetchone()['allowed']
        service.assign_job(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),assigned_user_id=user))
        assert admit(c,job['id'],[root])['items'][0]['code']=='disposition_assigned_preparer_required'
        service.assign_job(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),assigned_user_id=1))
        assert admit(c,job['id'],[root])['items'][0]['success']
        with pytest.raises(psycopg.Error,match='disposition_assignee_access_required'):
            service.assign_job(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),assigned_user_id=user))
        assert c.execute('SELECT assigned_user_id FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()['assigned_user_id']==1


@pytest.mark.parametrize('mode',['service','inactive','expired','not_governance','wrong_profile'])
def test_destruction_assignment_requires_current_specific_records_officer(client,mode):
    with db() as c:
        job=setup(c);user,role=candidate(c,profile='ALL_PRIVS' if mode=='wrong_profile' else 'INFO_GOV_OFFICER',governance=mode!='not_governance')
        if mode=='service':c.execute("UPDATE users SET account_type='service' WHERE id=%s",(user,))
        elif mode=='inactive':c.execute("UPDATE users SET date_deactivated=CURRENT_TIMESTAMP WHERE id=%s",(user,))
        elif mode=='expired':c.execute("UPDATE user_role_assignments SET valid_until=CURRENT_TIMESTAMP WHERE user_id=%s",(user,))
        with pytest.raises(psycopg.Error,match='disposition_assignee_not_authorized'):
            service.assign_job(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),assigned_user_id=user))


def test_destruction_owner_subtree_and_empty_never_submitted_owner_change(client):
    with db() as c:
        job=setup(c);inside=c.execute("INSERT INTO org_units(parent_org_unit_id,code,name) VALUES(1,'inside','Inside') RETURNING id").fetchone()['id']
        outside=c.execute("INSERT INTO org_units(code,name) VALUES('outside','Outside') RETURNING id").fetchone()['id']
        good,*_=ready(c,closed=None);bad,*_=ready(c,closed=None)
        # Apply the existing ownership-correction command while the units are
        # still open, then close and evaluate under their distinct owners.
        c.execute("SELECT set_config('app.ownership_correction_authorized','authorized',true)")
        c.execute('UPDATE aggregations SET owning_org_unit_id=%s WHERE id=%s',(inside,good))
        c.execute('UPDATE aggregations SET owning_org_unit_id=%s WHERE id=%s',(outside,bad))
        c.execute("SELECT set_config('app.ownership_correction_authorized','',true)")
        for root in [good,bad]:
            c.execute("UPDATE aggregations SET date_closed='2020-01-01' WHERE id=%s",(root,))
            from backend.services.api.disposition.eligibility import worker_actor,evaluate_root
            worker_actor(c);evaluate_root(c,root);actor(c)
        result=admit(c,job['id'],[good,bad]);assert [i['success'] for i in result['items']]==[True,False]
        assert result['items'][1]['code']=='disposition_owning_unit_mismatch'
        with pytest.raises(psycopg.Error,match='disposition_owning_unit_change_invalid'):
            service.change_job_owner(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),owning_org_unit_id=outside))
        remove(c,good)
        changed=service.change_job_owner(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),owning_org_unit_id=outside))
        assert changed['owning_org_unit_id']==outside
        command(c,'review_submit',lambda c:(c.execute("UPDATE disposition_jobs SET workflow_stage='records_manager_review' WHERE id=%s",(job['id'],)) and {}))
        with pytest.raises(psycopg.Error,match='disposition_owning_unit_change_invalid'):
            service.change_job_owner(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),owning_org_unit_id=1))


def test_reviewer_stage_rejects_membership_edits_and_termination_is_explicit(client):
    with db() as c:
        job=setup(c);root,*_=ready(c);admit(c,job['id'],[root])
        command(c,'review_submit',lambda c:(c.execute("UPDATE disposition_jobs SET workflow_stage='records_manager_review' WHERE id=%s",(job['id'],)) and {}))
        with pytest.raises(psycopg.Error,match='disposition_membership_stage_invalid'):remove(c,root)
        assert member(c,root) is not None and statuses(c,root)==[6]*4
        service.terminate_job(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),confirmed=True))
        assert member(c,root) is None and statuses(c,root)==[2]*4


def test_recalculated_member_can_be_corrected_explicitly_but_cannot_progress(client):
    with db() as c:
        from backend.services.api.tests.test_disposition_review import seeded,submit,claim,decide
        job,root,*_=seeded(c,'simplified')
        submit(c,job);claim(c,job)
        rule_change(c,root,years=100)
        # A real round and rejection create the assigned Officer's correction
        # task. Changing only a stage column is not an authorized open task.
        decide(c,job,'rejected','Correct the changed local retention rule')
        remove(c,root);assert statuses(c,root)==[1]*4
        assert not c.execute('SELECT removal_required FROM disposition_job_memberships WHERE membership_state=\'active\'').fetchone()


def test_reopened_job_termination_keeps_recalculated_status_and_history(client):
    with db() as c:
        job=setup(c);root,*_=ready(c);admit(c,job['id'],[root]);mid=member(c,root)['id']
        c.execute('UPDATE aggregations SET date_closed=NULL WHERE id=%s',(root,))
        service.terminate_job(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),confirmed=True))
        assert statuses(c,root)==[1]*4
        history=c.execute('SELECT * FROM disposition_job_memberships WHERE id=%s',(mid,)).fetchone()
        assert history['membership_state']=='terminated_history' and history['removal_required_reason']=='reopened'


def test_failed_multi_add_descendant_rolls_back_only_failed_unit_and_keeps_others(client):
    with db() as c:
        job=setup(c);bad,_,_,record=ready(c);good,*_=ready(c)
        c.execute(f"CREATE FUNCTION fail_phase9_add() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.id={record} AND NEW.disposition_status<>OLD.disposition_status THEN RAISE EXCEPTION 'Secret injected failure'; END IF; RETURN NEW; END $$")
        c.execute('CREATE TRIGGER fail_phase9_add BEFORE UPDATE ON records FOR EACH ROW EXECUTE FUNCTION fail_phase9_add()')
        try:
            result=admit(c,job['id'],[bad,good])
            assert result['items'][0]=={'root_id':bad,'success':False,'code':'disposition_item_not_added'}
            assert result['items'][1]['success'] and statuses(c,good)==[6]*4
            assert statuses(c,bad)==[2]*4 and member(c,bad) is None
            assert not c.execute("SELECT 1 FROM event_history WHERE operation='MEMBERSHIP_ADD' AND metadata#>>'{after,root_aggregation_id}'=%s",(str(bad),)).fetchone()
        finally:c.execute('DROP TRIGGER fail_phase9_add ON records');c.execute('DROP FUNCTION fail_phase9_add()')


def test_reopening_failure_rolls_back_closure_status_membership_flag_and_history(client):
    with db() as c:
        job=setup(c);root,_,_,record=ready(c);admit(c,job['id'],[root]);before=member(c,root)
        c.execute(f"CREATE FUNCTION fail_phase9_open() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.id={record} AND NEW.disposition_status<>OLD.disposition_status THEN RAISE EXCEPTION 'Reopen rollback'; END IF; RETURN NEW; END $$")
        c.execute('CREATE TRIGGER fail_phase9_open BEFORE UPDATE ON records FOR EACH ROW EXECUTE FUNCTION fail_phase9_open()')
        try:
            with pytest.raises(psycopg.Error,match='Reopen rollback'):
                with c.transaction():c.execute('UPDATE aggregations SET date_closed=NULL WHERE id=%s',(root,))
            assert c.execute('SELECT date_closed FROM aggregations WHERE id=%s',(root,)).fetchone()['date_closed'] is not None
            assert statuses(c,root)==[6]*4 and member(c,root)==before
            assert not c.execute("SELECT 1 FROM event_history WHERE operation='DISPOSITION_REOPENED' AND entity_id=%s",(root,)).fetchone()
        finally:c.execute('DROP TRIGGER fail_phase9_open ON records');c.execute('DROP FUNCTION fail_phase9_open()')


def test_hold_becomes_effective_during_admission_lock_wait_and_is_not_missed(client):
    with db() as c:
        job=setup(c);root,_,_,record=ready(c);hold=make_hold(c,'record',record)
        start=c.execute("UPDATE holds SET valid_from=clock_timestamp()+INTERVAL '1 second' WHERE id=%s RETURNING valid_from",(hold,)).fetchone()['valid_from']
        v=version(c,root)
    q=Queue()
    def add():
        with db() as c:
            actor(c);q.put(c.info.backend_pid)
            return service.add_many(c,**kwargs(job_id=job['id'],expected_version=job['version'],items=[{'root_id':root,'expected_version':v}]))
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db() as c:
            c.execute('SELECT pg_advisory_xact_lock(7357,1)');future=pool.submit(add);wait_for_waiter(c,q.get(timeout=5))
            deadline=time.monotonic()+5
            while c.execute('SELECT clock_timestamp()<%s waiting',(start,)).fetchone()['waiting']:
                assert time.monotonic()<deadline;time.sleep(.01)
            c.commit()
        result=future.result(timeout=10)
    assert result['items'][0]['code']=='disposition_admission_blocked'
    with db() as c:assert statuses(c,root)==[2]*4 and member(c,root) is None


def test_http_reopening_and_retention_edit_apply_immediate_unit_changes_with_existing_authority(client):
    with db() as c:job=setup(c);root,*_=ready(c);admit(c,job['id'],[root]);v=version(c,root)
    result=client.patch(f'/api/v1/aggregations/{root}',json={'date_closed':None},headers={'If-Match':str(v),'X-Change-Reason':'Reopen required for correction'})
    assert result.status_code==200,result.text
    with db() as c:
        assert statuses(c,root)==[1]*4 and member(c,root)['removal_required']
        assert result.json()['version']==version(c,root)
    # Existing rule endpoints retain their reason/version contract, not a
    # second job-local copy or a new disposition-only policy privilege.
    with db() as c:v=c.execute('SELECT version FROM aggregation_retention_rules WHERE aggregation_id=%s',(root,)).fetchone()['version']
    result=client.put(f'/api/v1/aggregations/{root}/retention-rule?version={v}',json={'current_period_years':0,'intermediate_period_years':0,'final_disposition':'retain_as_local_archives','justification':'Policy changed while reopened'},headers={'X-Change-Reason':'Approved local policy'})
    assert result.status_code==200,result.text
    with db() as c:assert statuses(c,root)==[1]*4 and member(c,root)['removal_required_reason']=='reopened'


def test_acceleration_closes_unit_and_rejects_new_descendants(client):
    with db() as c:
        setup(c);root,child,*_=ready(c,closed=None)
        service.accelerate(c,**kwargs(root_id=root,expected_version=version(c,root)))
        for statement,parameters in [
            ("INSERT INTO aggregations(parent_aggregation_id,aggregation_number,title) VALUES(%s,%s,'Later child')",(root,str(uuid4()))),
            ("INSERT INTO records(aggregation_id,record_number,title) VALUES(%s,%s,'Later record')",(child,str(uuid4())))]:
            with pytest.raises(psycopg.Error,match='closed'):
                with c.transaction():c.execute(statement,parameters)
        assert statuses(c,root)==[2]*4


def test_invalid_due_date_policy_rolls_back_immediately_instead_of_saving_inconsistent_state(client):
    with db() as c:
        setup(c);root,*_=ready(c)
        with pytest.raises(psycopg.errors.DatetimeFieldOverflow):
            with c.transaction():rule_change(c,root,years=2000000000)
        assert statuses(c,root)==[2]*4
        assert c.execute('SELECT current_period_years FROM aggregation_retention_rules WHERE aggregation_id=%s',(root,)).fetchone()['current_period_years']==5


def test_termination_failure_rolls_back_every_unit_job_episode_and_event(client):
    with db() as c:
        job=setup(c);one,*_=ready(c);two,_,_,record=ready(c);admit(c,job['id'],[one,two])
        before=[member(c,one),member(c,two)];events=c.execute('SELECT count(*) n FROM event_history').fetchone()['n']
        c.execute(f"CREATE FUNCTION fail_phase9_terminate() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.id={record} AND NEW.disposition_status<>OLD.disposition_status THEN RAISE EXCEPTION 'Terminate rollback'; END IF; RETURN NEW; END $$")
        c.execute('CREATE TRIGGER fail_phase9_terminate BEFORE UPDATE ON records FOR EACH ROW EXECUTE FUNCTION fail_phase9_terminate()')
        try:
            with pytest.raises(psycopg.Error,match='Terminate rollback'):
                service.terminate_job(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),confirmed=True))
            assert statuses(c,one)==statuses(c,two)==[6]*4
            assert [member(c,one),member(c,two)]==before
            assert c.execute('SELECT lifecycle_state FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()['lifecycle_state']=='active'
            assert c.execute('SELECT count(*) n FROM event_history').fetchone()['n']==events
        finally:c.execute('DROP TRIGGER fail_phase9_terminate ON records');c.execute('DROP FUNCTION fail_phase9_terminate()')


@pytest.mark.parametrize('detach',[False,True])
def test_accelerated_closed_subtree_cannot_move_or_detach(client,detach):
    with db() as c:
        setup(c);source,child,*_=ready(c,closed=None);destination,*_=ready(c,closed=None)
        service.accelerate(c,**kwargs(root_id=source,expected_version=version(c,source)))
        with pytest.raises(psycopg.Error,match='closed'):
            with c.transaction():
                if detach:c.execute('UPDATE aggregations SET parent_aggregation_id=NULL,classification_id=1 WHERE id=%s',(child,))
                else:c.execute('UPDATE aggregations SET parent_aggregation_id=%s WHERE id=%s',(destination,child))
        assert statuses(c,source)==[2]*4 and statuses(c,destination)==[1]*4


def test_committed_retry_rechecks_current_resource_access_without_granting_assignment_access(client):
    with db() as c:
        job=setup(c);root,*_=ready(c)
        options=kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),items=[{'root_id':root,'expected_version':version(c,root)}])
        result=service.add_many(c,**options);assert result['items'][0]['success']
        with c.transaction(force_rollback=True):
            c.execute("DELETE FROM profile_privileges WHERE profile_id IN (SELECT profile_id FROM roles WHERE id IN (SELECT role_id FROM user_role_assignments WHERE user_id=1)) AND privilege_id=(SELECT id FROM privileges WHERE code='aggregation.view')")
            with pytest.raises(psycopg.Error,match='disposition_resource_access_required'):service.add_many(c,**options)
            assert statuses(c,root)==[6]*4


@pytest.mark.parametrize('operation',['remove','terminate'])
@pytest.mark.parametrize('protection',['hold','vital','security'])
def test_protection_arising_after_admission_does_not_prevent_leaving_job_or_clear_protection(client,operation,protection):
    with db() as c:
        job=setup(c);root,_,_,record=ready(c);admit(c,job['id'],[root])
        with c.transaction(force_rollback=True):
            if protection=='hold':make_hold(c,'record',record)
            elif protection=='vital':
                c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)")
                c.execute('UPDATE records SET is_vital=true WHERE id=%s',(record,))
            else:c.execute('UPDATE security_levels SET prevents_disposition=true WHERE id=(SELECT security_level_id FROM records WHERE id=%s)',(record,))
            if operation=='remove':remove(c,root)
            else:service.terminate_job(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),confirmed=True))
            assert statuses(c,root)==[2]*4 and member(c,root) is None
            assert c.execute('SELECT count(*) n FROM disposition_private.protection_blockers(%s)',(root,)).fetchone()['n']>=1


def test_historical_membership_remains_immutable_after_former_root_moves_and_job_can_still_be_managed(client):
    with db() as c:
        job=setup(c);root,*_=ready(c);admit(c,job['id'],[root]);mid=member(c,root)['id'];remove(c,root)
        history=c.execute('SELECT * FROM disposition_job_memberships WHERE id=%s',(mid,)).fetchone()
        c.execute('UPDATE aggregations SET date_closed=NULL WHERE id=%s',(root,))
        c.execute('DELETE FROM aggregation_retention_rules WHERE aggregation_id=%s',(root,))
        destination,*_=ready(c,closed=None)
        c.execute('UPDATE aggregations SET parent_aggregation_id=%s,classification_id=NULL WHERE id=%s',(destination,root))
        service.assign_job(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),assigned_user_id=1))
        assert c.execute('SELECT * FROM disposition_job_memberships WHERE id=%s',(mid,)).fetchone()==history
        c.execute('SET CONSTRAINTS ALL IMMEDIATE')


@pytest.mark.parametrize('required,reason',[(True,None),(True,'unapproved_reason'),(False,'reopened')])
def test_removal_reason_database_constraint_rejects_partial_or_inconsistent_internal_writes(client,required,reason):
    # Isolate the CHECK from the stronger command trigger, only in the runner's
    # disposable database, to prove NULL cannot weaken the SQL backstop.
    with db() as c:
        job=setup(c);root,*_=ready(c);c.execute('SET CONSTRAINTS ALL IMMEDIATE')
        c.execute('ALTER TABLE disposition_job_memberships DISABLE TRIGGER disposition_guard')
        try:
            with pytest.raises(psycopg.errors.CheckViolation,match='disposition_removal_required_reason'):
                with c.transaction():
                    c.execute('INSERT INTO disposition_job_memberships(job_id,root_aggregation_id,added_by_user_id,removal_required,removal_required_reason) VALUES(%s,%s,1,%s,%s)',(job['id'],root,required,reason))
            assert member(c,root) is None and statuses(c,root)==[2]*4
        finally:c.execute('ALTER TABLE disposition_job_memberships ENABLE TRIGGER disposition_guard')


def test_routine_addition_without_reason_retains_audit_and_removal_requires_reason(client):
    with db() as c:
        job=setup(c);root,*_=ready(c)
        identity=job['id'];expected=job_version(c,identity);rv=version(c,root)
    payload={'command_id':str(uuid4()),'acting_role_id':1,'items':[{'root_id':root,'expected_version':rv}]}
    response=client.post(f'/api/v1/disposition/jobs/{identity}/memberships',json=payload,headers={'If-Match':str(expected)})
    assert response.status_code==200,response.text
    assert response.json()['items'][0]['success']
    again=client.post(f'/api/v1/disposition/jobs/{identity}/memberships',json=payload,headers={'If-Match':str(expected)})
    assert again.json()==response.json()
    with db() as c:
        actor(c)
        receipt=c.execute('SELECT * FROM disposition_private.command_receipts WHERE command_id=%s',(payload['command_id'],)).fetchone()
        assert receipt['reason']=='' and receipt['actor_user_id']==1
        assert c.execute("SELECT 1 FROM event_history WHERE entity_id=%s AND actor_user_id=1",(root,)).fetchone()
        membership=member(c,root)
        with pytest.raises(psycopg.Error,match='disposition_reason_required'):
            service.remove_member(c,**{**kwargs(membership_id=membership['id'],expected_version=job_version(c,identity),root_version=version(c,root)),'reason':''})
