#!/usr/bin/env python3
"""Assemble and validate review-only Arabic UI drafts with provenance."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "frontend/webui/i18n/messages.en.json"
SPEC = ROOT / "specs/internationalization-and-user-preferences.md"
OUTPUT = ROOT / "frontend/webui/i18n/messages.ar.generated.json"
PLACEHOLDER = re.compile(r"\{[a-z][a-z0-9_]*\}")
LATIN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.:/-]*")
ALLOWED_LATIN = {
    "ACL", "API", "CASE-2026", "SMTP", "HTTP", "HTTPS", "IANA", "ID", "IP",
    "ISO", "JSON", "MIME", "PDF", "POST", "SQL", "UTC", "health", "wti_",
    "application/octet-stream",
    "CSV", "MS", "Word", "DOCX", "docx", "Changa",  # Format/product/font names retain their spelling.
}


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def terminology_bytes(specification: str) -> bytes:
    section = specification.split(
        "### 21.1 Approved Arabic terminology reference", 1
    )[1]
    table = section.split("These mappings establish", 1)[0]
    return "\n".join(line for line in table.splitlines() if line.startswith("| ")).encode()


def placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER.findall(text))


def unexplained_latin(text: str) -> list[str]:
    without_placeholders = PLACEHOLDER.sub("", text)
    unexplained = []
    for token in LATIN_TOKEN.findall(without_placeholders):
        normalized = token.rstrip(".")
        if normalized in ALLOWED_LATIN:
            continue
        if normalized.startswith(("/", "api/", "http://", "https://")):
            continue
        if "." in normalized and normalized.lower() == normalized:
            continue
        unexplained.append(token)
    return unexplained


def load_candidates(paths: list[Path]) -> list[dict]:
    candidates: list[dict] = []
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError(f"{path}: expected a JSON array")
        candidates.extend(value)
    return candidates


def validate(definitions: list[dict], candidates: list[dict]) -> None:
    expected_keys = [item["message_key"] for item in definitions]
    actual_keys = [item.get("message_key") for item in candidates]
    if actual_keys != expected_keys:
        raise ValueError("candidate keys or ordering do not exactly match the English catalogue")
    if len(set(actual_keys)) != len(actual_keys):
        raise ValueError("candidate message keys are not unique")

    failures = []
    for definition, candidate in zip(definitions, candidates, strict=True):
        text = candidate.get("translated_text")
        if not isinstance(text, str) or not text.strip():
            failures.append(f"{definition['message_key']}: blank translation")
            continue
        if text == definition["default_text"] and unexplained_latin(text):
            failures.append(f"{definition['message_key']}: unchanged English source copy")
        if placeholders(text) != placeholders(definition["default_text"]):
            failures.append(f"{definition['message_key']}: placeholder mismatch")
        latin = unexplained_latin(text)
        if latin:
            failures.append(
                f"{definition['message_key']}: unexplained Latin text {', '.join(latin)}"
            )
        source = definition["default_text"]
        if re.search(r"\bAggregations?\b", source, re.IGNORECASE):
            if "ملف" not in text or "تجميع" in text:
                failures.append(
                    f"{definition['message_key']}: violates approved Aggregation → ملف/ملفات terminology"
                )
        # In an explicitly described imperative, initial "Record" is a verb
        # (تسجيل), not the governed document noun (وثيقة). Remaining noun uses
        # still require the approved terminology; no message-key exceptions.
        record_source = source
        if definition.get('grammatical_role') in {'action', 'action label', 'imperative sentence', 'action guidance', 'dialog-title action'}:
            record_source = re.sub(r'^Record\b\s*', '', source, count=1)
        if re.search(r"\bRecords?\b", record_source, re.IGNORECASE):
            if "وث" not in text or "سجل" in text:
                failures.append(
                    f"{definition['message_key']}: violates approved Record → وثيقة/وثائق terminology"
                )
        required_terms = {
            "Audit trail": "مسار التتبع",
            "Selective preservation": "الإنتقاء",
            "Vital record": "الوثائق الهيوية",
        }
        for english_term, approved_arabic in required_terms.items():
            if re.search(rf"\b{re.escape(english_term)}s?\b", source, re.IGNORECASE):
                if approved_arabic not in text:
                    failures.append(
                        f"{definition['message_key']}: violates approved {english_term} → {approved_arabic} terminology"
                    )
        flags = candidate.get("quality_flags")
        if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags):
            failures.append(f"{definition['message_key']}: invalid quality_flags")
    if failures:
        raise ValueError("Arabic draft validation failed:\n" + "\n".join(failures))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("batches", nargs="+", type=Path)
    parser.add_argument("--generated-at")
    args = parser.parse_args()

    definitions = json.loads(SOURCE.read_text(encoding="utf-8"))
    candidates = load_candidates(args.batches)
    validate(definitions, candidates)
    existing_payload = (
        json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    )
    terminology = terminology_bytes(SPEC.read_text(encoding="utf-8"))
    generated_at = args.generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload = {
        "generator": "OpenAI Codex",
        "model": "GPT-5.6 Sol Light",
        "model_version": "5.6-sol-light",
        "prompt_version": "wathiq-arabic-bootstrap-v2-contextual",
        "language_tag": "ar",
        "language_metadata": {
            "english_name": "Arabic",
            "native_name": "العربية",
            "direction": "rtl",
            "formatting_config": {"locale": "ar"},
        },
        "specification_sha256": digest(SPEC),
        "catalogue_sha256": digest(SOURCE),
        "terminology_sha256": sha256(terminology).hexdigest(),
        "batch_id": f"wathiq-ar-{generated_at.replace(':', '').replace('+00:00', 'Z')}",
        "generated_at": generated_at,
        # Guarded corrections are stable provenance, not generated message
        # content. Preserve them whenever the ordered message list is rebuilt.
        "superseded_translations": existing_payload.get(
            "superseded_translations", {}
        ),
        "items": candidates,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    flagged = sum(bool(item["quality_flags"]) for item in candidates)
    print(f"Validated and assembled {len(candidates)} Arabic review drafts; {flagged} flagged.")


if __name__ == "__main__":
    main()
