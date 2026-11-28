import os
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from backend.services.api.manage_auth import (
    BOOTSTRAP_ORG_UNIT_CODE,
    BOOTSTRAP_USER_EMAIL,
    bootstrap_administrator,
)
from backend.services.api.session_cleanup import cleanup_sessions
from .conftest import _allow_generator_fixture_reset, _restore_generator_fixture


def test_authenticated_principal_includes_roles(client: TestClient):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    principal = response.json()
    assert principal["user"]["email"] == "admin@test.invalid"
    assert principal["user"]["account_type"] == "person"
    assert [role["code"] for role in principal["roles"]] == ["system-administrator"]
    assert principal["previous_login_at"] is None


def test_account_menu_names_follow_language_and_fall_back(client: TestClient):
    from psycopg.types.json import Jsonb

    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        for table, name in (("users", "مدير النظام"), ("roles", "مسؤول النظام"), ("org_units", "الإدارة")):
            connection.execute(
                psycopg.sql.SQL("UPDATE {} SET translations=%s WHERE id=1").format(psycopg.sql.Identifier(table)),
                (Jsonb({"ar": {"name": name}}),),
            )
        connection.execute("INSERT INTO user_preferences(user_id,language_tag,working_timezone) VALUES (1,'ar','Asia/Dubai') ON CONFLICT(user_id) DO UPDATE SET language_tag='ar'")
    for response in (
        client.get("/api/v1/auth/me"),
        client.post("/api/v1/auth/login", json={"email": "admin@test.invalid", "password": "Temporary-Test-Password-123!"}),
    ):
        assert response.status_code == 200
        principal = response.json()
        assert principal["user"]["localized"]["name"] == "مدير النظام"
        assert principal["user"]["name"] == "Test Administrator"
        assert principal["roles"][0]["localized"]["name"] == "مسؤول النظام"
        assert principal["roles"][0]["org_unit"]["localized"]["name"] == "الإدارة"
        assert principal["user"]["email"] == "admin@test.invalid"
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("UPDATE roles SET translations='{}' WHERE id=1")
    assert client.get("/api/v1/auth/me").json()["roles"][0]["localized"]["name"] == "System Administrator"
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("UPDATE user_preferences SET language_tag='en' WHERE user_id=1")
    english = client.get("/api/v1/auth/me").json()
    assert english["user"]["localized"]["name"] == "Test Administrator"
    assert english["roles"][0]["org_unit"]["localized"]["name"] == "Test Root"


def test_principal_reports_previous_successful_login_excluding_current_session(client: TestClient):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.invalid", "password": "Temporary-Test-Password-123!"},
    )
    assert response.status_code == 200
    principal = response.json()
    assert principal["previous_login_at"] is not None

    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        previous_event = connection.execute(
            """SELECT occurred_at
                 FROM event_history
                WHERE operation = 'AUTHENTICATION_SUCCEEDED'
                  AND (metadata->>'session_id')::bigint <> %s
                ORDER BY occurred_at DESC, id DESC
                LIMIT 1""",
            (principal["session"]["id"],),
        ).fetchone()[0]
    assert datetime.fromisoformat(principal["previous_login_at"]) == previous_event


def test_protected_api_rejects_missing_session(client: TestClient):
    cookies = dict(client.cookies)
    client.cookies.clear()
    assert client.get("/api/v1/users").status_code == 401
    for name, value in cookies.items():
        client.cookies.set(name, value)


def test_failed_login_is_persisted_despite_unauthorized_response(client: TestClient):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.invalid", "password": "Definitely-Wrong-Password!"},
    )
    assert response.status_code == 401
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        credential = connection.execute(
            "SELECT failed_attempt_count, last_failed_at FROM user_credentials WHERE user_id=1"
        ).fetchone()
        failed_events = connection.execute(
            "SELECT count(*) FROM event_history WHERE operation='AUTHENTICATION_FAILED'"
        ).fetchone()[0]
    assert credential == (1, credential[1])
    assert credential[1] is not None
    assert failed_events == 1


def test_logout_revokes_session_and_removes_browser_cookies(client: TestClient):
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert "erms_session=" in response.headers["set-cookie"]
    assert client.cookies.get("erms_session") is None
    assert client.cookies.get("erms_csrf") is None
    assert client.get("/api/v1/auth/me").status_code == 401


def test_temporary_password_requires_change_and_never_enters_audit_snapshot(client: TestClient):
    created = client.post(
        "/api/v1/users", json={"name": "New Person", "email": "new.person@test.invalid", "account_type": "person"}
    )
    assert created.status_code == 201
    issued = client.post(f"/api/v1/auth/users/{created.json()['id']}/temporary-password")
    assert issued.status_code == 200
    temporary_password = issued.json()["temporary_password"]

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "new.person@test.invalid", "password": temporary_password},
    )
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True
    client.headers["X-CSRF-Token"] = client.cookies.get("erms_csrf")
    assert client.get("/api/v1/records").status_code == 403
    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": temporary_password, "new_password": "A-New-Secure-Password-456!"},
    )
    assert changed.status_code == 204
    assert client.get("/api/v1/auth/me").json()["must_change_password"] is False

    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        serialized = connection.execute("SELECT COALESCE(string_agg(row_to_json(e)::text, ''), '') FROM event_history e").fetchone()[0]
    assert temporary_password not in serialized
    assert "$argon2" not in serialized


def test_service_account_is_non_interactive_and_cannot_receive_password(client: TestClient):
    created = client.post(
        "/api/v1/users",
        json={
            "name": "Document Conversion Service",
            "email": "converter@test.invalid",
            "account_type": "service",
        },
    )
    assert created.status_code == 201
    assert created.json()["account_type"] == "service"
    issued = client.post(
        f"/api/v1/auth/users/{created.json()['id']}/temporary-password"
    )
    assert issued.status_code == 422
    assert issued.json()["detail"] == "local passwords require a person account with an email address"


def test_system_administrator_can_list_and_revoke_sessions(client: TestClient):
    sessions = client.get("/api/v1/auth/sessions")
    assert sessions.status_code == 200
    bounded = client.get(
        "/api/v1/auth/sessions", params={"user_id": 1, "limit": 1, "offset": 0},
    )
    assert bounded.status_code == 200
    assert len(bounded.json()) == 1
    assert bounded.json()[0]["user_id"] == 1
    page = client.get(
        "/api/v1/auth/sessions/page",
        params={"user_id": 1, "limit": 5, "sort_by": "date_created", "descending": True},
    )
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 1
    assert page.json()["active"] == 1
    assert page.json()["items"][0]["user_id"] == 1
    global_page = client.get(
        "/api/v1/auth/sessions/page",
        params={"limit": 20, "query": "test.invalid", "session_status": "active"},
    )
    assert global_page.status_code == 200, global_page.text
    assert global_page.json()["total"] >= 1
    assert global_page.json()["active"] == global_page.json()["total"]
    assert all("test.invalid" in row["user_email"] for row in global_page.json()["items"])
    current = next(row for row in sessions.json() if row["is_current"])
    assert current["status"] == "active"
    response = client.delete(f"/api/v1/auth/sessions/{current['id']}")
    assert response.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_deactivating_user_revokes_sessions_and_prevents_authentication(client: TestClient):
    # Preserve authorization-administration continuity while exercising the
    # session-revocation semantics of deactivating the signed-in account.
    backup = client.post(
        "/api/v1/users",
        json={"name": "Backup Administrator", "email": "backup-admin@test.invalid"},
    ).json()
    assigned = client.post(
        "/api/v1/user-role-assignments", json={"user_id": backup["id"], "role_id": 1},
    )
    assert assigned.status_code == 201
    current = client.get("/api/v1/users/1").json()
    response = client.post(
        "/api/v1/users/1/deactivate",
        headers={"If-Match": str(current["version"])},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "inactive"
    assert client.get("/api/v1/auth/me").status_code == 401
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        assert connection.execute(
            "SELECT bool_and(revoked_at IS NOT NULL) FROM login_sessions WHERE user_id=1"
        ).fetchone()[0] is True


def test_suspend_and_unsuspend_revoke_existing_sessions(client: TestClient):
    created = client.post(
        "/api/v1/users",
        json={"name": "Suspension Test", "email": "suspend@test.invalid"},
    ).json()
    password = client.post(
        f"/api/v1/auth/users/{created['id']}/temporary-password"
    ).json()["temporary_password"]
    user_client = TestClient(client.app)
    login = user_client.post(
        "/api/v1/auth/login",
        json={"email": "suspend@test.invalid", "password": password},
    )
    assert login.status_code == 200

    suspended = client.post(
        f"/api/v1/users/{created['id']}/suspend",
        headers={"If-Match": str(created["version"])},
    )
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"
    assert suspended.json()["date_deactivated"] is None
    assert suspended.json()["date_suspended"] is not None
    assert user_client.get("/api/v1/auth/me").status_code == 401
    assert user_client.post(
        "/api/v1/auth/login",
        json={"email": "suspend@test.invalid", "password": password},
    ).status_code == 401

    unsuspended = client.post(
        f"/api/v1/users/{created['id']}/unsuspend",
        headers={"If-Match": str(suspended.json()["version"])},
    )
    assert unsuspended.status_code == 200
    assert unsuspended.json()["status"] == "active"
    assert unsuspended.json()["date_suspended"] is None
    assert user_client.get("/api/v1/auth/me").status_code == 401
    assert user_client.post(
        "/api/v1/auth/login",
        json={"email": "suspend@test.invalid", "password": password},
    ).status_code == 200


def test_authentication_events_include_safe_client_and_session_metadata(client: TestClient):
    failed = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.invalid", "password": "wrong-password"},
        headers={"User-Agent": "ERMS-Test-Agent/1.0"},
    )
    assert failed.status_code == 401
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=psycopg.rows.dict_row) as connection:
        event = connection.execute(
            """SELECT metadata FROM event_history
                WHERE operation='AUTHENTICATION_FAILED'
                ORDER BY id DESC LIMIT 1"""
        ).fetchone()
    assert event["metadata"]["user_agent"] == "ERMS-Test-Agent/1.0"
    assert event["metadata"]["failed_attempt_count"] == 1
    assert event["metadata"]["lock_applied"] is False
    serialized = str(event["metadata"])
    assert "wrong-password" not in serialized
    assert "token_hash" not in serialized


def test_session_cleanup_is_dry_runnable_audited_and_bounded(client: TestClient):
    now = datetime.now(timezone.utc)
    with psycopg.connect(
        os.environ["DATABASE_URL"], row_factory=psycopg.rows.dict_row
    ) as connection:
        expired_id = connection.execute(
            """INSERT INTO login_sessions
                   (user_id, session_token_hash, csrf_token_hash, date_created,
                    last_seen_at, expires_at, absolute_expires_at, client_ip, user_agent)
               VALUES (1, %s, %s, %s, %s, %s, %s, '192.0.2.10', 'Expired Test')
               RETURNING id""",
            (
                b"expired-session-token", b"expired-csrf-token",
                now - timedelta(days=200), now - timedelta(days=190),
                now - timedelta(days=120), now - timedelta(days=110),
            ),
        ).fetchone()["id"]
        revoked_id = connection.execute(
            """INSERT INTO login_sessions
                   (user_id, session_token_hash, csrf_token_hash, date_created,
                    last_seen_at, expires_at, absolute_expires_at, revoked_at,
                    client_ip, user_agent)
               VALUES (1, %s, %s, %s, %s, %s, %s, %s, '192.0.2.11', 'Revoked Test')
               RETURNING id""",
            (
                b"revoked-session-token", b"revoked-csrf-token",
                now - timedelta(days=200), now - timedelta(days=190),
                now + timedelta(days=1), now + timedelta(days=2),
                now - timedelta(days=120),
            ),
        ).fetchone()["id"]
        connection.commit()

        dry_run = cleanup_sessions(
            connection, retention_days=90, batch_size=1, dry_run=True
        )
        assert dry_run.selected == 1
        connection.rollback()
        assert connection.execute(
            "SELECT count(*) FROM login_sessions WHERE id IN (%s, %s)",
            (expired_id, revoked_id),
        ).fetchone()["count"] == 2

        first = cleanup_sessions(connection, retention_days=90, batch_size=1)
        second = cleanup_sessions(connection, retention_days=90, batch_size=1)
        assert first.removed == 1
        assert second.removed == 1
        assert connection.execute(
            "SELECT count(*) FROM login_sessions WHERE id IN (%s, %s)",
            (expired_id, revoked_id),
        ).fetchone()["count"] == 0
        events = connection.execute(
            """SELECT operation, metadata FROM event_history
                WHERE operation IN ('SESSION_EXPIRED', 'SESSION_REVOKED')
                  AND (metadata->>'session_id')::bigint IN (%s, %s)
                ORDER BY id""",
            (expired_id, revoked_id),
        ).fetchall()
    assert {event["operation"] for event in events} == {
        "SESSION_EXPIRED", "SESSION_REVOKED",
    }
    assert all("session_token" not in str(event["metadata"]) for event in events)


def test_empty_database_can_bootstrap_one_interactive_administrator(client: TestClient):
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    with psycopg.connect(
        os.environ["DATABASE_URL"], row_factory=psycopg.rows.dict_row
    ) as connection:
        _allow_generator_fixture_reset(connection)
        connection.execute(
            """
            TRUNCATE login_sessions, user_credentials, user_role_assignments,
                     roles, users, org_units
            RESTART IDENTITY CASCADE
            """
        )
        _restore_generator_fixture(connection)
        result = bootstrap_administrator(connection)
        stored = connection.execute(
            """
            SELECT u.name, u.email, u.account_type, u.external_id,
                   c.password_hash, c.must_change_password, c.temporary_expires_at,
                   r.code AS role_code, p.code AS profile_code, ou.code AS org_unit_code
            FROM users AS u
            JOIN user_credentials AS c ON c.user_id = u.id
            JOIN user_role_assignments AS a ON a.user_id = u.id
            JOIN roles AS r ON r.id = a.role_id
            JOIN profiles AS p ON p.id = r.profile_id
            JOIN org_units AS ou ON ou.id = r.org_unit_id
            WHERE u.id = %s
            """,
            (result.user_id,),
        ).fetchone()
        events = connection.execute(
            """
            SELECT source, actor_type, reason, metadata
            FROM event_history
            WHERE metadata ->> 'provisioning_operation' = 'bootstrap_administrator'
            """
        ).fetchall()

    assert stored["name"] == "Bootstrap Administrator"
    assert stored["email"] == BOOTSTRAP_USER_EMAIL
    assert stored["account_type"] == "person"
    assert stored["external_id"] == "SYSTEM-BOOTSTRAP"
    assert stored["must_change_password"] is True
    assert stored["temporary_expires_at"] == result.expires_at
    assert stored["role_code"] == "system-administrator"
    assert stored["profile_code"] == "SYS_ADMIN"
    assert stored["org_unit_code"] == BOOTSTRAP_ORG_UNIT_CODE
    assert PasswordHasher().verify(stored["password_hash"], result.temporary_password)
    assert len(events) == 4
    assert all(event["source"] == "administrative_tool" for event in events)
    assert all(event["actor_type"] == "automated_process" for event in events)
    assert all(event["reason"] == "Initial system bootstrap" for event in events)
    assert result.temporary_password not in str(events)

    login = client.post(
        "/api/v1/auth/login",
        json={"email": BOOTSTRAP_USER_EMAIL, "password": result.temporary_password},
    )
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True
    assert [role["code"] for role in login.json()["roles"]] == ["system-administrator"]

    with psycopg.connect(
        os.environ["DATABASE_URL"], row_factory=psycopg.rows.dict_row
    ) as connection:
        with pytest.raises(RuntimeError, match="active system administrator already exists"):
            bootstrap_administrator(connection)


def test_bootstrap_refuses_nonempty_database_without_an_administrator(client: TestClient):
    with psycopg.connect(
        os.environ["DATABASE_URL"], row_factory=psycopg.rows.dict_row
    ) as connection:
        _allow_generator_fixture_reset(connection)
        connection.execute(
            """
            TRUNCATE login_sessions, user_credentials, user_role_assignments,
                     roles, users, org_units
            RESTART IDENTITY CASCADE
            """
        )
        _restore_generator_fixture(connection)
        connection.execute(
            "INSERT INTO users (name, email) VALUES ('Existing User', 'existing@test.invalid')"
        )
        with pytest.raises(RuntimeError, match="users table is empty"):
            bootstrap_administrator(connection)
