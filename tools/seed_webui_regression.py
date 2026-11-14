"""Small synthetic fixture for the disposable assembled-application tests."""
import os

import psycopg
from psycopg.conninfo import conninfo_to_dict


BASELINE_TIME = '2026-01-01T00:00:00Z'


def disposable_url():
    url = os.environ['DATABASE_URL']
    if not conninfo_to_dict(url)['dbname'].startswith('erms_webui_test_'):
        raise RuntimeError('This fixture requires the disposable WebUI runner')
    return url


def seed(*, browser=False, contextual_acls=False):
    url = disposable_url()
    from backend.services.api.authentication import hash_password
    with psycopg.connect(url) as connection:
        connection.execute("SELECT set_config('app.event_source','seeding',true)")
        unit = connection.execute("INSERT INTO org_units(code,name) VALUES('WEBUI-TEST','WebUI test unit') RETURNING id").fetchone()[0]
        for email, name, profile in [('admin@test.invalid', 'Test administrator', 'ALL_PRIVS'),
                                     ('officer@test.invalid', 'Test officer', 'INFO_GOV_OFFICER'),
                                     ('viewer@test.invalid', 'Test viewer', None)]:
            user = connection.execute('INSERT INTO users(name,email) VALUES(%s,%s) RETURNING id', (name, email)).fetchone()[0]
            connection.execute('INSERT INTO user_credentials(user_id,password_hash,must_change_password) VALUES(%s,%s,false)',
                               (user, hash_password('Temporary-Test-Password-123!')))
            if profile:
                role = connection.execute("INSERT INTO roles(org_unit_id,code,name,profile_id,security_level_id,is_information_governance) SELECT %s,%s,%s,p.id,l.id,true FROM profiles p CROSS JOIN security_levels l WHERE p.code=%s AND l.level_number=(SELECT max(level_number) FROM security_levels) RETURNING id",
                                          (unit, email.split('@')[0], name, profile)).fetchone()[0]
                connection.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)', (user, role))
        for i in range(1, 29):
            connection.execute("INSERT INTO classification_schemes(code,title,date_created,date_published) VALUES(%s,%s,%s,%s)", (f'T{i:02}', f'Test scheme {i}', BASELINE_TIME, BASELINE_TIME))
        scheme = connection.execute("SELECT id FROM classification_schemes WHERE code='T01'").fetchone()[0]
        terminal = connection.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal,date_created) VALUES(%s,'TERM','Test terminal',true,%s) RETURNING id", (scheme, BASELINE_TIME)).fetchone()[0]
        connection.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES(%s,5,0,'destruction')", (terminal,))
        if contextual_acls:
            # Use the normal creation trigger to populate both contextual principals.
            creator = connection.execute(
                "SELECT id FROM roles WHERE org_unit_id=%s AND code='admin'", (unit,),
            ).fetchone()[0]
            connection.execute("SELECT set_config('app.creator_acl_role_id', %s, true)", (str(creator),))
        aggregation = connection.execute("INSERT INTO aggregations(aggregation_number,title,classification_id,owning_org_unit_id,medium,date_created,date_opened) VALUES('TEST-AGG','Test aggregation',%s,%s,'physical',%s,%s) RETURNING id", (terminal, unit, BASELINE_TIME, BASELINE_TIME)).fetchone()[0]
        connection.execute("INSERT INTO records(aggregation_id,record_number,title,medium,date_created,date_originated) VALUES(%s,'TEST-REC','Test record','physical',%s,%s)", (aggregation, BASELINE_TIME, BASELINE_TIME))
        if browser:
            # Enough rows for real server/branch pagination, with stable dates.
            for i in range(1, 29):
                branch = connection.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal,date_created) VALUES(%s,%s,%s,false,%s) RETURNING id",
                                            (scheme, f'B{i:02}', f'Test branch {i:02}', BASELINE_TIME)).fetchone()[0]
                if i == 1:
                    for child in range(1, 29):
                        connection.execute("INSERT INTO classifications(classification_scheme_id,parent_classification_id,code,title,is_terminal,date_created) VALUES(%s,%s,%s,%s,true,%s)",
                                           (scheme, branch, f'C{child:02}', f'Test child {child:02}', BASELINE_TIME))
                    connection.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES(%s,5,0,'destruction')", (branch,))
    if browser:
        prepare_browser_languages_and_settings()


def prepare_browser_languages_and_settings():
    """Publish checked-in wording only inside the newly created test database."""
    disposable_url()
    from backend.services.api.main import app
    from backend.services.api.localization import synchronize_generated_arabic_drafts
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        client.headers['X-Event-Source'] = 'seeding'
        login = client.post('/api/v1/auth/login', json={
            'email': 'admin@test.invalid', 'password': 'Temporary-Test-Password-123!'})
        login.raise_for_status()
        client.headers['X-CSRF-Token'] = client.cookies['erms_csrf']
        synchronize_generated_arabic_drafts()
        preview = client.get('/api/v1/admin/i18n/translations/ar/bulk-publication-preview').json()
        assert not preview['invalid']
        client.post('/api/v1/admin/i18n/translations/ar/bulk-review-publish',
                    json={'items': preview['items']},
                    headers={'X-Change-Reason': 'Publish disposable browser fixture'}).raise_for_status()
        settings = {i['key']: i for i in client.get('/api/v1/application-settings').json()['items']}
        values = {'DEFAULT_WORKING_TIMEZONE': 'UTC', 'FULL_TEXT_SEARCH_ENABLED': True}
        client.put('/api/v1/application-settings', json={'changes': [
            {'key': key, 'expected_version': settings[key]['version'], 'value': value}
            for key, value in values.items()]}, headers={
                'X-Change-Reason': 'Configure reproducible disposable browser fixture'}).raise_for_status()


if __name__ == '__main__':
    seed()
