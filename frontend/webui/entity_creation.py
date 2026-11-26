"""Per-dialog creation and translation retries using the existing REST contracts."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


CREATION_TRANSLATION_REASON = "Initial translations supplied during creation"


@dataclass
class EntityCreation:
    fields: tuple[str, ...]
    translations: dict[str, dict[str, str]] = field(default_factory=dict)
    applied: dict[str, dict[str, str]] = field(default_factory=dict)
    row: dict[str, Any] | None = None

    def pending(self) -> dict[str, dict[str, str | None]]:
        """Include explicit removals when a partially saved draft is revised."""
        return {
            language: {name: self.translations.get(language, {}).get(name) for name in self.fields}
            for language in sorted(self.translations.keys() | self.applied.keys())
            if self.translations.get(language, {}) != self.applied.get(language, {})
        }

    async def save(self, api, resource: str, payload: dict) -> dict:
        if self.row is None:
            self.row = await api.create(resource, payload)
        for language, values in self.pending().items():
            saved = await api.update_entity_translation(
                resource, self.row["id"], language, values, self.row["version"], CREATION_TRANSLATION_REASON,
            )
            self.row["version"] = saved["version"]
            # Record only confirmed writes. A failed request retains its draft
            # and version; conflicts are never silently rebased over another edit.
            persisted = {name: value for name, value in values.items() if value is not None}
            if persisted:
                self.applied[language] = persisted
            else:
                self.applied.pop(language, None)
            self.row["translations"] = deepcopy(self.applied) or None
        return self.row
