"""Explicit, code-owned notification contracts. No import-time registration."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Callable, Literal
from types import MappingProxyType
import re
from pydantic import BaseModel, ConfigDict, Field
from .content import invalid


class Placeholder(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["text", "integer", "decimal", "date", "datetime", "boolean"]
    max_length: int = Field(default=1000, ge=1, le=8000)


@dataclass(frozen=True)
class SystemNotificationDefinition:
    producer_code: str
    feature_code: str
    event_type: str
    contract_version: int
    required_for_business_commit: bool
    placeholders: dict[str, Placeholder] = field(default_factory=dict)
    allow_static_audience: bool = True
    audience_resolvers: dict[str, Callable] = field(default_factory=dict)
    resource_link_kinds: tuple[str, ...] = ()
    resource_builder: Callable | None = None
    resource_configuration: type[BaseModel] | None = None
    sample_context: dict = field(default_factory=dict)

    def contract(self):
        return {
            "placeholders": {
                key: value.model_dump()
                for key, value in sorted(self.placeholders.items())
            },
            "audience_modes": (["static"] if self.allow_static_audience else [])
            + sorted(self.audience_resolvers),
            "resource_link_kinds": sorted(self.resource_link_kinds),
            "resource_configuration": (
                self.resource_configuration.model_json_schema()
                if self.resource_configuration
                else None
            ),
        }


class NotificationRegistry:
    def __init__(self, definitions=()):
        entries = {}
        for item in definitions:
            if item.producer_code in entries:
                raise RuntimeError(
                    "Duplicate system notification producer: " + item.producer_code
                )
            if not all(
                re.fullmatch(r"[a-z][a-z0-9_.-]{0,119}", value)
                for value in (item.producer_code, item.feature_code, item.event_type)
            ):
                raise RuntimeError("Invalid notification contract identifier")
            if item.event_type == "test" or item.contract_version < 1:
                raise RuntimeError("Invalid notification contract version/event")
            if any(
                not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key)
                for key in item.placeholders
            ):
                raise RuntimeError("Invalid notification placeholder")
            if (
                "static" in item.audience_resolvers
                or not item.contract()["audience_modes"]
            ):
                raise RuntimeError("Invalid notification audience contract")
            if any(
                kind not in {"record", "aggregation"}
                for kind in item.resource_link_kinds
            ):
                raise RuntimeError("Invalid notification resource kind")
            if bool(item.resource_link_kinds) != bool(
                item.resource_builder and item.resource_configuration
            ):
                raise RuntimeError(
                    "Resource contracts require a builder and configuration schema"
                )
            entries[item.producer_code] = item
        self.definitions = MappingProxyType(entries)

    def get(self, code):
        definition = self.definitions.get(code)
        if definition is None:
            invalid("notification_producer_unregistered", 409)
        return definition

    def reconcile(self, connection):
        """Read-only comparison: feature seeds/migrations own database contracts."""
        rows = {
            row["producer_code"]: row
            for row in connection.execute(
                "SELECT * FROM system_notification_producers"
            ).fetchall()
        }
        issues = []
        for code in sorted(set(rows) | set(self.definitions)):
            row, definition = rows.get(code), self.definitions.get(code)
            required = bool(
                (row and row["required_for_business_commit"])
                or (definition and definition.required_for_business_commit)
            )
            reason = None
            if row is None:
                reason = "missing_database_contract"
            elif definition is None:
                reason = "unknown_database_contract"
            elif (
                any(
                    row[key] != getattr(definition, key)
                    for key in (
                        "feature_code",
                        "event_type",
                        "contract_version",
                        "required_for_business_commit",
                    )
                )
                or row["contract_definition"] != definition.contract()
            ):
                reason = "incompatible_contract"
            if reason:
                issues.append(
                    {"producer_code": code, "code": reason, "required": required}
                )
        return {"ready": not any(item["required"] for item in issues), "issues": issues}


def application_definitions():
    # Explicitly assembled, separately approved feature contracts.
    from ..hold_notifications import definitions
    from ..disposition.notifications import definitions as disposition_definitions
    return (*definitions(), *disposition_definitions())


registry = NotificationRegistry()


def initialize_registry():
    global registry
    registry = NotificationRegistry(application_definitions())
    return registry


def validate_context(definition, context):
    if not isinstance(context, dict) or set(context) != set(definition.placeholders):
        invalid("notification_context_invalid")
    normalized = {}
    for key, rule in definition.placeholders.items():
        value = context[key]
        try:
            if rule.type == "text":
                valid = (
                    isinstance(value, str)
                    and bool(value.strip())
                    and len(value) <= rule.max_length
                )
            elif rule.type == "integer":
                valid = type(value) is int and abs(value) <= 9223372036854775807
            elif rule.type == "boolean":
                valid = type(value) is bool
            elif rule.type == "decimal":
                if (
                    type(value) not in (int, float, str, Decimal)
                    or len(str(value)) > 100
                ):
                    raise ValueError()
                value = Decimal(str(value))
                valid = value.is_finite() and abs(value) <= Decimal("1e18")
            elif rule.type == "date":
                value = date.fromisoformat(value) if isinstance(value, str) else value
                valid = type(value) is date
            else:
                value = (
                    datetime.fromisoformat(value) if isinstance(value, str) else value
                )
                valid = isinstance(value, datetime) and value.tzinfo is not None
            if not valid:
                raise ValueError()
        except (ValueError, TypeError, OverflowError, InvalidOperation):
            invalid("notification_context_invalid")
        normalized[key] = value
    return normalized
