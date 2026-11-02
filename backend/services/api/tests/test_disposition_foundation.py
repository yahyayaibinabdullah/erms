"""Phase 7 acceptance, restricted by conftest to disposable databases.

Trusted callbacks exercise private transaction primitives. No operational action
endpoint is exposed until its action-specific gates are implemented.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from backend.services.api.disposition.commands import execute_command, lock_job, StaleVersion, transition_unit, claim_task

ROOT = Path(__file__).resolve().parents[4]


from tools.historical_schema import historical_schema


def db():
    return psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row)


def actor(c, user=1, actor_type='user'):
    c.execute("SELECT set_config('app.user_id',%s,true),set_config('app.actor_type',%s,true),set_config('app.event_source','api',true)", (str(user),actor_type))


def command(c, operation, apply, *, key=None, payload=None, role=1, reason='Verify common disposition transaction'):
    return execute_command(c, command_id=key or uuid4(), operation=operation,
                           payload=payload or {}, acting_role_id=role, reason=reason, apply=apply)


def version(c, root):
    return c.execute('SELECT version FROM aggregations WHERE id=%s',(root,)).fetchone()['version']


def ensure_officer(c, user=1):
    role=c.execute("SELECT id FROM roles WHERE code='fixture-records-officer'").fetchone()
    if role is None:
        role=c.execute("INSERT INTO roles(org_unit_id,code,name,is_information_governance,profile_id) SELECT 1,'fixture-records-officer','Records Officer',true,id FROM profiles WHERE code='INFO_GOV_OFFICER' RETURNING id").fetchone()
    c.execute('INSERT INTO user_role_assignments(user_id,role_id) SELECT %s,%s WHERE NOT EXISTS(SELECT 1 FROM user_role_assignments WHERE user_id=%s AND role_id=%s)',(user,role['id'],user,role['id']))


def make_job(c, number=None, *, assigned=1, kind='destruction'):
    if kind=='destruction': ensure_officer(c)
    def apply(c):
        row=c.execute("""INSERT INTO disposition_jobs(job_number,job_type,workflow_stage,disposition_status,owning_org_unit_id,assigned_user_id,created_by_user_id)
         VALUES(%s,%s,%s,%s,1,%s,1) RETURNING id""",
         (number or str(uuid4()),kind,'officer_preparation' if kind=='destruction' else None,
          {'destruction':6,'permanent_transfer':7,'selective_transfer':8,'local_archives':9}[kind],assigned)).fetchone()
        return {'id':row['id']}
    return command(c,'job_create',apply)['id']


def prepare_unit(c, *, status=2):
    root=c.execute("INSERT INTO aggregations(aggregation_number,title,classification_id,owning_org_unit_id) VALUES(%s,'Root',1,1) RETURNING id",(str(uuid4()),)).fetchone()['id']
    child=c.execute("INSERT INTO aggregations(parent_aggregation_id,aggregation_number,title) VALUES(%s,%s,'Child') RETURNING id",(root,str(uuid4()))).fetchone()['id']
    leaf=c.execute("INSERT INTO aggregations(parent_aggregation_id,aggregation_number,title) VALUES(%s,%s,'Leaf') RETURNING id",(child,str(uuid4()))).fetchone()['id']
    record=c.execute("INSERT INTO records(aggregation_id,record_number,title) VALUES(%s,%s,'Record') RETURNING id",(leaf,str(uuid4()))).fetchone()['id']
    c.execute('UPDATE aggregations SET date_closed=CURRENT_TIMESTAMP WHERE id=%s',(root,))
    command(c,'eligibility_evaluate',lambda c: (transition_unit(c,root,version(c,root),status) or {}))
    return root,child,leaf,record


def add(c,job,root):
    def apply(c):
        lock_job(c,job,c.execute('SELECT version FROM disposition_jobs WHERE id=%s',(job,)).fetchone()['version'])
        member=c.execute('INSERT INTO disposition_job_memberships(job_id,root_aggregation_id,added_by_user_id) VALUES(%s,%s,1) RETURNING id',(job,root)).fetchone()['id']
        target=c.execute('SELECT disposition_status FROM disposition_jobs WHERE id=%s',(job,)).fetchone()['disposition_status']
        transition_unit(c,root,version(c,root),target)
        return {'id':member}
    return command(c,'membership_add',apply)['id']


def remove(c,member,root):
    def apply(c):
        transition_unit(c,root,version(c,root),2)
        c.execute("UPDATE disposition_job_memberships SET membership_state='removed',removal_reason='Preparation correction' WHERE id=%s",(member,))
        return {}
    return command(c,'membership_remove',apply)


def states(c):
    return [r['disposition_status'] for r in c.execute('SELECT disposition_status FROM aggregations UNION ALL SELECT disposition_status FROM records').fetchall()]


def test_status_defaults_and_ordinary_crud_cannot_write_outcomes(client, aggregation, record):
    for resource,row in [('aggregations',aggregation),('records',record)]:
        saved=client.get(f'/api/v1/{resource}/{row["id"]}')
        assert saved.status_code==200 and saved.json()['disposition_status']==1
        for field,value in [('disposition_status',6),('final_disposition_at','2026-10-15T00:00:00Z'),('disposition_job_id',1),('destruction_number','external!*')]:
            response=client.patch(f'/api/v1/{resource}/{row["id"]}',headers={'If-Match':str(row['version'])},json={field:value})
            assert response.status_code==422, response.text
    assert client.post('/api/v1/disposition_jobs',json={}).status_code in (404,405)


@pytest.mark.parametrize('target',[0,2,6,10,13,14])
def test_direct_sql_and_forged_guc_cannot_change_status(client,aggregation,target):
    with db() as c:
        actor(c)
        c.execute("SELECT set_config('app.disposition_authorized','authorized',true),set_config('app.change_reason','Forged flag',true)")
        with pytest.raises(psycopg.Error,match='disposition_protected_operation_required'):
            with c.transaction(): c.execute('UPDATE aggregations SET disposition_status=%s WHERE id=%s',(target,aggregation['id']))
        assert states(c)==[1]


def test_authorized_full_unit_transition_and_pending_membership_are_atomic(client):
    with db() as c:
        actor(c); root,*_=prepare_unit(c)
        assert states(c)==[2]*4
        job=make_job(c); member=add(c,job,root)
        assert states(c)==[6]*4
        remove(c,member,root)
        assert states(c)==[2]*4
        again=add(c,job,root)
        assert again!=member
        assert [x['membership_state'] for x in c.execute('SELECT membership_state FROM disposition_job_memberships ORDER BY id')]==['removed','active']


@pytest.mark.parametrize('mode',['status_only','membership_only','partial_unit','wrong_type','unassigned','child_root'])
def test_invalid_membership_or_partial_propagation_rolls_back_everything(client,mode):
    with db() as c:
        actor(c); root,child,*_=prepare_unit(c)
        job=make_job(c,assigned=None if mode=='unassigned' else 1,kind='permanent_transfer' if mode=='wrong_type' else 'destruction')
        events=c.execute('SELECT count(*) n FROM event_history').fetchone()['n']
        def invalid(c):
            if mode=='status_only': transition_unit(c,root,version(c,root),6)
            elif mode=='partial_unit': c.execute('UPDATE aggregations SET disposition_status=6 WHERE id=%s',(root,))
            else:
                c.execute('INSERT INTO disposition_job_memberships(job_id,root_aggregation_id,added_by_user_id) VALUES(%s,%s,1)',(job,child if mode=='child_root' else root))
                if mode!='membership_only': transition_unit(c,root,version(c,root),6)
            return {}
        with pytest.raises(psycopg.Error): command(c,'membership_add',invalid)
        assert states(c)==[2]*4
        assert c.execute('SELECT count(*) n FROM disposition_job_memberships').fetchone()['n']==0
        assert c.execute('SELECT count(*) n FROM event_history').fetchone()['n']==events


def test_injected_descendant_failure_rolls_back_membership_events_and_receipt(client):
    with db() as c:
        actor(c); root,*_=prepare_unit(c); job=make_job(c)
        c.execute("""CREATE FUNCTION disposition_test_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected descendant failure'; END $$""")
        c.execute('CREATE TRIGGER disposition_test_failure BEFORE UPDATE ON records FOR EACH ROW EXECUTE FUNCTION disposition_test_failure()')
        try:
            before=c.execute('SELECT count(*) n FROM disposition_private.command_receipts').fetchone()['n']
            with pytest.raises(psycopg.Error,match='injected descendant failure'): add(c,job,root)
            assert states(c)==[2]*4
            assert c.execute('SELECT count(*) n FROM disposition_job_memberships').fetchone()['n']==0
            assert c.execute('SELECT count(*) n FROM disposition_private.command_receipts').fetchone()['n']==before
        finally:
            c.execute('DROP TRIGGER disposition_test_failure ON records'); c.execute('DROP FUNCTION disposition_test_failure()')


def test_retry_returns_result_once_and_rejects_changed_intent(client):
    key=uuid4(); calls=[]
    with db() as c:
        actor(c)
        def apply(c): calls.append(1); return {'permanent':'result'}
        assert command(c,'job_assign',apply,key=key)=={'permanent':'result'}
    with db() as c:
        actor(c)
        assert command(c,'job_assign',apply,key=key)=={'permanent':'result'}
        assert calls==[1]
        with pytest.raises(psycopg.Error,match='disposition_command_conflict'): command(c,'job_assign',apply,key=key,payload={'changed':True})
        with pytest.raises(psycopg.Error,match='disposition_command_history_immutable'):
            with c.transaction(): c.execute('DELETE FROM disposition_private.command_receipts WHERE command_id=%s',(key,))


@pytest.mark.parametrize('change',['non_governance','inactive','actor_type','missing_privilege','expired'])
def test_commands_require_current_human_governance_privilege(client,change):
    with db() as c, c.transaction(force_rollback=True):
        actor(c,actor_type='automated_process' if change=='actor_type' else 'user')
        if change=='non_governance': c.execute('UPDATE roles SET is_information_governance=false WHERE id=1')
        elif change=='inactive': c.execute("UPDATE users SET date_deactivated=CURRENT_TIMESTAMP WHERE id=1")
        elif change=='missing_privilege': c.execute("DELETE FROM profile_privileges WHERE privilege_id=(SELECT id FROM privileges WHERE code='disposition.jobs.manage')")
        elif change=='expired': c.execute("UPDATE user_role_assignments SET valid_until=CURRENT_TIMESTAMP WHERE user_id=1")
        with pytest.raises(psycopg.Error,match='disposition_authorization_required'): command(c,'job_assign',lambda c:{})
        assert c.execute('SELECT count(*) n FROM disposition_private.command_receipts').fetchone()['n']==0


def test_stale_versions_and_final_execution_remain_closed(client):
    with db() as c:
        actor(c); root,*_=prepare_unit(c); job=make_job(c); add(c,job,root)
        with pytest.raises(psycopg.Error,match='disposition_stale_version'):
            command(c,'membership_remove',lambda c: (transition_unit(c,root,1,2) or {}))
        with pytest.raises(StaleVersion): command(c,'job_assign',lambda c: (lock_job(c,job,99) or {}))
        with pytest.raises(psycopg.Error,match='disposition_action_not_implemented'):
            command(c,'final_complete',lambda c: (transition_unit(c,root,version(c,root),10) or {}))
        assert states(c)==[6]*4


def test_termination_preserves_episodes_and_disallows_reactivation(client):
    with db() as c:
        actor(c); root,*_=prepare_unit(c); job=make_job(c); member=add(c,job,root)
        def terminate(c):
            transition_unit(c,root,version(c,root),2)
            c.execute("UPDATE disposition_job_memberships SET membership_state='terminated_history' WHERE id=%s",(member,))
            c.execute("UPDATE disposition_jobs SET lifecycle_state='terminated',termination_reason='Cancelled before execution' WHERE id=%s",(job,))
            return {}
        command(c,'job_terminate',terminate)
        assert states(c)==[2]*4
        assert c.execute('SELECT terminated_by_user_id FROM disposition_jobs WHERE id=%s',(job,)).fetchone()['terminated_by_user_id']==1
        with pytest.raises(psycopg.Error,match='disposition_history_immutable'):
            command(c,'job_assign',lambda c: (c.execute("UPDATE disposition_jobs SET lifecycle_state='active' WHERE id=%s",(job,)) and {}))
        other=make_job(c); add(c,other,root)
        assert c.execute('SELECT count(*) n FROM disposition_job_memberships').fetchone()['n']==2


def test_simultaneous_membership_admission_only_one_wins(client):
    with db() as c:
        actor(c); root,*_=prepare_unit(c); jobs=[make_job(c),make_job(c)]
    def admit(job):
        try:
            with db() as c: actor(c); add(c,job,root)
            return 'ok'
        except psycopg.Error: return 'rejected'
    with ThreadPoolExecutor(max_workers=2) as executor: results=list(executor.map(admit,jobs))
    assert sorted(results)==['ok','rejected']
    with db() as c:
        assert states(c)==[6]*4
        assert c.execute("SELECT count(*) n FROM disposition_job_memberships WHERE membership_state='active'").fetchone()['n']==1


def test_completed_jobs_require_consistent_fields_and_unimplemented_actions_fail_closed(client):
    with db() as c:
        actor(c); job=make_job(c)
        def complete(c): c.execute("UPDATE disposition_jobs SET lifecycle_state='completed',disposition_status=10 WHERE id=%s",(job,)); return {}
        with pytest.raises(psycopg.Error): command(c,'final_complete',complete)
        assert c.execute('SELECT lifecycle_state FROM disposition_jobs').fetchone()['lifecycle_state']=='active'


def test_historical_foundation_fixture_matches_independent_migration(client):
    migration=(ROOT/'database/migrations/053_disposition_foundation.sql').read_text()
    canonical=historical_schema()
    assert canonical.split('-- Common disposition foundation (053).\n',1)[1].split('-- Disposition eligibility and current blockers (054).',1)[0].strip()==migration.strip()
    assert '\\i' not in migration
    assert 'UPDATE event_history' not in migration and 'DELETE FROM event_history' not in migration


def make_task(c, job, *, role=1, user=None):
    def apply(c):
        stage='officer_preparation';kind='preparation'
        if role is not None:
            # Phase 13 prepares by direct assignment; queues belong to actual
            # configured review stages, rather than synthetic preparation queues.
            c.execute('UPDATE org_units SET file_administrator_role_id=%s WHERE id=1',(role,))
            c.execute("UPDATE disposition_tasks SET task_state='cancelled' WHERE job_id=%s AND task_state IN ('open','claimed')",(job,))
            c.execute("UPDATE disposition_jobs SET workflow_stage='file_administrator_review' WHERE id=%s",(job,))
            stage=kind='file_administrator_review'
        return dict(c.execute("""INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,destination_role_id,destination_user_id)
         VALUES(%s,%s,%s,%s,%s) RETURNING id""",(job,kind,stage,role,user)).fetchone())
    return command(c,'review_submit' if role is not None else 'job_create',apply)['id']


def claim(c, task, expected=1):
    def apply(c):
        claim_task(c,task,expected)
        return {'task':task}
    return command(c,'task_claim',apply)


def test_shared_task_claim_release_completion_and_immutable_history(client):
    with db() as c:
        actor(c); job=make_job(c); task=make_task(c,job)
        claim(c,task)
        before=c.execute('SELECT * FROM disposition_tasks WHERE id=%s',(task,)).fetchone()
        assert before['version']==2 and before['claimed_at'] is not None
        def release(c):
            c.execute("UPDATE disposition_tasks SET task_state='open' WHERE id=%s",(task,)); return {}
        command(c,'task_release',release)
        released=c.execute('SELECT * FROM disposition_tasks WHERE id=%s',(task,)).fetchone()
        assert released['claimed_by_user_id'] is None and released['released_by_user_id']==1
        claim(c,task,3)
        def complete(c): c.execute("UPDATE disposition_tasks SET task_state='completed' WHERE id=%s",(task,)); return {}
        command(c,'task_complete',complete)
        assert c.execute('SELECT completed_by_user_id FROM disposition_tasks WHERE id=%s',(task,)).fetchone()['completed_by_user_id']==1
        with pytest.raises(psycopg.Error,match='disposition_history_immutable'): command(c,'task_reassign',lambda c:(c.execute('UPDATE disposition_tasks SET priority=9 WHERE id=%s',(task,)) and {}))
        events=c.execute("SELECT metadata FROM event_history WHERE entity_type='disposition_task' AND entity_id=%s ORDER BY id",(task,)).fetchall()
        assert len(events)==5
        assert events[1]['metadata']['after']['task_state']=='claimed'
        assert events[2]['metadata']['before']['task_state']=='claimed'


def test_simultaneous_task_claims_only_one_wins(client):
    with db() as c:
        actor(c); job=make_job(c); task=make_task(c,job)
    def attempt(_):
        try:
            with db() as c: actor(c); claim(c,task)
            return 'ok'
        except psycopg.errors.SerializationFailure: return 'stale'
    with ThreadPoolExecutor(max_workers=2) as executor: results=list(executor.map(attempt,range(2)))
    assert sorted(results)==['ok','stale']


@pytest.mark.parametrize('destination', ['neither','both'])
def test_task_requires_exactly_one_destination(client,destination):
    with db() as c:
        actor(c); job=make_job(c)
        with pytest.raises(psycopg.Error): make_task(c,job,role=1 if destination=='both' else None,user=1 if destination=='both' else None)
        assert c.execute('SELECT count(*) n FROM disposition_tasks').fetchone()['n']==1


def test_round_snapshot_is_ordered_immutable_and_cannot_be_forged(client):
    with db() as c:
        actor(c); root,*_=prepare_unit(c); job=make_job(c); add(c,job,root)
        snapshot=c.execute('SELECT disposition_private.membership_snapshot(%s) s',(job,)).fetchone()['s']
        assert len(snapshot)==1 and len(snapshot[0]['aggregations'])==3 and len(snapshot[0]['records'])==1
        def start(c):
            return dict(c.execute('''INSERT INTO disposition_review_rounds(job_id,round_number,started_by_user_id,membership_snapshot)
             VALUES(%s,1,1,%s) RETURNING id''',(job,Jsonb(snapshot))).fetchone())
        round_id=command(c,'review_submit',start)['id']
        with pytest.raises(psycopg.Error,match='disposition_review_snapshot_immutable'):
            command(c,'review_decide',lambda c:(c.execute("UPDATE disposition_review_rounds SET membership_snapshot='[]' WHERE id=%s",(round_id,)) and {}))
        def forged(c):
            c.execute("INSERT INTO disposition_review_rounds(job_id,round_number,started_by_user_id,membership_snapshot) VALUES(%s,2,1,'[]')",(job,)); return {}
        with pytest.raises(psycopg.Error,match='disposition_review_snapshot_mismatch'): command(c,'review_submit',forged)
        def skipped(c):
            c.execute('INSERT INTO disposition_review_rounds(job_id,round_number,started_by_user_id,membership_snapshot) VALUES(%s,3,1,%s)',(job,Jsonb(snapshot))); return {}
        with pytest.raises(psycopg.Error,match='disposition_round_out_of_order'): command(c,'review_submit',skipped)
        assert c.execute('SELECT count(*) n FROM disposition_review_rounds').fetchone()['n']==1


def test_document_failure_retry_and_available_link_immutability(client,record):
    from io import BytesIO
    from fastapi import UploadFile
    from backend.services.api.content_storage import configured_storage,inspect_upload
    from backend.services.api.application_settings import load_snapshot
    from backend.services.api.tests.test_disposition_artifacts import configure
    with db() as c:
        actor(c); job=make_job(c);configure(c)
        upload=UploadFile(BytesIO(b'proof'),filename='proof.pdf')
        settings=load_snapshot(c);inspected=inspect_upload(upload,settings)
        checksum=inspected.checksum_value
        component=c.execute("""INSERT INTO digital_components(record_id,component_order,file_name,mime_type,size_in_bytes,checksum_algo,checksum_value,content_status)
         VALUES(%s,1,'proof.pdf','application/pdf',5,'sha256',%s,'available') RETURNING id""",(record['id'],checksum)).fetchone()['id']
        configured_storage().store_upload(c,component,upload,settings=settings)
        def create(c):
            return dict(c.execute("INSERT INTO disposition_job_documents(job_id,document_type,document_state,created_by_user_id,template_version,origin,acting_role_id) VALUES(%s,'destruction_request','generating',1,'v1','generated',1) RETURNING id",(job,)).fetchone())
        document=command(c,'document_save',create)['id']
        for state in ['failed','generating','available']:
            def update(c):
                c.execute('UPDATE disposition_job_documents SET document_state=%s,record_id=%s,digital_component_id=%s,checksum_algo=%s,checksum=%s,classification_scheme_id=1,classification_id=1,aggregation_id=%s WHERE id=%s',(state,record['id'],component,'sha256',checksum,record['aggregation_id'],document)); return {}
            command(c,'document_save',update)
        with pytest.raises(psycopg.Error,match='disposition_history_immutable'):
            command(c,'document_save',lambda c:(c.execute("UPDATE disposition_job_documents SET checksum='replacement' WHERE id=%s",(document,)) and {}))
        assert c.execute('SELECT count(*) n FROM disposition_job_documents').fetchone()['n']==1


@pytest.mark.parametrize('table',['disposition_jobs','disposition_job_memberships','disposition_tasks','disposition_review_rounds','disposition_review_decisions','disposition_job_documents'])
def test_workflow_tables_reject_direct_sql_delete_even_with_forged_flag(client,table):
    with db() as c:
        actor(c); job=make_job(c)
        # A direct row mutation must never be authorized by a GUC. For tables
        # without a row yet, inspect the installed before-delete guard too.
        assert c.execute("SELECT 1 FROM pg_trigger WHERE tgrelid=%s::regclass AND tgname='disposition_guard' AND NOT tgisinternal",(table,)).fetchone()
        if table=='disposition_jobs':
            with pytest.raises(psycopg.Error,match='disposition_protected_operation_required'):
                with c.transaction(): c.execute('DELETE FROM disposition_jobs WHERE id=%s',(job,))


def test_unfinished_command_cannot_commit_and_private_helpers_are_not_public(client):
    with db() as c:
        actor(c)
        with pytest.raises(psycopg.Error,match='disposition_command_not_finished'):
            with c.transaction():
                c.execute("SELECT disposition_private.begin_command(%s,'job_assign','{}',1,'Unfinished command')",(uuid4(),))
                c.execute('SET CONSTRAINTS ALL IMMEDIATE')
        assert c.execute('SELECT count(*) n FROM disposition_private.command_receipts').fetchone()['n']==0
        assert not c.execute("SELECT 1 FROM pg_namespace n,LATERAL aclexplode(n.nspacl) a WHERE n.nspname='disposition_private' AND a.grantee=0").fetchone()
        assert not c.execute("SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace,LATERAL aclexplode(p.proacl) a WHERE n.nspname='disposition_private' AND a.grantee=0").fetchone()


@pytest.mark.parametrize('table,statement',[
 ('jobs',"INSERT INTO disposition_jobs(job_number,job_type,workflow_stage,disposition_status,owning_org_unit_id,created_by_user_id) VALUES('bypass','destruction','officer_preparation',6,1,1)"),
 ('memberships',"INSERT INTO disposition_job_memberships(job_id,root_aggregation_id,added_by_user_id) VALUES(%s,%s,1)"),
 ('tasks',"INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,destination_user_id) VALUES(%s,'preparation','officer_preparation',1)"),
 ('rounds',"INSERT INTO disposition_review_rounds(job_id,round_number,started_by_user_id,membership_snapshot) VALUES(%s,1,1,'[]')"),
 ('decisions',"INSERT INTO disposition_review_decisions(job_id,round_id,review_stage,decision,task_id,actor_user_id,acting_role_id,reason,membership_snapshot) VALUES(%s,999,'records_manager_review','approved',999,1,1,'Bypass','[]')"),
 ('documents',"INSERT INTO disposition_job_documents(job_id,document_type,document_state,created_by_user_id) VALUES(%s,'destruction_request','generating',1)")])
def test_all_shared_tables_deny_direct_insert_without_private_command(client,table,statement):
    with db() as c:
        actor(c); root,*_=prepare_unit(c); job=make_job(c)
        params=(job,root) if table=='memberships' else (() if table=='jobs' else (job,))
        with pytest.raises(psycopg.Error,match='disposition_protected_operation_required'):
            with c.transaction(): c.execute(statement,params)


@pytest.mark.parametrize('number,valid',[('AUTH / رقم-١ !#',True),('x'*20,True),('x'*21,False),('',False)])
def test_external_numbers_preserve_characters_length_and_uniqueness(client,number,valid):
    with db() as c:
        actor(c); job=make_job(c)
        def set_number(c,identity=job):
            # Constraint fixture only, in this runner-owned database. Phase 17
            # now requires private external scope even for a number-only update;
            # real evidence/authority gates are tested by test_disposition_external.
            c.execute("INSERT INTO disposition_private.external_context SELECT transaction_id,backend_id,command_id,%s,'decision' FROM disposition_private.command_context WHERE transaction_id=txid_current()",(identity,))
            c.execute('UPDATE disposition_jobs SET destruction_number=%s WHERE id=%s',(number,identity))
            c.execute('DELETE FROM disposition_private.external_context WHERE transaction_id=txid_current()')
            return {}
        if valid:
            command(c,'job_assign',set_number)
            assert c.execute('SELECT destruction_number FROM disposition_jobs WHERE id=%s',(job,)).fetchone()['destruction_number']==number
            other=make_job(c)
            with pytest.raises(psycopg.errors.UniqueViolation):
                command(c,'job_assign',lambda x:set_number(x,other))
        else:
            with pytest.raises(psycopg.errors.CheckViolation): command(c,'job_assign',set_number)



def test_round_decisions_keep_actor_role_snapshot_and_are_immutable(client):
    with db() as c:
        actor(c); root,*_=prepare_unit(c); job=make_job(c); add(c,job,root)
        snapshot=c.execute('SELECT disposition_private.membership_snapshot(%s) s',(job,)).fetchone()['s']
        c.execute('UPDATE org_units SET managing_role_id=1 WHERE id=1')
        def submit(c):
            c.execute("UPDATE disposition_tasks SET task_state='cancelled' WHERE job_id=%s",(job,))
            c.execute("UPDATE disposition_jobs SET workflow_stage='unit_manager_review' WHERE id=%s",(job,))
            round_id=c.execute('INSERT INTO disposition_review_rounds(job_id,round_number,started_by_user_id,membership_snapshot) VALUES(%s,1,1,%s) RETURNING id',(job,Jsonb(snapshot))).fetchone()['id']
            task_id=c.execute("INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,destination_role_id,review_round) VALUES(%s,'unit_manager_review','unit_manager_review',1,1) RETURNING id",(job,)).fetchone()['id']
            return {'round':round_id,'task':task_id}
        review=command(c,'review_submit',submit)
        claim(c,review['task'])
        def decide(c):
            decision=c.execute("""INSERT INTO disposition_review_decisions(job_id,round_id,review_stage,decision,task_id,actor_user_id,acting_role_id,reason,membership_snapshot)
             VALUES(%s,%s,'unit_manager_review','approved',%s,1,1,'Overall approval',%s) RETURNING id""",(job,review['round'],review['task'],Jsonb(snapshot))).fetchone()['id']
            c.execute("UPDATE disposition_tasks SET task_state='completed' WHERE id=%s",(review['task'],))
            c.execute('UPDATE disposition_review_rounds SET completed_at=CURRENT_TIMESTAMP WHERE id=%s',(review['round'],))
            return {'id':decision}
        decision=command(c,'review_decide',decide)['id']
        with pytest.raises(psycopg.Error,match='disposition_history_immutable'):
            command(c,'review_decide',lambda c:(c.execute("UPDATE disposition_review_decisions SET decision='rejected' WHERE id=%s",(decision,)) and {}))
        saved=c.execute('SELECT * FROM disposition_review_decisions WHERE id=%s',(decision,)).fetchone()
        assert saved['membership_snapshot']==snapshot and saved['actor_user_id']==1 and saved['acting_role_id']==1


def test_illegal_stage_skip_and_premature_resource_final_fields_roll_back(client):
    with db() as c:
        actor(c); root,*_=prepare_unit(c); job=make_job(c)
        with pytest.raises(psycopg.Error,match='disposition_invalid_stage_transition'):
            command(c,'review_submit',lambda c:(c.execute("UPDATE disposition_jobs SET workflow_stage='digital_destruction' WHERE id=%s",(job,)) and {}))
        with pytest.raises(psycopg.Error,match='disposition_premature_final_fields'):
            command(c,'eligibility_evaluate',lambda c:(c.execute('UPDATE aggregations SET final_disposition_at=CURRENT_TIMESTAMP WHERE id IN (SELECT disposition_private.unit_ids(%s))',(root,)) and c.execute('UPDATE records SET final_disposition_at=CURRENT_TIMESTAMP') and {}))
        assert states(c)==[2]*4


@pytest.mark.parametrize('kind,status,pending', [('destruction',2,6),('permanent_transfer',3,7),('selective_transfer',4,8),('local_archives',5,9)])
def test_all_four_job_types_require_matching_pending_membership(client,kind,status,pending):
    with db() as c:
        actor(c); root,*_=prepare_unit(c,status=status); job=make_job(c,kind=kind); add(c,job,root)
        assert states(c)==[pending]*4


def test_assignment_is_specific_and_cannot_be_cleared_while_nonempty(client):
    with db() as c:
        actor(c); job=make_job(c,assigned=None); root,*_=prepare_unit(c)
        def assign(c): c.execute('UPDATE disposition_jobs SET assigned_user_id=1 WHERE id=%s',(job,)); return {}
        command(c,'job_assign',assign); add(c,job,root)
        with pytest.raises(psycopg.Error,match='disposition_active_membership_invalid'):
            command(c,'job_assign',lambda c:(c.execute('UPDATE disposition_jobs SET assigned_user_id=NULL WHERE id=%s',(job,)) and {}))
        assert c.execute('SELECT assigned_user_id FROM disposition_jobs WHERE id=%s',(job,)).fetchone()['assigned_user_id']==1


def test_system_admin_and_service_accounts_have_no_implicit_authority(client):
    with db() as c:
        assert not c.execute("SELECT 1 FROM profile_privileges pp JOIN profiles p ON p.id=pp.profile_id JOIN privileges v ON v.id=pp.privilege_id WHERE p.code='SYS_ADMIN' AND v.code='disposition.jobs.manage'").fetchone()
        service=c.execute("INSERT INTO users(name,email,account_type) VALUES('Indexer fixture','indexer@fixture.invalid','service') RETURNING id").fetchone()['id']
        role=c.execute("SELECT id FROM roles WHERE code='text-indexer-service'").fetchone()['id']
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(service,role))
        actor(c,user=service)
        with pytest.raises(psycopg.Error,match='disposition_authorization_required'):
            command(c,'job_create',lambda c:{},role=role)


def test_assignee_does_not_grant_root_access(client):
    with db() as c:
        actor(c); root,*_=prepare_unit(c); job=make_job(c)
        # This removes only the acting user's view privilege; assignment and
        # disposition authority remain in place, so no resource access is added.
        with c.transaction(force_rollback=True):
            c.execute("DELETE FROM profile_privileges WHERE profile_id IN (SELECT profile_id FROM roles WHERE id IN (SELECT role_id FROM user_role_assignments WHERE user_id=1)) AND privilege_id=(SELECT id FROM privileges WHERE code='aggregation.view')")
            with pytest.raises(psycopg.Error,match='disposition_resource_access_required'): add(c,job,root)
            assert states(c)==[2]*4


def test_descendant_read_and_search_projection_expose_stored_status(client):
    with db() as c:
        actor(c); root,child,leaf,record=prepare_unit(c)
    for resource,ids in [('aggregations',[root,child,leaf]),('records',[record])]:
        for entity_id in ids:
            response=client.get(f'/api/v1/{resource}/{entity_id}')
            assert response.status_code==200 and response.json()['disposition_status']==2
    with db() as c:
        actor(c)
        assert [r['disposition_status'] for r in c.execute('SELECT disposition_status FROM authorized_aggregations_for_search UNION ALL SELECT disposition_status FROM authorized_records_for_search')]==[2]*4


def test_stable_status_catalogue_does_not_depend_on_language(client):
    from backend.services.api.disposition.model import DispositionStatus, JobType, LifecycleState
    assert [int(s) for s in DispositionStatus]==list(range(1,14))
    assert DispositionStatus.partially_disposed_action_required==13
    assert set(JobType)=={'destruction','permanent_transfer','selective_transfer','local_archives'}
    assert set(LifecycleState)=={'active','completed','terminated'}


def test_reassignment_preserves_task_events_and_clears_claim(client):
    with db() as c:
        actor(c); job=make_job(c); task=make_task(c,job); claim(c,task)
        def reassign(c):
            c.execute("UPDATE disposition_tasks SET task_state='open' WHERE id=%s",(task,)); return {}
        command(c,'task_reassign',reassign)
        current=c.execute('SELECT * FROM disposition_tasks WHERE id=%s',(task,)).fetchone()
        assert current['destination_role_id']==1 and current['claimed_by_user_id'] is None
        assert current['reassigned_by_user_id']==1 and current['reassigned_at'] is not None
        events=c.execute("SELECT metadata FROM event_history WHERE entity_type='disposition_task' AND entity_id=%s ORDER BY id",(task,)).fetchall()
        assert events[-1]['metadata']['before']['destination_role_id']==1
        assert events[-1]['metadata']['after']['destination_role_id']==1


def test_retry_rechecks_authority_after_privilege_loss(client):
    with db() as c:
        actor(c); key=uuid4(); command(c,'job_assign',lambda c:{'saved':True},key=key)
        with c.transaction(force_rollback=True):
            c.execute('UPDATE roles SET is_information_governance=false WHERE id=1')
            with pytest.raises(psycopg.Error,match='disposition_authorization_required'):
                command(c,'job_assign',lambda c:{'saved':True},key=key)


def test_same_retry_key_is_deduplicated_across_simultaneous_connections(client):
    key=uuid4()
    with db() as c: actor(c); job=make_job(c)
    def apply_once(_):
        with db() as c:
            actor(c)
            def apply(c): return {'event_id':c.execute("SELECT append_domain_event('disposition_job',%s,'DISPOSITION_RETRY_PROBE') id",(job,)).fetchone()['id']}
            return command(c,'job_assign',apply,key=key)
    with ThreadPoolExecutor(max_workers=2) as executor: results=list(executor.map(apply_once,range(2)))
    assert results[0]==results[1]
    with db() as c: assert c.execute("SELECT count(*) n FROM event_history WHERE operation='DISPOSITION_RETRY_PROBE'").fetchone()['n']==1


def test_two_distinct_eligible_people_cannot_both_claim_role_task(client):
    with db() as c:
        actor(c); job=make_job(c); task=make_task(c,job)
        other=c.execute("INSERT INTO users(name,email) VALUES('Second eligible person','second@fixture.invalid') RETURNING id").fetchone()['id']
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,1)',(other,))
    def attempt(user):
        try:
            with db() as c: actor(c,user=user); command(c,'task_claim',lambda c: {'version':claim_task(c,task,1)})
            return user
        except psycopg.errors.SerializationFailure: return None
    with ThreadPoolExecutor(max_workers=2) as executor: results=list(executor.map(attempt,[1,other]))
    assert len([user for user in results if user is not None])==1
    with db() as c: assert c.execute('SELECT claimed_by_user_id FROM disposition_tasks WHERE id=%s',(task,)).fetchone()['claimed_by_user_id'] in [user for user in results if user is not None]


def test_workflow_mutations_and_audit_history_recheck_resource_access(client):
    with db() as c:
        actor(c); root,*_=prepare_unit(c); job=make_job(c); add(c,job,root)
        with c.transaction(force_rollback=True):
            c.execute("DELETE FROM profile_privileges WHERE profile_id IN (SELECT profile_id FROM roles WHERE id IN (SELECT role_id FROM user_role_assignments WHERE user_id=1)) AND privilege_id=(SELECT id FROM privileges WHERE code='aggregation.view')")
            with pytest.raises(psycopg.Error,match='disposition_resource_access_required'):
                command(c,'job_assign',lambda c:(c.execute('UPDATE disposition_jobs SET assigned_user_id=1 WHERE id=%s',(job,)) and {}))
            events=c.execute("SELECT metadata FROM authorized_event_history WHERE entity_type='disposition_job' AND entity_id=%s",(job,)).fetchall()
            assert events and all(e['metadata'].get('redacted') is True for e in events)
        with c.transaction(force_rollback=True):
            # A visible root does not reveal identifiers from a concealed record
            # in the immutable reviewed-membership snapshot or job history.
            c.execute("DELETE FROM profile_privileges WHERE profile_id IN (SELECT profile_id FROM roles WHERE id IN (SELECT role_id FROM user_role_assignments WHERE user_id=1)) AND privilege_id=(SELECT id FROM privileges WHERE code='record.view')")
            events=c.execute("SELECT metadata FROM authorized_event_history WHERE entity_type='disposition_job' AND entity_id=%s",(job,)).fetchall()
            assert events and all(e['metadata'].get('redacted') is True for e in events)


@pytest.mark.parametrize('kind,eligible,terminal,corrupt',[
 ('destruction',2,10,False),('permanent_transfer',3,11,False),
 ('local_archives',5,12,False),('destruction',2,10,True)])
def test_terminal_history_fixture_requires_complete_consistent_outcomes(client,kind,eligible,terminal,corrupt):
    """Verify outcome persistence, not an operational final-action implementation.

    The disposable-only fixture bypasses the deliberately closed job execution
    gate, leaving resource, membership and deferred consistency guards enabled.
    Phase 21 must implement and verify actual destruction before opening it.
    """
    with db() as c:
        actor(c); root,child,leaf,record=prepare_unit(c,status=eligible)
        job=make_job(c,kind=kind); member=add(c,job,root)
        c.execute('ALTER TABLE disposition_jobs DISABLE TRIGGER disposition_guard')
        try:
            def import_proven_outcome(c):
                event=c.execute("SELECT append_domain_event('disposition_job',%s,'DISPOSITION_FINAL_OUTCOME_FIXTURE') id",(job,)).fetchone()['id']
                destruction='AUTH ! ١' if terminal==10 else None
                transfer='TRANSFER / ١' if terminal==11 else None
                c.execute("""UPDATE disposition_jobs SET lifecycle_state='completed',disposition_status=%s,
                 completed_by_user_id=1,completed_by_name='Execution-time name',completed_at=CURRENT_TIMESTAMP,
                 destruction_number=%s,transfer_number=%s,final_event_id=%s WHERE id=%s""",(terminal,destruction,transfer,event,job))
                c.execute("UPDATE disposition_job_memberships SET membership_state='completed_history' WHERE id=%s",(member,))
                values=(terminal,job,destruction,transfer,event)
                c.execute('''UPDATE aggregations SET disposition_status=%s,final_disposition_at=CURRENT_TIMESTAMP,
                 final_disposition_by_user_id=1,disposition_job_id=%s,destruction_number=%s,transfer_number=%s,
                 final_disposition_event_id=%s WHERE id IN (SELECT disposition_private.unit_ids(%s)) AND NOT (%s AND id=%s)''',(*values,root,corrupt,leaf))
                c.execute('''UPDATE records SET disposition_status=%s,final_disposition_at=CURRENT_TIMESTAMP,
                 final_disposition_by_user_id=1,disposition_job_id=%s,destruction_number=%s,transfer_number=%s,
                 final_disposition_event_id=%s WHERE id=%s''',(*values,record))
                if corrupt:
                    c.execute("""UPDATE aggregations SET disposition_status=%s,final_disposition_at=CURRENT_TIMESTAMP+INTERVAL '1 hour',
                     final_disposition_by_user_id=1,disposition_job_id=%s,destruction_number=%s,transfer_number=%s,
                     final_disposition_event_id=%s WHERE id=%s""",(*values,leaf))
                return {'event_id':event}
            if corrupt:
                with pytest.raises(psycopg.Error,match='disposition_unit_inconsistent'):
                    command(c,'final_complete',import_proven_outcome)
                assert states(c)==[eligible+4]*4
                assert c.execute('SELECT lifecycle_state FROM disposition_jobs WHERE id=%s',(job,)).fetchone()['lifecycle_state']=='active'
            else:
                result=command(c,'final_complete',import_proven_outcome)
                assert states(c)==[terminal]*4
                final=c.execute('SELECT * FROM aggregations WHERE id=%s',(root,)).fetchone()
                assert final['disposition_job_id']==job and final['final_disposition_event_id']==result['event_id']
        finally:
            c.execute('ALTER TABLE disposition_jobs ENABLE TRIGGER disposition_guard')
        if not corrupt:
            with pytest.raises(psycopg.Error):
                with c.transaction(): c.execute("UPDATE aggregations SET title='Cannot rewrite final outcome' WHERE id=%s",(root,))
            with pytest.raises(psycopg.Error,match='disposition_history_immutable'):
                command(c,'job_assign',lambda c:(c.execute("UPDATE disposition_jobs SET lifecycle_state='active' WHERE id=%s",(job,)) and {}))


def test_task_completion_rechecks_queue_eligibility_after_claim(client):
    with db() as c:
        actor(c); job=make_job(c); task=make_task(c,job); claim(c,task)
        alternate=c.execute("INSERT INTO roles(org_unit_id,code,name,is_information_governance) VALUES(1,'alternate-governance','Alternate governance',true) RETURNING id").fetchone()['id']
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(1,%s)',(alternate,))
        c.execute('DELETE FROM user_role_assignments WHERE user_id=1 AND role_id=1')
        with pytest.raises(psycopg.Error,match='disposition_task_ineligible'):
            command(c,'task_complete',lambda c:(c.execute("UPDATE disposition_tasks SET task_state='completed' WHERE id=%s",(task,)) and {}),role=alternate)
        assert c.execute('SELECT task_state FROM disposition_tasks WHERE id=%s',(task,)).fetchone()['task_state']=='claimed'


def test_round_completion_is_immutable_and_later_invalidation_is_additive(client):
    with db() as c:
        actor(c); job=make_job(c)
        def start(c):
            return dict(c.execute("INSERT INTO disposition_review_rounds(job_id,round_number,started_by_user_id,membership_snapshot) VALUES(%s,1,1,'[]') RETURNING id",(job,)).fetchone())
        review=command(c,'review_submit',start)['id']
        command(c,'review_decide',lambda c:(c.execute('UPDATE disposition_review_rounds SET completed_at=CURRENT_TIMESTAMP WHERE id=%s',(review,)) and {}))
        completed=c.execute('SELECT completed_at FROM disposition_review_rounds WHERE id=%s',(review,)).fetchone()['completed_at']
        with pytest.raises(psycopg.Error,match='disposition_history_immutable'):
            command(c,'review_decide',lambda c:(c.execute("UPDATE disposition_review_rounds SET completed_at=CURRENT_TIMESTAMP+INTERVAL '1 hour' WHERE id=%s",(review,)) and {}))
        command(c,'review_submit',lambda c:(c.execute("UPDATE disposition_review_rounds SET invalidated_at=CURRENT_TIMESTAMP,invalidation_reason='Membership changed' WHERE id=%s",(review,)) and {}))
        saved=c.execute('SELECT * FROM disposition_review_rounds WHERE id=%s',(review,)).fetchone()
        assert saved['completed_at']==completed and saved['invalidated_at'] is not None
        with pytest.raises(psycopg.Error,match='disposition_history_immutable'):
            command(c,'review_decide',lambda c:(c.execute("UPDATE disposition_review_rounds SET invalidation_reason='Rewritten' WHERE id=%s",(review,)) and {}))


def test_termination_cancels_tasks_and_keeps_cancelled_history(client):
    with db() as c:
        actor(c); job=make_job(c); task=make_task(c,job)
        def terminate(c):
            c.execute("UPDATE disposition_tasks SET task_state='cancelled' WHERE id=%s",(task,))
            c.execute("UPDATE disposition_jobs SET lifecycle_state='terminated',termination_reason='Stop before execution' WHERE id=%s",(job,)); return {}
        command(c,'job_terminate',terminate)
        assert c.execute('SELECT task_state FROM disposition_tasks WHERE id=%s',(task,)).fetchone()['task_state']=='cancelled'
        with pytest.raises(psycopg.Error,match='disposition_history_immutable'):
            command(c,'task_reassign',lambda c:(c.execute("UPDATE disposition_tasks SET task_state='open' WHERE id=%s",(task,)) and {}))


@pytest.mark.parametrize('wrong',['record','checksum'])
def test_available_document_rejects_inconsistent_component_provenance(client,record,wrong):
    with db() as c:
        actor(c); job=make_job(c)
        other=c.execute("INSERT INTO records(aggregation_id,record_number,title) VALUES(%s,'other-document-container','Other record') RETURNING id",(record['aggregation_id'],)).fetchone()['id']
        component=c.execute("INSERT INTO digital_components(record_id,component_order,file_name,mime_type,size_in_bytes,checksum_algo,checksum_value) VALUES(%s,1,'proof.pdf','application/pdf',0,'sha256','empty') RETURNING id",(record['id'],)).fetchone()['id']
        def link(c):
            c.execute("""INSERT INTO disposition_job_documents(job_id,document_type,document_state,record_id,digital_component_id,created_by_user_id,checksum_algo,checksum)
             VALUES(%s,'destruction_request','available',%s,%s,1,'sha256',%s)""",(job,other if wrong=='record' else record['id'],component,'wrong' if wrong=='checksum' else 'empty')); return {}
        with pytest.raises(psycopg.Error,match='disposition_document_component_mismatch'): command(c,'document_save',link)
        assert c.execute('SELECT count(*) n FROM disposition_job_documents').fetchone()['n']==0


def test_review_decision_rejects_changed_membership_snapshot(client):
    with db() as c:
        actor(c); root,*_=prepare_unit(c); job=make_job(c); member=add(c,job,root)
        snapshot=c.execute('SELECT disposition_private.membership_snapshot(%s) s',(job,)).fetchone()['s']
        c.execute('UPDATE org_units SET managing_role_id=1 WHERE id=1')
        def submit(c):
            c.execute("UPDATE disposition_tasks SET task_state='cancelled' WHERE job_id=%s",(job,))
            c.execute("UPDATE disposition_jobs SET workflow_stage='unit_manager_review' WHERE id=%s",(job,))
            review=c.execute('INSERT INTO disposition_review_rounds(job_id,round_number,started_by_user_id,membership_snapshot) VALUES(%s,1,1,%s) RETURNING id',(job,Jsonb(snapshot))).fetchone()['id']
            task=c.execute("INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,destination_role_id,review_round) VALUES(%s,'unit_manager_review','unit_manager_review',1,1) RETURNING id",(job,)).fetchone()['id']
            return {'round':review,'task':task}
        review=command(c,'review_submit',submit)
        claim(c,review['task'])
        # Phase 9 rejects removal while a reviewer holds the job. A current
        # protective resource change still invalidates the reviewed versions.
        c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)")
        c.execute("UPDATE records SET is_vital=true WHERE aggregation_id IN (SELECT disposition_private.unit_ids(%s))",(root,))
        def approve_stale(c):
            c.execute("""INSERT INTO disposition_review_decisions(job_id,round_id,review_stage,decision,task_id,actor_user_id,acting_role_id,reason,membership_snapshot)
             VALUES(%s,%s,'unit_manager_review','approved',%s,1,1,'Outdated review',%s)""",(job,review['round'],review['task'],Jsonb(snapshot))); return {}
        with pytest.raises(psycopg.Error,match='disposition_review_snapshot_stale'): command(c,'review_decide',approve_stale)
        assert c.execute('SELECT count(*) n FROM disposition_review_decisions').fetchone()['n']==0
