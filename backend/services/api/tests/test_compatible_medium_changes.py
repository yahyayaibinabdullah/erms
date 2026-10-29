"""Approved compatible medium changes; run only with the disposable DB runner."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
import os

import psycopg
from psycopg.rows import dict_row
import pytest

from backend.services.api.tests.test_disposition_membership import actor
from backend.services.api.tests.test_disposition_eligibility import wait_for_waiter


def db():
    return psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row)


def root(client, medium='mixed'):
    result = client.post('/api/v1/aggregations', json={
        'aggregation_number': 'COMPATIBLE-1', 'title': 'Compatible change',
        'classification_id': 1, 'medium': medium,
    })
    assert result.status_code == 201, result.text
    return result.json()


def record(client, parent, medium, number='R-1'):
    result = client.post('/api/v1/records', json={
        'aggregation_id': parent['id'], 'record_number': number,
        'title': medium.title(), 'medium': medium,
    })
    assert result.status_code == 201, result.text
    return result.json()


def change(client, parent, medium, reason='Correct description of holdings'):
    headers = {'If-Match': str(parent['version'])}
    if reason:
        headers['X-Change-Reason'] = reason
    return client.patch(f"/api/v1/aggregations/{parent['id']}", json={'medium': medium}, headers=headers)


@pytest.mark.parametrize('contained', ['digital', 'physical', 'mixed'])
@pytest.mark.parametrize('target', ['digital', 'physical', 'mixed'])
def test_nonempty_record_compatibility_matrix(client, contained, target):
    parent = root(client)
    child = record(client, parent, contained)
    result = change(client, parent, target)
    allowed = target == 'mixed' or target == contained
    assert result.status_code == (200 if allowed else 422), result.text
    current = client.get(f"/api/v1/aggregations/{parent['id']}").json()
    assert current['medium'] == (target if allowed else 'mixed')
    if not allowed:
        assert result.json()['detail']['code'] == 'aggregation_medium_contents_conflict'
        assert current['version'] == parent['version']
    assert client.get(f"/api/v1/records/{child['id']}").json() == child


def test_digital_to_mixed_preserves_records_components_and_audits_reason(client):
    parent = root(client, 'digital')
    children = [record(client, parent, 'digital', f'R-{i}') for i in range(2)]
    upload = client.post(f"/api/v1/records/{children[0]['id']}/digital-components/upload",
                        data={'component_order': '1'}, files={'file': ('content.txt', b'unchanged digital content', 'text/plain')})
    assert upload.status_code == 201, upload.text
    with db() as c:
        before_records = c.execute('SELECT * FROM records ORDER BY id').fetchall()
        before_components = c.execute('SELECT * FROM digital_components ORDER BY id').fetchall()
    result = change(client, parent, 'mixed')
    assert result.status_code == 200, result.text
    with db() as c:
        assert c.execute('SELECT * FROM records ORDER BY id').fetchall() == before_records
        assert c.execute('SELECT * FROM digital_components ORDER BY id').fetchall() == before_components
        event = c.execute("SELECT * FROM event_history WHERE entity_type='aggregation' AND entity_id=%s AND operation='MEDIUM_CHANGED'", (parent['id'],)).fetchone()
        assert event['metadata']['old_medium'] == 'digital'
        assert event['metadata']['new_medium'] == 'mixed'
        assert event['reason'] == 'Correct description of holdings'
        assert event['actor_user_id'] == 1


def test_children_remain_equal_to_parent_and_no_cascade(client):
    parent = root(client)
    child = client.post('/api/v1/aggregations', json={
        'aggregation_number': 'CHILD', 'title': 'Child', 'parent_aggregation_id': parent['id'],
    }).json()
    result = change(client, parent, 'digital')
    assert result.status_code == 422
    assert result.json()['detail']['code'] == 'aggregation_medium_contents_conflict'
    assert client.get(f"/api/v1/aggregations/{child['id']}").json() == child
    result = change(client, child, 'digital')
    assert result.status_code == 422
    assert result.json()['detail']['code'] == 'aggregation_medium_mismatch'


def test_incompatible_draft_blocks_change_and_reason_is_still_required(client):
    parent = root(client)
    assert change(client, parent, 'digital', reason=None).json()['detail']['code'] == 'medium_change_reason_required'
    with db() as c:
        actor(c)
        c.execute("INSERT INTO record_drafts(owner_user_id,aggregation_id,title,medium) VALUES(1,%s,'Physical draft','physical')", (parent['id'],))
    result = change(client, parent, 'digital')
    assert result.status_code == 422
    assert result.json()['detail']['code'] == 'aggregation_medium_contents_conflict'
    with db() as c:
        assert c.execute('SELECT medium FROM aggregations WHERE id=%s', (parent['id'],)).fetchone()['medium'] == 'mixed'
        assert c.execute('SELECT medium FROM record_drafts').fetchone()['medium'] == 'physical'


@pytest.mark.parametrize('first', ['medium', 'record'])
def test_concurrent_medium_and_record_insert_revalidate_after_waiting(client, first):
    parent = root(client)
    queue = Queue()
    def mutate(c, kind):
        actor(c)
        if kind == 'medium':
            c.execute("UPDATE aggregations SET medium='digital' WHERE id=%s", (parent['id'],))
        else:
            c.execute("INSERT INTO records(aggregation_id,record_number,title,medium) VALUES(%s,'RACE','Physical record','physical')", (parent['id'],))
    def worker():
        try:
            with db() as c:
                queue.put(c.info.backend_pid)
                mutate(c, 'record' if first == 'medium' else 'medium')
        except psycopg.errors.CheckViolation as error:
            return error.diag.constraint_name
        return 'unexpected success'
    with ThreadPoolExecutor(max_workers=1) as pool, db() as owner:
        mutate(owner, first)
        future = pool.submit(worker)
        try:
            wait_for_waiter(owner, queue.get(timeout=5))
        finally:
            owner.commit()
        assert future.result(timeout=10) == (
            'record_medium_not_allowed_by_parent' if first == 'medium' else 'aggregation_medium_contents_conflict')
    with db() as c:
        assert c.execute('SELECT medium FROM aggregations WHERE id=%s', (parent['id'],)).fetchone()['medium'] == ('digital' if first == 'medium' else 'mixed')
        assert c.execute('SELECT count(*) AS n FROM records').fetchone()['n'] == (0 if first == 'medium' else 1)


def test_upgrade_is_idempotent_and_preserves_existing_data(client):
    parent = root(client, 'digital')
    record(client, parent, 'digital')
    path = Path(__file__).resolve().parents[4] / 'database/migrations/092_compatible_aggregation_medium_changes.sql'
    with db() as c:
        before = c.execute('SELECT * FROM records').fetchall()
        c.commit()
        for _ in range(2):
            c.execute(path.read_text(), prepare=False)
        assert c.execute('SELECT * FROM records').fetchall() == before
        assert c.execute("SELECT count(*) AS n FROM schema_migrations WHERE version='092_compatible_aggregation_medium_changes'").fetchone()['n'] == 1
    assert change(client, parent, 'mixed').status_code == 200


@pytest.mark.parametrize('initial,target,allowed', [
    ('physical', 'mixed', True), ('digital', 'mixed', True),
    ('physical', 'digital', False), ('digital', 'physical', False),
])
def test_pure_medium_transitions_respect_existing_records(client, initial, target, allowed):
    parent = root(client, initial)
    child = record(client, parent, initial)
    result = change(client, parent, target)
    assert result.status_code == (200 if allowed else 422), result.text
    if not allowed:
        assert result.json()['detail']['code'] == 'aggregation_medium_contents_conflict'
    assert client.get(f"/api/v1/records/{child['id']}").json() == child


@pytest.mark.parametrize('initial,target', [
    ('digital', 'physical'), ('physical', 'digital'),
    ('digital', 'mixed'), ('physical', 'mixed'),
    ('mixed', 'digital'), ('mixed', 'physical'),
])
def test_empty_root_allows_every_medium_transition(client, initial, target):
    parent = root(client, initial)
    result = change(client, parent, target)
    assert result.status_code == 200, result.text
    assert result.json()['medium'] == target
