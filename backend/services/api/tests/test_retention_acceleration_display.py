"""Retention provenance reads against the runner's disposable database only."""
from datetime import timezone

import pytest
from fastapi import HTTPException

from backend.services.api.classification_management import effective_aggregation_rule
from backend.services.api.disposition import membership as service
from backend.services.api.tests.test_disposition_membership import (
    actor, db, setup, ready, kwargs, version, rule_change, admit, remove,
)


def read(client, identity):
    response = client.get(f'/api/v1/aggregations/{identity}/effective-retention-rule')
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize('action', ['destruction', 'transfer_to_external_archive', 'selective_preservation', 'retain_as_local_archives'])
def test_existing_acceleration_is_visible_on_root_and_descendants(client, action):
    with db() as c:
        setup(c)
        root, child, *_ = ready(c, action, closed=None)
    assert read(client, root)['acceleration'] is None
    with db() as c:
        actor(c)
        service.accelerate(c, **kwargs(root_id=root, expected_version=version(c, root)))
        event = c.execute("SELECT * FROM event_history WHERE entity_id=%s AND operation='DISPOSITION_ACCELERATED'", (root,)).fetchone()
        # The display must use the immutable actor snapshot, not today's name.
        c.execute("UPDATE users SET name='Renamed administrator' WHERE id=1")
    for identity in (root, child):
        result = read(client, identity)
        assert result['current_period_years'] == 5
        assert result['acceleration'] == dict(event_id=event['id'], occurred_at=event['occurred_at'].astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'), actor_name=event['actor_name'], reason=event['reason'])


@pytest.mark.parametrize('invalidate', ['reopen', 'changed_rule'])
def test_invalidated_acceleration_does_not_reappear_on_later_natural_eligibility(client, invalidate):
    with db() as c:
        setup(c)
        root, *_ = ready(c, closed=None)
        service.accelerate(c, **kwargs(root_id=root, expected_version=version(c, root)))
    assert read(client, root)['acceleration']
    with db() as c:
        actor(c)
        if invalidate == 'reopen':
            c.execute('UPDATE aggregations SET date_closed=NULL WHERE id=%s', (root,))
        else:
            rule_change(c, root, years=10)
    assert read(client, root)['acceleration'] is None
    with db() as c:
        actor(c)
        if invalidate == 'reopen':
            c.execute("UPDATE aggregations SET date_closed='2020-01-01' WHERE id=%s", (root,))
        rule_change(c, root, years=0)
    assert read(client, root)['acceleration'] is None


def test_same_rule_and_job_admission_preserve_provenance_but_new_acceleration_replaces_it(client):
    with db() as c:
        job = setup(c)
        root, *_ = ready(c, closed=None)
        service.accelerate(c, **kwargs(root_id=root, expected_version=version(c, root)))
    original = read(client, root)['acceleration']
    with db() as c:
        actor(c)
        rule_change(c, root, years=5)
        admit(c, job['id'], [root])
    assert read(client, root)['acceleration'] == original
    with db() as c:
        actor(c)
        remove(c, root)
        c.execute('UPDATE aggregations SET date_closed=NULL WHERE id=%s', (root,))
        service.accelerate(c, **{**kwargs(root_id=root, expected_version=version(c, root)), 'reason': 'Second acceleration'})
    assert read(client, root)['acceleration']['event_id'] > original['event_id']
    assert read(client, root)['acceleration']['reason'] == 'Second acceleration'


def test_unauthorized_resource_does_not_expose_acceleration(client):
    with db() as c:
        setup(c)
        root, *_ = ready(c, closed=None)
        service.accelerate(c, **kwargs(root_id=root, expected_version=version(c, root)))
        user = c.execute("INSERT INTO users(name,email) VALUES('No permissions','none@test.invalid') RETURNING id").fetchone()['id']
        actor(c, user=user)
        with pytest.raises(HTTPException) as caught:
            effective_aggregation_rule(root, None, c)
        assert caught.value.status_code in (403, 404)


def test_acceleration_actor_translation_uses_viewer_language_without_changing_history(client):
    from psycopg.types.json import Jsonb
    with db() as c:
        setup(c);root,*_=ready(c,closed=None)
        service.accelerate(c,**kwargs(root_id=root,expected_version=version(c,root)))
        event=c.execute("SELECT id,actor_name FROM event_history WHERE entity_id=%s AND operation='DISPOSITION_ACCELERATED'",(root,)).fetchone()
        c.execute('UPDATE users SET translations=%s WHERE id=1',(Jsonb({'ar':{'name':'يحيى عبدالله'}}),))
        c.execute("INSERT INTO user_preferences(user_id,language_tag,working_timezone) VALUES(1,'ar','Asia/Dubai') ON CONFLICT(user_id) DO UPDATE SET language_tag='ar'")
    assert read(client,root)['acceleration']['actor_name']=='يحيى عبدالله'
    assert client.get('/api/v1/disposition/eligibility').json()['items'][0]['acceleration']['actor_name']=='يحيى عبدالله'
    with db() as c:
        assert c.execute('SELECT actor_name FROM event_history WHERE id=%s',(event['id'],)).fetchone()['actor_name']==event['actor_name']
        c.execute("UPDATE user_preferences SET language_tag='en' WHERE user_id=1")
    assert read(client,root)['acceleration']['actor_name']==event['actor_name']
    with db() as c:
        c.execute("UPDATE users SET translations='{}' WHERE id=1")
        c.execute("UPDATE user_preferences SET language_tag='ar' WHERE user_id=1")
    assert read(client,root)['acceleration']['actor_name']==event['actor_name']
