"""Checked-in contextual English message catalogue and safe renderer."""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any

from nicegui import context


MANIFEST_PATH = Path(__file__).with_name("i18n") / "messages.en.json"
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
PLACEHOLDER_PATTERN = re.compile(r"(?<!\{)\{([a-z][a-z0-9_]*)\}(?!\})")
TEXT_TOKEN_PATTERN = re.compile(r"\{\{|\}\}|\{([a-z][a-z0-9_]*)\}")
ALLOWED_TYPES = {"text", "integer", "decimal", "date", "datetime", "duration", "identifier", "url"}
ISOLATE_START = "\u2068"
ISOLATE_END = "\u2069"
# Keep translation-inspector metadata invisible while the browser hydrates.
# Each UTF-8 key byte is represented by two invisible variation selectors.
INSPECTOR_START = "\u2063"
INSPECTOR_SEPARATOR = "\u2064"
VARIATION_SELECTOR_BASE = 0xFE00
INSPECTOR_MARKER_PATTERN = re.compile(
    r"\u2063[\uFE00-\uFE0F]+\u2064[\uFE00-\uFE01]\u2064[\uFE00-\uFE0F]+\u2064"
)


def strip_diagnostic_metadata(text: str) -> str:
    """Remove framed inspector metadata from copied text, preserving visible text."""
    return INSPECTOR_MARKER_PATTERN.sub("", text)


_active_messages: ContextVar[dict[str, str]] = ContextVar(
    "wathiq_active_messages", default={},
)
_client_messages: dict[str, dict[str, str]] = {}
_active_fallback_keys: ContextVar[frozenset[str]] = ContextVar(
    "wathiq_active_fallback_keys", default=frozenset(),
)
_client_fallback_keys: dict[str, frozenset[str]] = {}
_diagnostic_clients: set[str] = set()
_render_metrics: Counter[str] = Counter()
logger = logging.getLogger(__name__)


def renderer_metrics() -> dict[str, int]:
    return dict(_render_metrics)


def _bounded_warning(metric: str, message_key: str) -> None:
    _render_metrics[metric] += 1
    count = _render_metrics[metric]
    if count == 1 or count & (count - 1) == 0:
        logger.warning(
            "localization_render_fallback",
            extra={"reason": metric, "message_key": message_key, "occurrences": count},
        )


@lru_cache(maxsize=1)
def load_english_manifest(path: Path = MANIFEST_PATH) -> dict[str, dict[str, Any]]:
    """Parse and validate the immutable process-local English catalogue once."""
    entries = json.loads(path.read_text(encoding="utf-8"))
    catalogue: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = entry.get("message_key", "")
        if not KEY_PATTERN.fullmatch(key) or key in catalogue:
            raise ValueError(f"invalid or duplicate contextual message key: {key}")
        required = {"context_group", "default_text", "semantic_meaning", "common_locations", "translator_guidance", "grammatical_role", "parameter_schema", "rendered_example"}
        missing = sorted(required - entry.keys())
        if missing or any(not entry[field] for field in required - {"parameter_schema"}):
            raise ValueError(f"{key} lacks required translator metadata: {missing}")
        schema = entry["parameter_schema"]
        if not isinstance(schema, dict) or any(value not in ALLOWED_TYPES for value in schema.values()):
            raise ValueError(f"{key} has an invalid parameter schema")
        placeholders = set(PLACEHOLDER_PATTERN.findall(entry["default_text"]))
        if placeholders != set(schema):
            raise ValueError(f"{key} placeholder schema does not match its English text")
        catalogue[key] = entry
    return catalogue


def render_english(catalogue_key: str, **parameters: object) -> str:
    definition = load_english_manifest()[catalogue_key]
    schema = definition["parameter_schema"]
    if set(parameters) != set(schema):
        raise ValueError("message parameters must exactly match the declared schema")
    return _interpolate_text(definition["default_text"], parameters)


def _interpolate_text(template: str, parameters: dict[str, object]) -> str:
    """Return literal text for NiceGUI text properties, never HTML markup.

    NiceGUI/Vue escape text at the DOM boundary. Encoding it here would display
    entities verbatim (or encode nested messages twice). HTML/template callers
    must explicitly html.escape the complete result. Interpolate in one pass so
    a name containing braces cannot become another placeholder or message syntax.
    """
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token in {"{{", "}}"}:
            return token[0]
        return ISOLATE_START + str(parameters[match.group(1)]) + ISOLATE_END

    return TEXT_TOKEN_PATTERN.sub(replace, template)


def set_active_messages(
    messages: dict[str, str], fallback_keys: list[str] | set[str] | frozenset[str] = frozenset(),
) -> None:
    copied = dict(messages)
    copied_fallbacks = frozenset(fallback_keys)
    _active_messages.set(copied)
    _active_fallback_keys.set(copied_fallbacks)
    try:
        _client_messages[context.client.id] = copied
        _client_fallback_keys[context.client.id] = copied_fallbacks
    except RuntimeError:
        pass


def clear_active_messages(client_id: str) -> None:
    _client_messages.pop(client_id, None)
    _client_fallback_keys.pop(client_id, None)
    _diagnostic_clients.discard(client_id)


def enable_diagnostic_metadata(client_id: str) -> None:
    _diagnostic_clients.add(client_id)


def disable_diagnostic_metadata(client_id: str) -> None:
    _diagnostic_clients.discard(client_id)


def _messages_for_context() -> dict[str, str]:
    try:
        return _client_messages.get(context.client.id, _active_messages.get())
    except RuntimeError:
        return _active_messages.get()


def _fallback_keys_for_context() -> frozenset[str]:
    try:
        return _client_fallback_keys.get(context.client.id, _active_fallback_keys.get())
    except RuntimeError:
        return _active_fallback_keys.get()


@lru_cache(maxsize=None)
def _encoded_diagnostic_key(message_key: str) -> str:
    """Encode immutable inspector key metadata once rather than per render."""
    return "".join(
        chr(VARIATION_SELECTOR_BASE + int(nibble, 16))
        for byte in message_key.encode("utf-8")
        for nibble in f"{byte:02x}"
    )


@lru_cache(maxsize=1024)
def _encoded_diagnostic_length(length: int) -> str:
    """Encode a rendered code-point length for collision-safe marker framing."""
    return "".join(
        chr(VARIATION_SELECTOR_BASE + int(nibble, 16))
        for nibble in f"{length:x}"
    )


def _diagnostic_marker(message_key: str, rendered: str) -> str:
    try:
        client_id = context.client.id
    except RuntimeError:
        return rendered
    if client_id not in _diagnostic_clients:
        return rendered
    encoded_key = _encoded_diagnostic_key(message_key)
    fallback = chr(
        VARIATION_SELECTOR_BASE
        + (1 if message_key in _fallback_keys_for_context() else 0)
    )
    return (
        f"{INSPECTOR_START}{encoded_key}{INSPECTOR_SEPARATOR}"
        f"{fallback}{INSPECTOR_SEPARATOR}{_encoded_diagnostic_length(len(rendered))}"
        f"{INSPECTOR_SEPARATOR}{rendered}"
    )


def _render_message_text(catalogue_key: str, parameters: dict[str, object]) -> tuple[str, str]:
    message_key = catalogue_key
    definition = load_english_manifest().get(message_key)
    if definition is None:
        _bounded_warning("missing_key_count", message_key)
        definition = load_english_manifest()["shared.errors.unexpected"]
        message_key = "shared.errors.unexpected"
        parameters = {}
    schema = definition["parameter_schema"]
    if set(parameters) != set(schema):
        _bounded_warning("invalid_parameter_count", message_key)
        definition = load_english_manifest()["shared.errors.unexpected"]
        message_key = "shared.errors.unexpected"
        parameters = {}
    rendered = _messages_for_context().get(message_key, definition["default_text"])
    return message_key, _interpolate_text(rendered, parameters)


def render_message_plain(catalogue_key: str, **parameters: object) -> str:
    """Literal UI text without inspector metadata; escape explicitly for HTML."""
    return _render_message_text(catalogue_key, parameters)[1]


def render_message(catalogue_key: str, **parameters: object) -> str:
    """Literal UI text with optional inspector metadata; not an HTML fragment."""
    effective_key, rendered = _render_message_text(catalogue_key, parameters)
    return _diagnostic_marker(effective_key, rendered)
