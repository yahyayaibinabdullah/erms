"""Phase 2 governed settings acceptance; run only with the disposable runner."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys

from cryptography.fernet import Fernet
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from backend.services.api.application_settings import (
    apply_changes, cache, capture_artifact_settings, capture_email_settings,
    capture_job_settings, load_snapshot,
)
from backend.services.api.application_settings_registry import GROUPS, REGISTRY, SettingsInvalid
from backend.services.api.application_settings_routes import SettingChange
from backend.services.api.application_settings_secret import decrypt

PATH = "/api/v1/application-settings"
ROOT = Path(__file__).resolve().parents[4]


def db():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def items(client):
    response = client.get(PATH)
    assert response.status_code == 200, response.text
    return {item["key"]: item for item in response.json()["items"]}


def save(client, values, *, versions=None, group=None, reason="Configure approved application settings"):
    before = items(client)
    keys = set(values) | (set(GROUPS[group]) if group else set())
    changes = [{"key": key, "expected_version": (versions or {}).get(key, before[key]["version"]),
                **({"value": values[key]} if key in values else {})} for key in sorted(keys)]
    return client.put(PATH, headers={"X-Change-Reason": reason}, json={"changes": changes})


def actor(c, user=1):
    c.execute("SELECT set_config('app.user_id',%s,true),set_config('app.actor_type','user',true),set_config('app.event_source','api',true),set_config('app.change_reason','Settings test operation',true)", (str(user),))


def save_smtp(client, *, password=None, clear=False, values=None):
    before = items(client)
    changes = [{"key": key, "expected_version": before[key]["version"],
                **({"value": values[key]} if values and key in values else {})}
               for key in sorted(GROUPS["smtp"])]
    credential = next(change for change in changes if change["key"] == "SMTP_PASSWORD")
    if password is not None:
        credential["secret_value"] = password
    if clear:
        credential["clear_secret"] = True
    return client.put(PATH, headers={"X-Change-Reason": "Configure document email"}, json={"changes": changes})


def test_encrypted_password_is_write_only_and_send_capture_is_fresh(client, monkeypatch, caplog):
    monkeypatch.setenv("APPLICATION_SETTINGS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert save(client, {"DISPOSITION_EXTERNAL_AUTHORITY_EMAIL": "first@example.invalid"}).status_code == 200
    result = save_smtp(client, password="fixture-password-one", values={
        "SMTP_HOST": "smtp.example.invalid", "SMTP_SECURITY": "starttls", "SMTP_AUTH_ENABLED": True,
        "SMTP_USERNAME": "fixture-user", "SMTP_SENDER_EMAIL": "sender@example.invalid"})
    assert result.status_code == 200, result.text
    assert "fixture-password-one" not in result.text
    credential = items(client)["SMTP_PASSWORD"]
    assert credential["secret_is_set"] and credential["value"] is None and credential["effective_value"] is None
    with db() as c:
        ciphertext = bytes(c.execute("SELECT protected_secret FROM application_settings WHERE key='SMTP_PASSWORD'").fetchone()["protected_secret"])
        assert b"fixture-password-one" not in ciphertext and ciphertext.startswith(b"fernet:v1:")
        snapshot = cache.for_connection(c)
        assert "SMTP_PASSWORD" not in snapshot.values and "fixture-password-one" not in repr(snapshot)
        evidence = str(c.execute("SELECT metadata FROM event_history WHERE entity_type='application_setting'").fetchall())
        assert "fixture-password-one" not in evidence and ciphertext.decode() not in evidence
        assert "credential_changed" in evidence
    captured = capture_email_settings(decrypt_secret=decrypt)
    assert captured.password.get_secret_value() == "fixture-password-one"
    assert captured.port == 587 and captured.recipient == "first@example.invalid"
    assert "fixture-password-one" not in repr(captured) and "password" not in captured.safe_values()
    assert save(client, {"DISPOSITION_EXTERNAL_AUTHORITY_EMAIL": "second@example.invalid"}).status_code == 200
    assert save_smtp(client, password="fixture-password-two", values={"SMTP_SECURITY": "implicit_tls"}).status_code == 200
    fresh = capture_email_settings(decrypt_secret=decrypt)
    assert fresh.recipient == "second@example.invalid" and fresh.port == 465
    assert fresh.password.get_secret_value() == "fixture-password-two"
    assert captured.recipient == "first@example.invalid" and captured.password.get_secret_value() == "fixture-password-one"
    monkeypatch.setenv("APPLICATION_SETTINGS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(SettingsInvalid, match="secret_unavailable"):
        capture_email_settings(decrypt_secret=decrypt)
    assert "fixture-password" not in caplog.text and ciphertext.decode() not in caplog.text
    assert save_smtp(client, clear=True).status_code == 422  # Still required by authentication.
    assert save_smtp(client, clear=True, values={"SMTP_AUTH_ENABLED": False}).status_code == 200
    assert not items(client)["SMTP_PASSWORD"]["secret_is_set"]
    assert capture_email_settings(decrypt_secret=decrypt).password is None


def test_missing_key_allows_nonsecret_settings_but_rolls_back_credential_group(client, monkeypatch):
    monkeypatch.delenv("APPLICATION_SETTINGS_ENCRYPTION_KEY", raising=False)
    assert save(client, {"REVIEW_WARNING_WINDOW_DAYS": 31}).status_code == 200
    before = items(client)
    result = save_smtp(client, password="fixture-unavailable-password", values={"SMTP_HOST": "smtp.example.invalid"})
    assert result.status_code == 503 and "fixture-unavailable-password" not in result.text
    assert items(client) == before
    with db() as c:
        assert not c.execute("SELECT 1 FROM event_history WHERE operation='APPLICATION_SETTING_CHANGED' AND metadata->>'setting_key'='SMTP_HOST'").fetchone()


def test_audit_failure_rolls_back_group_and_migration_completion(client):
    with db() as c:
        c.execute("""CREATE FUNCTION settings_test_fail_audit() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN IF NEW.entity_type='application_setting' AND NEW.operation='APPLICATION_SETTING_CHANGED'
           THEN RAISE EXCEPTION 'settings_test_audit_failure'; END IF; RETURN NEW; END $$""")
        c.execute("CREATE TRIGGER settings_test_fail_audit BEFORE INSERT ON event_history FOR EACH ROW EXECUTE FUNCTION settings_test_fail_audit()")
    try:
        before = items(client)
        assert save(client, {"REVIEW_WARNING_WINDOW_DAYS": 42, "AUDIT_TRAIL_SEARCH_RESULT_LIMIT": 50}).status_code == 422
        assert items(client) == before
        with db() as c:
            actor(c)
            with pytest.raises(psycopg.errors.RaiseException):
                with c.transaction():
                    apply_changes(c, [SettingChange(key="REVIEW_WARNING_WINDOW_DAYS", expected_version=1, value=42)], "Audit failure is atomic", migration_id="audit-failure")
            assert not c.execute("SELECT 1 FROM application_settings_migration_keys WHERE migration_id='audit-failure'").fetchone()
    finally:
        with db() as c:
            c.execute("DROP TRIGGER settings_test_fail_audit ON event_history")
            c.execute("DROP FUNCTION settings_test_fail_audit()")


def test_fresh_capture_bypasses_older_repeatable_read_transaction(client):
    with db() as old:
        old.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        assert load_snapshot(old)["DISPOSITION_DESTRUCTION_REVIEW_ROUTE"] == "standard"
        assert save(client, {"DISPOSITION_DESTRUCTION_REVIEW_ROUTE": "simplified"}).status_code == 200
        assert load_snapshot(old)["DISPOSITION_DESTRUCTION_REVIEW_ROUTE"] == "standard"
        assert capture_job_settings().review_route == "simplified"


def test_settings_labels_use_published_preferred_language_and_english_fallback(client):
    category = "settings.category.email"
    field = "settings.field.smtp_host.label"
    with db() as c:
        actor(c)
        c.execute("UPDATE ui_message_translations SET translated_text='البريد الإلكتروني',published_text='البريد الإلكتروني',status='published',origin='manual' WHERE message_key=%s AND language_tag='ar'", (category,))
        c.execute("UPDATE ui_message_translations SET translated_text='مسودة غير منشورة' WHERE message_key=%s AND language_tag='ar'", (field,))
        c.execute("INSERT INTO user_preferences(user_id,language_tag,working_timezone) VALUES(1,'ar','Asia/Dubai') ON CONFLICT(user_id) DO UPDATE SET language_tag='ar'")
    row = items(client)["SMTP_HOST"]
    assert row["category_label"] == "البريد الإلكتروني"
    assert row["label"] == "SMTP server hostname"


def test_exact_registry_defaults_and_protected_public_metadata(client, monkeypatch):
    monkeypatch.setenv("AUDIT_TRAIL_SEARCH_RESULT_LIMIT", "77")
    monkeypatch.setenv("DISPOSITION_DESTRUCTION_REVIEW_ROUTE", "simplified")
    result = items(client)
    assert set(result) == set(REGISTRY)
    for key, definition in REGISTRY.items():
        assert result[key]["default"] == definition.default
        assert result[key]["value"] == definition.default
        assert result[key]["category"] == definition.category
        assert result[key]["category_label"]
        assert result[key]["editable"] is True
    assert result["SMTP_PASSWORD"]["secret_is_set"] is False
    assert result["SMTP_SECURITY"]["value"] is None
    with db() as c:
        snapshot = load_snapshot(c)
        assert snapshot["AUDIT_TRAIL_SEARCH_RESULT_LIMIT"] == 1000
        assert "SMTP_PASSWORD" not in snapshot.values
        assert "DATABASE_URL" not in snapshot.values
        assert c.execute("SELECT count(*) AS count FROM event_history WHERE entity_type='application_setting' AND source='seeding'").fetchone()["count"] == 51


def test_sys_admin_grant_does_not_grant_settings_to_governance_profiles(client):
    with db() as c:
        rows = c.execute("SELECT p.code FROM profiles p JOIN profile_privileges pp ON pp.profile_id=p.id JOIN privileges v ON v.id=pp.privilege_id WHERE v.code='app.settings.manage' ORDER BY p.code").fetchall()
    assert {row["code"] for row in rows} == {"SYS_ADMIN", "ALL_PRIVS"}
    with db() as c:
        c.execute("UPDATE roles SET profile_id=(SELECT id FROM profiles WHERE code='INFO_GOV_OFFICER') WHERE id=1")
    assert client.get(PATH).status_code == 403
    assert client.put(PATH, json={"changes": [{"key": "AUDIT_TRAIL_SEARCH_RESULT_LIMIT", "expected_version": 1, "value": 10}]}).status_code == 403


@pytest.mark.parametrize("key,value", [
    ("AUDIT_TRAIL_SEARCH_RESULT_LIMIT", 0), ("AUDIT_TRAIL_SEARCH_RESULT_LIMIT", True),
    ("CONTENT_SEGMENT_SIZE_BYTES", 67108865), ("AUTH_PASSWORD_MIN_LENGTH", 7),
    ("DISPOSITION_DESTRUCTION_REVIEW_ROUTE", "other"),
    ("DISPOSITION_EXTERNAL_AUTHORITY_EMAIL", "not an address"),
    ("DEFAULT_WORKING_TIMEZONE", "Invented/Timezone"),
])
def test_invalid_setting_keeps_all_submitted_values_and_history_unchanged(client, key, value):
    before = items(client)
    with db() as c:
        count = c.execute("SELECT count(*) AS count FROM event_history WHERE entity_type='application_setting'").fetchone()["count"]
    response = save(client, {key: value, "REVIEW_WARNING_WINDOW_DAYS": 80})
    assert response.status_code == 422, response.text
    assert items(client) == before
    with db() as c:
        assert c.execute("SELECT count(*) AS count FROM event_history WHERE entity_type='application_setting'").fetchone()["count"] == count


def test_reason_unknown_keys_deployment_values_and_generic_crud_are_rejected(client):
    for key in ("DATABASE_URL", "WEBUI_STORAGE_SECRET", "unknown"):
        response = client.put(PATH, headers={"X-Change-Reason": "Attempt invalid key"}, json={"changes": [{"key": key, "expected_version": 1, "value": "private"}]})
        assert response.status_code == 422 and "private" not in response.text
    assert save(client, {"AUDIT_TRAIL_SEARCH_RESULT_LIMIT": 10}, reason=" ").status_code == 422
    assert client.patch("/api/v1/application_settings/1", json={"value": 10}).status_code in {404,405}
    invalid = client.put(PATH, headers={"X-Change-Reason": "Invalid credential input"}, json={"changes": [{"key": "SMTP_PASSWORD", "expected_version": "secret-input", "secret_value": {"private": "never-return-this"}}]})
    assert invalid.status_code == 422 and "never-return-this" not in invalid.text and "secret-input" not in invalid.text


def test_configured_default_provenance_versions_atomic_audit_and_conflict(client):
    before = items(client)
    response = save(client, {"AUDIT_TRAIL_SEARCH_RESULT_LIMIT": 1000, "REVIEW_WARNING_WINDOW_DAYS": 60})
    assert response.status_code == 200, response.text
    current = items(client)
    assert current["AUDIT_TRAIL_SEARCH_RESULT_LIMIT"]["provenance"] == "configured"
    assert current["AUDIT_TRAIL_SEARCH_RESULT_LIMIT"]["version"] == 2
    conflict = save(client, {"AUDIT_TRAIL_SEARCH_RESULT_LIMIT": 200, "REVIEW_WARNING_WINDOW_DAYS": 70}, versions={"AUDIT_TRAIL_SEARCH_RESULT_LIMIT": before["AUDIT_TRAIL_SEARCH_RESULT_LIMIT"]["version"]})
    assert conflict.status_code == 409 and items(client) == current
    with db() as c:
        events = c.execute("SELECT * FROM event_history WHERE operation='APPLICATION_SETTING_CHANGED' ORDER BY id").fetchall()
        assert len(events) == 2
        assert all(event["actor_user_id"] == 1 and event["actor_type"] == "user" and event["reason"] for event in events)
        assert {event["metadata"]["setting_key"] for event in events} == {"AUDIT_TRAIL_SEARCH_RESULT_LIMIT", "REVIEW_WARNING_WINDOW_DAYS"}


def test_destinations_require_complete_group_and_reject_inconsistent_sets(client):
    assert save(client, {"DISPOSITION_CLASSIFICATION_SCHEME_ID": 1}).status_code == 422
    response = save(client, {"DISPOSITION_CLASSIFICATION_SCHEME_ID": 1, "DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID": 1, "DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID": 1}, group="destinations")
    assert response.status_code == 200, response.text
    before = items(client)
    with db() as c:
        other = c.execute("INSERT INTO classification_schemes(code,title) VALUES('OTHER','Other') RETURNING id").fetchone()["id"]
    bad = save(client, {"DISPOSITION_CLASSIFICATION_SCHEME_ID": other}, group="destinations")
    assert bad.status_code == 422 and items(client) == before
    bad = save(client, {"DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID": 987654}, group="destinations")
    assert bad.status_code == 422 and items(client) == before
    with db() as c:
        with pytest.raises(psycopg.errors.CheckViolation):
            with c.transaction():
                c.execute("UPDATE classifications SET is_terminal=false WHERE id=1")
                c.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_smtp_group_auto_port_and_incomplete_optional_configuration(client):
    assert save(client, {"SMTP_SECURITY": "starttls"}).status_code == 422
    result = save(client, {"SMTP_SECURITY": "starttls"}, group="smtp")
    assert result.status_code == 200, result.text
    assert items(client)["SMTP_PORT"]["effective_value"] == 587
    assert save(client, {"SMTP_SECURITY": "implicit_tls"}, group="smtp").status_code == 200
    assert items(client)["SMTP_PORT"]["effective_value"] == 465
    assert save(client, {"SMTP_PORT": 2525}, group="smtp").status_code == 200
    assert save(client, {"SMTP_SECURITY": "starttls"}, group="smtp").status_code == 200
    assert items(client)["SMTP_PORT"]["effective_value"] == 2525
    assert save(client, {"SMTP_AUTH_ENABLED": True}, group="smtp").status_code == 422
    with pytest.raises(SettingsInvalid, match="email_incomplete"):
        capture_email_settings(decrypt_secret=lambda *args: pytest.fail("should not decrypt incomplete mail config"))


def test_direct_sql_requires_authority_reason_and_schema_validation(client):
    with db() as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with c.transaction():
                c.execute("UPDATE application_settings SET value='2000',provenance='configured' WHERE key='AUDIT_TRAIL_SEARCH_RESULT_LIMIT'")
        actor(c)
        for value in ('0', 'true', '"2000"'):
            with pytest.raises(psycopg.errors.CheckViolation):
                with c.transaction():
                    c.execute("UPDATE application_settings SET value=%s::jsonb,provenance='configured' WHERE key='AUDIT_TRAIL_SEARCH_RESULT_LIMIT'", (value,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with c.transaction():
                c.execute("TRUNCATE application_settings CASCADE")


def test_fresh_operations_ignore_cached_and_repeatable_read_values(client):
    with db() as c:
        stale = cache.for_connection(c)
    old_job = capture_job_settings()
    old_dest = capture_artifact_settings()
    assert save(client, {"DISPOSITION_DESTRUCTION_REVIEW_ROUTE": "records_manager_only"}).status_code == 200
    assert save(client, {"DISPOSITION_CLASSIFICATION_SCHEME_ID": 1, "DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID": 1}, group="destinations").status_code == 200
    assert stale["DISPOSITION_DESTRUCTION_REVIEW_ROUTE"] == "standard"
    assert old_job.review_route == "standard" and old_dest.scheme_id is None
    assert capture_job_settings().review_route == "records_manager_only"
    assert capture_artifact_settings().scheme_id == 1
    @contextmanager
    def failed_connection():
        raise psycopg.OperationalError("private connection error")
        yield
    with pytest.raises(psycopg.OperationalError):
        capture_job_settings(failed_connection)
    with pytest.raises(psycopg.OperationalError):
        capture_artifact_settings(failed_connection)


def test_migration_provenance_completion_rollback_safe_rerun_and_new_keys(client):
    with db() as c:
        actor(c)
        apply_changes(c, [SettingChange(key="AUDIT_TRAIL_SEARCH_RESULT_LIMIT", expected_version=1, value=77)], "Preserve legacy cap", migration_id="search-v1")
    row = items(client)["AUDIT_TRAIL_SEARCH_RESULT_LIMIT"]
    assert row["value"] == 77 and row["provenance"] == "migrated"
    assert save(client, {"AUDIT_TRAIL_SEARCH_RESULT_LIMIT": 88}).status_code == 200
    with db() as c:
        actor(c)
        apply_changes(c, [SettingChange(key="AUDIT_TRAIL_SEARCH_RESULT_LIMIT", expected_version=1, value=99)], "Safe completed rerun", migration_id="search-v1")
        apply_changes(c, [SettingChange(key="SEARCH_RATE_LIMIT_PER_MINUTE", expected_version=1, value=61)], "Migrate an additional key", migration_id="search-v2")
    assert items(client)["AUDIT_TRAIL_SEARCH_RESULT_LIMIT"]["value"] == 88
    assert save(client, {"REVIEW_WARNING_WINDOW_DAYS": 30}).status_code == 200
    with db() as c:
        actor(c)
        with pytest.raises(psycopg.errors.CheckViolation):
            with c.transaction():
                apply_changes(c, [SettingChange(key="MAX_UPLOAD_SIZE_BYTES", expected_version=1, value=1234), SettingChange(key="REVIEW_WARNING_WINDOW_DAYS", expected_version=2, value=45)], "Conflict must roll everything back", migration_id="mixed-conflict")
        assert not c.execute("SELECT 1 FROM application_settings_migration_keys WHERE migration_id='mixed-conflict'").fetchone()
        assert c.execute("SELECT value FROM application_settings WHERE key='MAX_UPLOAD_SIZE_BYTES'").fetchone()["value"] == 52428800
        assert c.execute("SELECT 1 FROM event_history WHERE operation='APPLICATION_SETTINGS_MIGRATION_COMPLETED' AND source='migration'").fetchone()


def test_concurrent_administrators_have_one_winner(client):
    def configure(value):
        try:
            with db() as c:
                actor(c)
                apply_changes(c, [SettingChange(key="AUDIT_TRAIL_SEARCH_RESULT_LIMIT", expected_version=1, value=value)], "Concurrent settings edit")
            return "saved"
        except psycopg.errors.SerializationFailure:
            return "stale"
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(configure, (111,222)))
    assert sorted(outcomes) == ["saved", "stale"]


def test_concurrent_migration_and_configuration_preserve_winning_value(client):
    def configure(migration):
        try:
            with db() as c:
                actor(c)
                apply_changes(c, [SettingChange(key="REVIEW_WARNING_WINDOW_DAYS", expected_version=1,
                                               value=41 if migration else 42)],
                              "Concurrent reviewed migration/configuration", migration_id="race-v1" if migration else None)
            return migration
        except psycopg.errors.SerializationFailure:
            return "stale"
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(configure, (True, False)))
    assert outcomes.count("stale") == 1
    winner = next(value for value in outcomes if value != "stale")
    row = items(client)["REVIEW_WARNING_WINDOW_DAYS"]
    assert row["value"] == (41 if winner else 42) and row["version"] == 2
    with db() as c:
        completion = c.execute("SELECT 1 FROM application_settings_migration_keys WHERE migration_id='race-v1'").fetchone()
        assert bool(completion) == winner


def test_missing_canonical_rows_fail_startup_without_environment_fallback(client):
    with db() as c:
        c.execute("ALTER TABLE application_settings DISABLE TRIGGER USER")
        c.execute("DELETE FROM application_settings WHERE key='DEFAULT_WORKING_TIMEZONE'")
        c.execute("ALTER TABLE application_settings ENABLE TRIGGER USER")
    try:
        probe = subprocess.run([sys.executable, "-c", """
from fastapi.testclient import TestClient
from backend.services.api.main import app
from backend.services.api.application_settings_registry import SettingsInvalid
try:
    with TestClient(app):
        raise AssertionError('Startup accepted missing settings')
except SettingsInvalid:
    print('startup-rejected')
"""], cwd=ROOT, env={**os.environ, "APPLICATION_SETTINGS_ENCRYPTION_KEY": ""},
            capture_output=True, text=True, timeout=30)
        assert probe.returncode == 0, probe.stderr
        assert probe.stdout.strip() == "startup-rejected"
    finally:
        with db() as c:
            c.execute("SELECT set_config('app.event_source','seeding',true)")
            c.execute("INSERT INTO application_settings(key,value) VALUES('DEFAULT_WORKING_TIMEZONE','\"Asia/Dubai\"')")
        cache.invalidate()


def test_api_fixture_refuses_persistent_database_before_startup(client, monkeypatch):
    from backend.services.api.tests import conftest
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/persistent_erms")
    monkeypatch.setattr(conftest, "TestClient", lambda *args, **kwargs: pytest.fail("Must reject before API startup"))
    with pytest.raises(RuntimeError, match="new disposable database"):
        next(conftest.client.__wrapped__())


def test_upgrade_repeats_portable_ddl_preserves_values_and_fresh_schema_parity(client):
    assert save(client, {"AUDIT_TRAIL_SEARCH_RESULT_LIMIT": 77}).status_code == 200
    before = items(client)
    with db() as c:
        c.execute((ROOT / "database/migrations/050_application_settings.sql").read_text(), prepare=False)
    assert items(client) == before
    with db() as c:
        columns = c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='application_settings'").fetchall()
    assert "category" not in {row["column_name"] for row in columns}
