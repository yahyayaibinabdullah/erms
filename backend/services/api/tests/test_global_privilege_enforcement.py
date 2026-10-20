from datetime import datetime, timedelta, timezone
import json
import os

import psycopg
import pytest
from fastapi.routing import APIRoute
from psycopg.rows import dict_row
from uuid import uuid4

from backend.services.api.authentication import hash_password
from backend.services.api.main import app


REPRESENTATIVE_ROUTES = (
    ("GET", "/api/v1/users/1/deletion-preflight", "identity.users.administer"),
    ("GET", "/api/v1/auth/sessions", "identity.sessions.administer"),
    ("GET", "/api/v1/org-units/1/deletion-preflight", "organization.administer"),
    ("GET", "/api/v1/browse/organization/roots", "organization.browse"),
    ("GET", "/api/v1/privileges", "authorization.administer"),
    ("GET", "/api/v1/classification-schemes/classification-counts", "classifications.administer"),
    ("GET", "/api/v1/event-history", "audit.view"),
)


def _account(client, *, privileges: tuple[str, ...], suffix: str = "limited") -> tuple[str, int, int]:
    password = "Limited-Test-Password-123!"
    unique = uuid4().hex[:10]
    suffix = f"{suffix}-{unique}"
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        profile_id = connection.execute(
            "INSERT INTO profiles(code,name) VALUES (%s,%s) RETURNING id",
            (f"P_{suffix.upper()}", f"Profile {suffix}"),
        ).fetchone()[0]
        if privileges:
            connection.execute(
                """INSERT INTO profile_privileges(profile_id,privilege_id)
                   SELECT %s,id FROM privileges WHERE code=ANY(%s)""",
                (profile_id, list(privileges)),
            )
        org_id = connection.execute(
            "INSERT INTO org_units(code,name) VALUES (%s,%s) RETURNING id",
            (f"OU-{suffix}", f"Unit {suffix}"),
        ).fetchone()[0]
        role_id = connection.execute(
            """INSERT INTO roles(org_unit_id,code,name,profile_id)
               VALUES (%s,%s,%s,%s) RETURNING id""",
            (org_id, f"ROLE-{suffix}", f"Role {suffix}", profile_id),
        ).fetchone()[0]
        user_id = connection.execute(
            "INSERT INTO users(name,email) VALUES (%s,%s) RETURNING id",
            (f"Person {suffix}", f"{suffix}@test.invalid"),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO user_role_assignments(user_id,role_id) VALUES (%s,%s)",
            (user_id, role_id),
        )
        connection.execute(
            "INSERT INTO user_credentials(user_id,password_hash,must_change_password) VALUES (%s,%s,false)",
            (user_id, hash_password(password)),
        )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": f"{suffix}@test.invalid", "password": password},
    )
    assert login.status_code == 200, login.text
    return login.cookies["erms_session"], user_id, role_id


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(("method", "path", "privilege"), REPRESENTATIVE_ROUTES)
def test_each_global_administration_area_accepts_its_privilege(client, method, path, privilege):
    token, _, _ = _account(client, privileges=(privilege,), suffix=privilege.split(".")[0])
    response = client.request(method, path, headers=_bearer(token))
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(("method", "path", "privilege"), REPRESENTATIVE_ROUTES)
def test_each_global_administration_area_rejects_missing_privilege(client, method, path, privilege):
    token, _, _ = _account(client, privileges=(), suffix=f"no-{privilege.split('.')[0]}")
    response = client.request(method, path, headers=_bearer(token))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "insufficient_privilege"


def test_inactive_role_and_expired_assignment_take_effect_on_next_request(client):
    token, user_id, role_id = _account(
        client, privileges=("identity.users.administer",), suffix="timing",
    )
    governed_path = f"/api/v1/users/{user_id}/deletion-preflight"
    assert client.get(governed_path, headers=_bearer(token)).status_code == 200
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(
            "UPDATE roles SET date_deactivated=CURRENT_TIMESTAMP WHERE id=%s",
            (role_id,),
        )
    inactive = client.get(governed_path, headers=_bearer(token))
    assert inactive.status_code == 403
    assert inactive.json()["detail"]["code"] == "no_effective_role"

    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(
            "UPDATE roles SET date_deactivated=NULL WHERE id=%s", (role_id,)
        )
        connection.execute(
            """UPDATE user_role_assignments
                  SET valid_from=%s, valid_until=%s
                WHERE user_id=%s AND role_id=%s""",
            (
                datetime.now(timezone.utc) - timedelta(days=1),
                datetime.now(timezone.utc) - timedelta(seconds=1),
                user_id, role_id,
            ),
        )
    expired = client.get(governed_path, headers=_bearer(token))
    assert expired.status_code == 403
    assert expired.json()["detail"]["code"] == "no_effective_role"


def test_revoked_session_cannot_reuse_previously_authorized_privilege(client):
    token, user_id, _ = _account(
        client, privileges=("audit.view",), suffix="stale-session",
    )
    assert client.get("/api/v1/event-history", headers=_bearer(token)).status_code == 200
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(
            "UPDATE login_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE user_id=%s",
            (user_id,),
        )
    assert client.get("/api/v1/event-history", headers=_bearer(token)).status_code == 401


def test_denial_is_audited_without_sensitive_request_data(client):
    token, user_id, _ = _account(client, privileges=(), suffix="audited-denial")
    denied = client.get("/api/v1/users/1/deletion-preflight", headers=_bearer(token))
    assert denied.status_code == 403
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        event = connection.execute(
            """SELECT operation,metadata FROM event_history
                WHERE entity_type='user' AND entity_id=%s AND operation='AUTHORIZATION_DENIED'
                ORDER BY id DESC LIMIT 1""",
            (user_id,),
        ).fetchone()
    assert event["operation"] == "AUTHORIZATION_DENIED"
    expected_metadata = {
        "required_privilege": "identity.users.administer",
        "decision_code": "insufficient_privilege",
        "http_method": "GET",
        "request_path": "/api/v1/users/1/deletion-preflight",
    }
    assert {key: event["metadata"][key] for key in expected_metadata} == expected_metadata
    assert event["metadata"]["reference_snapshots"]["entity"]["id"] == user_id
    assert token not in json.dumps(event["metadata"])


def test_governance_labels_are_readable_without_catalogue_administration(client):
    catalogue = client.get("/api/v1/security-levels").json()
    custom = client.post("/api/v1/security-levels", json={
        "code": "LABEL-" + uuid4().hex[:12], "name": "Custom readable label",
        "level_number": max(item["level_number"] for item in catalogue) + 1,
    }, headers={"X-Change-Reason": "Create disposable custom governance label"})
    assert custom.status_code == 201, custom.text
    expected_codes = {item["code"] for item in catalogue} | {custom.json()["code"]}
    token, _, _ = _account(client, privileges=(), suffix="level-reader")
    response = client.get("/api/v1/security-levels", headers=_bearer(token))
    assert response.status_code == 200
    assert {item["code"] for item in response.json()} == expected_codes

    path = client.get("/api/v1/classifications/1/path", headers=_bearer(token))
    assert path.status_code == 200
    assert path.json()[-1]["id"] == 1

    assert client.get("/api/v1/classification-schemes", headers=_bearer(token)).status_code == 200
    assert client.get("/api/v1/classifications", headers=_bearer(token)).status_code == 200
    assert client.get("/api/v1/org-units", headers=_bearer(token)).status_code == 200
    assert client.get("/api/v1/roles", headers=_bearer(token)).status_code == 200
    assert client.get("/api/v1/users", headers=_bearer(token)).status_code == 200

    denied_create = client.post(
        "/api/v1/security-levels",
        json={"code": "X", "name": "Example", "level_number": 125},
        headers=_bearer(token),
    )
    assert denied_create.status_code == 403
    assert denied_create.json()["detail"]["code"] == "insufficient_privilege"


def test_dashboard_activity_is_self_only_and_does_not_require_audit_view(client):
    token, user_id, _ = _account(
        client,
        privileges=("aggregation.view", "aggregation.create_root"),
        suffix="self-activity",
    )
    created = client.post(
        "/api/v1/aggregations",
        json={
            "aggregation_number": "SELF-ACTIVITY-001",
            "title": "My recent work",
            "classification_id": 1,
        },
        headers=_bearer(token),
    )
    assert created.status_code == 201, created.text

    activity = client.get("/api/v1/auth/me/recent-activity", headers=_bearer(token))
    assert activity.status_code == 200, activity.text
    assert activity.json() == [{
        "entity_type": "aggregation",
        "entity_id": created.json()["id"],
        "operation": "CREATE",
        "occurred_at": activity.json()[0]["occurred_at"],
    }]
    assert user_id != 1


def test_reserved_role_name_is_not_a_runtime_bypass(client):
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        empty_profile = connection.execute(
            "INSERT INTO profiles(code,name) VALUES ('EMPTY_BOOTSTRAP_TEST','Empty bootstrap test') RETURNING id"
        ).fetchone()[0]
        connection.execute(
            "UPDATE roles SET profile_id=%s WHERE code='system-administrator'",
            (empty_profile,),
        )
    denied = client.get("/api/v1/users/1/deletion-preflight")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "insufficient_privilege"


def test_principal_exposes_effective_global_capabilities(client):
    principal = client.get("/api/v1/auth/me")
    assert principal.status_code == 200
    assert "authorization.administer" in principal.json()["global_privileges"]
    assert "identity.users.administer" in principal.json()["global_privileges"]


def test_every_unconditional_global_registry_route_has_the_matching_dependency():
    registry = json.loads(open("security/operation-policy-registry.json", encoding="utf-8").read())
    def expanded(routes):
        for route in routes:
            if isinstance(route, APIRoute):
                yield route
            elif hasattr(route, "original_router"):
                yield from expanded(route.original_router.routes)

    routes = {
        (method, route.path): route
        for route in expanded(app.routes)
        for method in route.methods
    }
    for operation in registry["api_operations"]:
        if operation["target_policy_class"] != "globally_privileged":
            continue
        route = routes[(operation["method"], operation["path"])]
        dependency_names = {
            dependency.call.__name__
            for dependency in route.dependant.dependencies
            if dependency.call is not None
        }
        expected = f"require_{operation['global_privilege'].replace('.', '_')}"
        assert expected in dependency_names, operation


@pytest.mark.parametrize("privileges", [
    (),
    ("aggregation.acl.manage",),
    ("record.acl.manage",),
    ("aggregation.acl.manage", "record.acl.manage"),
    ("authorization.administer",),
])
def test_permission_catalogue_conditional_global_privileges(client, privileges):
    """Catalogue access needs global privileges, not a resource-instance grant."""
    token, _, _ = _account(client, privileges=privileges, suffix="catalogue-reader")
    for resource_type in (None, "aggregation", "record"):
        params = {} if resource_type is None else {"resource_type": resource_type}
        response = client.get("/api/v1/permissions", params=params, headers=_bearer(token))
        allowed = "authorization.administer" in privileges or (
            resource_type is not None and f"{resource_type}.acl.manage" in privileges
        )
        assert response.status_code == (200 if allowed else 403), response.text
        if allowed:
            assert response.json(), "Authorized catalogue must not be empty"
            kinds = {item["resource_type"] for item in response.json()}
            assert kinds == ({resource_type} if resource_type else {"aggregation", "record"})
    assert client.get(
        "/api/v1/permissions", params={"resource_type": "unsupported"}, headers=_bearer(token)
    ).status_code == 422


def test_permission_catalogue_requires_authentication(client):
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    for params in ({}, {"resource_type": "aggregation"}, {"resource_type": "record"}):
        assert client.get("/api/v1/permissions", params=params).status_code == 401
