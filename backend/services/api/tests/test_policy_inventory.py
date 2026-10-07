import json
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient

from tools.generate_policy_inventory import PROJECT_ROOT, _target_policy, build_inventory


REGISTRY_PATH = PROJECT_ROOT / "security" / "operation-policy-registry.json"
SEED_PATH = PROJECT_ROOT / "security" / "catalogue-seed.json"


def test_database_sql_contains_no_psql_meta_commands():
    offenders = []
    # Check project SQL, including new untracked files, but not ignored
    # pg_dump backups, virtual environments, or other local artifacts.
    project_sql = subprocess.check_output([
        "git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.sql",
    ], cwd=PROJECT_ROOT, text=True).splitlines()
    for path in (PROJECT_ROOT / name for name in sorted(set(project_sql))):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("\\"):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{line_number}: {line}")

    assert not offenders, (
        "SQL files must be executable by PostgreSQL clients without psql "
        "meta-commands:\n" + "\n".join(offenders)
    )


def test_canonical_schema_is_self_contained_and_current():
    schema = (PROJECT_ROOT / "database" / "schema.sql").read_text(encoding="utf-8")

    assert "\\i " not in schema
    assert "\\ir " not in schema
    assert "CREATE TABLE schema_migrations" in schema
    assert "INSERT INTO schema_migrations" not in schema
    assert "aggregation.location.change" in schema
    assert "aggregations_protect_vital_deletion" in schema
    assert "aggregations_owner_review_due_idx" in schema


def test_seed_utilities_are_distinct_from_migrations():
    seeds = PROJECT_ROOT / "database" / "seeds"
    for path in sorted(seeds.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        assert "app.event_source', 'seeding'" in sql, path
        assert "INSERT INTO schema_migrations" not in sql, path

    importer = (seeds / "import_mutamathilah.py").read_text(encoding="utf-8")
    assert '("app.event_source", "seeding")' in importer
    assert "schema_migrations" not in importer
    assert '"seed": SEED_NAME' in importer


def test_api_operation_inventory_is_complete_and_current():
    committed = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    generated = build_inventory()

    assert committed == generated, (
        "API routes or policy classifications changed without security review; run "
        "PYTHONPATH=. backend/services/api/.venv/bin/python "
        "tools/generate_policy_inventory.py and review the diff"
    )
    assert committed["schema_version"] == 2
    assert committed["scope"] == "api_authorization_boundary"
    assert "ui_actions" not in committed
    assert committed["enforcement_status"] == "authorization_dependent_permanent_deletion_enforced"
    assert committed["phase"] == 12
    assert len(committed["api_operations"]) == len(
        {(item["method"], item["path"]) for item in committed["api_operations"]}
    )
    assert all(item["phase_0_enforced"] is False for item in committed["api_operations"])
    assert all(
        item["phase_4_enforced"] == (item["target_policy_class"] == "globally_privileged")
        for item in committed["api_operations"]
    )
    assert all("phase_7_enforced" in item for item in committed["api_operations"])
    assert all("phase_8_enforced" in item for item in committed["api_operations"])
    assert all("phase_9_enforced" in item for item in committed["api_operations"])
    assert all("phase_11_enforced" in item for item in committed["api_operations"])
    assert all("phase_12_enforced" in item for item in committed["api_operations"])
    assert all(
        item["phase_5_enforced"] == (
            item["path"] == "/api/v1/permissions"
            or (("permissions" in item["path"] or "/acl-move" in item["path"]) and item["path"].startswith(("/api/v1/aggregations/", "/api/v1/records/")))
        )
        for item in committed["api_operations"]
    )


def test_unclassified_api_operation_is_rejected_instead_of_getting_a_fallback():
    with pytest.raises(ValueError, match="has no explicit policy classification"):
        _target_policy("POST", "/api/v1/new-unreviewed-operation")


def test_number_suggestions_have_explicit_relationship_scoped_policy():
    assert _target_policy("GET", "/api/v1/number-suggestions/{resource}") == (
        "relationship_scoped",
        None,
        None,
    )


def test_registry_declares_every_policy_class_it_uses():
    registry = build_inventory()
    used = {
        operation["target_policy_class"]
        for operation in registry["api_operations"]
    }
    assert used <= set(registry["access_classes"])


def test_every_target_policy_reference_exists_in_approved_seed():
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    privileges = {item["code"] for item in seed["privileges"]}
    permissions = {
        code
        for catalogue in seed["permissions"].values()
        for code in catalogue
    }

    for operation in registry["api_operations"]:
        if operation["global_privilege"]:
            assert operation["global_privilege"] in privileges, operation
        if operation["resource_permission"]:
            assert operation["resource_permission"] in permissions, operation


def test_approved_seed_catalogue_and_dependencies_are_internally_consistent():
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    levels = seed["security_levels"]
    privileges = {item["code"] for item in seed["privileges"]}
    permissions = {
        code
        for catalogue in seed["permissions"].values()
        for code in catalogue
    }

    assert [(item["code"], item["level_number"]) for item in levels] == [
        ("G", 0),
        ("R", 50),
        ("S", 75),
        ("TS", 100),
    ]
    assert sum(item["prevents_disposition"] for item in levels) == 1
    assert next(item for item in levels if item["prevents_disposition"])["code"] == "TS"

    dependencies = seed["permission_dependencies"]
    assert set(dependencies) <= permissions
    assert all(set(requirements) <= permissions for requirements in dependencies.values())

    profiles = {item["code"]: item for item in seed["profiles"]}
    assert profiles["ALL_PRIVS"]["privilege_codes"] == "*"
    for profile in profiles.values():
        if profile["privilege_codes"] != "*":
            assert set(profile["privilege_codes"]) <= privileges
    assert not {
        "aggregation.view",
        "record.view",
        "record.component.download",
    } & set(profiles["SYS_ADMIN"]["privilege_codes"])
    assert set(profiles["INFO_GOV_MGR"]["privilege_codes"]) == set(
        profiles["INFO_GOV_OFFICER"]["privilege_codes"]
    )
    assert "search.saved_search.administer" in profiles["INFO_GOV_MGR"]["privilege_codes"]
    assert "search.saved_search.delete" in profiles["INFO_GOV_MGR"]["privilege_codes"]
    assert "classifications.administer" in profiles["INFO_GOV_MGR"]["privilege_codes"]
    assert "security_levels.administer" in profiles["INFO_GOV_MGR"]["privilege_codes"]
    assert "organization.browse" in profiles["SYS_ADMIN"]["privilege_codes"]
    assert "organization.browse" in profiles["INFO_GOV_MGR"]["privilege_codes"]


def test_phase_zero_current_access_characterization(client: TestClient):
    """Freeze the pre-enforcement public/authenticated boundary."""
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)

    assert client.get("/health").status_code == 200
    assert client.post(
        "/api/v1/auth/login",
        json={"email": "missing@test.invalid", "password": "not-the-password"},
    ).status_code == 401
    assert client.get("/api/v1/aggregations").status_code == 401
    assert client.get("/api/v1/users").status_code == 401
    assert client.get("/api/v1/event-history").status_code == 401


def test_permission_catalogue_records_conditional_policy():
    assert _target_policy("GET", "/api/v1/permissions") == ("relationship_scoped", None, None)
    registry = build_inventory()
    conditional = [operation for operation in registry["api_operations"]
                   if "conditional_global_privileges" in operation]
    assert [operation["id"] for operation in conditional] == ["GET:/api/v1/permissions"]
    assert conditional[0]["conditional_global_privileges"] == {
        "query_parameter": "resource_type",
        "match": "any",
        "when_omitted": ["authorization.administer"],
        "by_value": {
            "aggregation": ["authorization.administer", "aggregation.acl.manage"],
            "record": ["authorization.administer", "record.acl.manage"],
        },
    }
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    privileges = {item["code"] for item in seed["privileges"]}
    rule = conditional[0]["conditional_global_privileges"]
    assert set(rule["when_omitted"]) <= privileges
    assert all(set(alternatives) <= privileges for alternatives in rule["by_value"].values())
