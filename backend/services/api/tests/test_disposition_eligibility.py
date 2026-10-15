"""Phase 8 database-clock, bounded-worker and current blocker acceptance."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
import os
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
import pytest
from fastapi import HTTPException

from backend.services.api.disposition.eligibility import evaluate_root,worker_actor,run_pass
from backend.services.api.disposition.blockers import summary,protection_page,relationship_page
from backend.services.api.tests.test_disposition_foundation import make_job,add,remove,command,version


def db(): return psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row)


def actor(c):
    c.execute("SELECT set_config('app.user_id','1',true),set_config('app.actor_type','user',true),set_config('app.event_source','api',true),set_config('app.change_reason','Verify Phase 8 eligibility and protections',true)")


def unit(c,*,closed='2020-01-01T00:00:00Z',vital=False):
    root=c.execute("INSERT INTO aggregations(aggregation_number,title,classification_id,owning_org_unit_id,date_opened) VALUES(%s,'Root',1,1,'1900-01-01') RETURNING id",(str(uuid4()),)).fetchone()['id']
    child=c.execute("INSERT INTO aggregations(parent_aggregation_id,aggregation_number,title,is_vital) VALUES(%s,%s,'Child',%s) RETURNING id",(root,str(uuid4()),vital)).fetchone()['id']
    leaf=c.execute("INSERT INTO aggregations(parent_aggregation_id,aggregation_number,title) VALUES(%s,%s,'Leaf') RETURNING id",(child,str(uuid4()))).fetchone()['id']
    record=c.execute("INSERT INTO records(aggregation_id,record_number,title) VALUES(%s,%s,'Record') RETURNING id",(leaf,str(uuid4()))).fetchone()['id']
    if closed is not None: c.execute('UPDATE aggregations SET date_closed=%s WHERE id=%s',(closed,root))
    return root,child,leaf,record


def rule(c,action='destruction',current=5,intermediate=0):
    c.execute('UPDATE classification_retention_rules SET current_period_years=%s,intermediate_period_years=%s,final_disposition=%s WHERE classification_id=1',(current,intermediate,action))


def evaluate(c,root,key=None):
    worker_actor(c)
    result=evaluate_root(c,root,command_id=key)
    actor(c)
    return result


def statuses(c,root):
    return [r['disposition_status'] for r in c.execute('SELECT disposition_status FROM aggregations WHERE id IN (SELECT disposition_private.unit_ids(%s)) UNION ALL SELECT disposition_status FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(%s))',(root,root))]


@pytest.mark.parametrize('action,status',[('destruction',2),('transfer_to_external_archive',3),('selective_preservation',4),('retain_as_local_archives',5)])
def test_effective_action_maps_to_complete_unit_and_permanent_rule_dates(client,action,status):
    with db() as c:
        actor(c); rule(c,action); root,*_=unit(c)
        result=evaluate(c,root)
        assert result['changed'] and result['status']==status
        assert statuses(c,root)==[status]*4
        event=c.execute("SELECT * FROM event_history WHERE operation='DISPOSITION_ELIGIBILITY_EVALUATED' AND entity_id=%s",(root,)).fetchone()
        assert event['actor_type']=='automated_process' and event['actor_user_id'] is None
        assert event['actor_name']=='Disposition eligibility service' and event['source']=='background_service'
        snapshot=event['metadata']; assert snapshot['rule_snapshot']['final_disposition']==action
        assert snapshot['rule_snapshot']['definition']['version']==2
        assert snapshot['date_closed'].startswith('2020-01-01') and snapshot['calculated_disposition_at'].startswith('2025-01-01')
        assert c.execute('SELECT count(*) n FROM disposition_private.command_context').fetchone()['n']==0


@pytest.mark.parametrize('offset,expected',[(-1,True),(0,False),(1,False)])
def test_strict_exact_database_due_boundary(client,offset,expected):
    with db() as c:
        actor(c); rule(c,current=1)
        now=c.execute("SELECT CURRENT_TIMESTAMP-INTERVAL '1 year' now").fetchone()['now']
        root,*_=unit(c,closed=now+timedelta(microseconds=offset))
        result=evaluate(c,root)
        assert result['changed'] is expected
        assert statuses(c,root)==([2]*4 if expected else [1]*4)


@pytest.mark.parametrize('zone',['UTC','Asia/Dubai','America/New_York','Pacific/Kiritimati'])
@pytest.mark.parametrize('closed,years,expected',[
 ('2020-02-29T23:30:00Z',1,'2021-02-28T23:30:00+00:00'),
 ('2020-02-29T23:30:00Z',4,'2024-02-29T23:30:00+00:00'),
 ('2024-03-10T06:30:00Z',1,'2025-03-10T06:30:00+00:00')])
def test_database_due_arithmetic_is_utc_calendar_and_session_zone_independent(client,zone,closed,years,expected):
    with db() as c:
        actor(c); rule(c,current=years//2,intermediate=years-years//2); root,*_=unit(c,closed=closed)
        c.execute("SELECT set_config('TimeZone',%s,true)",(zone,))
        result=c.execute('SELECT * FROM disposition_private.eligibility(%s)',(root,)).fetchone()
        assert result['calculated_disposition_at'].astimezone(timezone.utc).isoformat()==expected


def test_root_local_rule_precedes_classification_and_open_roots_stay_not_ready(client):
    with db() as c:
        actor(c); root,*_=unit(c); opened,*_=unit(c,closed=None)
        c.execute("INSERT INTO aggregation_retention_rules(aggregation_id,current_period_years,intermediate_period_years,final_disposition,justification) VALUES(%s,0,0,'retain_as_local_archives','Local policy takes precedence')",(root,))
        result=evaluate(c,root)
        # Phase 9 makes the policy change recalculate immediately; the worker
        # then observes the completed transition and does not duplicate it.
        assert not result['changed'] and statuses(c,root)==[5]*4
        captured=c.execute("SELECT metadata#>'{new_evaluation,rule_snapshot}' snapshot FROM event_history WHERE operation='DISPOSITION_RECALCULATED' AND entity_type='aggregation' AND entity_id=%s ORDER BY id DESC LIMIT 1",(root,)).fetchone()['snapshot']
        assert captured['rule_source']=='aggregation' and captured['justification']=='Local policy takes precedence'
        assert not evaluate(c,opened)['changed'] and statuses(c,opened)==[1]*4


def test_repeated_and_simultaneous_evaluation_are_idempotent(client):
    with db() as c: actor(c); root,*_=unit(c)
    def attempt(_):
        with db() as c: return evaluate(c,root)
    with ThreadPoolExecutor(max_workers=2) as executor: results=list(executor.map(attempt,range(2)))
    assert sum(r['changed'] for r in results)==1
    with db() as c:
        assert not evaluate(c,root)['changed']
        assert c.execute("SELECT count(*) n FROM event_history WHERE operation='DISPOSITION_ELIGIBILITY_EVALUATED' AND entity_id=%s",(root,)).fetchone()['n']==1
        assert c.execute("SELECT count(*) n FROM disposition_private.command_receipts WHERE actor_type='automated_process'").fetchone()['n']==1


def test_worker_receipt_retries_return_exact_result_and_reject_changed_root(client):
    key=uuid4()
    with db() as c:
        actor(c); root,*_=unit(c); other,*_=unit(c)
        result=evaluate(c,root,key)
        assert evaluate(c,root,key)==result
        with pytest.raises(psycopg.Error,match='disposition_command_conflict'):
            with c.transaction(): evaluate(c,other,key)


def test_human_or_guc_only_client_cannot_invoke_automated_transition(client):
    with db() as c:
        actor(c); root,*_=unit(c)
        with pytest.raises(psycopg.Error,match='disposition_eligibility_worker_required'):
            with c.transaction(): evaluate_root(c,root)
        worker_actor(c)
        c.execute("SELECT set_config('app.disposition_authorized','authorized',true)")
        with pytest.raises(psycopg.Error,match='disposition_protected_operation_required'):
            with c.transaction(): c.execute('UPDATE aggregations SET disposition_status=2 WHERE id=%s',(root,))
        assert statuses(c,root)==[1]*4


def make_hold(c,kind,resource,preserve=True):
    hold=c.execute("INSERT INTO holds(code,name,valid_from,owner_user_id,preserve_resource_state) VALUES(%s,'Confidential hold',CURRENT_TIMESTAMP-INTERVAL '1 day',1,%s) RETURNING id",(str(uuid4()),preserve)).fetchone()['id']
    table='hold_aggregation_assignments' if kind=='aggregation' else 'hold_record_assignments'
    field='aggregation_id' if kind=='aggregation' else 'record_id'
    c.execute(f'INSERT INTO {table}(hold_id,{field}) VALUES(%s,%s)',(hold,resource))
    return hold


@pytest.mark.parametrize('kind',['root_hold','descendant_hold','record_hold','vital','security'])
def test_current_protections_block_admission_but_do_not_stop_eligibility(client,kind):
    with db() as c, c.transaction(force_rollback=True):
        actor(c); root,child,leaf,record=unit(c,vital=kind=='vital')
        if kind=='root_hold': make_hold(c,'aggregation',root)
        elif kind=='descendant_hold': make_hold(c,'aggregation',child)
        elif kind=='record_hold': make_hold(c,'record',record)
        elif kind=='security': c.execute('UPDATE security_levels SET prevents_disposition=true WHERE id=(SELECT security_level_id FROM records WHERE id=%s)',(record,))
        assert evaluate(c,root)['changed'] and statuses(c,root)==[2]*4
        assert summary(c,root)['blocks_admission'] is True
        blockers=protection_page(c,root)['items']; assert blockers
        if kind=='root_hold': assert len(blockers)==4
        if kind=='descendant_hold': assert len(blockers)==3
        if kind=='record_hold': assert len(blockers)==1


def test_blocker_rows_are_bounded_separate_and_redacted_without_identity_leaks(client):
    with db() as c:
        actor(c); root,child,leaf,record=unit(c,vital=True)
        make_hold(c,'record',record)
        with c.transaction(force_rollback=True):
            c.execute("DELETE FROM profile_privileges WHERE profile_id=(SELECT profile_id FROM roles WHERE id=1) AND privilege_id=(SELECT id FROM privileges WHERE code='record.view')")
            first=protection_page(c,root,limit=1); second=protection_page(c,root,limit=1,offset=1)
            assert first['has_more'] and len(first['items'])==1 and len(second['items'])==1
            hidden=second['items'][0]
            assert hidden['redacted'] and hidden['resource_id'] is None and hidden['holds']==[] and hidden['legal_hold']
        assert protection_page(c,root,limit=1)['has_more']
        with pytest.raises(ValueError): protection_page(c,root,limit=101)


def test_preserve_state_hold_still_rejects_ordinary_metadata_edits(client):
    with db() as c:
        actor(c); root,child,leaf,record=unit(c,closed=None); make_hold(c,'record',record)
        with pytest.raises(psycopg.Error,match='effective_hold_prevents_metadata_change'):
            with c.transaction(): c.execute("UPDATE records SET title='Not an eligibility change' WHERE id=%s",(record,))


def link(c,kind,source,target,type_id=None):
    if type_id is None: type_id=c.execute('SELECT id FROM relationship_types WHERE resource_kind=%s ORDER BY id LIMIT 1',(kind,)).fetchone()['id']
    return c.execute(f'INSERT INTO {kind}_relationships(relationship_type_id,source_id,target_id) VALUES(%s,%s,%s) RETURNING id',(type_id,source,target)).fetchone()['id']


@pytest.mark.parametrize('kind',['aggregation','record'])
@pytest.mark.parametrize('reverse',[False,True])
def test_all_relationship_types_both_directions_and_same_job_rules(client,kind,reverse):
    with db() as c:
        actor(c); root,child,leaf,record=unit(c); other,other_child,_,other_record=unit(c)
        source,target=(child,other_child) if kind=='aggregation' else (record,other_record)
        if reverse: source,target=target,source
        types=c.execute('SELECT id FROM relationship_types WHERE resource_kind=%s ORDER BY id',(kind,)).fetchall()
        for definition in types: link(c,kind,source,target,definition['id'])
        assert evaluate(c,root)['changed'] and evaluate(c,other)['changed']
        assert summary(c,root)=={'blocks_admission':False,'relationships_block_final':True,'blocks_final':True}
        assert len(relationship_page(c,root)['items'])==len(types)
        first_job=make_job(c); second_job=make_job(c)
        first_member=add(c,first_job,root); other_member=add(c,second_job,other)
        assert summary(c,root)['relationships_block_final']  # Different jobs.
        remove(c,other_member,other); add(c,first_job,other)
        rows=relationship_page(c,root)['items']
        assert all(r['is_same_job'] and not r['blocks_final'] for r in rows)
        assert not summary(c,root)['relationships_block_final']
        assert statuses(c,root)==[6]*4  # Read-only blocker checks preserve pending state.


@pytest.mark.parametrize('kind',['aggregation','record'])
def test_internal_links_do_not_block_and_removal_from_either_endpoint_refreshes(client,kind):
    with db() as c:
        actor(c); root,child,leaf,record=unit(c); other,other_child,_,other_record=unit(c)
        if kind=='aggregation': internal_source,internal_target=child,leaf
        else:
            # Create a second record before closing a new unit for its internal link.
            root,child,leaf,record=unit(c,closed=None)
            internal_source=record
            internal_target=c.execute("INSERT INTO records(aggregation_id,record_number,title) VALUES(%s,%s,'Internal record') RETURNING id",(leaf,str(uuid4()))).fetchone()['id']
            c.execute("UPDATE aggregations SET date_closed='2020-01-01' WHERE id=%s",(root,))
        link(c,kind,internal_source,internal_target)
        assert not summary(c,root)['relationships_block_final']
        external=link(c,kind,internal_source,other_child if kind=='aggregation' else other_record)
        assert summary(c,root)['relationships_block_final'] and summary(c,other)['relationships_block_final']
        c.execute(f'DELETE FROM {kind}_relationships WHERE id=%s',(external,))
        assert not summary(c,root)['relationships_block_final'] and not summary(c,other)['relationships_block_final']


def test_hidden_relationship_endpoint_is_redacted_but_still_blocks_final(client):
    with db() as c:
        actor(c); root,child,leaf,record=unit(c); other,_,_,other_record=unit(c)
        link(c,'record',record,other_record)
        with c.transaction(force_rollback=True):
            c.execute("DELETE FROM profile_privileges WHERE profile_id=(SELECT profile_id FROM roles WHERE id=1) AND privilege_id=(SELECT id FROM privileges WHERE code='record.view')")
            page=relationship_page(c,root)
            assert len(page['items'])==1
            row=page['items'][0]
            assert row['redacted'] and row['relationship_id'] is None and row['source_id'] is None and row['target_id'] is None
            assert row['relationship_type_id'] is None and row['blocks_final']
            assert summary(c,root)['relationships_block_final']


def test_pending_protection_appears_and_resolves_without_membership_or_status_changes(client):
    with db() as c:
        actor(c); root,child,leaf,record=unit(c); evaluate(c,root); job=make_job(c); add(c,job,root)
        before_members=c.execute('SELECT * FROM disposition_job_memberships').fetchall()
        hold=make_hold(c,'record',record)
        assert summary(c,root)['blocks_admission'] and statuses(c,root)==[6]*4
        c.execute('DELETE FROM hold_record_assignments WHERE hold_id=%s',(hold,))
        assert not summary(c,root)['blocks_admission'] and statuses(c,root)==[6]*4
        assert c.execute('SELECT * FROM disposition_job_memberships').fetchall()==before_members
        assert c.execute("SELECT count(*) n FROM event_history WHERE entity_type='hold_record_assignment' AND entity_id IS NOT NULL").fetchone()['n']>=2


def test_bounded_worker_advances_cursor_reports_individual_failure_and_retries_safely(client):
    with db() as c:
        actor(c); bad,*_=unit(c); future,*_=unit(c,closed='2025-01-01'); good,*_=unit(c)
        # Model a pre-upgrade invalid policy; Phase 9 correctly rejects such
        # a new policy atomically before storage. This disposable-only fixture
        # suppresses only its new policy hooks to retain worker failure coverage.
        c.execute('SET CONSTRAINTS ALL IMMEDIATE')
        for name in ('disposition_recalculation_capture','disposition_recalculation_apply'):
            c.execute(f'ALTER TABLE aggregation_retention_rules DISABLE TRIGGER {name}')
        try:
            c.execute("INSERT INTO aggregation_retention_rules(aggregation_id,current_period_years,intermediate_period_years,final_disposition,justification) VALUES(%s,2000000000,0,'destruction','Deliberately unrepresentable legacy date')",(bad,))
        finally:
            for name in ('disposition_recalculation_capture','disposition_recalculation_apply'):
                c.execute(f'ALTER TABLE aggregation_retention_rules ENABLE TRIGGER {name}')
    first=run_pass(os.environ['DATABASE_URL'],batch_size=2)
    assert first['examined']==2 and len(first['failures'])==1 and first['failures'][0]['root_id']==bad
    assert first['next_after_id']==future and first['unchanged']==1
    second=run_pass(os.environ['DATABASE_URL'],batch_size=2,after_id=first['next_after_id'])
    assert second['changed']==1 and second['failures']==[] and second['next_after_id']==0
    with db() as c:
        actor(c); assert statuses(c,bad)==[1]*4 and statuses(c,good)==[2]*4
        c.execute('DELETE FROM aggregation_retention_rules WHERE aggregation_id=%s',(bad,))
        assert statuses(c,bad)==[2]*4
        repair=c.execute("SELECT metadata FROM event_history WHERE operation='DISPOSITION_RECALCULATED' AND entity_type='aggregation' AND entity_id=%s ORDER BY id DESC LIMIT 1",(bad,)).fetchone()['metadata']
        assert repair['old_evaluation']['calculation_error']=='unrepresentable_due_timestamp'
    third=run_pass(os.environ['DATABASE_URL'],batch_size=10)
    assert third['changed']==0 and third['failures']==[]
    with db() as c:
        assert c.execute("SELECT count(*) n FROM event_history WHERE operation='DISPOSITION_ELIGIBILITY_EVALUATED' AND entity_id=%s",(good,)).fetchone()['n']==1


def test_descendant_failure_rolls_back_one_unit_and_worker_continues(client):
    with db() as c:
        actor(c); bad,_,_,bad_record=unit(c); good,*_=unit(c)
        c.execute(f"""CREATE FUNCTION fail_eligibility_descendant() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.id={bad_record} AND NEW.disposition_status<>OLD.disposition_status THEN RAISE EXCEPTION 'disposable failure'; END IF; RETURN NEW; END $$""")
        c.execute('CREATE TRIGGER fail_eligibility_descendant BEFORE UPDATE ON records FOR EACH ROW EXECUTE FUNCTION fail_eligibility_descendant()')
    try:
        result=run_pass(os.environ['DATABASE_URL'])
        assert result['changed']==1 and result['failures']==[{'root_id':bad,'sqlstate':'P0001'}]
        with db() as c:
            assert statuses(c,bad)==[1]*4 and statuses(c,good)==[2]*4
            assert not c.execute("SELECT 1 FROM event_history WHERE operation='DISPOSITION_ELIGIBILITY_EVALUATED' AND entity_id=%s",(bad,)).fetchone()
    finally:
        with db() as c:
            c.execute('DROP TRIGGER fail_eligibility_descendant ON records'); c.execute('DROP FUNCTION fail_eligibility_descendant()')


def wait_for_waiter(connection,pid):
    import time
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        if connection.execute('SELECT 1 FROM pg_locks WHERE pid=%s AND NOT granted',(pid,)).fetchone(): return
        time.sleep(0.01)
    raise AssertionError('Concurrent worker did not reach its database lock')


@pytest.mark.parametrize('change',['rule','local_rule','reopen','reparent','close'])
def test_concurrent_policy_closure_and_hierarchy_changes_are_rechecked_after_lock(client,change):
    from queue import Queue
    with db() as c:
        actor(c); root,*_=unit(c,closed=None if change=='close' else '2020-01-01T00:00:00Z')
        other,*_=unit(c,closed=None)
    ready=Queue()
    def worker():
        with db() as c:
            ready.put(c.info.backend_pid)
            return evaluate(c,root)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with db() as mutation:
            actor(mutation)
            if change=='rule': rule(mutation,current=100)
            elif change=='local_rule': mutation.execute("INSERT INTO aggregation_retention_rules(aggregation_id,current_period_years,intermediate_period_years,final_disposition,justification) VALUES(%s,100,0,'destruction','Concurrent new policy')",(root,))
            elif change in ('reopen','reparent'):
                mutation.execute('UPDATE aggregations SET date_closed=NULL WHERE id=%s',(root,))
                if change=='reparent': mutation.execute('UPDATE aggregations SET parent_aggregation_id=%s,classification_id=NULL WHERE id=%s',(other,root))
            else: mutation.execute("UPDATE aggregations SET date_closed='2020-01-01' WHERE id=%s",(root,))
            future=executor.submit(worker)
            pid=ready.get(timeout=5)
            wait_for_waiter(mutation,pid)
            mutation.commit()
        result=future.result(timeout=10)
    assert result['changed'] is (change=='close')
    with db() as c: assert statuses(c,root)==([2]*4 if change=='close' else [1]*4)


@pytest.mark.parametrize('change',['vital','hold','security','relationship','membership'])
def test_locked_blocker_check_coordinates_current_protective_and_scope_changes(client,change):
    from backend.services.api.disposition.blockers import locked_summary
    with db() as c:
        actor(c); root,child,leaf,record=unit(c); other,other_child,_,other_record=unit(c)
        hold=make_hold(c,'record',other_record) if change=='hold' else None
        if change=='membership':
            evaluate(c,root);evaluate(c,other); job=make_job(c);add(c,job,root); member=add(c,job,other)
            link(c,'aggregation',child,other_child)
    def mutate():
        try:
            with db() as c:
                actor(c);c.execute("SET LOCAL lock_timeout='250ms'")
                if change=='vital':
                    c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)")
                    c.execute('UPDATE records SET is_vital=true WHERE id=%s',(record,))
                elif change=='hold': c.execute('INSERT INTO hold_record_assignments(hold_id,record_id) VALUES(%s,%s)',(hold,record))
                elif change=='security': c.execute('UPDATE security_levels SET prevents_disposition=true WHERE id=(SELECT security_level_id FROM records WHERE id=%s)',(record,))
                elif change=='relationship': link(c,'record',record,other_record)
                else: remove(c,member,other)
            return 'changed'
        except psycopg.errors.LockNotAvailable: return 'locked'
    with db() as reader:
        actor(reader);facts=locked_summary(reader,root)
        with ThreadPoolExecutor(max_workers=1) as executor: assert executor.submit(mutate).result(timeout=5)=='locked'
        assert summary(reader,root)==facts
    assert mutate()=='changed'
    with db() as c:
        actor(c);facts=summary(c,root)
        assert facts['blocks_final']
        if change=='security':
            # This canonical shared policy catalogue is not reset by API fixtures.
            c.execute('UPDATE security_levels SET prevents_disposition=false WHERE prevents_disposition')


def test_blocker_reads_require_current_governance_role_and_visible_root(client):
    with db() as c:
        actor(c); root,*_=unit(c)
        with c.transaction(force_rollback=True):
            c.execute('UPDATE roles SET is_information_governance=false WHERE id=1')
            with pytest.raises(HTTPException) as error: summary(c,root)
            assert error.value.status_code==403
        with c.transaction(force_rollback=True):
            c.execute("DELETE FROM profile_privileges WHERE profile_id=(SELECT profile_id FROM roles WHERE id=1) AND privilege_id=(SELECT id FROM privileges WHERE code='aggregation.view')")
            with pytest.raises(HTTPException) as error: summary(c,root)
            assert error.value.status_code==404


def test_hold_effective_time_boundaries_follow_existing_half_open_policy(client):
    with db() as c:
        actor(c); root,child,leaf,record=unit(c); hold=make_hold(c,'record',record)
        times=c.execute("UPDATE holds SET valid_from=CURRENT_TIMESTAMP,valid_to=CURRENT_TIMESTAMP+INTERVAL '1 day' WHERE id=%s RETURNING valid_from,valid_to",(hold,)).fetchone()
        assert c.execute('SELECT count(*) n FROM disposition_private.protection_blockers(%s,%s)',(root,times['valid_from']-timedelta(microseconds=1))).fetchone()['n']==0
        assert c.execute('SELECT count(*) n FROM disposition_private.protection_blockers(%s,%s)',(root,times['valid_from'])).fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM disposition_private.protection_blockers(%s,%s)',(root,times['valid_to'])).fetchone()['n']==0


def test_worker_interruption_before_commit_rolls_back_and_next_run_recovers(client):
    with db() as c: actor(c); root,*_=unit(c)
    with pytest.raises(RuntimeError,match='Interrupted'):
        with db() as c:
            assert evaluate(c,root)['changed']
            raise RuntimeError('Interrupted before committing the unit')
    with db() as c:
        assert statuses(c,root)==[1]*4
        assert not c.execute("SELECT 1 FROM event_history WHERE operation='DISPOSITION_ELIGIBILITY_EVALUATED' AND entity_id=%s",(root,)).fetchone()
        assert evaluate(c,root)['changed']


def test_inherited_classification_rule_provenance_is_captured(client):
    with db() as c:
        actor(c)
        parent=c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(1,'POLICY-PARENT','Inherited policy',false) RETURNING id").fetchone()['id']
        c.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES(%s,1,1,'destruction')",(parent,))
        c.execute('UPDATE classifications SET parent_classification_id=%s WHERE id=1',(parent,))
        c.execute('DELETE FROM classification_retention_rules WHERE classification_id=1')
        root,*_=unit(c)
        assert evaluate(c,root)['status']==2
        snapshot=c.execute("SELECT metadata->'rule_snapshot' s FROM event_history WHERE operation='DISPOSITION_ELIGIBILITY_EVALUATED' AND entity_id=%s",(root,)).fetchone()['s']
        assert snapshot['defined_by_classification_id']==parent and snapshot['inheritance_depth']==1
        assert snapshot['current_period_years']==1 and snapshot['intermediate_period_years']==1


def test_worker_supports_bigint_resource_versions_without_narrowing(client):
    with db() as c:
        actor(c);root,*_=unit(c,closed=None)
        c.execute('SET CONSTRAINTS ALL IMMEDIATE')
        c.execute('ALTER TABLE aggregations DISABLE TRIGGER aggregations_bump_version')
        try: c.execute('UPDATE aggregations SET version=3000000000 WHERE id=%s',(root,))
        finally:
            c.execute('SET CONSTRAINTS ALL IMMEDIATE')
            c.execute('ALTER TABLE aggregations ENABLE TRIGGER aggregations_bump_version')
            c.execute('SET CONSTRAINTS ALL DEFERRED')
        c.execute("UPDATE aggregations SET date_closed='2020-01-01' WHERE id=%s",(root,))
        assert evaluate(c,root)['changed']
        assert c.execute('SELECT version FROM aggregations WHERE id=%s',(root,)).fetchone()['version']==3000000002


def test_scheduled_pass_records_utc_instants(client):
    with db() as c: actor(c);root,*_=unit(c,closed='2020-02-29T23:30:00Z')
    assert run_pass(os.environ['DATABASE_URL'])['changed']==1
    with db() as c:
        metadata=c.execute("SELECT metadata FROM event_history WHERE operation='DISPOSITION_ELIGIBILITY_EVALUATED' AND entity_id=%s",(root,)).fetchone()['metadata']
        assert metadata['date_closed']=='2020-02-29T23:30:00+00:00'
        assert metadata['calculated_disposition_at']=='2025-02-28T23:30:00+00:00'
        assert metadata['database_now'].endswith('+00:00')


def test_many_holds_remain_blocking_with_a_bounded_metadata_preview(client):
    with db() as c:
        actor(c);root,child,leaf,record=unit(c)
        for _ in range(30): make_hold(c,'record',record)
        page=protection_page(c,root)
        assert len(page['items'])==1
        row=page['items'][0]
        assert row['legal_hold'] and row['holds_has_more'] and len(row['holds'])==25
        assert summary(c,root)['blocks_final']
        assert len(c.execute('SELECT hold_ids FROM disposition_private.protection_blockers(%s)',(root,)).fetchone()['hold_ids'])==26
