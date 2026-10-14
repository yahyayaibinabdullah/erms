import os

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb
import pytest
from fastapi.testclient import TestClient

from backend.services.api.main import app
from backend.services.api.authentication import hash_password
from backend.services.api.application_settings_registry import REGISTRY
from backend.services.api.application_settings import cache as settings_cache


def _require_disposable_database():
    name = conninfo_to_dict(os.environ["DATABASE_URL"]).get("dbname", "")
    if not name.startswith("erms_messaging_test_acl_"):
        raise RuntimeError("API fixtures require a new disposable database from tools/run_disposable_acl_tests.py")


def _allow_settings_fixture_reset(connection):
    _require_disposable_database()
    # TRUNCATE classifications CASCADE also clears its generated settings FKs.
    # This explicit fixture reset is restricted to the disposable runner database.
    for table in ("application_settings", "application_settings_migration_keys"):
        connection.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")


def _restore_settings_fixture(connection):
    for table in ("application_settings", "application_settings_migration_keys"):
        connection.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
    source = connection.execute("SELECT current_setting('app.event_source',true)").fetchone()[0]
    connection.execute("SELECT set_config('app.event_source','seeding',true)")
    connection.cursor().executemany(
        "INSERT INTO application_settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO NOTHING",
        [(key, Jsonb(setting.default)) for key, setting in REGISTRY.items()],
    )
    connection.execute("SELECT set_config('app.event_source',%s,true)", (source or "",))
    settings_cache.invalidate()


@pytest.fixture(scope="session")
def client():
    # Reject before lifespan can synchronize any persistent database catalogue.
    _require_disposable_database()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_database(client: TestClient):
    password = "Temporary-Test-Password-123!"
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        _allow_settings_fixture_reset(connection)
        connection.execute("TRUNCATE saved_searches, user_favourite_records, user_favourite_aggregations, user_classification_selections, aggregation_retention_rules, classification_retention_rules, classifications, classification_schemes, login_sessions, user_credentials, user_role_assignments, roles, users, org_units, record_draft_components, record_drafts, digital_components, records, aggregations RESTART IDENTITY CASCADE")
        # Resetting the now-complete UI catalogue for every test is fixture
        # setup, not a governed user change. Suppress per-row audit events here
        # to avoid generating thousands of throwaway WAL records per test.
        connection.execute("ALTER TABLE ui_message_translations DISABLE TRIGGER USER")
        connection.execute("TRUNCATE ui_message_translations")
        connection.execute("SELECT set_config('app.change_reason','Reset localization test catalogue',true)")
        connection.execute("DELETE FROM supported_languages WHERE lower(language_tag) NOT IN ('en','ar')")
        connection.execute("UPDATE supported_languages SET catalogue_revision=1")
        connection.execute(
            """INSERT INTO ui_message_translations(message_key,language_tag,translated_text,status,origin)
               SELECT definition.message_key,language.language_tag,definition.default_text,'draft','source_copy'
                 FROM ui_message_definitions definition CROSS JOIN supported_languages language
                WHERE lower(language.language_tag)<>'en'"""
        )
        connection.execute("ALTER TABLE ui_message_translations ENABLE TRIGGER USER")
        connection.execute("ALTER TABLE event_history DISABLE TRIGGER USER")
        # Security Levels are canonical seeded catalogue rows and are not
        # truncated between tests. Preserve their matching immutable baseline
        # CREATE events as well; deleting them made the seed history disappear
        # while leaving the seeded entities behind.
        connection.execute(
            """DELETE FROM event_history
                WHERE NOT (
                    entity_type='security_level'
                    AND operation='CREATE'
                    AND source='seeding'
                    AND entity_id IN (SELECT id FROM security_levels)
                )"""
        )
        connection.execute("ALTER TABLE event_history ENABLE TRIGGER USER")
        org_id = connection.execute("INSERT INTO org_units (code,name) VALUES ('test-root','Test Root') RETURNING id").fetchone()[0]
        user_id = connection.execute("INSERT INTO users (name,email) VALUES ('Test Administrator','admin@test.invalid') RETURNING id").fetchone()[0]
        role_id = connection.execute("INSERT INTO roles (org_unit_id,code,name,is_information_governance) VALUES (%s,'system-administrator','System Administrator',true) RETURNING id", (org_id,)).fetchone()[0]
        connection.execute(
            """INSERT INTO roles(
                   org_unit_id,supervisor_role_id,code,name,description,security_level_id,
                   profile_id,is_information_governance,is_system,account_type_restriction
               )
               SELECT NULL,NULL,'text-indexer-service','Text Indexer Service',
                      'Protected non-organizational role for text-indexer service accounts.',
                      level.id,profile.id,false,true,'service'
               FROM security_levels level CROSS JOIN profiles profile
               WHERE level.level_number=(SELECT min(level_number) FROM security_levels)
                 AND profile.code='TEXT_INDEXER_SERVICE'"""
        )
        connection.execute("INSERT INTO user_role_assignments (user_id,role_id) VALUES (%s,%s)", (user_id,role_id))
        connection.execute("INSERT INTO user_credentials (user_id,password_hash,must_change_password) VALUES (%s,%s,false)", (user_id,hash_password(password)))
        scheme_id = connection.execute("INSERT INTO classification_schemes (code,title,date_published) VALUES ('TEST','Test Scheme',CURRENT_TIMESTAMP) RETURNING id").fetchone()[0]
        classification_id = connection.execute("INSERT INTO classifications (classification_scheme_id,code,title,is_terminal) VALUES (%s,'TEST-01','Test Classification',true) RETURNING id", (scheme_id,)).fetchone()[0]
        connection.execute("INSERT INTO classification_retention_rules (classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES (%s,5,0,'destruction')", (classification_id,))
        _restore_settings_fixture(connection)
    login = client.post("/api/v1/auth/login", json={"email": "admin@test.invalid", "password": password})
    assert login.status_code == 200, login.text
    client.headers["X-CSRF-Token"] = client.cookies.get("erms_csrf")
    yield
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        _allow_settings_fixture_reset(connection)
        connection.execute(
            """
            TRUNCATE
                saved_searches,
                user_favourite_records,
                user_favourite_aggregations,
                record_draft_components,
                record_drafts,
                login_sessions,
                user_credentials,
                user_role_assignments,
                roles,
                users,
                org_units,
                digital_components,
                records,
                aggregations
                ,user_classification_selections
                ,aggregation_retention_rules
                ,classification_retention_rules
                ,classifications
                ,classification_schemes
            RESTART IDENTITY CASCADE
            """
        )
        connection.execute("ALTER TABLE event_history DISABLE TRIGGER USER")
        # Keep the canonical Security Level seed events in lockstep with the
        # catalogue rows retained by this fixture.
        connection.execute(
            """DELETE FROM event_history
                WHERE NOT (
                    entity_type='security_level'
                    AND operation='CREATE'
                    AND source='seeding'
                    AND entity_id IN (SELECT id FROM security_levels)
                )"""
        )
        connection.execute("ALTER TABLE event_history ENABLE TRIGGER USER")
        _restore_settings_fixture(connection)
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)


@pytest.fixture
def aggregation(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/aggregations",
        json={"aggregation_number": "AGG-001", "title": "Root aggregation", "classification_id": 1},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def record(client: TestClient, aggregation: dict) -> dict:
    response = client.post(
        "/api/v1/records",
        json={
            "aggregation_id": aggregation["id"],
            "record_number": "REC-001",
            "title": "Example record",
        },
    )
    assert response.status_code == 201
    return response.json()
