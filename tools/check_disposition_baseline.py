"""Check disposition traceability without importing services or opening a database.

The ledger records source coverage and planned acceptance, not acceptance results.
Update it deliberately when a specification changes; this checker never regenerates
requirements or changes their implementation/verification status.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
LEDGER = Path("docs/disposition-requirement-ledger.json")
CORE_SOURCES = {
    "ACFG": "specs/application-configuration.md",
    "ADMIN": "specs/administration-settings.md",
    "DISP": "specs/disposition.md",
    "DEST": "specs/destruction-process.md",
}
# Deliberately maintained scope of the contracts referenced by this baseline.
# This prevents a supporting contract from disappearing just because a ledger
# editor deletes its entries. It does not import unrelated subsystem features.
REFERENCED_SECTIONS = {
    "security": "3 4 5 6 8 9 10 12 13 14 16.4 18 19 21",
    "oversight": "3 5 7 10 11",
    "ownership": "4 5 6",
    "relationships": "5 7 8",
    "holds": "3 4 5 7 8 11 13 future-disposition",
    "retention": "5.3 5.4 6 7 16",
    "storage": "4 5 6 7 8 9 11 12 15",
    "resources": "4 5 6 8 9",
    "medium": "4 5 7 9 11 15 16 18",
    "notifications": "8 11.5 12 13 MSG-018 MSG-019 MSG-021",
    "i18n": "7.5 7.8 14 15 16 19 21.1",
    "performance": "3 4 5 6 7 8 9 10",
    "design": "6 7 19.1",
    "authentication": "2 4 5 6 8 9",
    "search": "4 5 6 12 13 14",
}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sections(value: str) -> dict[str, dict]:
    """Include each numbered heading's own body, including parent introductions.

    A parent's body ends at its first child heading. Consequently a prose clause
    cannot disappear between leaf sections and every numbered body has one owner.
    """
    lines = value.splitlines(keepends=True)
    headings = [
        (index, match.group(1))
        for index, line in enumerate(lines)
        if (match := re.match(r"^#{2,6} (.+?)\s*$", line))
    ]
    result = {}
    for position, (index, heading) in enumerate(headings):
        number = re.match(r"^(\d+(?:\.\d+)*)(?:\.|\s)", heading)
        if number is None:
            continue
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        result[number.group(1)] = {
            "heading": heading,
            "start_line": index + 1,
            "end_line": end,
            "sha256": digest("".join(lines[index:end])),
        }
    return result


def requirement_ids(value: str, prefix: str) -> set[str]:
    # Acceptance tables plus DEST-40/41, which are acceptance prose paragraphs.
    return set(re.findall(rf"^(?:\|\s*)?({prefix}-\d+)\b", value, re.MULTILINE))


def setting_inventory(value: str) -> dict[str, dict]:
    """Exact section 4/5 rows; section 5.6/5.7 deliberately have no invented keys."""
    result = {}
    section = None
    for line in value.splitlines():
        heading = re.match(r"^### ([45]\.\d+)\s", line)
        if heading:
            section = heading.group(1)
        elif line.startswith("## "):
            section = None
        if section and line.startswith("| "):
            cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
            if cells[0] in {"Setting", "Setting key", "---", "--- "}:
                continue
            if cells[0].startswith("---"):
                continue
            result[cells[0]] = {
                "section": section,
                "contract_cells": cells,
                "ownership": "deployment" if section.startswith("4.") else "database",
            }
    return result


def principal_phases(value: str) -> dict[str, set[int]]:
    result = {}
    for line in value.splitlines():
        if not line.startswith("| "):
            continue
        columns = line.split("|")
        identities = re.findall(r"(?:ACFG|DISP|DEST)-\d+", columns[1])
        if not identities:
            continue
        phases = set()
        for first, last in re.findall(r"(\d+)(?:[–-](\d+))?", columns[2]):
            phases.update(range(int(first), int(last) + 1) if last else [int(first)])
        for identity in identities:
            result[identity] = phases
    return result


def check(ledger: dict, root: Path = ROOT) -> list[str]:
    errors = []
    entries = ledger.get("requirements", [])
    by_id = {entry.get("id"): entry for entry in entries}
    if len(by_id) != len(entries):
        errors.append("duplicate requirement IDs")
    expected = set()
    expected.update(
        f"REF-{contract}-{section}"
        for contract, scopes in REFERENCED_SECTIONS.items()
        for section in scopes.split()
    )
    expected.add("REF-local-env-reconciliation")
    for prefix, path in CORE_SOURCES.items():
        source = (root / path).read_text()
        if ledger.get("sources", {}).get(path, {}).get("sha256") != digest(source):
            errors.append(f"source snapshot changed: {path}; reconcile the ledger deliberately")
        for number, locator in sections(source).items():
            identity = f"{prefix}-S{number}"
            expected.add(identity)
            entry = by_id.get(identity)
            if entry and entry.get("source") != {"path": path, **locator}:
                errors.append(f"source range changed: {identity}")
        for identity in requirement_ids(source, prefix):
            expected.add(identity)
    missing = expected - by_id.keys()
    if missing:
        errors.append(f"unowned source requirements: {', '.join(sorted(missing))}")
    unexpected = by_id.keys() - expected
    if unexpected:
        errors.append(f"unknown source requirements: {', '.join(sorted(unexpected))}")
    baseline_ids = {item["id"] for item in ledger.get("baseline", [])}
    approved_phases = principal_phases((root / "specs/disposition-implementation-plan.md").read_text())
    phase_plans = ledger.get("phase_plans", {})
    for phase in range(1, 25):
        plan = phase_plans.get(f"phase_{phase:02d}", {})
        if not plan.get("planned_locations") or not plan.get("acceptance_cases"):
            errors.append(f"missing integration/acceptance plan: phase {phase}")
    for entry in entries:
        identity = entry.get("id")
        phases = entry.get("phases", [])
        if not phases or any(type(phase) is not int or not 1 <= phase <= 24 for phase in phases):
            errors.append(f"missing/invalid phase owner: {identity}")
        if identity in approved_phases and not approved_phases[identity].issubset(set(phases)):
            errors.append(f"approved principal phase omitted: {identity}")
        if not entry.get("planned_locations") or not entry.get("planned_checks"):
            errors.append(f"missing implementation or verification plan: {identity}")
        for planned in entry.get("planned_checks", []):
            if not planned.get("name") or not planned.get("cases"):
                errors.append(f"unnamed or empty planned check: {identity}")
            for key in planned.get("phase_plans", []):
                if key not in phase_plans:
                    errors.append(f"unknown verification phase plan: {identity}: {key}")
        for key in entry.get("planned_locations", []):
            if key.startswith("phase_") and key not in phase_plans:
                errors.append(f"unknown integration phase plan: {identity}: {key}")
        for reference in entry.get("baseline_refs", []):
            if reference not in baseline_ids:
                errors.append(f"unknown baseline reference: {identity}: {reference}")
        if entry.get("status") == "complete":
            if not entry.get("implementation") or not entry.get("verification"):
                errors.append(f"completion without implementation and passing results: {identity}")
            elif any(result.get("result") != "passed" for result in entry["verification"]):
                errors.append(f"completion with unpassed verification: {identity}")
            elif not set(phases).issubset({result.get("phase") for result in entry["verification"]}):
                errors.append(f"completion missing an applicable phase's evidence: {identity}")
        elif entry.get("status") not in {"planned", "in_progress", "blocked"}:
            errors.append(f"unknown status: {identity}")
        if identity.startswith("REF-"):
            source = entry["source"]
            lines = (root / source["path"]).read_text().splitlines(keepends=True)
            actual = "".join(lines[source["start_line"] - 1:source["end_line"]])
            if digest(actual) != source["sha256"]:
                errors.append(f"referenced contract changed: {identity}")
    expected_settings = setting_inventory((root / CORE_SOURCES["ACFG"]).read_text())
    actual_settings = {item["setting"]: item for item in ledger.get("settings", [])}
    if actual_settings.keys() != expected_settings.keys():
        errors.append("section 4/5 setting inventory coverage differs")
    for key, contract in expected_settings.items():
        item = actual_settings.get(key, {})
        if any(item.get(field) != value for field, value in contract.items()):
            errors.append(f"setting contract differs: {key}")
        if contract["ownership"] == "database" and item.get("editable") is not True:
            errors.append(f"database setting must remain editable: {key}")
        if not item.get("phases") or not item.get("planned_checks"):
            errors.append(f"setting has no cutover/verification owner: {key}")
    decisions = {item["id"]: item for item in ledger.get("decisions", [])}
    required_decisions = {
        "general_cache_seconds": 30,
        "all_database_settings_editable": True,
        "preserve_existing_nondefaults": True,
        "related_saves_atomic": True,
    }
    for identity, value in required_decisions.items():
        decision = decisions.get(identity, {})
        if decision.get("value") != value or type(decision.get("value")) is not type(value):
            errors.append(f"approved decision differs: {identity}")
        if not decision.get("planned_checks") or not decision.get("phases"):
            errors.append(f"approved decision has no tests/owner: {identity}")
    for item in ledger.get("baseline", []):
        for location in item.get("locations", []):
            if location["anchor"] not in (root / location["path"]).read_text():
                errors.append(f"missing baseline symbol: {item['id']}: {location}")
        for selector in item.get("tests", []):
            path, _, test = selector.partition("::")
            if not (root / path).is_file():
                errors.append(f"missing baseline test file: {selector}")
            elif test and not re.search(rf"^def {re.escape(test)}\(", (root / path).read_text(), re.MULTILINE):
                errors.append(f"missing baseline test: {selector}")
        evidence = ledger.get("verification_runs", {}).get(item.get("run"), {})
        if item.get("status") == "verified_reuse" and (
            evidence.get("result") != "passed" or not item.get("tests")
        ):
            errors.append(f"baseline claim lacks passing test evidence: {item['id']}")
        if item.get("status") == "verified_reuse":
            for selector in item.get("tests", []):
                path = selector.partition("::")[0]
                if selector not in evidence.get("targets", []) and path not in evidence.get("targets", []):
                    errors.append(f"baseline test absent from recorded run: {selector}")
            if evidence.get("database") and (
                evidence.get("creation") != "succeeded" or not evidence.get("cleanup", "").startswith("succeeded")
            ):
                errors.append(f"baseline database lifecycle lacks evidence: {item['id']}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=ROOT / LEDGER)
    args = parser.parse_args()
    ledger = json.loads(args.ledger.read_text())
    errors = check(ledger)
    if errors:
        print("\n".join(errors))
        return 1
    print(
        f"Disposition baseline valid: {len(ledger['requirements'])} owned entries, "
        f"{len(ledger['settings'])} settings, four approved decisions. "
        "Planned acceptance is not a passing product result."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
