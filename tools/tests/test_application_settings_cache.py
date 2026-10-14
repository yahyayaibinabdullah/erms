"""Deterministic cache/registry checks without database or environment setup."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import MappingProxyType

import pytest

from backend.services.api.application_settings import SettingsCache, Snapshot
from backend.services.api.application_settings_registry import REGISTRY, SettingsInvalid, validate_value


def snapshot(route="standard"):
    return Snapshot("test-db", MappingProxyType({"route": route}), MappingProxyType({}), False, "fresh")


def test_cache_hit_expiry_and_load_completion_clock():
    now = [0.0]
    cache = SettingsCache(lambda: now[0])
    calls = []
    def load():
        calls.append(1)
        now[0] += 5
        return snapshot()
    first = cache.get("one", load)
    now[0] = 34.99
    assert cache.get("one", load) is first
    assert len(calls) == 1
    now[0] = 35
    cache.get("one", load)
    assert len(calls) == 2


def test_concurrent_reload_is_single_load_and_databases_are_isolated():
    cache = SettingsCache()
    calls = []
    def load():
        calls.append(1)
        return snapshot()
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda _: cache.get("one", load), range(16)))
    assert len(calls) == 1 and all(value is values[0] for value in values)
    assert cache.get("two", lambda: snapshot("simplified"))["route"] == "simplified"
    assert cache.get("one", load)["route"] == "standard"


def test_updating_process_invalidates_and_other_instance_converges():
    now = [0]
    first, second = SettingsCache(lambda: now[0]), SettingsCache(lambda: now[0])
    current = [snapshot()]
    for cache in (first, second):
        cache.get("db", lambda: current[0])
    current[0] = snapshot("records_manager_only")
    first.invalidate("db")
    assert first.get("db", lambda: current[0]) is current[0]
    assert second.get("db", lambda: current[0])["route"] == "standard"
    now[0] = 30
    assert second.get("db", lambda: current[0]) is current[0]


def test_refresh_failure_retains_only_valid_snapshot_and_logs_no_error_values(caplog):
    now = [0]
    cache = SettingsCache(lambda: now[0])
    old = cache.get("db", lambda: snapshot())
    now[0] = 30
    def fail():
        raise ValueError("private-password-or-database-URL")
    assert cache.get("db", fail) is old
    assert "private-password-or-database-URL" not in caplog.text
    with pytest.raises(SettingsInvalid, match="unavailable"):
        cache.get("another-db", fail)


def test_unknown_keys_secrets_and_mutation_are_not_ordinary_snapshot_lookups():
    loaded = snapshot()
    with pytest.raises(KeyError):
        loaded["SMTP_PASSWORD"]
    with pytest.raises(KeyError):
        loaded["DATABASE_URL"]
    with pytest.raises(TypeError):
        loaded.values["route"] = "changed"


@pytest.mark.parametrize("key,value", [
    ("MAX_UPLOAD_SIZE_BYTES", True), ("AUTH_LOCKOUT_ATTEMPTS", "5"),
    ("CONTENT_SEGMENT_SIZE_BYTES", 67108865), ("AUTH_PASSWORD_MIN_LENGTH", 7),
    ("SMTP_PORT", 65536), ("SMTP_AUTH_ENABLED", "false"),
    ("DISPOSITION_EXTERNAL_AUTHORITY_EMAIL", "missing-at"),
    ("DISPOSITION_DESTRUCTION_REVIEW_ROUTE", "invented"),
])
def test_registry_rejects_ambiguous_types_and_invalid_values(key, value):
    with pytest.raises(SettingsInvalid):
        validate_value(REGISTRY[key], value)


def test_registry_is_complete_explicit_editable_and_defaults_are_valid():
    assert len(REGISTRY) == 51
    for setting in REGISTRY.values():
        assert setting.category and setting.editable and setting.label_key and setting.description_key
        if not setting.secret:
            validate_value(setting, setting.default)
    assert REGISTRY["DISPOSITION_DESTRUCTION_REMINDER_MONTHS"].default == 6
    assert REGISTRY["AUDIT_TRAIL_SEARCH_RESULT_LIMIT"].default == 1000
    assert "WEBUI_FULL_TEXT_SEARCH_ENABLED" not in REGISTRY


def test_canonical_and_upgrade_settings_ddl_are_identical_except_installation_kind():
    root = Path(__file__).resolve().parents[2]
    schema = (root / "database/schema.sql").read_text()
    upgrade = (root / "database/migrations/050_application_settings.sql").read_text()
    marker = "-- Shared configuration foundation."
    canonical = schema[schema.index(marker):].strip()
    migration = upgrade[upgrade.index(marker):].removesuffix("\nCOMMIT;\n").strip()
    marker_051="INSERT INTO schema_migrations(version) VALUES('051_database_indexing_policy') ON CONFLICT DO NOTHING;"
    assert canonical.count(marker_051)==1
    canonical=canonical.replace("\n"+marker_051,"")
    assert canonical == migration.replace("VALUES(true,'upgrade')", "VALUES(true,'fresh')")
