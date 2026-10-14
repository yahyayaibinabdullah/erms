"""Validated snapshots, the 30-second non-secret cache and governed updates."""
from dataclasses import dataclass, field
import logging
from threading import RLock
from time import monotonic
from types import MappingProxyType
from typing import Any, Callable, Mapping

from psycopg.types.json import Jsonb

from .application_settings_registry import REGISTRY, SettingsInvalid, validate_snapshot, validate_value

LOGGER = logging.getLogger(__name__)
CACHE_SECONDS = 30


@dataclass(frozen=True)
class Snapshot:
    database_id: str
    values: Mapping[str, Any]
    versions: Mapping[str, int]
    secret_is_set: bool
    installation_kind: str

    def __getitem__(self, key):
        # Secrets and unknown/deployment keys cannot be ordinary lookups.
        return self.values[key]


def _rows(connection, *, include_send_secret=False):
    return connection.execute(
        """SELECT s.key,s.value,s.version,s.provenance,s.date_updated,s.updated_by_user_id,
                  s.protected_secret IS NOT NULL AS secret_is_set,
                  CASE WHEN %s AND s.key='SMTP_PASSWORD' THEN s.protected_secret END AS send_secret,
                  state.database_id,state.installation_kind,
                  application_settings_set_valid() AS set_valid
             FROM application_settings s CROSS JOIN application_settings_state state
            ORDER BY s.key""", (include_send_secret,),
    ).fetchall()


def _snapshot(rows):
    if len(rows) != len(REGISTRY) or {row["key"] for row in rows} != set(REGISTRY):
        raise SettingsInvalid("application_settings_registry_mismatch")
    if any(not row["set_valid"] for row in rows):
        raise SettingsInvalid("application_settings_group_inconsistent")
    values = {row["key"]: row["value"] for row in rows if row["key"] != "SMTP_PASSWORD"}
    secret_set = next(row["secret_is_set"] for row in rows if row["key"] == "SMTP_PASSWORD")
    if values["SMTP_PORT"] is None and values["SMTP_SECURITY"] is not None:
        values["SMTP_PORT"] = 465 if values["SMTP_SECURITY"] == "implicit_tls" else 587
    validate_snapshot(values, secret_set)
    return Snapshot(str(rows[0]["database_id"]), MappingProxyType(values),
                    MappingProxyType({row["key"]: row["version"] for row in rows}),
                    secret_set, rows[0]["installation_kind"])


def load_snapshot(connection) -> Snapshot:
    """One query, all validated non-secret settings, never an environment read."""
    return _snapshot(_rows(connection))


def connection_key(connection):
    # No credentials, user identity, labels or authorization are in this cache.
    # Each deployed process uses one pool for one logical database.
    return (connection.info.host, connection.info.port, connection.info.dbname)


class SettingsCache:
    def __init__(self, clock: Callable[[], float] = monotonic):
        self.clock = clock
        self._entries = {}
        self._lock = RLock()

    def get(self, database_key, loader: Callable[[], Snapshot]) -> Snapshot:
        with self._lock:
            prior = self._entries.get(database_key)
            if prior and self.clock() - prior[1] < CACHE_SECONDS:
                return prior[0]
            try:
                snapshot = loader()
            except Exception as error:
                # Never log exception text, query parameters or row payloads.
                LOGGER.warning("application_settings_refresh_failed", extra={"failure_type": type(error).__name__})
                if prior:
                    return prior[0]
                raise SettingsInvalid("application_settings_unavailable") from None
            self._entries[database_key] = (snapshot, self.clock())
            return snapshot

    def for_connection(self, connection):
        return self.get(connection_key(connection), lambda: load_snapshot(connection))

    def invalidate(self, database_key=None):
        with self._lock:
            if database_key is None:
                self._entries.clear()
            else:
                self._entries.pop(database_key, None)


cache = SettingsCache()


def apply_changes(connection, changes, reason, *, migration_id=None, encrypt_secret=None):
    """Caller owns commit; public API invalidates only after commit succeeds.

    Migration is an internal governed path for the later explicit command.
    Omitted values retain current rows; completion never reimports finished keys.
    """
    prepared = []
    database_id = None
    for change in changes:
        key = change.key
        if key not in REGISTRY:
            raise SettingsInvalid("application_settings_invalid_update")
        definition = REGISTRY[key]
        item = {"key": key, "expected_version": change.expected_version}
        provided = change.model_fields_set
        if definition.secret:
            if "value" in provided or (change.clear_secret and change.secret_value is not None):
                raise SettingsInvalid("application_settings_invalid_update")
            if change.clear_secret:
                item["encrypted_secret"] = None
            elif change.secret_value is not None:
                value = change.secret_value.get_secret_value()
                if not value.strip() or encrypt_secret is None:
                    raise SettingsInvalid("application_settings_secret_unavailable")
                if database_id is None:
                    database_id = str(connection.execute("SELECT database_id FROM application_settings_state").fetchone()["database_id"])
                item["encrypted_secret"] = encrypt_secret(value, database_id)
        else:
            if change.secret_value is not None or change.clear_secret:
                raise SettingsInvalid("application_settings_invalid_update")
            if "value" in provided:
                validate_value(definition, change.value)
                item["value"] = change.value
        prepared.append(item)
    connection.execute("SELECT apply_application_settings(%s,%s,%s)", (Jsonb(prepared), reason, migration_id))


@dataclass(frozen=True)
class JobSettings:
    review_route: str


@dataclass(frozen=True)
class ArtifactSettings:
    scheme_id: int | None
    uploaded_evidence_classification_id: int | None
    generated_reports_classification_id: int | None
    authority_name: str


@dataclass(frozen=True)
class EmailSettings:
    recipient: str
    host: str
    port: int
    security: str
    authentication_enabled: bool
    username: str | None
    password: Any = field(repr=False)
    sender_email: str
    sender_name: str | None
    reply_to: str | None
    timeout_seconds: int

    def safe_values(self):
        return {key: value for key, value in self.__dict__.items() if key != "password"}


def _fresh_capture(operation, connection_factory=None):
    # A separate read transaction guarantees current committed values even when
    # a caller already has an older repeatable-read transaction. No cache fallback.
    if connection_factory is None:
        from .database import pool
        connection_factory = pool.connection
    with connection_factory() as connection:
        return operation(connection)


def capture_job_settings(connection_factory=None):
    return _fresh_capture(lambda c: JobSettings(load_snapshot(c)["DISPOSITION_DESTRUCTION_REVIEW_ROUTE"]), connection_factory)


def capture_artifact_settings(connection_factory=None):
    def capture(c):
        snapshot = load_snapshot(c)
        return ArtifactSettings(snapshot["DISPOSITION_CLASSIFICATION_SCHEME_ID"],
                                snapshot["DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID"],
                                snapshot["DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID"],
                                snapshot["DISPOSITION_EXTERNAL_AUTHORITY_NAME"])
    return _fresh_capture(capture, connection_factory)


def capture_email_settings(*, decrypt_secret, connection_factory=None):
    def capture(c):
        rows = _rows(c, include_send_secret=True)
        snapshot = _snapshot(rows)
        required = ("DISPOSITION_EXTERNAL_AUTHORITY_EMAIL", "SMTP_HOST", "SMTP_PORT", "SMTP_SECURITY", "SMTP_AUTH_ENABLED", "SMTP_SENDER_EMAIL")
        if any(snapshot[key] is None for key in required):
            raise SettingsInvalid("application_settings_email_incomplete")
        password = None
        if snapshot["SMTP_AUTH_ENABLED"]:
            encrypted = next(row["send_secret"] for row in rows if row["key"] == "SMTP_PASSWORD")
            password = decrypt_secret(bytes(encrypted), snapshot.database_id)
        return EmailSettings(snapshot["DISPOSITION_EXTERNAL_AUTHORITY_EMAIL"], snapshot["SMTP_HOST"],
                             snapshot["SMTP_PORT"], snapshot["SMTP_SECURITY"], snapshot["SMTP_AUTH_ENABLED"],
                             snapshot["SMTP_USERNAME"], password, snapshot["SMTP_SENDER_EMAIL"],
                             snapshot["SMTP_SENDER_NAME"], snapshot["SMTP_REPLY_TO_EMAIL"], snapshot["SMTP_TIMEOUT_SECONDS"])
    return _fresh_capture(capture, connection_factory)
