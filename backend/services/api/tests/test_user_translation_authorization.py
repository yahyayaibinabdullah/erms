"""User translations share ordinary identity administration; disposable DB only."""
import os
from pathlib import Path
from uuid import uuid4
import psycopg
import pytest
from backend.services.api.tests.test_global_privilege_enforcement import _account,_bearer


@pytest.mark.parametrize('privileges,allowed',[
    (('identity.users.administer',),True),
    (('localization.administer',),False),
    ((),False),
])
def test_localized_user_names_use_user_administration(client,privileges,allowed):
    token,_,_=_account(client,privileges=privileges,suffix='user-translation')
    headers=_bearer(token)
    response=client.get('/api/v1/entity-translations/users/1/ar',headers=headers)
    assert response.status_code==(200 if allowed else 403),response.text
    if not allowed:
        rejected=client.patch('/api/v1/entity-translations/users/1/ar',json={'name':'اسم غير مصرح'},headers={**headers,'If-Match':'1','X-Change-Reason':'Verify denial'})
        assert rejected.status_code==403,rejected.text
        return
    current=response.json()
    saved=client.patch('/api/v1/entity-translations/users/1/ar',json={'name':'اسم المستخدم بالعربية'},headers={**headers,'If-Match':str(current['version']),'X-Change-Reason':'User administrator maintains localized name'})
    assert saved.status_code==200,saved.text
    assert saved.json()['fields']['name']=='اسم المستخدم بالعربية'
    assert saved.json()['canonical']==current['canonical']
    assert saved.json()['version']>current['version']
    stale=client.patch('/api/v1/entity-translations/users/1/ar',json={'name':'تعديل قديم'},headers={**headers,'If-Match':str(current['version']),'X-Change-Reason':'Verify stale version protection'})
    assert stale.status_code==409,stale.text


def test_retirement_removes_old_grants_without_promoting_profiles_and_preserves_history(client):
    migration=Path(__file__).resolve().parents[4]/'database/migrations/090_unify_user_translation_authorization.sql'
    with psycopg.connect(os.environ['DATABASE_URL'],autocommit=True) as c:
        assert c.execute('SELECT current_database()').fetchone()[0].startswith('erms_messaging_test_acl_')
        c.execute("SELECT set_config('app.actor_type','automated_process',false),set_config('app.event_source','api',false),set_config('app.change_reason','Disposable legacy privilege retirement fixture',false)")
        c.execute("INSERT INTO privileges(code,name,description,category,is_reserved,account_type_restriction) VALUES('user.modify_metadata','Legacy user translation','Disposable retired-privilege fixture','administration',false,'person') ON CONFLICT DO NOTHING")
        old=c.execute("SELECT id FROM privileges WHERE code='user.modify_metadata'").fetchone()[0]
        profile=c.execute("INSERT INTO profiles(code,name) VALUES(%s,'Legacy narrow translator') RETURNING id",('LEGACY_'+uuid4().hex,)).fetchone()[0]
        c.execute('INSERT INTO profile_privileges(profile_id,privilege_id) VALUES(%s,%s)',(profile,old))
        before=c.execute("SELECT count(*) FROM event_history WHERE metadata::text LIKE '%user.modify_metadata%' OR before_state::text LIKE '%user.modify_metadata%' OR after_state::text LIKE '%user.modify_metadata%'").fetchone()[0]
        c.execute(migration.read_text(),prepare=False)
        assert not c.execute("SELECT 1 FROM privileges WHERE code='user.modify_metadata'").fetchone()
        assert not c.execute('SELECT 1 FROM profile_privileges WHERE profile_id=%s',(profile,)).fetchone()
        assert not c.execute('SELECT 1 FROM privilege_dependencies WHERE privilege_id=%s OR required_privilege_id=%s',(old,old)).fetchone()
        after=c.execute("SELECT count(*) FROM event_history WHERE metadata::text LIKE '%user.modify_metadata%' OR before_state::text LIKE '%user.modify_metadata%' OR after_state::text LIKE '%user.modify_metadata%'").fetchone()[0]
        assert after>=before>0
        c.execute(migration.read_text(),prepare=False)
