"""Negative controls for the source/phase traceability completion gate.

These tests are database-free. They test omissions and false completion claims,
not runtime settings or disposition behavior owned by later phases.
"""

from copy import deepcopy
import json

import pytest

from tools.check_disposition_baseline import LEDGER, ROOT, check, sections


@pytest.fixture
def ledger():
    return json.loads((ROOT / LEDGER).read_text())


def test_current_baseline_has_complete_source_and_setting_coverage(ledger):
    assert check(ledger) == []


@pytest.mark.parametrize("identity", [
    "ACFG-05", "DEST-40", "DEST-41", "ADMIN-S2", "DISP-S14.2",
    "REF-performance-6", "REF-i18n-7.8", "REF-relationships-7",
])
def test_missing_id_or_unidentified_prose_cannot_pass(ledger, identity):
    ledger["requirements"] = [row for row in ledger["requirements"] if row["id"] != identity]
    assert any("unowned source requirements" in error for error in check(ledger))


def test_parent_introductory_prose_is_not_lost_between_leaf_sections():
    source = "## 2. Parent\nRequired parent prose.\n### 2.1 Child\nRequired child prose.\n"
    result = sections(source)
    assert set(result) == {"2", "2.1"}
    assert result["2"]["end_line"] == 2
    assert result["2.1"]["start_line"] == 3


def test_source_drift_requires_deliberate_reconciliation(ledger):
    ledger["sources"]["specs/disposition.md"]["sha256"] = "outdated"
    assert any("source snapshot changed" in error for error in check(ledger))


def test_owner_and_acceptance_plan_are_required(ledger):
    ledger["requirements"][0]["phases"] = []
    ledger["requirements"][0]["planned_checks"] = []
    errors = check(ledger)
    assert any("phase owner" in error for error in errors)
    assert any("verification plan" in error for error in errors)


def test_approved_plan_principal_owners_cannot_be_dropped(ledger):
    entry = next(row for row in ledger["requirements"] if row["id"] == "ACFG-14")
    entry["phases"] = [2]
    assert any("approved principal phase omitted" in error for error in check(ledger))


@pytest.mark.parametrize("identity,rejected", [
    ("general_cache_seconds", 60),
    ("all_database_settings_editable", False),
    ("preserve_existing_nondefaults", False),
    ("related_saves_atomic", False),
])
def test_approved_configuration_decisions_cannot_silently_change(ledger, identity, rejected):
    next(item for item in ledger["decisions"] if item["id"] == identity)["value"] = rejected
    assert any(f"approved decision differs: {identity}" in error for error in check(ledger))


def test_approved_decisions_need_named_future_tests(ledger):
    ledger["decisions"][0]["planned_checks"] = []
    assert any("approved decision has no tests/owner" in error for error in check(ledger))


def test_all_database_settings_remain_editable_in_the_plan(ledger):
    next(item for item in ledger["settings"] if item["ownership"] == "database")["editable"] = False
    assert any("database setting must remain editable" in error for error in check(ledger))


def test_setting_omissions_and_changed_defaults_cannot_pass(ledger):
    changed = deepcopy(ledger)
    changed["settings"].pop()
    assert any("inventory coverage differs" in error for error in check(changed))
    ledger["settings"][0]["contract_cells"][1] = "invented default"
    assert any("setting contract differs" in error for error in check(ledger))


def test_planned_checks_and_baseline_reuse_do_not_prove_product_completion(ledger):
    entry = next(row for row in ledger["requirements"] if row["id"] == "DISP-01")
    assert entry["baseline_refs"]
    entry["status"] = "complete"
    assert any("completion without implementation and passing results" in error for error in check(ledger))


def test_multiphase_requirement_needs_evidence_for_each_applicable_phase(ledger):
    entry = next(row for row in ledger["requirements"] if row["id"] == "ACFG-14")
    entry["status"] = "complete"
    entry["implementation"] = [{"path": "a real implementation would be recorded here"}]
    entry["verification"] = [{"phase": entry["phases"][0], "result": "passed"}]
    assert any("completion missing an applicable phase" in error for error in check(ledger))


def test_reuse_claim_requires_a_passing_run_and_real_test_selector(ledger):
    item = next(row for row in ledger["baseline"] if row["status"] == "verified_reuse")
    ledger["verification_runs"][item["run"]]["result"] = "failed"
    assert any("baseline claim lacks passing test evidence" in error for error in check(ledger))
    item["tests"] = ["backend/services/api/tests/test_api.py::test_nonexistent"]
    assert any("missing baseline test" in error for error in check(ledger))


def test_database_baseline_claim_cannot_hide_cleanup_failure(ledger):
    item = next(row for row in ledger["baseline"] if row["status"] == "verified_reuse")
    ledger["verification_runs"][item["run"]]["cleanup"] = "failed"
    assert any("database lifecycle lacks evidence" in error for error in check(ledger))
