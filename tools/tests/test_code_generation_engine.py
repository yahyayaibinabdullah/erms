"""Exact formatting/scoping simulations shared by allocation and preview."""

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext

import pytest

from backend.services.api.code_generation import (
    CodeGenerationError, GenerationContext, GeneratorConfig, add_serial,
    code_affixes, counter_key, is_blank_text, next_serial, parse_pattern, preview_sequence, render, serial_text,
)


def config(**changes):
    return GeneratorConfig.from_mapping({
        "name": "Record codes", "pattern": "{SERIAL}", "start": "10",
        "increment": "10", "max_code_length": 200, **changes,
    })


def context(**changes):
    return GenerationContext(
        **{"instant": datetime(2026, 11, 26, tzinfo=timezone.utc),
           "working_timezone": "Asia/Dubai", "parent_aggregation_id": 12,
           "parent_aggregation_number": "FIN-12", "classification_id": 31,
           "classification_code": "3110", "classification_scheme_code": "WTH",
           "org_unit_id": 7, "org_unit_code": "FIN", "role_code": "FIN-OFFICER",
           **changes}
    )


def sequence(settings, scenario="same_scope"):
    first = context()
    second = context(parent_aggregation_id=13, parent_aggregation_number="HR-13",
                     classification_id=32, classification_code="4110",
                     org_unit_id=8, org_unit_code="HR", role_code="HR-OFFICER")
    return preview_sequence(settings, first, second, scenario)


@pytest.mark.parametrize("pattern,expected", [
    ("REC-{YYYY}-{SERIAL}", "REC-2026-0007"),
    ("{PARENT_AGGREGATION_NUMBER}/{SERIAL}", "FIN-12/0007"),
    ("{CLASSIFICATION_SCHEME_CODE}/{CLASSIFICATION_CODE}/{YYYY}/{SERIAL}", "WTH/3110/2026/0007"),
    ("{ORG_UNIT_CODE}/{YYYY}/{MM}/{SERIAL}", "FIN/2026/11/0007"),
    ("{ORG_UNIT_CODE}-{ROLE_CODE}-{DATE}-{SERIAL}", "FIN-FIN-OFFICER-20261126-0007"),
    ("{YY}.{MM}.{DD}.{SERIAL}", "26.11.26.0007"),
    ("{{literal}}-{{{SERIAL}}}", "{literal}-{0007}"),
])
def test_specification_examples_and_escaped_braces(pattern, expected):
    assert render(config(pattern=pattern, padding_width=4), context(), "7") == expected


@pytest.mark.parametrize("pattern", [
    "", "plain", "{{SERIAL}}", "{SERIAL}/{SERIAL}", "{UNKNOWN}-{SERIAL}",
    "{serial}", "{SERIAL", "SERIAL}", "{SERIAL}}", "{SERIAL+1}",
    "{SERIAL}\x00", "{YYYY-{SERIAL}", None,
])
def test_invalid_patterns(pattern):
    with pytest.raises(CodeGenerationError) as error:
        parse_pattern(pattern)
    assert error.value.field == "pattern"


@pytest.mark.parametrize("changes,field", [
    ({"name": None}, "name"), ({"name": " \t\n\u00a0"}, "name"),
    ({"start": "-1"}, "start"), ({"start": "1.1"}, "start"),
    ({"start": True}, "start"), ({"start": 1.0}, "start"),
    ({"start": "١"}, "start"), ({"increment": "0"}, "increment"),
    ({"increment": Decimal("NaN")}, "increment"),
    ({"increment": Decimal("Infinity")}, "increment"),
    ({"padding_width": -1}, "padding_width"),
    ({"padding_width": 2.5}, "padding_width"),
    ({"padding_width": True}, "padding_width"),
    ({"max_code_length": None}, "max_code_length"),
    ({"max_code_length": 0}, "max_code_length"),
    ({"max_code_length": True}, "max_code_length"),
    ({"scope": "role"}, "scope"), ({"reset_frequency": "fiscal_year"}, "reset_frequency"),
])
def test_invalid_configuration(changes, field):
    with pytest.raises(CodeGenerationError) as error:
        config(**changes)
    assert error.value.field == field


def test_required_name_is_only_a_label():
    before = config()
    after = replace(before, name="رموز السجلات")
    assert counter_key(before, context()) == counter_key(after, context())
    assert sequence(before) == sequence(after)


@pytest.mark.parametrize("width,expected", [(None, "7"), (0, "7"), (4, "0007")])
def test_padding_is_optional_minimum_width(width, expected):
    settings = config(padding_width=width)
    assert render(settings, context(), 7) == expected
    assert render(settings, context(), 10000) == "10000"


def test_total_length_and_target_capacity_are_distinct_from_padding():
    with pytest.raises(CodeGenerationError):
        config(padding_width=1_000_000_000, max_code_length=10)
    with pytest.raises(CodeGenerationError):
        GeneratorConfig.from_mapping({"name": "Test", "pattern": "{SERIAL}",
                                     "max_code_length": 10}, field_max_length=9)
    settings = config(pattern="عقد-{SERIAL}", start="1", max_code_length=5)
    assert render(settings, context(), 7) == "عقد-7"
    with pytest.raises(CodeGenerationError) as error:
        render(settings, context(), 10)
    assert error.value.code == "code_generator_length_exceeded"
    assert error.value.parameters == {"length": 6, "maximum": 5}


def test_dynamic_placeholder_length_rechecked_without_truncation():
    settings = config(pattern="{ORG_UNIT_CODE}/{SERIAL}", start="1", max_code_length=5)
    assert render(settings, context(), 1) == "FIN/1"
    with pytest.raises(CodeGenerationError):
        render(settings, context(org_unit_code="FINANCE"), 1)


def test_exact_sequences_ignore_decimal_context_precision_and_browser_limit():
    assert [v.serial for v in sequence(config())] == ["10", "20", "30", "40", "50"]
    assert [v.serial for v in sequence(config(start="0", increment="1"))] == ["0", "1", "2", "3", "4"]
    start = "900719925474099312345678901234567890"
    with localcontext() as limited:
        limited.prec = 2
        values = sequence(config(start=start, increment="10"))
    assert [v.serial for v in values] == [str(int(start) + index * 10) for index in range(5)]
    # Supported PostgreSQL numeric strings may exceed Python's int conversion
    # threshold. Do not rely on a global interpreter-limit change.
    huge = "9" * 5000
    assert serial_text(add_serial(huge, "1")) == "1" + "0" * 5000


def test_changed_start_only_affects_unused_counters_and_adjustment_advances():
    settings = config(start="500", increment="10")
    assert next_serial(settings, None) == 500
    assert next_serial(settings, "100") == 110
    assert next_serial(settings, "100", "501") == 501
    assert next_serial(settings, "501") == 511
    with pytest.raises(CodeGenerationError):
        next_serial(settings, "501", "500")


@pytest.mark.parametrize("reset,pattern,year,month", [
    ("never", "{SERIAL}", [10, 20, 30, 40, 50], [10, 20, 30, 40, 50]),
    ("yearly", "{YYYY}/{SERIAL}", [10, 20, 30, 10, 20], [10, 20, 30, 40, 50]),
    ("monthly", "{YYYY}/{MM}/{SERIAL}", [10, 20, 30, 10, 20], [10, 20, 30, 10, 20]),
])
def test_year_and_month_reset_scenarios(reset, pattern, year, month):
    settings = config(pattern=pattern, reset_frequency=reset)
    year_values = sequence(settings, "year_transition")
    month_values = sequence(settings, "month_transition")
    assert [int(v.serial) for v in year_values] == year
    assert [int(v.serial) for v in month_values] == month
    assert [v.reset for v in year_values] == [False, False, False, reset != "never", False]
    assert year_values[2].date == date(2026, 12, 31)
    assert year_values[3].date == date(2027, 1, 1)


@pytest.mark.parametrize("scope,pattern", [
    ("parent_aggregation", "{PARENT_AGGREGATION_NUMBER}/{SERIAL}"),
    ("classification", "{CLASSIFICATION_CODE}/{SERIAL}"),
    ("org_unit", "{ORG_UNIT_CODE}/{SERIAL}"),
])
def test_independent_scopes_and_combined_periods(scope, pattern):
    scoped = config(scope=scope, pattern=pattern)
    assert [v.serial for v in sequence(scoped, "different_scopes")] == ["10", "20", "10", "30", "20"]
    settings = config(scope=scope, pattern="{YYYY}/{MM}/" + pattern, reset_frequency="monthly")
    values = sequence(settings, "combined")
    assert [v.serial for v in values] == ["10", "20", "10", "10", "10"]
    assert [v.reset for v in values] == [False, False, False, True, True]
    assert [v.serial for v in sequence(config(), "different_scopes")] == ["10", "20", "30", "40", "50"]


def test_context_and_counter_identity_follow_stable_ids_and_working_timezone():
    settings = config(scope="classification", pattern="{CLASSIFICATION_CODE}/{YYYY}/{MM}/{SERIAL}",
                      reset_frequency="monthly")
    original = context(instant=datetime(2026, 12, 31, 21, 1, tzinfo=timezone.utc))
    assert counter_key(settings, original).period_bucket == date(2027, 1, 1)
    renamed = replace(original, classification_code="NEW-CODE")
    assert counter_key(settings, original) == counter_key(settings, renamed)
    assert render(settings, original, 10) == "3110/2027/01/10"
    january_2026 = replace(original, instant=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert counter_key(settings, january_2026) != counter_key(settings, original)


@pytest.mark.parametrize("changes", [
    {"scope": "org_unit"}, {"reset_frequency": "yearly"},
    {"pattern": "{YYYY}/{SERIAL}", "reset_frequency": "monthly"},
    {"pattern": "{MM}/{SERIAL}", "reset_frequency": "monthly"},
])
def test_scope_and_reset_require_placeholders(changes):
    with pytest.raises(CodeGenerationError):
        config(**changes)


def test_unique_primary_number_scope_requires_distinguishing_context():
    for scope, pattern in [("parent_aggregation", "{SERIAL}"),
                           ("classification", "{CLASSIFICATION_CODE}/{SERIAL}")]:
        with pytest.raises(CodeGenerationError):
            GeneratorConfig.from_mapping({"name": "Codes", "scope": scope, "pattern": pattern,
                                         "max_code_length": 100}, globally_unique_number=True)
    settings = config(pattern="{DATE}/{SERIAL}", reset_frequency="monthly")
    assert not settings.warnings
    assert config(pattern="{YY}/{MM}/{SERIAL}", reset_frequency="monthly").warnings == ("two_digit_year_repeats",)


def test_required_context_and_naive_instant_are_rejected():
    with pytest.raises(CodeGenerationError):
        render(config(pattern="{ROLE_CODE}/{SERIAL}"), context(role_code=None), 10)
    with pytest.raises(CodeGenerationError):
        counter_key(config(scope="parent_aggregation"), context(parent_aggregation_id=None))
    with pytest.raises(CodeGenerationError):
        render(config(), context(instant=datetime(2026, 1, 1)), 10)


def test_leap_day_and_simulation_state_are_isolated():
    settings = config(pattern="{DATE}/{SERIAL}", reset_frequency="monthly")
    first, second = context(), context(org_unit_id=8, org_unit_code="HR")
    values = preview_sequence(settings, first, second, "month_transition", sample_date=date(2028, 2, 1))
    assert values[2].value == "20280229/30"
    assert values[3].value == "20280301/10"
    assert values == preview_sequence(settings, first, second, "month_transition", sample_date=date(2028, 2, 1))
    assert first.instant == datetime(2026, 11, 26, tzinfo=timezone.utc)
    assert settings.start == 10


def test_negative_zero_and_extreme_preview_date_remain_canonical():
    assert serial_text(Decimal("-0.000")) == "0"
    assert preview_sequence(config(), context(), context(), sample_date=date(9999, 12, 31))[0].serial == "10"
    with pytest.raises(CodeGenerationError):
        preview_sequence(config(pattern="{YYYY}/{SERIAL}", reset_frequency="yearly"),
                         context(), context(), "year_transition", sample_date=date(9999, 12, 31))
    with pytest.raises(CodeGenerationError):
        preview_sequence(config(), context(), context(), [])


@pytest.mark.parametrize("pattern", ["{SERIAL}", "10/{SERIAL}/10", "{{{SERIAL}}}", "{ORG_UNIT_CODE}-{DATE}-{SERIAL}/{ROLE_CODE}"])
def test_occupied_number_affixes_use_the_same_renderer(pattern):
    settings = config(pattern=pattern, padding_width=4)
    prefix, suffix = code_affixes(settings, context())
    assert prefix + "0007" + suffix == render(settings, context(), 7)


@pytest.mark.parametrize("value,blank", [(None,True),("",True),("\t\u00a0\u2003\u3000",True),("0",False),(0,False),(False,False),("\u001c",False)])
def test_blank_text_uses_existing_unicode_metadata_rules(value,blank):
    assert is_blank_text(value) is blank
