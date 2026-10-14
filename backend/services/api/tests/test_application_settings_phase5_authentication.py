"""Runtime authentication policies never revive expired sessions or invalidate hashes."""
from datetime import datetime,timedelta,timezone
import secrets
import pytest
from backend.services.api.authentication import hash_secret,resolve_principal
from backend.services.api import session_cleanup,manage_auth
from backend.services.api.tests.test_application_settings_phase4 import db,save,items,plan_for,apply_plan
from backend.services.api import application_settings_migration as migration

PASSWORD='Temporary-Test-Password-123!'


def make_session(*,age_hours=2,last_seen_minutes=0,expired=False):
    token=secrets.token_urlsafe(32);now=datetime.now(timezone.utc)
    with db() as c:
        row=c.execute('INSERT INTO login_sessions(user_id,session_token_hash,csrf_token_hash,date_created,last_seen_at,expires_at,absolute_expires_at) VALUES(1,%s,%s,%s,%s,%s,%s) RETURNING id',
            (hash_secret(token),hash_secret(secrets.token_urlsafe(32)),now-timedelta(hours=age_hours),
             now-timedelta(minutes=last_seen_minutes),now+timedelta(minutes=-1 if expired else 20),now+timedelta(hours=10))).fetchone()
    return token,row['id']


def session(row_id):
    with db() as c:return c.execute('SELECT * FROM login_sessions WHERE id=%s',(row_id,)).fetchone()


def test_active_session_uses_new_idle_absolute_policy_and_expired_never_revives(client,monkeypatch):
    for key in migration.AUTHENTICATION_KEYS:monkeypatch.setenv(key,'invalid-obsolete-auth-policy')
    token,row_id=make_session()
    assert save(client,{'AUTH_SESSION_IDLE_MINUTES':45,'AUTH_SESSION_ABSOLUTE_HOURS':24}).status_code==200
    now=datetime.now(timezone.utc)
    with db() as c:assert resolve_principal(c,token) is not None
    row=session(row_id)
    assert 44*60 < (row['expires_at']-now).total_seconds() <= 45*60
    assert 21*3600 < (row['absolute_expires_at']-now).total_seconds() <= 22*3600
    expired,expired_id=make_session(expired=True);before=session(expired_id)
    with db() as c:assert resolve_principal(c,expired) is None
    assert session(expired_id)==before
    assert save(client,{'AUTH_SESSION_IDLE_MINUTES':120,'AUTH_SESSION_ABSOLUTE_HOURS':48}).status_code==200
    with db() as c:assert resolve_principal(c,expired) is None
    assert session(expired_id)==before


@pytest.mark.parametrize('policy', ['idle','absolute'])
def test_shortened_lifetime_persists_expiry_before_later_increase(client,policy):
    token,row_id=make_session(age_hours=2,last_seen_minutes=2)
    change={'AUTH_SESSION_IDLE_MINUTES':1} if policy=='idle' else {'AUTH_SESSION_ABSOLUTE_HOURS':1}
    assert save(client,change).status_code==200
    with db() as c:assert resolve_principal(c,token) is None
    assert session(row_id)['expires_at']<=datetime.now(timezone.utc)
    assert save(client,{'AUTH_SESSION_IDLE_MINUTES':60,'AUTH_SESSION_ABSOLUTE_HOURS':24}).status_code==200
    with db() as c:assert resolve_principal(c,token) is None


def test_lockout_and_new_password_policy_refresh_preserves_existing_hash(client):
    assert save(client,{'AUTH_LOCKOUT_ATTEMPTS':2,'AUTH_LOCKOUT_MINUTES':3,'AUTH_PASSWORD_MIN_LENGTH':40}).status_code==200
    with db() as c:before=c.execute('SELECT password_hash FROM user_credentials WHERE user_id=1').fetchone()['password_hash']
    response=client.post('/api/v1/auth/login',json={'email':'admin@test.invalid','password':PASSWORD})
    assert response.status_code==200 # Existing shorter hash is still accepted.
    client.headers['X-CSRF-Token']=client.cookies.get('erms_csrf')
    response=client.post('/api/v1/auth/change-password',json={'current_password':PASSWORD,'new_password':'x'*39})
    assert response.status_code==422
    with db() as c:assert c.execute('SELECT password_hash FROM user_credentials WHERE user_id=1').fetchone()['password_hash']==before
    for attempt in range(2):
        response=client.post('/api/v1/auth/login',json={'email':'admin@test.invalid','password':'wrong'})
        assert response.status_code==401
        with db() as c:
            credential=c.execute('SELECT failed_attempt_count,locked_until FROM user_credentials WHERE user_id=1').fetchone()
        assert credential['failed_attempt_count']==attempt+1
        assert (credential['locked_until'] is not None)==(attempt==1)
    assert 175 < (credential['locked_until']-datetime.now(timezone.utc)).total_seconds() <= 180
    assert client.post('/api/v1/auth/login',json={'email':'admin@test.invalid','password':PASSWORD}).status_code==401
    # Credential lock does not revoke the current authenticated session.
    assert client.get('/api/v1/auth/me').status_code==200
    assert client.get('/api/v1/application-settings').status_code==403 # Existing authorization lock gate remains intact.
    with db() as c:c.execute("UPDATE user_credentials SET locked_until=CURRENT_TIMESTAMP-interval '1 second' WHERE user_id=1")
    assert save(client,{'AUTH_PASSWORD_MIN_LENGTH':8}).status_code==200
    response=client.post('/api/v1/auth/change-password',json={'current_password':PASSWORD,'new_password':'New-Valid-123!'})
    assert response.status_code==204
    with db() as c:
        assert c.execute('SELECT password_hash FROM user_credentials WHERE user_id=1').fetchone()['password_hash']!=before
        history=c.execute("SELECT coalesce(string_agg(metadata::text,''),'') AS text FROM event_history").fetchone()['text']
        assert 'New-Valid-123!' not in history and '$argon2' not in history


def test_temporary_password_api_and_recovery_use_database_minimum(client):
    assert save(client,{'AUTH_PASSWORD_MIN_LENGTH':64}).status_code==200
    response=client.post('/api/v1/users',json={'name':'Temporary fixture','email':'phase5@test.invalid','account_type':'person'})
    assert response.status_code==201
    issued=client.post(f"/api/v1/auth/users/{response.json()['id']}/temporary-password")
    assert issued.status_code==200 and len(issued.json()['temporary_password'])>=64
    with db() as c:
        recovery=manage_auth.set_temporary_password(c,'phase5@test.invalid',make_admin=False,org_unit_code=None)
    assert len(recovery)>=64


def test_session_cleanup_database_retention_batch_interval_overrides_and_large_values(client,monkeypatch):
    expired_ids=[]
    for _ in range(3):expired_ids.append(make_session(expired=True)[1])
    assert save(client,{'AUTH_SESSION_RETENTION_DAYS':1,'AUTH_SESSION_CLEANUP_BATCH_SIZE':1,'AUTH_SESSION_CLEANUP_INTERVAL_SECONDS':7}).status_code==200
    result,interval=session_cleanup._run_pass(dry_run=True)
    assert result.selected==0 and interval==7
    assert save(client,{'AUTH_SESSION_RETENTION_DAYS':0,'AUTH_SESSION_CLEANUP_INTERVAL_SECONDS':9}).status_code==200
    result,interval=session_cleanup._run_pass(watch=True)
    assert result.removed==1 and interval==9
    with db() as c:
        assert c.execute('SELECT count(*) AS n FROM login_sessions WHERE id=ANY(%s)',(expired_ids,)).fetchone()['n']==2
        assert c.execute("SELECT count(*) AS n FROM event_history WHERE operation='SESSION_EXPIRED'").fetchone()['n']==1
    result,interval=session_cleanup._run_pass(retention_days=0,batch_size=5,dry_run=True,interval_seconds=2)
    assert result.selected==2 and interval==2
    assert save(client,{'AUTH_SESSION_RETENTION_DAYS':9223372036854775807}).status_code==200
    assert session_cleanup._run_pass(dry_run=True)[0].selected==0
    called=[]
    monkeypatch.setattr(session_cleanup,'cleanup_sessions',lambda *a,**k:called.append(True))
    def fail(*args):raise RuntimeError('fixture_unavailable')
    monkeypatch.setattr(session_cleanup,'load_snapshot',fail)
    with pytest.raises(RuntimeError):session_cleanup.run_once()
    assert called==[]


def test_auth_migration_extends_completed_content_without_reimporting(client,tmp_path,monkeypatch):
    original=migration.MIGRATED_KEYS
    path=tmp_path/'legacy.env';path.write_text('MAX_UPLOAD_SIZE_BYTES=12345\nAUTH_PASSWORD_MIN_LENGTH=20\nAUTH_SESSION_RETENTION_DAYS=0\n')
    monkeypatch.setattr(migration,'MIGRATED_KEYS',migration.GENERAL_INTERFACE_KEYS+migration.CONTENT_KEYS)
    apply_plan(plan_for(path),path)
    before=items(client)['MAX_UPLOAD_SIZE_BYTES']
    monkeypatch.setattr(migration,'MIGRATED_KEYS',original)
    path.write_text('MAX_UPLOAD_SIZE_BYTES=invalid-later-edit\nAUTH_PASSWORD_MIN_LENGTH=20\nAUTH_SESSION_RETENTION_DAYS=0\n')
    apply_plan(plan_for(path),path)
    assert items(client)['MAX_UPLOAD_SIZE_BYTES']==before
    assert items(client)['AUTH_PASSWORD_MIN_LENGTH']['value']==20 and items(client)['AUTH_SESSION_RETENTION_DAYS']['value']==0


def test_valid_large_session_lifetimes_and_idle_above_absolute_are_safe(client):
    assert save(client,{'AUTH_SESSION_IDLE_MINUTES':120,'AUTH_SESSION_ABSOLUTE_HOURS':1}).status_code==200
    response=client.post('/api/v1/auth/login',json={'email':'admin@test.invalid','password':PASSWORD})
    assert response.status_code==200,response.text
    client.headers['X-CSRF-Token']=client.cookies.get('erms_csrf')
    with db() as c:
        row=c.execute('SELECT expires_at,absolute_expires_at FROM login_sessions WHERE id=%s',(response.json()['session']['id'],)).fetchone()
    assert row['expires_at']==row['absolute_expires_at']
    assert save(client,{'AUTH_SESSION_IDLE_MINUTES':9223372036854775807,'AUTH_SESSION_ABSOLUTE_HOURS':9223372036854775807}).status_code==200
    response=client.post('/api/v1/auth/login',json={'email':'admin@test.invalid','password':PASSWORD})
    assert response.status_code==200,response.text
    client.headers['X-CSRF-Token']=client.cookies.get('erms_csrf')
    assert client.get('/api/v1/auth/me').status_code==200
    with db() as c:
        row=c.execute('SELECT expires_at,absolute_expires_at FROM login_sessions WHERE id=%s',(response.json()['session']['id'],)).fetchone()
    assert row['expires_at'].year==row['absolute_expires_at'].year==9999


def test_standalone_cleanup_workers_block_unreviewed_upgrade_then_accept_completion(client,tmp_path):
    from backend.services.api import content_cleanup
    path=tmp_path/'legacy.env';path.write_text('')
    try:
        with db() as c:
            c.execute('ALTER TABLE application_settings_state DISABLE TRIGGER application_settings_state_immutable')
            c.execute("UPDATE application_settings_state SET installation_kind='upgrade'")
            c.execute('ALTER TABLE application_settings_state ENABLE TRIGGER application_settings_state_immutable')
        for worker,kwargs in [(content_cleanup,{'batch_size':1,'dry_run':True}),(session_cleanup,{'dry_run':True})]:
            with pytest.raises(migration.MigrationInvalid,match='migration_incomplete'):worker._run_pass(**kwargs)
        apply_plan(plan_for(path),path)
        assert content_cleanup._run_pass(batch_size=1,dry_run=True)[1]>0
        assert session_cleanup._run_pass(dry_run=True)[1]>0
    finally:
        with db() as c:
            c.execute('ALTER TABLE application_settings_state DISABLE TRIGGER application_settings_state_immutable')
            c.execute("UPDATE application_settings_state SET installation_kind='fresh'")
            c.execute('ALTER TABLE application_settings_state ENABLE TRIGGER application_settings_state_immutable')
