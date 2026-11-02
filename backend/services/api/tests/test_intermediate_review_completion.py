"""Intermediate completion is distinct from authorization to apply proposals."""
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from backend.services.api.disposition import approval, proposals
from backend.services.api.tests.test_disposition_review import (
    db, seeded, person, payloads, save, submit, actor, claim, decide,
    task, data, job_version,
)


from tools.historical_schema import historical_schema


def restricted_review(c, stage, kind):
    job, root, um, fa, mgr = seeded(c, fa=True)
    reviewer = person(c, 'Intermediate reviewer')
    review_role = fa if stage == 'file_administrator_review' else um
    c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)', (reviewer, review_role))
    change = next(p for p in payloads(c, root) if p['proposal_type'] == kind)
    proposal_id = save(c, job, changes=[change])['changes'][0]['id']
    table = 'aggregation_relationships' if kind == 'remove_aggregation_relationship' else 'record_relationships'
    other = c.execute(f'SELECT target_id FROM {table} WHERE id=%s', (change['proposed_values']['relationship_id'],)).fetchone()['target_id']
    high = c.execute("INSERT INTO security_levels(level_number,code,name,prevents_disposition) SELECT max(level_number)+1,%s,%s,false FROM security_levels RETURNING id", (uuid4().hex, 'Restricted endpoint '+uuid4().hex)).fetchone()['id']
    c.execute('UPDATE roles SET security_level_id=%s WHERE id=1', (high,))
    c.execute("SELECT set_config('app.security_level_change_authorized','authorized',true)")
    if kind == 'remove_record_relationship':
        ancestors = c.execute('''WITH RECURSIVE chain AS (
            SELECT a.id,a.parent_aggregation_id,0 depth FROM aggregations a JOIN records r ON r.aggregation_id=a.id WHERE r.id=%s
            UNION ALL SELECT a.id,a.parent_aggregation_id,chain.depth+1 FROM aggregations a JOIN chain ON a.id=chain.parent_aggregation_id
        ) SELECT id FROM chain ORDER BY depth DESC''', (other,)).fetchall()
        for a in ancestors:
            c.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s', (high, a['id']))
    c.execute(f'UPDATE {"aggregations" if table == "aggregation_relationships" else "records"} SET security_level_id=%s WHERE id=%s', (high, other))
    submit(c, job)
    if stage == 'unit_manager_review':
        claim(c, job)
        decide(c, job)
    actor(c, reviewer)
    assert c.execute('SELECT current_user_can_view_aggregation(%s) ok', (root,)).fetchone()['ok']
    claim(c, job)
    return job, root, mgr, reviewer, review_role, proposal_id, high


@pytest.mark.parametrize('stage', ['file_administrator_review', 'unit_manager_review'])
@pytest.mark.parametrize('kind', ['remove_aggregation_relationship', 'remove_record_relationship'])
def test_complete_with_hidden_endpoint_preserves_redaction_proposals_and_resources(client, stage, kind):
    with db() as c:
        job, root, mgr, reviewer, review_role, pid, high = restricted_review(c, stage, kind)
        for language in ('en', 'ar'):
            row = proposals.page(c, job['id'], limit=25, offset=0, language_tag=language)['items'][0]
            assert row['partial'] and row['redacted'] and row['proposal_type'] == kind
            assert not {'current_values', 'proposed_values', 'reason', 'relationship_source_label', 'relationship_target_label'} & set(row)
        before = data(c, root)
        proposal_before = c.execute('SELECT to_jsonb(p) value FROM disposition_review_proposals p WHERE id=%s', (pid,)).fetchone()['value']
        old_task = task(c, job['id'])
        # Direct edits still require access to both endpoints.
        with pytest.raises(psycopg.Error, match='disposition_resource_access_required'):
            save(c, job, changes=[dict(action='revise', proposal_id=pid, expected_version=proposal_before['version'], target_version=proposal_before['current_values']['record']['version'] if kind == 'remove_record_relationship' else proposal_before['current_values']['aggregation_version'], proposed_values=proposal_before['proposed_values'], reason='Review edit')])
        result = decide(c, job)
        assert result['workflow_stage'] == ('unit_manager_review' if stage == 'file_administrator_review' else 'records_manager_review')
        assert c.execute('SELECT task_state FROM disposition_tasks WHERE id=%s', (old_task['id'],)).fetchone()['task_state'] == 'completed'
        decision = c.execute('SELECT * FROM disposition_review_decisions WHERE task_id=%s', (old_task['id'],)).fetchone()
        assert decision['actor_user_id'] == reviewer and decision['review_stage'] == stage
        assert any(p['id'] == pid for p in decision['proposal_snapshot'])
        assert data(c, root) == before
        assert c.execute('SELECT to_jsonb(p) value FROM disposition_review_proposals p WHERE id=%s', (pid,)).fetchone()['value'] == proposal_before
        assert not c.execute('SELECT 1 FROM disposition_proposal_effects').fetchone()
        # Reach final approval with a manager who has root access but cannot see
        # this endpoint. No active proposal may be silently omitted there.
        actor(c)
        if stage == 'file_administrator_review':
            claim(c, job)
            decide(c, job)
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)', (reviewer, mgr))
        from backend.services.api.tests.test_disposition_workflow import act
        act(c, task(c, job['id']), 'release', mgr)
        actor(c, reviewer)
        claim(c, job)
        t = task(c, job['id'])
        preview = approval.preview(c, t['id'], mgr)
        with pytest.raises(psycopg.Error, match='disposition_proposal_requires_correction'):
            approval.approve(c, task_id=t['id'], expected_version=preview['job_version'], task_version=preview['task_version'], membership_token=preview['membership_token'], proposals_token=preview['proposals_token'], acting_role_id=mgr, command_id=uuid4())
        assert not c.execute('SELECT 1 FROM disposition_proposal_effects').fetchone()
        assert data(c, root) == before
        assert not c.execute("SELECT 1 FROM disposition_review_decisions WHERE review_stage='records_manager_review'").fetchone()
        act(c, task(c, job['id']), 'release', mgr)
        actor(c)
        claim(c, job)
        from backend.services.api.tests.test_disposition_approval import approve
        approve(c, job, mgr)
        assert c.execute('SELECT proposal_state FROM disposition_review_proposals WHERE id=%s', (pid,)).fetchone()['proposal_state'] == 'executed'
        assert c.execute('SELECT executed_by_user_id FROM disposition_review_proposals WHERE id=%s', (pid,)).fetchone()['executed_by_user_id'] == 1


@pytest.mark.parametrize('stage', ['file_administrator_review', 'unit_manager_review'])
@pytest.mark.parametrize('failure', ['root_access', 'assignment', 'claim', 'stale'])
def test_intermediate_completion_retains_current_task_and_root_checks(client, failure, stage):
    with db() as c:
        job, root, mgr, reviewer, review_role, pid, high = restricted_review(c, stage, 'remove_aggregation_relationship')
        t = task(c, job['id'])
        if failure == 'root_access':
            actor(c)
            c.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s', (high, root))
            actor(c, reviewer)
        elif failure == 'assignment':
            c.execute('DELETE FROM user_role_assignments WHERE user_id=%s AND role_id=%s', (reviewer, review_role))
        elif failure == 'claim':
            from backend.services.api.tests.test_disposition_workflow import act
            act(c, t, 'release', review_role)
        before = c.execute('SELECT count(*) n FROM disposition_review_decisions').fetchone()['n']
        with pytest.raises(psycopg.Error):
            if failure == 'stale':
                proposals.decide(c, task_id=t['id'], expected_version=job_version(c, job['id']), task_version=t['version']-1, decision='approved', decision_reason='', acting_role_id=review_role, command_id=uuid4())
            else:
                decide(c, job)
        assert c.execute('SELECT count(*) n FROM disposition_review_decisions').fetchone()['n'] == before
        assert c.execute('SELECT task_state FROM disposition_tasks WHERE id=%s', (t['id'],)).fetchone()['task_state'] != 'completed'


def test_upgrade_preserves_occupied_review_and_allows_retry(client):
    with db() as c:
        # Restore the old definition only inside this disposable test transaction.
        source = historical_schema()
        start = source.index('CREATE FUNCTION disposition_private.decide_review_work(')
        end = source.index('END $$;', start) + len('END $$;')
        c.execute(source[start:end].replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1), prepare=False)
        job, root, mgr, reviewer, review_role, pid, high = restricted_review(c, 'file_administrator_review', 'remove_aggregation_relationship')
        with pytest.raises(psycopg.Error, match='disposition_resource_access_required'):
            decide(c, job)
        tables = ('disposition_tasks', 'disposition_review_proposals', 'disposition_review_decisions', 'disposition_review_rounds', 'event_history')
        def snapshot():
            return [c.execute(f'SELECT jsonb_agg(to_jsonb(t) ORDER BY id) value FROM {table} t').fetchone()['value'] for table in tables]
        before = snapshot()
        migration = Path('database/migrations/086_intermediate_review_completion.sql').read_text()
        c.execute(migration.removeprefix('BEGIN;\n').removesuffix('COMMIT;\n'), prepare=False)
        assert snapshot() == before
        decide(c, job)
        assert task(c, job['id'])['workflow_stage'] == 'unit_manager_review'


@pytest.mark.parametrize('stage', ['file_administrator_review', 'unit_manager_review'])
def test_non_governance_reviewer_with_root_acl_can_complete_redacted_review(client, stage):
    with db() as c:
        job, root, mgr, reviewer, review_role, pid, high = restricted_review(c, stage, 'remove_aggregation_relationship')
        c.execute('''INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,role_id,permission_id)
            SELECT a.id,'role',%s,p.id FROM disposition_private.unit_ids(%s) a(id) CROSS JOIN permissions p
            WHERE p.code='aggregation.view' ON CONFLICT DO NOTHING''', (review_role, root))
        c.execute('''INSERT INTO record_acl_grants(record_id,principal_type,role_id,permission_id)
            SELECT r.id,'role',%s,p.id FROM records r CROSS JOIN permissions p
            WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(%s)) AND p.code='record.view'
            ON CONFLICT DO NOTHING''', (review_role, root))
        c.execute('''INSERT INTO aggregation_child_record_acl_defaults(aggregation_id,principal_type,role_id,permission_id)
            SELECT a.id,'role',%s,p.id FROM disposition_private.unit_ids(%s) a(id) CROSS JOIN permissions p
            WHERE p.code='record.view' ON CONFLICT DO NOTHING''', (review_role, root))
        c.execute('UPDATE roles SET is_information_governance=false WHERE id=%s', (review_role,))
        assert not c.execute('SELECT disposition_private.can_manage() ok').fetchone()['ok']
        assert proposals.page(c, job['id'], limit=25, offset=0)['items'][0]['partial']
        decide(c, job)
        assert not c.execute('SELECT 1 FROM disposition_proposal_effects').fetchone()


@pytest.mark.parametrize('stage', ['file_administrator_review', 'unit_manager_review'])
@pytest.mark.parametrize('shared', [False, True])
@pytest.mark.parametrize('language', ['en', 'ar'])
def test_completion_http_reports_actual_localized_next_person_or_queue(client, stage, shared, language):
    from psycopg.types.json import Jsonb
    with db() as c:
        job, root, um, fa, mgr = seeded(c, fa=True)
        next_role = um if stage == 'file_administrator_review' else mgr
        if shared:
            other = person(c, 'Another eligible reviewer')
            c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)', (other, next_role))
        c.execute('UPDATE roles SET translations=%s WHERE id=%s', (Jsonb({'ar': {'name': 'فريق المراجعة'}}), next_role))
        c.execute('UPDATE users SET translations=%s WHERE id=1', (Jsonb({'ar': {'name': 'المراجع التالي'}}),))
        c.execute('INSERT INTO user_preferences(user_id,language_tag,working_timezone) VALUES(1,%s,\'Asia/Dubai\') ON CONFLICT(user_id) DO UPDATE SET language_tag=EXCLUDED.language_tag', (language,))
        submit(c, job)
        if stage == 'unit_manager_review':
            claim(c, job)
            decide(c, job)
        claim(c, job)
        t = task(c, job['id'])
        payload = dict(command_id=str(uuid4()), acting_role_id=t['destination_role_id'], task_version=t['version'], decision='approved', decision_reason='')
        headers = {'If-Match': str(job_version(c, job['id'])), 'X-CSRF-Token': client.cookies.get('erms_csrf')}
        expected = c.execute('SELECT name FROM roles WHERE id=%s', (next_role,)).fetchone()['name'] if shared else 'Test Administrator'
    response = client.post(f"/api/v1/disposition/tasks/{t['id']}/review-decision", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['next_recipients'] == [{'kind': 'role_queue' if shared else 'person', 'name': ('فريق المراجعة' if shared else 'المراجع التالي') if language == 'ar' else expected}]
    # Exact retry must not create a second decision or infer an arbitrary user.
    again = client.post(f"/api/v1/disposition/tasks/{t['id']}/review-decision", json=payload, headers=headers)
    assert again.status_code == 200 and again.json()['next_recipients'] == response.json()['next_recipients']
