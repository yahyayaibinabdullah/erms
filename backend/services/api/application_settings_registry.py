"""Closed, typed application configuration contract (ACFG sections 5 and 7).

This module performs no environment reads, database access, or startup seeding.
Categories are explicit application metadata, never columns or key-prefix rules.
"""
from dataclasses import dataclass
from email.headerregistry import Address
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class Setting:
    key: str
    category: str
    kind: str
    default: Any
    label: str
    purpose: str
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()
    nullable: bool = False
    group: str | None = None
    secret: bool = False
    editable: bool = True

    @property
    def label_key(self):
        return f"settings.field.{self.key.lower()}.label"

    @property
    def description_key(self):
        return f"settings.field.{self.key.lower()}.description"


CATEGORIES = MappingProxyType({
    "general": "General application behavior",
    "content": "Content and document viewing",
    "authentication": "Authentication and sessions",
    "interface_limits": "Dashboard and selection limits",
    "search": "Search and indexing",
    "disposition": "Disposition",
    "email": "Email",
})


def integer(key, category, default, label, purpose, minimum=1, maximum=None):
    return Setting(key, category, "integer", default, label, purpose, minimum, maximum)


_DEFINITIONS = (
    Setting("DEFAULT_WORKING_TIMEZONE", "general", "timezone", "Asia/Dubai", "Default working timezone", "Working timezone used when a person has no saved timezone preference."),
    Setting("DEFAULT_ROOT_AGGREGATION_MEDIUM", "general", "enum", "mixed", "Default root aggregation medium", "Initial medium for a new root aggregation.", choices=("digital", "physical", "mixed")),
    integer("REVIEW_WARNING_WINDOW_DAYS", "general", 30, "Review warning window", "Days before a scheduled review when the resource appears as approaching review.", 0),
    integer("MAX_UPLOAD_SIZE_BYTES", "content", 52428800, "Maximum upload size", "Maximum complete logical file size in bytes."),
    integer("CONTENT_SEGMENT_SIZE_BYTES", "content", 16777216, "Content segment size", "Target segment size in bytes; from 1 byte to 64 MiB.", maximum=67108864),
    Setting("CONTENT_SEGMENT_CHECKSUMS_ENABLED", "content", "boolean", True, "Content segment checksums", "Store and verify per-segment checksums."),
    integer("CONTENT_UPLOAD_SESSION_TTL_SECONDS", "content", 86400, "Upload session lifetime", "Lifetime of an incomplete content upload in seconds."),
    integer("CONTENT_CLEANUP_INTERVAL_SECONDS", "content", 3600, "Content cleanup interval", "Seconds between content cleanup passes."),
    integer("DOCUMENT_CONVERSION_TIMEOUT_SECONDS", "content", 60, "Document conversion timeout", "Maximum document conversion time in seconds."),
    integer("MAX_RENDITION_SIZE_BYTES", "content", 104857600, "Maximum rendition size", "Maximum generated document rendition size in bytes."),
    integer("AUTH_SESSION_IDLE_MINUTES", "authentication", 30, "Session idle lifetime", "Idle session lifetime in minutes; changes apply on the next evaluation and never revive an expired session."),
    integer("AUTH_SESSION_ABSOLUTE_HOURS", "authentication", 12, "Session absolute lifetime", "Absolute session lifetime in hours; changes never revive an expired session."),
    integer("AUTH_LOCKOUT_ATTEMPTS", "authentication", 5, "Lockout attempts", "Failed login attempts before temporary credential lockout."),
    integer("AUTH_LOCKOUT_MINUTES", "authentication", 15, "Lockout duration", "Temporary credential lockout duration in minutes."),
    integer("AUTH_PASSWORD_MIN_LENGTH", "authentication", 12, "Minimum password length", "Minimum characters for newly set or changed passwords; existing password hashes remain valid.", 8),
    integer("AUTH_SESSION_RETENTION_DAYS", "authentication", 90, "Session history retention", "Session history retention in days.", 0),
    integer("AUTH_SESSION_CLEANUP_INTERVAL_SECONDS", "authentication", 3600, "Session cleanup interval", "Seconds between session history cleanup passes."),
    integer("AUTH_SESSION_CLEANUP_BATCH_SIZE", "authentication", 500, "Session cleanup batch size", "Maximum session history rows considered per cleanup batch."),
    integer("DASHBOARD_FAVOURITE_ITEM_LIMIT", "interface_limits", 5, "Dashboard favourite limit", "Maximum favourite items shown in the dashboard preview."),
    integer("DASHBOARD_RECENT_ITEM_LIMIT", "interface_limits", 4, "Dashboard recent item limit", "Maximum recent items shown in the dashboard preview."),
    integer("DASHBOARD_RECENT_DAYS", "interface_limits", 30, "Dashboard recent period", "Days included in the dashboard recent-items preview."),
    integer("DASHBOARD_REVIEW_PREVIEW_LIMIT", "interface_limits", 5, "Dashboard review preview limit", "Maximum resources shown in the dashboard review preview."),
    integer("CLASSIFICATION_RECENT_SELECTION_LIMIT", "interface_limits", 4, "Recent classification selection limit", "Maximum recent classification selections shown."),
    integer("USER_DETAILS_SESSION_LIMIT", "interface_limits", 5, "User session page size", "Session rows per page in user details; server pagination remains required."),
    Setting("FULL_TEXT_SEARCH_ENABLED", "search", "boolean", False, "Full-text search enabled", "Availability of API-enforced full-text search."),
    Setting("CONTENT_INDEXING_SCHEDULING_ENABLED", "search", "boolean", False, "Content indexing scheduling enabled", "Schedule API-owned content indexing work."),
    integer("CONTENT_INDEXING_HISTORY_RETENTION_DAYS", "search", 365, "Indexing history retention", "Content indexing history retention in days.", 0),
    integer("CONTENT_INDEXING_CLEANUP_INTERVAL_SECONDS", "search", 3600, "Indexing cleanup interval", "Seconds between API-owned indexing cleanup passes."),
    integer("CONTENT_INDEXING_CLEANUP_BATCH_SIZE", "search", 500, "Indexing cleanup batch size", "Maximum indexing history rows considered per cleanup batch."),
    integer("TEXT_INDEXER_CREDENTIAL_HISTORY_RETENTION_DAYS", "search", 365, "Indexer credential history retention", "API-owned indexer credential history retention in days.", 0),
    integer("TEXT_INDEXER_RATE_LIMIT_PER_MINUTE", "search", 600, "Indexer request rate limit", "Maximum authenticated indexer requests per minute."),
    integer("SEARCH_RATE_LIMIT_PER_MINUTE", "search", 600, "Search request rate limit", "Maximum authenticated search requests per minute."),
    integer("MANUAL_REINDEX_RATE_LIMIT_PER_MINUTE", "search", 60, "Manual reindex rate limit", "Maximum manual reindex requests per minute."),
    integer("AUDIT_TRAIL_SEARCH_RESULT_LIMIT", "search", 1000, "Audit Trail search result limit", "Maximum matching Audit Trail results and bounded count work; one effective cap applies throughout each request."),
    Setting("DISPOSITION_DESTRUCTION_REVIEW_ROUTE", "disposition", "enum", "standard", "Destruction review route", "New jobs capture this route permanently. Records Manager Only omits independent internal review.", choices=("standard", "simplified", "records_manager_only")),
    Setting("DISPOSITION_CLASSIFICATION_SCHEME_ID", "disposition", "scheme", None, "Classification scheme", "Scheme for both disposition destinations; unset blocks the relevant artifact tasks.", nullable=True, group="destinations"),
    Setting("DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID", "disposition", "classification", None, "Uploaded evidence classification", "Terminal classification in the selected scheme for uploads and the digital destruction certificate.", nullable=True, group="destinations"),
    Setting("DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID", "disposition", "classification", None, "Generated reports classification", "Terminal classification in the selected scheme for generated reports, excluding the digital destruction certificate.", nullable=True, group="destinations"),
    Setting("DISPOSITION_EXTERNAL_AUTHORITY_NAME", "disposition", "string", "Sharjah Archives", "External archives authority name", "Recipient authority on new request forms; earlier forms retain their original name."),
    Setting("DISPOSITION_EXTERNAL_AUTHORITY_EMAIL", "disposition", "email", None, "External archives authority email address", "Recipient for subsequent document email attempts; unset prevents sending.", nullable=True),
    integer("DISPOSITION_DESTRUCTION_REMINDER_MONTHS", "disposition", 6, "Destruction reminder interval", "Calendar months between future eligibility reminders; no historical reminders are sent."),
    Setting("SMTP_HOST", "email", "string", None, "SMTP server hostname", "Outgoing mail server; unset prevents sending.", nullable=True, group="smtp"),
    Setting("SMTP_PORT", "email", "integer", None, "SMTP port", "Port from 1 to 65535; untouched default follows security mode: 587 for STARTTLS or 465 for implicit TLS.", 1, 65535, nullable=True, group="smtp"),
    Setting("SMTP_SECURITY", "email", "enum", None, "SMTP connection security", "Configure STARTTLS or implicit TLS; certificate verification stays enabled.", choices=("starttls", "implicit_tls"), nullable=True, group="smtp"),
    Setting("SMTP_AUTH_ENABLED", "email", "boolean", None, "SMTP authentication enabled", "Configure whether authentication is needed; enabled requires username and password.", nullable=True, group="smtp"),
    Setting("SMTP_USERNAME", "email", "string", None, "SMTP username", "Username required when SMTP authentication is enabled.", nullable=True, group="smtp"),
    Setting("SMTP_PASSWORD", "email", "secret", None, "SMTP password", "Protected credential replacement; saved passwords are never readable. Required when authentication is enabled.", nullable=True, group="smtp", secret=True),
    Setting("SMTP_SENDER_EMAIL", "email", "email", None, "Sender email address", "Sender address required for outgoing document email.", nullable=True, group="smtp"),
    Setting("SMTP_SENDER_NAME", "email", "string", None, "Sender display name", "Optional sender display name.", nullable=True, group="smtp"),
    Setting("SMTP_REPLY_TO_EMAIL", "email", "email", None, "Reply-to email address", "Optional reply-to address for outgoing document email.", nullable=True, group="smtp"),
    Setting("SMTP_TIMEOUT_SECONDS", "email", "integer", 30, "Connection and send timeout", "Positive connection and send timeout in seconds.", 1, group="smtp"),
)
REGISTRY = MappingProxyType({item.key: item for item in _DEFINITIONS})
GROUPS = MappingProxyType({
    "destinations": frozenset(item.key for item in _DEFINITIONS if item.group == "destinations"),
    "smtp": frozenset(item.key for item in _DEFINITIONS if item.group == "smtp"),
})
MESSAGE_KEYS = frozenset(
    [f"settings.category.{category}" for category in CATEGORIES]
    + [key for setting in _DEFINITIONS for key in (setting.label_key, setting.description_key)]
)


class SettingsInvalid(ValueError):
    """A safe error: never interpolate a rejected value or secret."""


def validate_value(setting: Setting, value: Any) -> None:
    if value is None and setting.nullable:
        return
    valid = False
    if setting.kind == "integer":
        valid = type(value) is int and value >= setting.minimum and value <= (setting.maximum or 9223372036854775807)
    elif setting.kind == "boolean":
        valid = type(value) is bool
    elif setting.kind in {"string", "email", "timezone", "enum"}:
        valid = isinstance(value, str) and bool(value.strip()) and "\r" not in value and "\n" not in value
        if valid and setting.kind == "enum":
            valid = value in setting.choices
        if valid and setting.kind == "email":
            try:
                address = Address(addr_spec=value)
                valid = bool(address.username and address.domain) and address.addr_spec == value
            except ValueError:
                valid = False
        if valid and setting.kind == "timezone":
            try:
                valid = ZoneInfo(value).key == value
            except (ZoneInfoNotFoundError, ValueError):
                valid = False
    elif setting.kind in {"scheme", "classification"}:
        valid = type(value) is int and 0 < value <= 9223372036854775807
    elif setting.secret:
        # Decrypted credentials never form part of a validated public snapshot.
        valid = False
    if not valid:
        raise SettingsInvalid("application_setting_value_invalid")


def validate_snapshot(values: dict, secret_set: bool) -> None:
    expected = set(REGISTRY) - {"SMTP_PASSWORD"}
    if set(values) != expected:
        raise SettingsInvalid("application_settings_registry_mismatch")
    for key, value in values.items():
        validate_value(REGISTRY[key], value)
    if values["SMTP_AUTH_ENABLED"] is True and (not values["SMTP_USERNAME"] or not secret_set):
        raise SettingsInvalid("application_settings_smtp_inconsistent")
    if values["SMTP_SECURITY"] is not None and values["SMTP_PORT"] is None:
        raise SettingsInvalid("application_settings_smtp_inconsistent")
