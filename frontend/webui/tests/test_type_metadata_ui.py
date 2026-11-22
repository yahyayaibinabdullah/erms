"""Typed metadata wire contracts and the editable Advanced Search tree."""

import pytest

from frontend.webui.advanced_search_model import (
    advanced_search_node_from_expression,
    compile_advanced_search_node,
)
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
