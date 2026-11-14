"""Reviewer assignments for the disposable WebUI disposition acceptance fixture."""
import json
import sys
import psycopg
from psycopg.rows import dict_row
from tools.seed_webui_regression import disposable_url


def seed():
    from backend.services.api.tests.test_disposition_foundation import ensure_officer
    with psycopg.connect(disposable_url(), row_factory=dict_row) as connection:
        connection.execute("SELECT set_config('app.event_source','seeding',true)")
        user = connection.execute("SELECT id FROM users WHERE email='admin@test.invalid'").fetchone()['id']
        role = connection.execute("SELECT id,org_unit_id FROM roles WHERE code='admin'").fetchone()
        previous = connection.execute('SELECT file_administrator_role_id,managing_role_id FROM org_units WHERE id=%s', (role['org_unit_id'],)).fetchone()
        assigned = connection.execute("SELECT 1 FROM user_role_assignments a JOIN roles r ON r.id=a.role_id WHERE r.code='fixture-records-officer' AND a.user_id=%s", (user,)).fetchone() is not None
        ensure_officer(connection, user)
        # Both designations have an active assigned user and remain subject to
        # the canonical creation/review gates. No trigger or validation bypass.
        connection.execute('UPDATE org_units SET file_administrator_role_id=%s,managing_role_id=%s WHERE id=%s',
                           (role['id'], role['id'], role['org_unit_id']))

    return dict(user=user, unit=role['org_unit_id'], assigned_before=assigned, previous=previous)


def cleanup(before):
    with psycopg.connect(disposable_url()) as connection:
        connection.execute("SELECT set_config('app.event_source','seeding',true)")
        if not before['assigned_before']:
            connection.execute("DELETE FROM user_role_assignments WHERE user_id=%s AND role_id=(SELECT id FROM roles WHERE code='fixture-records-officer')", (before['user'],))
        connection.execute('UPDATE org_units SET file_administrator_role_id=%s,managing_role_id=%s WHERE id=%s',
                           (before['previous']['file_administrator_role_id'],before['previous']['managing_role_id'],before['unit']))


if __name__ == '__main__':
    if sys.argv[1:] == ['cleanup']:cleanup(json.load(sys.stdin))
    else:print(json.dumps(seed()))
