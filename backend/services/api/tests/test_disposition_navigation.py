"""Navigation reflects configured workflow roles, never role display names."""
import pytest
from backend.services.api.tests.test_disposition_membership import db, actor


def capability(client):
    response = client.get('/api/v1/auth/me')
    assert response.status_code == 200, response.text
    return response.json()['can_access_disposition_tasks']


@pytest.mark.parametrize('column', ['file_administrator_role_id', 'managing_role_id'])
def test_navigation_tracks_configured_role_and_assignment_expiry(client, column):
    assert capability(client)  # Effective Information Governance manager.
    with db() as c:
        actor(c)
        c.execute('UPDATE roles SET is_information_governance=false WHERE id=1')
    assert not capability(client)  # Broad privileges alone do not qualify.
    with db() as c:
        actor(c)
        c.execute(f'UPDATE org_units SET {column}=1 WHERE id=1')
    assert capability(client)  # Configured reviewer; no tasks required.
    with db() as c:
        actor(c)
        c.execute(f'UPDATE org_units SET {column}=NULL WHERE id=1')
    assert not capability(client)
    with db() as c:
        actor(c)
        c.execute(f'UPDATE org_units SET {column}=1 WHERE id=1')
        c.execute("UPDATE user_role_assignments SET valid_from=CURRENT_TIMESTAMP - interval '2 days', valid_until=CURRENT_TIMESTAMP - interval '1 day' WHERE user_id=1 AND role_id=1")
    assert not capability(client)
