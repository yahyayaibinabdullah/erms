"""Credential retry policy: run only through the disposable database runner."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os

from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import pytest

from backend.services.api import authentication, manage_auth
from backend.services.api.tests.test_application_settings import save


PASSWORD = "Temporary-Test-Password-123!"
NEW_PASSWORD = "Replacement-Secure-Password-456!"


def db():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def credential():
    with db() as connection:
        return connection.execute("SELECT * FROM user_credentials WHERE user_id=1").fetchone()


def failures():
    with db() as connection:
        return connection.execute(
            "SELECT metadata FROM event_history WHERE operation='AUTHENTICATION_FAILED' ORDER BY id"
        ).fetchall()


def attempt(client, endpoint, password="wrong", new_password=NEW_PASSWORD):
    if endpoint == "login":
        response = client.post("/api/v1/auth/login", json={"email": "admin@test.invalid", "password": password})
        if response.status_code == 200:
            client.headers["X-CSRF-Token"] = client.cookies.get("erms_csrf")
        return response
    return client.post("/api/v1/auth/change-password", json={"current_password": password, "new_password": new_password})


def configure(client, attempts=3, minutes=2):
    assert save(client, {"AUTH_LOCKOUT_ATTEMPTS": attempts, "AUTH_LOCKOUT_MINUTES": minutes}).status_code == 200


def set_expired_lock(monkeypatch, *, count=3):
    instant = datetime.now(timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(authentication, "datetime", Clock)
    with db() as connection:
        # Exact equality is expired, not one additional locked instant.
        connection.execute(
            "UPDATE user_credentials SET failed_attempt_count=%s, locked_until=%s WHERE user_id=1",
            (count, instant),
        )


@pytest.mark.parametrize("endpoint", ["login", "change-password"])
def test_threshold_locks_both_password_checks_without_extending_deadline(client, endpoint):
    configure(client)
    for count in range(1, 4):
        response = attempt(client, endpoint)
        assert response.status_code == (401 if endpoint == "login" else 429 if count == 3 else 400)
        stored = credential()
        assert stored["failed_attempt_count"] == count
        assert (stored["locked_until"] is not None) == (count == 3)
    assert 115 < (stored["locked_until"] - datetime.now(timezone.utc)).total_seconds() <= 120
    before = failures()
    for other_endpoint in ("login", "change-password"):
        for password in (PASSWORD, "wrong-again"):
            response = attempt(client, other_endpoint, password)
            assert response.status_code == (401 if other_endpoint == "login" else 429)
            if other_endpoint == "change-password":
                assert 1 <= int(response.headers["Retry-After"]) <= 120
                detail = response.json()["detail"]
                assert detail["code"] == "password_attempts_locked"
                assert detail["parameters"]["seconds"] == int(response.headers["Retry-After"])
            assert credential() == stored
    assert failures() == before
    assert client.get("/api/v1/auth/me").status_code == 200


def test_switching_endpoints_does_not_bypass_shared_limit(client):
    configure(client)
    assert attempt(client, "login").status_code == 401
    assert attempt(client, "change-password").status_code == 400
    assert attempt(client, "change-password").status_code == 429
    assert credential()["failed_attempt_count"] == 3
    assert [row["metadata"]["authentication_context"] for row in failures()] == [
        "login", "password_change", "password_change",
    ]


@pytest.mark.parametrize("endpoint", ["login", "change-password"])
def test_expired_cooldown_starts_a_full_new_allowance(client, monkeypatch, endpoint):
    configure(client)
    set_expired_lock(monkeypatch)
    for count in range(1, 4):
        response = attempt(client, endpoint)
        assert response.status_code == (401 if endpoint == "login" else 429 if count == 3 else 400)
        stored = credential()
        assert stored["failed_attempt_count"] == count
        assert (stored["locked_until"] is not None) == (count == 3)
    assert [row["metadata"]["failed_attempt_count"] for row in failures()] == [1, 2, 3]


@pytest.mark.parametrize("endpoint", ["login", "change-password"])
@pytest.mark.parametrize("expired", [False, True])
def test_success_clears_counter_and_expired_lock(client, monkeypatch, endpoint, expired):
    configure(client)
    if expired:
        set_expired_lock(monkeypatch)
    else:
        assert attempt(client, "login").status_code == 401
        assert attempt(client, "change-password").status_code == 400
    response = attempt(client, endpoint, PASSWORD)
    assert response.status_code == (200 if endpoint == "login" else 204)
    stored = credential()
    assert stored["failed_attempt_count"] == 0 and stored["locked_until"] is None
    assert attempt(client, "change-password").status_code == 400
    assert credential()["failed_attempt_count"] == 1


@pytest.mark.parametrize("new_password", ["", "short", "x" * 11])
def test_new_password_validation_does_not_increment_or_clear_existing_failures(client, new_password):
    configure(client)
    assert attempt(client, "login").status_code == 401
    assert attempt(client, "change-password").status_code == 400
    before = credential()
    before_events = failures()
    # More rejected new passwords than the retry limit still cannot lock out.
    for _ in range(4):
        response = attempt(client, "change-password", PASSWORD, new_password)
        assert response.status_code == 422
        assert credential() == before
    assert failures() == before_events
    assert attempt(client, "change-password", PASSWORD).status_code == 204
    assert credential()["failed_attempt_count"] == 0


def test_expired_lock_reset_persists_despite_new_password_validation_error(client, monkeypatch):
    configure(client)
    set_expired_lock(monkeypatch)
    before = credential()
    assert attempt(client, "change-password", PASSWORD, "short").status_code == 422
    after = credential()
    assert after["failed_attempt_count"] == 0 and after["locked_until"] is None
    assert after["password_hash"] == before["password_hash"]
    assert failures() == []
    assert attempt(client, "change-password").status_code == 400
    assert credential()["failed_attempt_count"] == 1


def test_bad_current_password_still_counts_when_new_password_is_invalid(client):
    configure(client, attempts=1)
    assert attempt(client, "change-password", "wrong", "short").status_code == 429
    assert credential()["failed_attempt_count"] == 1


def test_request_validation_errors_do_not_count(client):
    before = credential()
    for payload in ({"current_password": PASSWORD}, {"current_password": PASSWORD, "new_password": None}):
        assert client.post("/api/v1/auth/change-password", json=payload).status_code == 422
    assert credential() == before and failures() == []


def test_forced_temporary_password_change_obeys_retry_limit(client):
    created = client.post("/api/v1/users", json={"name": "Forced-change fixture", "email": "forced-retry@test.invalid"})
    user_id = created.json()["id"]
    issued = client.post(f"/api/v1/auth/users/{user_id}/temporary-password")
    temporary = issued.json()["temporary_password"]
    configure(client, attempts=1)
    session = TestClient(client.app)
    try:
        response = session.post("/api/v1/auth/login", json={"email": "forced-retry@test.invalid", "password": temporary})
        assert response.status_code == 200 and response.json()["must_change_password"]
        session.headers["X-CSRF-Token"] = session.cookies.get("erms_csrf")
        assert attempt(session, "change-password", temporary, "short").status_code == 422
        assert attempt(session, "change-password").status_code == 429
        assert attempt(session, "change-password", temporary).status_code == 429
        assert session.get("/api/v1/auth/me").status_code == 200
    finally:
        session.close()


def test_password_change_failures_are_shared_across_sessions_and_concurrent_requests(client):
    configure(client)
    sessions = [TestClient(client.app) for _ in range(2)]
    try:
        for session in sessions:
            assert attempt(session, "login", PASSWORD).status_code == 200
            session.headers["X-CSRF-Token"] = session.cookies.get("erms_csrf")
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda session: attempt(session, "change-password"), sessions))
        assert [response.status_code for response in responses] == [400, 400]
        assert credential()["failed_attempt_count"] == 2
        assert attempt(client, "change-password").status_code == 429
        assert attempt(sessions[0], "change-password", PASSWORD).status_code == 429
        assert [row["metadata"]["failed_attempt_count"] for row in failures()] == [1, 2, 3]
    finally:
        for session in sessions:
            session.close()


def test_failure_audit_does_not_leak_passwords_and_commits_atomically(client):
    configure(client)
    assert attempt(client, "change-password", "Secret-Wrong-Current!", "Secret-New-Proposal!").status_code == 400
    metadata = failures()[0]["metadata"]
    assert metadata["authentication_context"] == "password_change"
    assert metadata["failed_attempt_count"] == 1 and metadata["lock_applied"] is False
    assert metadata["client_ip"] is not None or metadata["user_agent"] is not None
    serialized = json.dumps(metadata)
    assert "Secret-Wrong-Current!" not in serialized and "Secret-New-Proposal!" not in serialized
    assert "password_hash" not in serialized and "$argon2" not in serialized
    before = credential()
    with db() as connection:
        connection.execute("CREATE FUNCTION reject_password_failure_fixture() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.operation='AUTHENTICATION_FAILED' THEN RAISE EXCEPTION 'fixture audit failure'; END IF; RETURN NEW; END $$")
        connection.execute("CREATE TRIGGER reject_password_failure_fixture BEFORE INSERT ON event_history FOR EACH ROW EXECUTE FUNCTION reject_password_failure_fixture()")
    try:
        failing_client = TestClient(client.app, raise_server_exceptions=False)
        try:
            failing_client.headers["Authorization"] = "Bearer " + client.cookies.get("erms_session")
            # The API maps a PostgreSQL trigger rejection to a conflict.
            assert attempt(failing_client, "change-password").status_code == 409
        finally:
            failing_client.close()
        assert credential() == before
        assert len(failures()) == 1
    finally:
        with db() as connection:
            connection.execute("DROP TRIGGER reject_password_failure_fixture ON event_history")
            connection.execute("DROP FUNCTION reject_password_failure_fixture()")


@pytest.mark.parametrize("recovery", ["api", "tool"])
def test_temporary_password_recovery_clears_counter_and_lock(client, recovery):
    created = client.post("/api/v1/users", json={"name": "Recovery fixture", "email": "retry-recovery@test.invalid"})
    assert created.status_code == 201
    user_id = created.json()["id"]
    with db() as connection:
        connection.execute(
            "INSERT INTO user_credentials(user_id,password_hash,failed_attempt_count,locked_until) VALUES(%s,%s,5,%s)",
            (user_id, authentication.hash_password(PASSWORD), datetime.now(timezone.utc) + timedelta(minutes=15)),
        )
    if recovery == "api":
        assert client.post(f"/api/v1/auth/users/{user_id}/temporary-password").status_code == 200
    else:
        with db() as connection:
            manage_auth.set_temporary_password(connection, "retry-recovery@test.invalid", make_admin=False, org_unit_code=None)
    with db() as connection:
        stored = connection.execute("SELECT failed_attempt_count,locked_until FROM user_credentials WHERE user_id=%s", (user_id,)).fetchone()
    assert stored == {"failed_attempt_count": 0, "locked_until": None}


def test_cooldown_arabic_seed_is_unpublished_and_source_changes_preserve_curated_text(client):
    from backend.services.api.localization import (
        synchronize_generated_arabic_drafts, synchronize_message_definitions,
    )

    result = synchronize_generated_arabic_drafts(missing_only=True)
    assert result["failed"] == 0 and result["awaiting_generation"] == 0
    with db() as connection:
        draft = connection.execute(
            "SELECT * FROM ui_message_translations WHERE message_key='authentication.error.password_attempts_locked' AND language_tag='ar'"
        ).fetchone()
        assert draft["origin"] == "generated" and draft["status"] == "draft"
        assert draft["published_text"] is None and draft["date_reviewed"] is None
        assert "{seconds}" in draft["translated_text"] and "مؤقتاً" in draft["translated_text"]
        assert draft["generation_metadata"]["batch_id"] == "wathiq-ar-password-attempt-cooldown-20261104"
        connection.execute("SELECT set_config('app.change_reason','Prepare source-change preservation verification',true)")
        connection.execute(
            "UPDATE ui_message_translations SET translated_text='صياغة إدارية محفوظة',origin='manual' WHERE message_key='settings.field.auth_lockout_attempts.description' AND language_tag='ar'"
        )
        connection.execute(
            "UPDATE ui_message_definitions SET default_text='Previous login-only description' WHERE message_key='settings.field.auth_lockout_attempts.description'"
        )
    synchronize_message_definitions()
    with db() as connection:
        preserved = connection.execute(
            "SELECT translated_text,origin,needs_review FROM ui_message_translations WHERE message_key='settings.field.auth_lockout_attempts.description' AND language_tag='ar'"
        ).fetchone()
    assert preserved == {"translated_text": "صياغة إدارية محفوظة", "origin": "manual", "needs_review": True}
