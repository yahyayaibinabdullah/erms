"""Typed metadata wire contracts and the editable Advanced Search tree."""

import pytest

from frontend.webui.advanced_search_model import (
    advanced_search_node_from_expression,
    compile_advanced_search_node,
)
from frontend.webui.type_administration import MAX_INT32, _positive_integer
from frontend.webui.type_controls import MetadataForm, literal


@pytest.mark.parametrize("resource", ["aggregations", "records"])
def test_round_trip_mixed_conditions(resource):
    expression = {
        "and": [
            {"field": "title", "operator": "eq", "value": "Invoice"},
            {
                "or": [
                    {
                        "field": "type.2.field.4",
                        "operator": "between",
                        "value": ["0.000000000000000123", "1.99"],
                    },
                    {"field": "type_id", "operator": "in", "value": [2, 7]},
                ]
            },
            {"not": {"field": "type.7.field.8", "operator": "eq", "value": False}},
        ]
    }
    root = advanced_search_node_from_expression(expression)
    assert root["children"][1]["children"][0]["kind"] == "type_field"
    assert compile_advanced_search_node(root, resource) == expression


def test_paged_form_preserves_explicit_values_and_validates_visited_fields():
    form = MetadataForm(None, "record")
    form.selected = 4
    form.definitions = {
        "1": {
            "id": 1,
            "name": "Flag",
            "data_type": "boolean",
            "required": True,
            "max_length": None,
            "default": False,
        },
        "2": {
            "id": 2,
            "name": "Length",
            "data_type": "text",
            "required": True,
            "max_length": 3,
            "default": None,
        },
    }
    form.changes = {"2": "م😀ن"}
    assert form.payload() == {"type_id": 4, "field_values": {"2": "م😀ن"}}
    form.changes["2"] = "  "
    with pytest.raises(ValueError):
        form.payload()
    assert literal("integer", "0") == 0
    assert literal("decimal", "0.12345678901234567890") == "0.12345678901234567890"
    with pytest.raises(ValueError):
        literal("text", "😀" * 4, 3)


def test_saved_definition_preserves_secondary_typed_sort_and_stable_ties():
    from frontend.webui.advanced_search_model import workspace_sort

    state = dict(
        sort_field="title",
        sort_direction="desc",
        sort_tail=[
            {"field": "type.5.field.2", "direction": "asc"},
            {"field": "id", "direction": "desc"},
        ],
    )
    assert workspace_sort(state) == [
        {"field": "title", "direction": "desc"},
        *state["sort_tail"],
    ]
    state["sort_field"] = "type.5.field.2"
    assert workspace_sort(state) == [
        {"field": "type.5.field.2", "direction": "desc"},
        {"field": "id", "direction": "desc"},
    ]


@pytest.mark.parametrize(("typed", "limit"), [
    ("255", 255), (" ١٠٢٤ ", 1024), ("۱۲۸", 128), ("2147483647", 2147483647),
    ("", None), ("٠", None), ("-1", None), ("1.5", None), ("1e3", None),
    ("2147483648", None),
])
def test_maximum_characters_requires_a_positive_database_integer(typed, limit):
    assert _positive_integer(typed, MAX_INT32) == limit


@pytest.mark.parametrize(("typed", "position"), [
    ("1", 1), ("3", 3), ("٣", 3), ("4", None), ("0", None),
    ("", None), ("-2", None), ("2.5", None), ("1e0", None),
])
def test_display_order_respects_the_current_last_position(typed, position):
    assert _positive_integer(typed, 3) == position

@pytest.mark.parametrize(("dtype", "invalid"), [
    ("text", {"ar": "نص"}), ("integer", str(-(2**63)-1)), ("integer", "1.0"),
    ("integer", True), ("decimal", "NaN"), ("decimal", "Infinity"),
    ("boolean", 1), ("boolean", "false"), ("date", "2026-02-29"),
    ("datetime", "2026-11-23"), ("datetime", "2026-11-23T25:60"),
])
def test_invalid_metadata_literals_cannot_be_submitted(dtype, invalid):
    with pytest.raises(ValueError):
        literal(dtype, invalid)
