"""Existing advanced-query fields, grammar, validation and localized options."""
from __future__ import annotations
from typing import Any
from .i18n_catalogue import render_message

ADVANCED_SEARCH_FIELDS: dict[str, dict[str, tuple[str, str, bool]]] = {
    "records": {
        "record_number": ("advanced_search.field.record_number", "text", False),
        "disposition_status": ("disposition.ui.status", "integer", False),
        "title": ("advanced_search.field.title", "text", False),
        "description": ("advanced_search.field.description", "text", True),
        "aggregation_id": ("advanced_search.field.aggregation", "integer", True),
        "date_created": ("advanced_search.field.date_created", "datetime", False),
        "date_originated": ("advanced_search.field.date_originated", "datetime", False),
        "medium": ("advanced_search.field.medium", "text", False),
        "is_vital": ("advanced_search.field.vital_record", "boolean", False),
        "date_of_next_review": ("advanced_search.field.next_review", "datetime", True),
        "effective_assigned_location": ("advanced_search.field.assigned_location", "text", True),
        "effective_current_location": ("advanced_search.field.current_location", "text", True),
        "security_level_id": ("advanced_search.field.security_level", "integer", False),
        "owning_org_unit_id": ("advanced_search.field.owning_org_unit", "integer", False),
        "on_effective_hold": ("advanced_search.field.on_hold", "boolean", False),
        "component.file_name": ("advanced_search.field.file_name", "text", False),
        "component.mime_type": ("advanced_search.field.mime_type", "text", False),
        "component.size_in_bytes": ("advanced_search.field.size_in_bytes", "integer", False),
        "component.date_created": ("advanced_search.field.date_created", "datetime", False),
        "component.date_originated": ("advanced_search.field.date_originated", "datetime", False),
        "component.checksum_algorithm": ("advanced_search.field.checksum_algorithm", "text", False),
        "component.checksum_value": ("advanced_search.field.checksum_value", "text", False),
        "component.content_status": ("advanced_search.field.content_status", "text", False),
    },
    "aggregations": {
        "aggregation_number": ("advanced_search.field.aggregation_number", "text", False),
        "effective_retention.current_period_years": ("advanced_search.field.effective_current_period_years", "integer", False),
        "effective_retention.intermediate_period_years": ("advanced_search.field.effective_intermediate_period_years", "integer", False),
        "effective_retention.final_disposition": ("advanced_search.field.effective_disposition_action", "choice", False),
        "disposition_status": ("disposition.ui.status", "integer", False),
        "title": ("advanced_search.field.title", "text", False),
        "description": ("advanced_search.field.description", "text", True),
        "parent_aggregation_id": ("advanced_search.field.parent_aggregation", "integer", True),
        "classification_id": ("advanced_search.field.classification", "integer", True),
        "date_created": ("advanced_search.field.date_created", "datetime", False),
        "date_opened": ("advanced_search.field.date_opened", "datetime", False),
        "date_closed": ("advanced_search.field.date_closed", "datetime", True),
        "medium": ("advanced_search.field.medium", "text", False),
        "is_vital": ("advanced_search.field.vital_aggregation", "boolean", False),
        "date_of_next_review": ("advanced_search.field.next_review", "datetime", True),
        "effective_assigned_location": ("advanced_search.field.assigned_location", "text", True),
        "effective_current_location": ("advanced_search.field.current_location", "text", True),
        "security_level_id": ("advanced_search.field.security_level", "integer", False),
        "owning_org_unit_id": ("advanced_search.field.owning_org_unit", "integer", False),
        "on_effective_hold": ("advanced_search.field.on_hold", "boolean", False),
    },
}


ADVANCED_SEARCH_COMPONENT_FIELDS = frozenset(
    field for field in ADVANCED_SEARCH_FIELDS["records"] if field.startswith("component.")
)


ADVANCED_SEARCH_RETENTION_FIELDS = frozenset(
    field for field in ADVANCED_SEARCH_FIELDS["aggregations"] if field.startswith("effective_retention.")
)


ADVANCED_SEARCH_RELATIONSHIP_FIELDS = frozenset({
    "aggregation_id", "parent_aggregation_id", "classification_id",
    "security_level_id", "owning_org_unit_id",
})


ADVANCED_SEARCH_CONTROLLED_VALUES: dict[str, dict[Any, str]] = {
    "effective_retention.final_disposition": {
        "destruction": "disposition.ui.destruction",
        "transfer_to_external_archive": "disposition.ui.permanent_transfer",
        "selective_preservation": "disposition.ui.selective_transfer",
        "retain_as_local_archives": "disposition.ui.local_archives",
    },
    "disposition_status": {1: "disposition.ui.status_1",2: "disposition.ui.status_2",3: "disposition.ui.status_3",4: "disposition.ui.status_4",5: "disposition.ui.status_5",6: "disposition.ui.status_6",7: "disposition.ui.status_7",8: "disposition.ui.status_8",9: "disposition.ui.status_9",10: "disposition.ui.status_10",11: "disposition.ui.status_11",12: "disposition.ui.status_12",13: "disposition.ui.status_13"},
    "medium": {"digital": "advanced_search.value.digital", "physical": "advanced_search.value.physical", "mixed": "advanced_search.value.mixed"},
    "component.content_status": {
        "pending": "advanced_search.value.pending", "uploading": "advanced_search.value.uploading", "available": "advanced_search.value.available",
        "failed": "advanced_search.value.failed", "quarantined": "advanced_search.value.quarantined", "deleted": "advanced_search.value.deleted",
    },
}


def advanced_search_field_options(resource: str, *, can_manage_disposition: bool = False) -> dict[str, str]:
    """Return visibly grouped labels while retaining canonical field values."""
    return {
        field: (
            render_message("advanced_search.field.digital_component_qualified", field=render_message(details[0]))
            if field in ADVANCED_SEARCH_COMPONENT_FIELDS
            else render_message(
                "advanced_search.field.resource_qualified",
                resource=render_message(
                    "advanced_search.resource.record" if resource == "records"
                    else "advanced_search.resource.aggregation"
                ),
                field=render_message(details[0]),
            )
        )
        for field, details in ADVANCED_SEARCH_FIELDS[resource].items()
        if field != "disposition_status" or can_manage_disposition
    }


def advanced_search_empty_value(field: str, operator: str, kind: str) -> Any:
    if operator in {"between", "in", "not_in"}:
        return []
    if field in ADVANCED_SEARCH_RELATIONSHIP_FIELDS or kind in {"integer", "boolean", "choice"}:
        return None
    return ""


def advanced_search_operators(kind: str, nullable: bool) -> dict[str, str]:
    common = {"eq": render_message("advanced_search.operator.is"), "ne": render_message("advanced_search.operator.is_not")}
    if kind == "choice":
        common |= {"in": render_message("advanced_search.operator.is_one_of"), "not_in": render_message("advanced_search.operator.is_not_one_of")}
    if kind == "text":
        common |= {"contains_ci": render_message("advanced_search.operator.contains"), "starts_with_ci": render_message("advanced_search.operator.starts_with"), "ends_with_ci": render_message("advanced_search.operator.ends_with"), "in": render_message("advanced_search.operator.is_one_of"), "not_in": render_message("advanced_search.operator.is_not_one_of")}
    elif kind in {"integer", "datetime"}:
        common |= {"lt": render_message("advanced_search.operator.less_than"), "lte": render_message("advanced_search.operator.at_most"), "gt": render_message("advanced_search.operator.greater_than"), "gte": render_message("advanced_search.operator.at_least"), "between": render_message("advanced_search.operator.between"), "in": render_message("advanced_search.operator.is_one_of"), "not_in": render_message("advanced_search.operator.is_not_one_of")}
    if nullable:
        common |= {"is_null": render_message("advanced_search.operator.is_empty"), "is_not_null": render_message("advanced_search.operator.is_not_empty")}
    return common


def advanced_search_leaf_count(node: dict[str, Any]) -> int:
    if node.get("type") == "condition":
        return 1
    return sum(advanced_search_leaf_count(child) for child in node.get("children", []))


def advanced_search_depth(node: dict[str, Any]) -> int:
    if node.get("type") == "condition":
        return 1
    children = node.get("children", [])
    return 1 + (max((advanced_search_depth(child) for child in children), default=0))


def advanced_search_has_positive_full_text(node: dict[str, Any], positive: bool = True) -> bool:
    if node.get("type") == "condition":
        return positive and node.get("kind") == "full_text"
    polarity = not positive if node.get("operator") == "not" else positive
    return any(advanced_search_has_positive_full_text(child, polarity) for child in node.get("children", []))


def advanced_search_has_component_field(node: dict[str, Any]) -> bool:
    if node.get("type") == "condition":
        return node.get("kind") == "structured" and node.get("field") in ADVANCED_SEARCH_COMPONENT_FIELDS
    return any(advanced_search_has_component_field(child) for child in node.get("children", []))


def compile_advanced_search_node(node: dict[str, Any], resource: str) -> dict[str, Any]:
    if node.get("type") == "condition":
        if node.get("kind") == "full_text":
            query = str(node.get("query") or "").strip()
            if not query:
                raise ValueError(render_message("advanced_search.validation.full_text_required"))
            sources = node.get("sources") or (["metadata", "components"] if resource == "records" else ["metadata"])
            return {"full_text": {"query": query, "sources": sources}}
        field = node.get("field")
        if field not in ADVANCED_SEARCH_FIELDS[resource]:
            raise ValueError(render_message("advanced_search.validation.field_required"))
        _, kind, nullable = ADVANCED_SEARCH_FIELDS[resource][field]
        operator = node.get("operator")
        if operator not in advanced_search_operators(kind, nullable):
            raise ValueError(render_message("advanced_search.validation.operator_required"))
        result: dict[str, Any] = {"field": field, "operator": operator}
        if operator not in {"is_null", "is_not_null"}:
            value = node.get("value")
            if operator in {"between", "in", "not_in"}:
                if not isinstance(value, list) or not value or any(item in (None, "") for item in value):
                    raise ValueError(render_message("advanced_search.validation.value_required"))
            elif value in (None, ""):
                raise ValueError(render_message("advanced_search.validation.value_required"))
            if field in ADVANCED_SEARCH_RETENTION_FIELDS:
                values = value if operator in {"between", "in", "not_in"} else [value]
                if field == "effective_retention.final_disposition":
                    if any(item not in ADVANCED_SEARCH_CONTROLLED_VALUES[field] for item in values):
                        raise ValueError(render_message("advanced_search.validation.retention_action"))
                else:
                    normalized = []
                    try:
                        for item in values:
                            number = int(item)
                            if isinstance(item, bool) or number < 0 or (not isinstance(item, str) and number != item):
                                raise ValueError
                            normalized.append(number)
                    except (ValueError, TypeError, OverflowError):
                        raise ValueError(render_message("advanced_search.validation.retention_years")) from None
                    value = normalized if operator in {"between", "in", "not_in"} else normalized[0]
                if operator == "between" and len(values) != 2:
                    raise ValueError(render_message("advanced_search.validation.value_required"))
            result["value"] = value
        return result
    children = node.get("children", [])
    if not children:
        raise ValueError(render_message("advanced_search.validation.group_empty"))
    operator = node.get("operator", "and")
    if operator == "not":
        if len(children) != 1:
            raise ValueError(render_message("advanced_search.validation.not_single_child"))
        return {"not": compile_advanced_search_node(children[0], resource)}
    if operator not in {"and", "or"}:
        raise ValueError(render_message("advanced_search.validation.group_operator_required"))
    return {operator: [compile_advanced_search_node(child, resource) for child in children]}


def advanced_search_node_from_expression(expression: dict[str, Any]) -> dict[str, Any]:
    """Convert canonical API grammar into the visual builder's editable tree."""
    if "full_text" in expression:
        full_text = expression["full_text"]
        return {
            "type": "condition", "kind": "full_text",
            "query": full_text.get("query", ""),
            "sources": list(full_text.get("sources") or []),
        }
    if "field" in expression:
        node = {
            "type": "condition", "kind": "structured",
            "field": expression["field"], "operator": expression["operator"],
        }
        if "value" in expression:
            node["value"] = expression["value"]
        return node
    if "not" in expression:
        return {
            "type": "group", "operator": "not",
            "children": [advanced_search_node_from_expression(expression["not"])],
        }
    operator = "and" if "and" in expression else "or"
    return {
        "type": "group", "operator": operator,
        "children": [advanced_search_node_from_expression(child) for child in expression[operator]],
    }
