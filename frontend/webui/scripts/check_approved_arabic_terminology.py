#!/usr/bin/env python3
"""Verify generated Arabic UI drafts against every approved glossary entry."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ENGLISH = ROOT / "frontend/webui/i18n/messages.en.json"
ARABIC = ROOT / "frontend/webui/i18n/messages.ar.generated.json"


@dataclass(frozen=True)
class Rule:
    term: str
    source: str
    required: str
    forbidden: str | None = None


# Patterns allow ordinary Arabic agreement/definiteness while preserving the
# approved Wathiq domain concept. Context-limited glossary entries are matched
# by their complete English phrase, not by an ambiguous individual word.
RULES = (
    Rule("Parent aggregation", r"\bparent aggregations?\b", r"ملف[^\s]*\s+(?:ال)?حاوي"),
    Rule("Containing aggregation", r"\bcontaining aggregations?\b", r"ملف[^\s]*\s+(?:ال)?حاوي"),
    Rule("Digital component", r"\bdigital components?\b", r"(?:ال)?مكو[ّ]?ن(?:ات)?\s+(?:ال)?رقمي"),
    Rule("Sharjah Archives", r"\bSharjah Archives\b", r"دار الوثائق في إمارة الشارقة"),
    Rule("Audit Trail", r"\baudit trail\b", r"مسار التتبع"),
    Rule("Current period", r"\bcurrent period\b", r"الفترة الجارية"),
    Rule("Intermediate period", r"\bintermediate period\b", r"الفترة الوسيطة"),
    Rule("Legal Hold", r"\blegal holds?\b", r"تعليق(?:ات|\s+حالات)?\s+قنوني|تعليق قنوني"),
    Rule("Records Unit", r"\bRecords Unit\b", r"وحدة الوثائق"),
    Rule("Retention Rule", r"\bretention rules?\b", r"(?:قاعدة|قواعد)\s+(?:ال)?حفظ"),
    Rule("Security Level", r"\bsecurity levels?\b", r"درج(?:ة|ات)\s+(?:ال)?سرية", r"مستو(?:ى|يات)\s+(?:ال)?سرية"),
    Rule("Selective Preservation", r"\bselective preservation\b", r"الإنتقاء"),
    Rule("Permanent Preservation", r"\bpermanent preservation\b", r"حفظ الدائم"),
    Rule("Vital record", r"\bvital records?\b", r"الوثائق الحيوية"),
    Rule("Checksum", r"\bchecksums?\b", r"مجموع التحقق"),
    Rule("System Administrator", r"\bSystem Administrators?\b", r"مسؤول(?:و|ي|ا)?\s+النظام"),
    Rule("Dashboard", r"\bdashboard\b", r"لوحة المعلومات"),
    Rule("Scheme", r"\b(?:classification )?schemes?\b", r"(?:نظام|نظم)\s+(?:ال)?تصنيف"),
    Rule("Classification", r"\bclassifications?\b", r"تصنيف"),
    Rule("Destruction", r"\bdestruction\b", r"إتلاف"),
    Rule("Mixed (record medium)", r"^Mixed$", r"^هجين$"),
    Rule("Physical (record medium)", r"^Physical$", r"^مادي$"),
    Rule("Close (aggregation lifecycle action)", r"^Close aggregation$|^Close$", r"إغلاق"),
    Rule("Inherit", r"^Inherit$", r"يستمد"),
    Rule("Delete", r"^Delete$", r"حذف"),
    Rule("Filter", r"^Filter$", r"التصفية"),
    Rule("Title", r"^Title(?: \*)?$", r"العنوان"),
    Rule("Aggregation", r"\baggregations?\b", r"ملف", r"تجميع"),
    Rule("Record", r"\brecords?\b", r"وثيق|وثائق", r"سجل"),
)


def main() -> None:
    definitions = json.loads(ENGLISH.read_text(encoding="utf-8"))
    artifact = json.loads(ARABIC.read_text(encoding="utf-8"))
    translations = {item["message_key"]: item["translated_text"] for item in artifact["items"]}
    failures: list[str] = []
    matched = {rule.term: 0 for rule in RULES}
    for definition in definitions:
        source = definition["default_text"]
        # Diacritics enrich Arabic wording without changing its terminology.
        # Normalize only for comparison; preserve the canonical translation.
        target = re.sub(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]", "",
                        translations[definition["message_key"]])
        for rule in RULES:
            if not re.search(rule.source, source, re.IGNORECASE):
                continue
            matched[rule.term] += 1
            if not re.search(rule.required, target) or (
                rule.forbidden and re.search(rule.forbidden, target)
            ):
                failures.append(
                    f"{rule.term}: {definition['message_key']}\n"
                    f"  English: {source}\n  Arabic: {target}"
                )
    if failures:
        raise SystemExit("Approved Arabic terminology violations:\n" + "\n".join(failures))
    print(
        f"Approved Arabic terminology verified across {sum(matched.values())} contextual uses "
        f"of all {len(RULES)} glossary mappings."
    )


if __name__ == "__main__":
    main()
