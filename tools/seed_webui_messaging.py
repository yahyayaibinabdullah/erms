"""Temporary recipient capability for disposable mailbox acceptance tests only."""
import json
import sys
import psycopg
from tools.seed_webui_regression import disposable_url


def seed():
    with psycopg.connect(disposable_url()) as connection:
        connection.execute("SELECT set_config('app.event_source','seeding',true)")
        assignment = connection.execute("INSERT INTO user_role_assignments(user_id,role_id) SELECT u.id,r.id FROM users u CROSS JOIN roles r WHERE u.email='officer@test.invalid' AND r.code='admin' RETURNING id").fetchone()[0]
        return {'assignment_id': assignment}


def cleanup(saved):
    with psycopg.connect(disposable_url()) as connection:
        connection.execute("SELECT set_config('app.event_source','seeding',true)")
        connection.execute('DELETE FROM user_role_assignments WHERE id=%s', (saved['assignment_id'],))


if __name__ == '__main__':
    if sys.argv[1:] == ['cleanup']:
        cleanup(json.load(sys.stdin))
    else:
        print(json.dumps(seed()))
