"""Approved restoration of reopened active members; disposable DB only."""
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg.types.json import Jsonb
import pytest

from backend.services.api.disposition import membership
from backend.services.api.tests.test_disposition_membership import (
    db, actor, setup, ready, admit, member, statuses, version, kwargs, rule_change, job_version,
)
from backend.services.api.tests.test_disposition_foundation import command
from backend.services.api.tests.test_disposition_eligibility import make_hold


def reopen(c, root):
    c.execute('UPDATE aggregations SET date_closed=NULL WHERE id=%s', (root,))
    assert member(c, root)['removal_required_reason'] == 'reopened'
    assert statuses(c, root) == [1]*4


def accelerate(c, root, **options):
    return membership.accelerate(c, **kwargs(root_id=root, expected_version=version(c, root), **options))


@pytest.mark.parametrize('kind,action,pending', [
    ('destruction', 'destruction', 6), ('permanent_transfer', 'transfer_to_external_archive', 7),
    ('selective_transfer', 'selective_preservation', 8), ('local_archives', 'retain_as_local_archives', 9),
])
def test_accelerate_reopened_member_retains_episode_restores_whole_unit_and_retries(client, kind, action, pending):
    with db() as c:
        job = setup(c, kind);root, *_ = ready(c, action)
        admit(c, job['id'], [root]);before = member(c, root)
        old_closed=c.execute('SELECT date_closed FROM aggregations WHERE id=%s',(root,)).fetchone()['date_closed']
        reopen(c, root)
        options = kwargs(root_id=root, expected_version=version(c, root))
        result = membership.accelerate(c, **options)
        assert result == {'root_id': root, 'status': pending}
        assert statuses(c, root) == [pending]*4
        after = member(c, root)
        assert (after['id'], after['job_id'], after['added_at'], after['added_by_user_id']) == (
            before['id'], before['job_id'], before['added_at'], before['added_by_user_id'])
        assert not after['removal_required'] and after['removal_required_reason'] is None
        assert c.execute('SELECT date_closed FROM aggregations WHERE id=%s', (root,)).fetchone()['date_closed'] > old_closed
        assert not c.execute('SELECT 1 FROM disposition_private.recalculation_context').fetchone()
        c.execute('SELECT disposition_private.require_progress(%s)', (job['id'],))
        assert membership.accelerate(c, **options) == result
        assert len(c.execute('SELECT * FROM disposition_job_memberships').fetchall()) == 1
        assert c.execute("SELECT count(*) AS n FROM event_history WHERE operation='DISPOSITION_ACCELERATED' AND entity_id=%s", (root,)).fetchone()['n'] == 1
        assert c.execute("SELECT count(*) AS n FROM event_history WHERE operation='MEMBERSHIP_ADD' AND entity_type='disposition_job_membership'").fetchone()['n'] == 1
        assert not c.execute("SELECT 1 FROM event_history WHERE operation='MEMBERSHIP_REMOVE'").fetchone()
        event = c.execute("SELECT metadata,reason FROM event_history WHERE operation='DISPOSITION_ACCELERATED' AND entity_id=%s", (root,)).fetchone()
        assert event['metadata']['membership_id'] == before['id'] and event['metadata']['job_id'] == job['id']
        assert event['reason']


@pytest.mark.parametrize('change', ['wrong_action', 'stale'])
def test_rejection_preserves_open_root_membership_flag_and_all_events(client, change):
    with db() as c:
        job=setup(c);root, *_=ready(c);assert admit(c,job['id'],[root])['items'][0]['success'];reopen(c,root)
        if change=='wrong_action':rule_change(c,root,action='retain_as_local_archives')
        before=member(c,root);v=version(c,root);events=c.execute('SELECT count(*) AS n FROM event_history').fetchone()['n']
        expected={'wrong_action':'disposition_job_type_status_mismatch','stale':'disposition_stale_version'}[change]
        with pytest.raises(psycopg.Error,match=expected):
            membership.accelerate(c,**kwargs(root_id=root,expected_version=v-1 if change=='stale' else v))
        assert member(c,root)==before and version(c,root)==v and statuses(c,root)==[1]*4
        assert c.execute('SELECT date_closed FROM aggregations WHERE id=%s',(root,)).fetchone()['date_closed'] is None
        assert c.execute('SELECT count(*) AS n FROM event_history').fetchone()['n']==events


@pytest.mark.parametrize('protection', ['normal_hold', 'preserve_hold', 'vital', 'security'])
def test_protections_survive_and_preserve_state_closure_remains_enforced(client, protection):
    with db() as c, c.transaction(force_rollback=True):
        job=setup(c);root,child,leaf,record=ready(c);assert admit(c,job['id'],[root])['items'][0]['success'];reopen(c,root)
        if protection.endswith('hold'):make_hold(c,'aggregation' if protection=='preserve_hold' else 'record',root if protection=='preserve_hold' else record,preserve=protection=='preserve_hold')
        elif protection=='vital':
            c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)")
            c.execute('UPDATE records SET is_vital=true WHERE id=%s',(record,))
        else:c.execute('UPDATE security_levels SET prevents_disposition=true WHERE id=(SELECT security_level_id FROM records WHERE id=%s)',(record,))
        before=c.execute('SELECT * FROM hold_record_assignments').fetchall()
        if protection=='preserve_hold':
            with pytest.raises(psycopg.Error):accelerate(c,root)
            assert statuses(c,root)==[1]*4 and member(c,root)['removal_required']
            assert c.execute('SELECT date_closed FROM aggregations WHERE id=%s',(root,)).fetchone()['date_closed'] is None
        else:
            accelerate(c,root)
            assert statuses(c,root)==[6]*4 and not member(c,root)['removal_required']
            assert c.execute('SELECT 1 FROM disposition_private.protection_blockers(%s)',(root,)).fetchone()
        assert c.execute('SELECT * FROM hold_record_assignments').fetchall()==before


def test_regular_reclosure_keeps_recovery_required_until_explicit_acceleration(client):
    with db() as c:
        job=setup(c);root,*_=ready(c);assert admit(c,job['id'],[root])['items'][0]['success'];reopen(c,root)
        c.execute("UPDATE aggregations SET date_closed='2020-01-01' WHERE id=%s",(root,))
        closed=c.execute('SELECT date_closed FROM aggregations WHERE id=%s',(root,)).fetchone()['date_closed']
        accelerate(c,root)
        assert c.execute('SELECT date_closed FROM aggregations WHERE id=%s',(root,)).fetchone()['date_closed']==closed
        assert statuses(c,root)==[6]*4 and not member(c,root)['removal_required']


def test_direct_commands_cannot_clear_flags_or_create_pending_status_without_scoped_restoration(client):
    with db() as c:
        job=setup(c);root,*_=ready(c);assert admit(c,job['id'],[root])['items'][0]['success'];reopen(c,root)
        for mutation in [
            lambda x:x.execute('UPDATE disposition_job_memberships SET removal_required=false,removal_required_reason=NULL WHERE root_aggregation_id=%s',(root,)),
            lambda x:x.execute('UPDATE aggregations SET disposition_status=6 WHERE id=%s',(root,)),
        ]:
            with pytest.raises(psycopg.Error,match='disposition_(recalculation|command)_scope_invalid'):
                command(c,'eligibility_accelerate',mutation,payload={'root_id':root})
        assert member(c,root)['removal_required'] and statuses(c,root)==[1]*4


@pytest.mark.parametrize('material_change', [False, True])
def test_approval_follows_approved_facts_and_preserves_valid_historical_closure(client, material_change):
    from backend.services.api.tests.test_disposition_external import prepared
    from backend.services.api.disposition import external
    with db() as c:
        job,root,mgr,rid=prepared(c)
        old_closed=c.execute('SELECT date_closed FROM aggregations WHERE id=%s',(root,)).fetchone()['date_closed']
        assert c.execute('SELECT disposition_private.request_approval_current(%s,%s) ok',(job['id'],rid)).fetchone()['ok']
        reopen(c,root)
        if material_change:
            c.execute("UPDATE aggregations SET title='Changed approved description' WHERE id=%s",(root,))
        c.execute('UPDATE aggregations SET date_closed=%s WHERE id=%s',(old_closed,root))
        accelerate(c,root)
        assert not member(c,root)['removal_required']
        assert c.execute('SELECT date_closed FROM aggregations WHERE id=%s',(root,)).fetchone()['date_closed']==old_closed
        assert c.execute('SELECT disposition_private.request_approval_current(%s,%s) ok',(job['id'],rid)).fetchone()['ok'] is (not material_change)
        if not material_change:
            assert c.execute('SELECT current_review_round FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()['current_review_round']==1
            assert c.execute('SELECT count(*) AS n FROM disposition_review_rounds WHERE job_id=%s',(job['id'],)).fetchone()['n']==1
        else:
            # Changed approved facts still use the existing complete-review flow.
            result=external.renew(c,job_id=job['id'],round_id=rid,expected_version=job_version(c,job['id']),acting_role_id=mgr,command_id=uuid4(),reason='Review changed contents again')
            assert result['review_required']
            from backend.services.api.tests.test_disposition_approval import reach_manager,approve
            reach_manager(c,job,'simplified')
            fresh=approve(c,job,mgr)
            assert fresh['round_id']!=rid
            assert c.execute('SELECT disposition_private.request_approval_current(%s,%s) ok',(job['id'],fresh['round_id'])).fetchone()['ok']


def test_migration_preserves_existing_flagged_members_then_allows_restoration(client):
    with db() as c:
        job=setup(c);root,*_=ready(c);assert admit(c,job['id'],[root])['items'][0]['success'];reopen(c,root);before=member(c,root)
        c.commit()
        migration=Path('database/migrations/093_restore_reopened_job_members.sql').read_text()
        for _ in range(2):c.execute(migration,prepare=False)
        actor(c)
        assert member(c,root)==before
        accelerate(c,root)
        assert member(c,root)['id']==before['id'] and statuses(c,root)==[6]*4


def test_other_reopened_members_still_block_the_job(client):
    with db() as c:
        job=setup(c);one,*_=ready(c);two,*_=ready(c);admit(c,job['id'],[one,two])
        reopen(c,one);reopen(c,two);accelerate(c,one)
        assert not member(c,one)['removal_required'] and member(c,two)['removal_required']
        with c.transaction(force_rollback=True):
            with pytest.raises(psycopg.Error,match='disposition_removal_required'):
                c.execute('SELECT disposition_private.require_progress(%s)',(job['id'],))
        accelerate(c,two);c.execute('SELECT disposition_private.require_progress(%s)',(job['id'],))


def test_competing_accelerations_have_one_commit_and_one_stale_rejection(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    with db() as c:
        job=setup(c);root,*_=ready(c);assert admit(c,job['id'],[root])['items'][0]['success'];reopen(c,root);v=version(c,root)
    barrier=Barrier(2)
    def worker():
        try:
            with db() as c:
                actor(c);barrier.wait(timeout=10)
                membership.accelerate(c,**kwargs(root_id=root,expected_version=v))
            return 'ok'
        except psycopg.errors.SerializationFailure:return 'stale'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _:worker(),range(2)))==['ok','stale']
    with db() as c:
        assert statuses(c,root)==[6]*4 and not member(c,root)['removal_required']
        assert c.execute("SELECT count(*) AS n FROM event_history WHERE operation='DISPOSITION_ACCELERATED' AND entity_id=%s",(root,)).fetchone()['n']==1


def test_preparation_keeps_saved_proposals_task_stage_and_round_without_any_approval(client):
    from backend.services.api.tests.test_disposition_review import seeded,save,create,task
    with db() as c:
        job,root,*_=seeded(c)
        save(c,job,changes=[create(c,root)],review_notes='Saved draft proposal',note_version=0)
        proposals=c.execute('SELECT * FROM disposition_review_proposals ORDER BY id').fetchall()
        before_task=task(c,job['id'])
        assert not c.execute('SELECT 1 FROM disposition_review_rounds WHERE job_id=%s',(job['id'],)).fetchone()
        reopen(c,root);accelerate(c,root)
        assert c.execute('SELECT * FROM disposition_review_proposals ORDER BY id').fetchall()==proposals
        assert task(c,job['id'])==before_task
        j=c.execute('SELECT workflow_stage,current_review_round FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()
        assert j=={'workflow_stage':'officer_preparation','current_review_round':0}
        assert not c.execute('SELECT 1 FROM disposition_review_rounds WHERE job_id=%s',(job['id'],)).fetchone()
        assert not c.execute("SELECT 1 FROM event_history WHERE operation='REVIEW_PROPOSALS_APPROVED' AND entity_id=%s",(job['id'],)).fetchone()


def test_descendant_failure_rolls_back_closure_flags_versions_history_and_context(client):
    with db() as c:
        job=setup(c);root,_,_,record=ready(c);assert admit(c,job['id'],[root])['items'][0]['success'];reopen(c,root)
        before=member(c,root);root_version=version(c,root);before_job=job_version(c,job['id'])
        events=c.execute('SELECT count(*) AS n FROM event_history').fetchone()['n']
        c.execute("CREATE FUNCTION fail_restoration() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN IF NEW.disposition_status=6 THEN RAISE EXCEPTION 'disposable descendant failure'; END IF; RETURN NEW; END$$")
        c.execute('CREATE TRIGGER fail_restoration BEFORE UPDATE ON records FOR EACH ROW EXECUTE FUNCTION fail_restoration()')
        try:
            with pytest.raises(psycopg.Error,match='disposable descendant failure'):accelerate(c,root)
            assert member(c,root)==before and version(c,root)==root_version and job_version(c,job['id'])==before_job
            assert statuses(c,root)==[1]*4
            assert c.execute('SELECT date_closed FROM aggregations WHERE id=%s',(root,)).fetchone()['date_closed'] is None
            assert c.execute('SELECT count(*) AS n FROM event_history').fetchone()['n']==events
            assert not c.execute('SELECT 1 FROM disposition_private.recalculation_context').fetchone()
        finally:
            c.execute('DROP TRIGGER fail_restoration ON records');c.execute('DROP FUNCTION fail_restoration()')


def test_already_reclosed_preserve_state_hold_allows_status_only_restoration(client):
    with db() as c:
        job=setup(c);root,*_=ready(c);assert admit(c,job['id'],[root])['items'][0]['success'];reopen(c,root)
        c.execute("UPDATE aggregations SET date_closed='2020-01-01' WHERE id=%s",(root,))
        make_hold(c,'aggregation',root,preserve=True)
        before=c.execute('SELECT * FROM hold_aggregation_assignments').fetchall()
        accelerate(c,root)
        assert statuses(c,root)==[6]*4 and not member(c,root)['removal_required']
        assert c.execute('SELECT * FROM hold_aggregation_assignments').fetchall()==before
