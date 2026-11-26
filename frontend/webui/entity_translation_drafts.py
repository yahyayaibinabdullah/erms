"""Dialog-scoped Edit drafts; existing locale PATCH and version contracts."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from .api_client import ApiError

TranslationUpdate = tuple[str, dict[str, str | None], str]


@dataclass
class EntityTranslationDrafts:
    fields: tuple[str, ...]
    values: dict[str, dict[str, str]] = field(default_factory=dict)
    baselines: dict[str, dict[str, str]] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    writing: bool = False
    applied_any: bool = False

    def normalized(self, values: dict) -> dict[str, str]:
        return {name: (values.get(name) or "").strip() for name in self.fields}

    def dirty_languages(self) -> list[str]:
        return sorted(tag for tag, values in self.values.items()
                      if values != self.baselines[tag])

    def loaded(self, tag: str, current: dict, row: dict) -> None:
        # A newly fetched locale must not silently rebase outstanding edits onto
        # somebody else's version. Keep the drafts and let the normal 409 UI act.
        if current["version"] != row["version"]:
            if self.dirty_languages():
                raise ApiError(409, {"code": "stale_version"})
            # Clean snapshots from the previous version must be fetched again.
            # Otherwise a later edit could overwrite a concurrent locale change
            # using the newer version learned from a different language.
            self.values.clear()
            self.baselines.clear()
        row["version"] = current["version"]
        if tag not in self.values or self.values[tag] == self.baselines[tag]:
            self.baselines[tag] = self.normalized(current["fields"])
            self.values[tag] = deepcopy(self.baselines[tag])

    def updates(self, shared_reason: str | None = None) -> list[TranslationUpdate]:
        return [(tag, {name: value or None for name, value in self.values[tag].items()},
                 shared_reason if shared_reason is not None else self.reasons.get(tag, ""))
                for tag in self.dirty_languages()]

    def accepted(self, tag: str, values: dict, result: dict, row: dict) -> None:
        row["version"] = result["version"]
        self.baselines[tag] = self.normalized(values)
        self.values[tag] = deepcopy(self.baselines[tag])
        translations = deepcopy(row.get("translations") or {})
        persisted = {name: value for name, value in self.baselines[tag].items() if value}
        if persisted:
            translations[tag] = persisted
        else:
            translations.pop(tag, None)
        row["translations"] = translations or None
        self.applied_any = True

    async def save(self, api, resource: str, row: dict, updates: list[TranslationUpdate]) -> None:
        for tag, values, reason in updates:
            result = await api.update_entity_translation(
                resource, row["id"], tag, values, row["version"], reason,
            )
            self.accepted(tag, values, result, row)
