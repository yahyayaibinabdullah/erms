#!/usr/bin/env python3
"""Validate contextual message definitions against literal application references."""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_DIR))

from frontend.webui.i18n_catalogue import load_english_manifest  # noqa: E402


def referenced_keys() -> set[str]:
    # The renderer itself uses this key for unknown keys and parameter failures.
    keys: set[str] = {"shared.errors.unexpected"}
    roots = (PROJECT_DIR / "frontend" / "webui", PROJECT_DIR / "backend" / "services" / "api")
    for root in roots:
        for path in root.rglob("*.py"):
            if any(part in {".venv", "__pycache__", "tests"} for part in path.parts):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, (ast.Assign, ast.AnnAssign))
                    and any(
                        isinstance(target, ast.Name)
                        and target.id in {
                            "RESOURCE_PICKER_MESSAGE_KEYS", "RELATIONSHIP_MESSAGE_KEYS", "MESSAGING_MESSAGE_KEYS", "TRANSFER_MESSAGE_KEYS", "ADVANCED_SEARCH_FIELDS",
                            "ADVANCED_SEARCH_CONTROLLED_VALUES",
                            "ENTITY_METADATA_LABEL_KEYS",
                            "PERMISSION_MESSAGE_KEYS", "ACL_SOURCE_MESSAGE_KEYS", "EVENT_MESSAGE_KEYS",
                        }
                        for target in (
                            node.targets if isinstance(node, ast.Assign) else [node.target]
                        )
                    )
                ):
                    value = node.value
                    keys.update(
                        child.value for child in ast.walk(value)
                        if isinstance(child, ast.Constant)
                        and isinstance(child.value, str)
                        and child.value.startswith(("resource_picker.", "relationships.", "messaging.", "classification_transfer.", "advanced_search.", "entity_metadata.", "authorization.permission.", "authorization.acl_source.", "audit.event.", "security_operations.event."))
                    )
                if (
                    isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id in {"messages", "status_messages", "CAPTURE_ERROR_KEYS"} for target in node.targets)
                    and isinstance(node.value, ast.Dict)
                ):
                    keys.update(
                        value.value for value in node.value.values
                        if isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                        and ".error." in value.value
                    )
                if not isinstance(node, ast.Call):
                    continue
                name = node.func.id if isinstance(node.func, ast.Name) else None
                if name == "_stale_version":
                    keys.add("common.error.stale_version")
                index = (
                    2 if name == "_error"
                    else 0 if name in {
                        "render_english", "render_message", "render_message_plain",
                        "LocalizedTimezoneError",
                    }
                    else None
                )
                if index is not None and len(node.args) > index and isinstance(node.args[index], ast.Constant) and isinstance(node.args[index].value, str):
                    keys.add(node.args[index].value)
                elif index is not None and len(node.args) > index:
                    # Conditional key selection is valid when the alternatives
                    # are still explicit contextual catalogue keys.
                    keys.update(
                        child.value for child in ast.walk(node.args[index])
                        if isinstance(child, ast.Constant)
                        and isinstance(child.value, str)
                        and "." in child.value
                    )
    return keys


def validate_repository_catalogue() -> None:
    manifest_path = PROJECT_DIR / "frontend" / "webui" / "i18n" / "messages.en.json"
    manifest_rows = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_keys = [row["message_key"] for row in manifest_rows]
    if manifest_keys != sorted(manifest_keys):
        raise ValueError(
            "messages.en.json must be sorted lexicographically by contextual message_key"
        )
    defined = set(load_english_manifest())
    referenced = referenced_keys()
    unknown = sorted(referenced - defined)
    # Privileges are a database-backed catalogue whose contextual keys are
    # selected dynamically from immutable privilege codes at runtime. Their
    # exact database-to-manifest coverage is maintained by
    # sync_privilege_translation_keys.py, so they are intentionally not
    # discoverable as literal render_message calls.
    data_driven = {key for key in defined if key.startswith("privilege.")}
    stale = sorted(defined - referenced - data_driven)
    if unknown or stale:
        raise ValueError(f"catalogue mismatch; unknown={unknown}, stale={stale}")
    privilege_fields: dict[str, set[str]] = {}
    for key in data_driven:
        if key.startswith("privilege.category."):
            continue
        code, field = key.removeprefix("privilege.").rsplit(".", 1)
        privilege_fields.setdefault(code, set()).add(field)
    incomplete = sorted(
        code for code, fields in privilege_fields.items()
        if fields != {"name", "description"}
    )
    if incomplete:
        raise ValueError(f"privilege catalogue entries require name and description pairs: {incomplete}")
    for artifact_path in sorted(manifest_path.parent.glob("messages.*.generated.json")):
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact_keys = [item["message_key"] for item in artifact.get("items", [])]
        if artifact_keys != sorted(artifact_keys):
            raise ValueError(
                f"{artifact_path.name} must be sorted lexicographically by message_key"
            )
        if artifact_keys != manifest_keys:
            raise ValueError(
                f"{artifact_path.name} key coverage must exactly match messages.en.json"
            )


if __name__ == "__main__":
    validate_repository_catalogue()
    print("Internationalization catalogue references are complete and current.")
