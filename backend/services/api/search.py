from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import re
import base64
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from psycopg import Connection, sql
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter, ValidationError

from .schemas import GlobalSearchRequest, SearchExpression, SearchRequest
from .crud import redact_hidden_relationships
from .application_settings import cache as settings_cache
from .application_settings_registry import SEARCH_RESULT_LIMIT_MAXIMUM
from .dashboard_visibility import visibility_ctes
from .search_page import page_details, page_permission_ctes


MAX_SEARCH_DEPTH = 5
MAX_SEARCH_CONDITIONS = 50
MAX_IN_VALUES = 100
MAX_FULL_TEXT_TOKENS = 50
FULL_TEXT_SOURCES = {
    "records": ("metadata", "components"),
    "aggregations": ("metadata",),
    "digital_components": ("metadata", "content"),
}


class FieldType(str, Enum):
    INTEGER = "integer"
    TEXT = "text"
    DATETIME = "datetime"
    UUID = "uuid"
    BOOLEAN = "boolean"


@dataclass(frozen=True)
class SearchField:
    type: FieldType
    nullable: bool = False


INTEGER = SearchField(FieldType.INTEGER)
NULLABLE_INTEGER = SearchField(FieldType.INTEGER, nullable=True)
TEXT = SearchField(FieldType.TEXT)
NULLABLE_TEXT = SearchField(FieldType.TEXT, nullable=True)
DATETIME = SearchField(FieldType.DATETIME)
NULLABLE_DATETIME = SearchField(FieldType.DATETIME, nullable=True)
NULLABLE_UUID = SearchField(FieldType.UUID, nullable=True)
BOOLEAN = SearchField(FieldType.BOOLEAN)

SEARCH_FIELDS: dict[str, dict[str, SearchField]] = {
    "aggregations": {
        "id": INTEGER,
        "version": INTEGER,
        "parent_aggregation_id": NULLABLE_INTEGER,
        "classification_id": NULLABLE_INTEGER,
        "aggregation_number": TEXT,
        "title": TEXT,
        "description": NULLABLE_TEXT,
        "date_created": DATETIME,
        "date_opened": DATETIME,
        "date_closed": NULLABLE_DATETIME,
        "medium": TEXT,
        "is_vital": BOOLEAN,
        "date_of_next_review": NULLABLE_DATETIME,
        "assigned_location": NULLABLE_TEXT,
        "current_location": NULLABLE_TEXT,
        "effective_assigned_location": NULLABLE_TEXT,
        "effective_current_location": NULLABLE_TEXT,
        "security_level_id": INTEGER,
        "owning_org_unit_id": INTEGER,
        "on_effective_hold": BOOLEAN,
        "resource_state_changes_blocked": BOOLEAN,
        "effective_hold_id": INTEGER,
        "disposition_status": INTEGER,
        "disposition_job_id": NULLABLE_INTEGER,
    },
    "records": {
        "id": INTEGER,
        "version": INTEGER,
        "aggregation_id": NULLABLE_INTEGER,
        "record_number": TEXT,
        "title": TEXT,
        "description": NULLABLE_TEXT,
        "date_created": DATETIME,
        "date_originated": DATETIME,
        "medium": TEXT,
        "is_vital": BOOLEAN,
        "date_of_next_review": NULLABLE_DATETIME,
        "effective_assigned_location": NULLABLE_TEXT,
        "effective_current_location": NULLABLE_TEXT,
        "security_level_id": INTEGER,
        "owning_org_unit_id": INTEGER,
        "on_effective_hold": BOOLEAN,
        "resource_state_changes_blocked": BOOLEAN,
        "effective_hold_id": INTEGER,
        "disposition_status": INTEGER,
        "disposition_job_id": NULLABLE_INTEGER,
    },
    "digital_components": {
        "id": INTEGER,
        "version": INTEGER,
        "record_id": INTEGER,
        "component_order": INTEGER,
        "file_name": TEXT,
        "date_created": DATETIME,
        "date_originated": DATETIME,
        "mime_type": TEXT,
        "size_in_bytes": INTEGER,
        "checksum_algo": TEXT,
        "checksum_value": TEXT,
        "storage_backend": TEXT,
        "storage_key": NULLABLE_TEXT,
        "content_status": TEXT,
    },
    "event_history": {
        "id": INTEGER,
        "occurred_at": DATETIME,
        "transaction_id": INTEGER,
        "entity_type": TEXT,
        "entity_id": INTEGER,
        "operation": TEXT,
        "actor_user_id": NULLABLE_INTEGER,
        "actor_name": NULLABLE_TEXT,
        "actor_email": NULLABLE_TEXT,
        "actor_type": TEXT,
        "source": TEXT,
        "request_id": NULLABLE_UUID,
        "correlation_id": NULLABLE_UUID,
        "reason": NULLABLE_TEXT,
    },
    "org_units": {
        "id": INTEGER,
        "version": INTEGER,
        "parent_org_unit_id": NULLABLE_INTEGER,
        "code": TEXT,
        "name": TEXT,
        "description": NULLABLE_TEXT,
        "status": TEXT,
        "date_created": DATETIME,
        "date_deactivated": NULLABLE_DATETIME,
    },
    "users": {
        "id": INTEGER,
        "version": INTEGER,
        "name": TEXT,
        "description": NULLABLE_TEXT,
        "email": NULLABLE_TEXT,
        "external_id": NULLABLE_TEXT,
        "account_type": TEXT,
        "status": TEXT,
        "date_created": DATETIME,
        "date_deactivated": NULLABLE_DATETIME,
        "date_suspended": NULLABLE_DATETIME,
    },
    "roles": {
        "id": INTEGER,
        "version": INTEGER,
        "org_unit_id": INTEGER,
        "supervisor_role_id": NULLABLE_INTEGER,
        "code": TEXT,
        "name": TEXT,
        "description": NULLABLE_TEXT,
        "status": TEXT,
        "date_created": DATETIME,
        "date_deactivated": NULLABLE_DATETIME,
        "security_level_id": INTEGER,
    },
    "user_role_assignments": {
        "id": INTEGER,
        "version": INTEGER,
        "user_id": INTEGER,
        "role_id": INTEGER,
        "date_assigned": DATETIME,
        "valid_from": DATETIME,
        "valid_until": NULLABLE_DATETIME,
    },
    "classification_schemes": {
        "id": INTEGER, "version": INTEGER, "code": TEXT, "title": TEXT,
        "description": NULLABLE_TEXT, "authority": NULLABLE_TEXT,
        "scope_note": NULLABLE_TEXT, "edition": NULLABLE_TEXT,
        "date_created": DATETIME, "date_updated": DATETIME,
        "date_published": NULLABLE_DATETIME, "date_deactivated": NULLABLE_DATETIME,
        "date_first_used": NULLABLE_DATETIME,
    },
    "classifications": {
        "id": INTEGER, "version": INTEGER, "classification_scheme_id": INTEGER,
        "parent_classification_id": NULLABLE_INTEGER, "code": TEXT, "title": TEXT,
        "description": NULLABLE_TEXT, "authority": NULLABLE_TEXT,
        "scope_note": NULLABLE_TEXT, "keywords": NULLABLE_TEXT,
        "is_terminal": BOOLEAN, "date_created": DATETIME, "date_updated": DATETIME,
        "date_deactivated": NULLABLE_DATETIME, "date_first_used": NULLABLE_DATETIME,
    },
}

# Public record-search names deliberately differ from physical component
# columns where the API contract uses a clearer name. These fields are filters
# only: they are compiled inside an authorized correlated component scope and
# are never exposed as record columns or sort keys.
RECORD_COMPONENT_SEARCH_FIELDS: dict[str, tuple[SearchField, str]] = {
    "component.file_name": (TEXT, "file_name"),
    "component.mime_type": (TEXT, "mime_type"),
    "component.size_in_bytes": (INTEGER, "size_in_bytes"),
    "component.date_created": (DATETIME, "date_created"),
    "component.date_originated": (DATETIME, "date_originated"),
    "component.checksum_algorithm": (TEXT, "checksum_algo"),
    "component.checksum_value": (TEXT, "checksum_value"),
    "component.content_status": (TEXT, "content_status"),
}

# These are filters, not resource columns or sort keys. One optional lateral
# resolver supplies the same effective rule to every predicate in the query.
AGGREGATION_RETENTION_SEARCH_FIELDS: dict[str, tuple[SearchField, str]] = {
    "effective_retention.current_period_years": (INTEGER, "current_period_years"),
    "effective_retention.intermediate_period_years": (INTEGER, "intermediate_period_years"),
    "effective_retention.final_disposition": (TEXT, "final_disposition"),
}
RETENTION_DISPOSITIONS = frozenset({
    "destruction", "transfer_to_external_archive",
    "selective_preservation", "retain_as_local_archives",
})

SET_OPERATORS = {"in", "not_in"}
TEXT_OPERATORS = {"contains_ci", "starts_with_ci", "ends_with_ci", "matches_ci"}
SIMPLE_SQL_OPERATORS = {
    "eq": "=",
    "ne": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
}


def _invalid(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=message)


def _coerce_value(field_name: str, field: SearchField, value: Any) -> Any:
    try:
        if field.type is FieldType.INTEGER:
            if isinstance(value, bool):
                raise ValueError
            return TypeAdapter(int).validate_python(value)
        if field.type is FieldType.TEXT:
            if not isinstance(value, str):
                raise ValueError
            return value
        if field.type is FieldType.UUID:
            return TypeAdapter(UUID).validate_python(value)
        if field.type is FieldType.BOOLEAN:
            return TypeAdapter(bool).validate_python(value)
        parsed = TypeAdapter(datetime).validate_python(value)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed
    except (ValidationError, ValueError, TypeError) as exception:
        raise _invalid(f"invalid {field.type.value} value for field '{field_name}'") from exception


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _wildcard_like(value: str) -> str:
    escaped = _escape_like(value)
    return escaped.replace("*", "%").replace("?", "_")


def _compile_comparison(
    expression: SearchExpression,
    fields: dict[str, SearchField],
    *,
    table_alias: str = "resource",
    column_name: str | None = None,
) -> tuple[sql.Composable, list[Any]]:
    field_name = expression.field
    operator = expression.operator
    if field_name not in fields:
        raise _invalid(f"field '{field_name}' is not searchable")

    field = fields[field_name]
    if field_name == "effective_hold_id":
        if operator in {"eq", "ne"}:
            value = _coerce_value(field_name, field, expression.value)
            clause = sql.SQL("%s = ANY(resource.effective_hold_ids)")
            return (sql.SQL("NOT ({})").format(clause) if operator == "ne" else clause), [value]
        if operator in SET_OPERATORS:
            if not isinstance(expression.value, list) or not expression.value or len(expression.value) > MAX_IN_VALUES:
                raise _invalid(f"operator '{operator}' requires 1 to {MAX_IN_VALUES} values")
            values = [_coerce_value(field_name, field, value) for value in expression.value]
            clause = sql.SQL("resource.effective_hold_ids && %s::bigint[]")
            return (sql.SQL("NOT ({})").format(clause) if operator == "not_in" else clause), [values]
        raise _invalid("effective_hold_id supports eq, ne, in, and not_in")
    identifier = sql.SQL("{}.{} ").format(
        sql.Identifier(table_alias), sql.Identifier(column_name or field_name),
    )

    if operator in TEXT_OPERATORS and field.type is not FieldType.TEXT:
        raise _invalid(f"operator '{operator}' is only valid for text fields")
    if operator in {"is_null", "is_not_null"} and not field.nullable:
        raise _invalid(f"field '{field_name}' is not nullable")

    if operator == "is_null":
        return sql.SQL("{} IS NULL").format(identifier), []
    if operator == "is_not_null":
        return sql.SQL("{} IS NOT NULL").format(identifier), []

    if operator in SET_OPERATORS:
        if not isinstance(expression.value, list):
            raise _invalid(f"operator '{operator}' requires an array value")
        if not expression.value or len(expression.value) > MAX_IN_VALUES:
            raise _invalid(f"operator '{operator}' requires 1 to {MAX_IN_VALUES} values")
        values = [_coerce_value(field_name, field, value) for value in expression.value]
        keyword = sql.SQL("IN") if operator == "in" else sql.SQL("NOT IN")
        placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in values)
        return sql.SQL("{} {} ({})").format(identifier, keyword, placeholders), values

    if operator == "between":
        if not isinstance(expression.value, list) or len(expression.value) != 2:
            raise _invalid("operator 'between' requires an array containing two values")
        values = [_coerce_value(field_name, field, value) for value in expression.value]
        return sql.SQL("{} BETWEEN %s AND %s").format(identifier), values

    if operator in TEXT_OPERATORS:
        raw_value = _coerce_value(field_name, field, expression.value)
        value = _wildcard_like(raw_value) if operator == "matches_ci" else _escape_like(raw_value)
        if operator == "contains_ci":
            value = f"%{value}%"
        elif operator == "starts_with_ci":
            value = f"{value}%"
        elif operator == "ends_with_ci":
            value = f"%{value}"
        return sql.SQL("{} ILIKE %s ESCAPE '\\'").format(identifier), [value]

    if operator not in SIMPLE_SQL_OPERATORS:
        raise _invalid(f"operator '{operator}' is not supported")
    value = _coerce_value(field_name, field, expression.value)
    return sql.SQL("{} {} %s").format(
        identifier,
        sql.SQL(SIMPLE_SQL_OPERATORS[operator]),
    ), [value]


def _full_text_sources(resource: str, query: str, requested: list[str] | None) -> list[str]:
    if len(re.findall(r"\S+", query)) > MAX_FULL_TEXT_TOKENS:
        raise _invalid(f"full-text queries may contain at most {MAX_FULL_TEXT_TOKENS} tokens")
    allowed = FULL_TEXT_SOURCES.get(resource)
    if allowed is None:
        raise _invalid(f"full_text is not supported for {resource}")
    sources = requested or list(allowed)
    if len(sources) != len(set(sources)) or any(source not in allowed for source in sources):
        raise _invalid(f"invalid full-text sources for {resource}")
    return sources


def _compile_expression(
    expression: SearchExpression,
    fields: dict[str, SearchField],
    *,
    resource: str,
    depth: int,
    condition_counter: list[int],
    component_alias: str | None = None,
    component_absent: bool = False,
    batch_permissions: bool = False,
) -> tuple[sql.Composable, list[Any]]:
    def component_permission(record_id):
        return ("page_access.can_view_component" if batch_permissions else
                f"current_user_can_record_component_operation({record_id},'record.component.view','record.component.view')")
    if depth > MAX_SEARCH_DEPTH:
        raise _invalid(f"search expressions may be nested at most {MAX_SEARCH_DEPTH} levels")

    if expression.field is not None:
        condition_counter[0] += 1
        if condition_counter[0] > MAX_SEARCH_CONDITIONS:
            raise _invalid(f"searches may contain at most {MAX_SEARCH_CONDITIONS} conditions")
        retention_field = AGGREGATION_RETENTION_SEARCH_FIELDS.get(expression.field)
        if retention_field is not None:
            if resource != "aggregations":
                raise _invalid(f"field '{expression.field}' is not searchable")
            field, column = retention_field
            allowed = {"eq", "ne", "in", "not_in"}
            if field.type is FieldType.INTEGER:
                allowed |= {"gt", "gte", "lt", "lte", "between"}
            if expression.operator not in allowed:
                raise _invalid(f"operator '{expression.operator}' is not supported for '{expression.field}'")
            comparison, parameters = _compile_comparison(
                expression, {expression.field: field},
                table_alias="search_retention", column_name=column,
            )
            if field.type is FieldType.INTEGER:
                if any(value < 0 for value in parameters):
                    raise _invalid(f"field '{expression.field}' requires nonnegative whole years")
            elif any(value not in RETENTION_DISPOSITIONS for value in parameters):
                raise _invalid(f"invalid disposition action for '{expression.field}'")
            return comparison, parameters
        component_field = RECORD_COMPONENT_SEARCH_FIELDS.get(expression.field)
        if component_field is not None:
            if resource != "records":
                raise _invalid(f"field '{expression.field}' is not searchable")
            if component_absent:
                return sql.SQL("FALSE"), []
            if component_alias is None:
                comparison, parameters = _compile_comparison(
                    expression,
                    {expression.field: component_field[0]},
                    table_alias="search_component",
                    column_name=component_field[1],
                )
                return sql.SQL(
                    "EXISTS (SELECT 1 FROM digital_components search_component "
                    "WHERE search_component.record_id=resource.id "
                    f"AND {component_permission('search_component.record_id')} "
                    "AND ({}))"
                ).format(comparison), parameters
            return _compile_comparison(
                expression,
                {expression.field: component_field[0]},
                table_alias=component_alias,
                column_name=component_field[1],
            )
        comparison, parameters = _compile_comparison(expression, fields)
        multilingual_fields = {
            "classification_schemes": {"title", "description"},
            "classifications": {"title", "description"},
            "users": {"name", "description"},
            "roles": {"name", "description"},
            "org_units": {"name", "description"},
            "security_levels": {"name", "description"},
        }
        if (
            expression.field in multilingual_fields.get(resource, set())
            and expression.operator in TEXT_OPERATORS | {"eq"}
        ):
            raw_value = _coerce_value(expression.field, fields[expression.field], expression.value)
            value = _wildcard_like(raw_value) if expression.operator == "matches_ci" else _escape_like(raw_value)
            if expression.operator == "contains_ci":
                value = f"%{value}%"
            elif expression.operator == "starts_with_ci":
                value = f"{value}%"
            elif expression.operator == "ends_with_ci":
                value = f"%{value}"
            translated = sql.SQL(
                "(resource.translations::text ILIKE %s ESCAPE '\\' AND "
                "EXISTS (SELECT 1 "
                "FROM jsonb_each(COALESCE(resource.translations,'{{}}'::jsonb)) translation "
                "JOIN supported_languages search_language "
                "ON search_language.language_tag=translation.key AND search_language.is_enabled "
                "WHERE translation.value->>{} ILIKE %s ESCAPE '\\'))"
            ).format(sql.Literal(expression.field))
            # The first predicate is a conservative indexed prefilter. The
            # second preserves field and enabled-language semantics.
            return sql.SQL("(({}) OR ({}))").format(comparison, translated), [
                *parameters, value, value,
            ]
        return comparison, parameters

    if expression.full_text is not None:
        condition_counter[0] += 1
        if condition_counter[0] > MAX_SEARCH_CONDITIONS:
            raise _invalid(f"searches may contain at most {MAX_SEARCH_CONDITIONS} conditions")
        query = expression.full_text.query
        sources = _full_text_sources(resource, query, expression.full_text.sources)
        predicates: list[sql.Composable] = []
        parameters: list[Any] = []
        if resource == "records":
            if "metadata" in sources:
                predicates.append(sql.SQL(
                    "EXISTS (SELECT 1 FROM authorized_record_search_documents ftd "
                    "WHERE ftd.record_id=resource.id AND ftd.search_vector@@websearch_to_tsquery(ftd.text_search_config,%s))"
                )); parameters.append(query)
            if "components" in sources:
                predicates.append(sql.SQL(
                    "EXISTS (SELECT 1 FROM digital_components ftc "
                    "JOIN digital_component_search_documents fts ON fts.digital_component_id=ftc.id "
                    "LEFT JOIN digital_component_search_chunks ftk ON ftk.digital_component_id=ftc.id "
                    "WHERE ftc.record_id=resource.id AND fts.status IN ('indexed','processing') AND fts.indexed_at IS NOT NULL "
                    "AND fts.content_set_id=ftc.active_content_set_id "
                    f"AND {component_permission('ftc.record_id')} "
                    "AND (to_tsvector('pg_catalog.simple',coalesce(ftc.file_name,''))@@websearch_to_tsquery('pg_catalog.simple',%s) "
                    "OR ftk.search_vector@@websearch_to_tsquery(ftk.text_search_config,%s)))"
                ))
                parameters.extend((query, query))
        elif resource == "aggregations":
            predicates.append(sql.SQL(
                "EXISTS (SELECT 1 FROM authorized_aggregation_search_documents ftd "
                "WHERE ftd.aggregation_id=resource.id AND ftd.search_vector@@websearch_to_tsquery(ftd.text_search_config,%s))"
            )); parameters.append(query)
        else:
            if "metadata" in sources:
                predicates.append(sql.SQL(
                    "to_tsvector('pg_catalog.simple',coalesce(resource.file_name,''))@@websearch_to_tsquery('pg_catalog.simple',%s)"
                )); parameters.append(query)
            if "content" in sources:
                predicates.append(sql.SQL(
                    "EXISTS (SELECT 1 FROM digital_component_search_documents fts "
                    "JOIN digital_component_search_chunks ftk ON ftk.digital_component_id=fts.digital_component_id "
                    "WHERE fts.digital_component_id=resource.id AND fts.status IN ('indexed','processing') AND fts.indexed_at IS NOT NULL "
                    "AND fts.content_set_id=resource.active_content_set_id "
                    "AND ftk.search_vector@@websearch_to_tsquery(ftk.text_search_config,%s))"
                )); parameters.append(query)
        return sql.SQL("({})").format(sql.SQL(" OR ").join(predicates)), parameters

    if expression.not_ is not None:
        clause, parameters = _compile_expression(
            expression.not_, fields, resource=resource, depth=depth + 1,
            condition_counter=condition_counter, component_alias=component_alias,
            component_absent=component_absent, batch_permissions=batch_permissions,
        )
        return sql.SQL("NOT ({})").format(clause), parameters

    children = expression.and_ if expression.and_ is not None else expression.or_
    joiner = sql.SQL(" AND ") if expression.and_ is not None else sql.SQL(" OR ")
    opens_component_scope = (
        resource == "records"
        and not component_absent
        and component_alias is None
        and expression.and_ is not None
        and any(_expression_has_component_field(child) for child in children)
    )
    active_component_alias = "search_component" if opens_component_scope else component_alias
    compiled = [
        _compile_expression(
            child, fields, resource=resource, depth=depth + 1,
            condition_counter=condition_counter, component_alias=active_component_alias,
            component_absent=component_absent, batch_permissions=batch_permissions,
        )
        for child in children
    ]
    clauses = [clause for clause, _ in compiled]
    parameters = [value for _, values in compiled for value in values]
    combined = sql.SQL("({})").format(joiner.join(clauses))
    if opens_component_scope:
        component_exists = sql.SQL(
            "EXISTS (SELECT 1 FROM digital_components search_component "
            "WHERE search_component.record_id=resource.id "
            f"AND {component_permission('search_component.record_id')} "
            "AND ({}))"
        ).format(combined)
        # Preserve ordinary Boolean meaning when a mixed alternative can be
        # satisfied entirely by record predicates and the record has no
        # authorized components. Component leaves evaluate false in that
        # branch; otherwise one authorized component must satisfy the whole
        # enclosing All scope.
        without_component, without_parameters = _compile_expression(
            expression, fields, resource=resource, depth=depth,
            condition_counter=[0], component_absent=True, batch_permissions=batch_permissions,
        )
        combined = sql.SQL("(({}) OR ({}))").format(
            without_component, component_exists,
        )
        parameters = [*without_parameters, *parameters]
    return combined, parameters


def _expression_has_component_field(expression: SearchExpression) -> bool:
    if expression.field is not None:
        return expression.field in RECORD_COMPONENT_SEARCH_FIELDS
    if expression.not_ is not None:
        return _expression_has_component_field(expression.not_)
    return any(
        _expression_has_component_field(child)
        for child in (expression.and_ or expression.or_ or [])
    )


def _search_from(
    table: sql.Composable, resource: str, expression: SearchExpression | None,
) -> sql.Composable:
    def has_retention(node: SearchExpression | None) -> bool:
        if node is None:
            return False
        if node.field is not None:
            return node.field in AGGREGATION_RETENTION_SEARCH_FIELDS
        return has_retention(node.not_) or any(
            has_retention(child) for child in (node.and_ or node.or_ or [])
        )

    source = sql.SQL("{} resource").format(table)
    if resource == "aggregations" and has_retention(expression):
        # LEFT JOIN preserves other OR alternatives if resolution
        # returns no rule. No synthetic zero or action is introduced.
        source += sql.SQL(
            " LEFT JOIN LATERAL aggregation_effective_retention_rule(resource.id) "
            "search_retention ON true"
        )
    return source


def _full_text_leaves(expression: SearchExpression | None, *, positive: bool = True) -> list[tuple[str, Any]]:
    counter=[0]
    def visit(node: SearchExpression | None, polarity: bool) -> list[tuple[str,Any]]:
        if node is None: return []
        if node.full_text is not None:
            counter[0]+=1
            return [(f"fts_{counter[0]}",node.full_text)] if polarity else []
        if node.not_ is not None: return visit(node.not_,not polarity)
        return [leaf for child in (node.and_ or node.or_ or []) for leaf in visit(child,polarity)]
    return visit(expression,positive)


def _validate_indexable(connection: Connection, leaves: list[tuple[str, Any]]) -> None:
    for _, leaf in leaves:
        indexable = connection.execute(
            """SELECT numnode(websearch_to_tsquery('pg_catalog.simple',%s))>0
                      OR numnode(websearch_to_tsquery('pg_catalog.english',%s))>0
                      OR numnode(websearch_to_tsquery('pg_catalog.arabic',%s))>0 AS value""",
            (leaf.query, leaf.query, leaf.query),
        ).fetchone()["value"]
        if not indexable:
            raise HTTPException(status_code=422, detail={"code": "non_indexable_full_text_query"})


def _canonical_request(resource: str, request: SearchRequest) -> dict[str, Any]:
    value = request.model_dump(mode="json", by_alias=True, exclude_none=True)
    leaves = _full_text_leaves(request.where)
    for _, leaf in leaves:
        leaf.sources = sorted(leaf.sources or FULL_TEXT_SOURCES[resource])
    value = request.model_dump(mode="json", by_alias=True, exclude_none=True)
    sort = value.get("sort", [])
    if leaves and not sort:
        sort = [{"field": "_relevance", "direction": "desc"}]
    if not any(item["field"] == "id" for item in sort):
        sort.append({"field": "id", "direction": "asc"})
    value["sort"] = sort
    value.pop("debug", None)
    return value


def canonicalize_search_request(
    connection: Connection, resource: str, request: SearchRequest,
) -> dict[str, Any]:
    """Validate and canonicalize a request without executing the resource search."""
    if resource not in {"records", "aggregations"}:
        raise _invalid("saved searches support only records or aggregations")
    fields = SEARCH_FIELDS[resource]
    positive_leaves = _full_text_leaves(request.where)
    all_leaves = positive_leaves + _full_text_leaves(request.where, positive=False)
    _validate_indexable(connection, all_leaves)
    if request.include and not positive_leaves:
        raise _invalid("full_text_matches requires a positive full_text expression")
    if request.where is not None:
        _compile_expression(
            request.where, fields, resource=resource, depth=1, condition_counter=[0]
        )
    seen: set[str] = set()
    for item in request.sort:
        if item.field == "_relevance":
            if not positive_leaves:
                raise _invalid("_relevance requires a positive full_text expression")
        elif item.field in RECORD_COMPONENT_SEARCH_FIELDS or item.field not in fields:
            raise _invalid(f"sort field '{item.field}' is not allowed")
        if item.field in seen:
            raise _invalid(f"sort field '{item.field}' is duplicated")
        seen.add(item.field)
    return _canonical_request(resource, request)


def _debug(connection: Connection, endpoint: str, received: dict, canonical: dict) -> dict:
    from .resource_authorization import require_global
    require_global(connection, "search.query.debug")
    encoded = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    request_id = connection.execute("SELECT nullif(current_setting('app.request_id',true),'') AS value").fetchone()["value"]
    return {"method": "POST", "endpoint": endpoint, "received_request": received,
            "canonical_query": canonical, "request_id": request_id,
            "query_fingerprint": "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()}


def _attribution(connection: Connection, resource: str, item: dict, leaves: list[tuple[str, Any]], score: float) -> dict:
    metadata_matched = False
    components: dict[int, dict[str, Any]] = {}
    for leaf_id, leaf in leaves:
        sources = leaf.sources or list(FULL_TEXT_SOURCES[resource])
        if "metadata" in sources:
            if resource == "records":
                metadata_matched |= connection.execute(
                    """SELECT EXISTS(SELECT 1 FROM authorized_record_search_documents d
                           WHERE d.record_id=%s AND d.search_vector@@websearch_to_tsquery(d.text_search_config,%s)) AS value""",
                    (item["id"],leaf.query),
                ).fetchone()["value"]
            elif resource == "aggregations":
                metadata_matched |= connection.execute(
                    """SELECT EXISTS(SELECT 1 FROM authorized_aggregation_search_documents d
                           WHERE d.aggregation_id=%s AND d.search_vector@@websearch_to_tsquery(d.text_search_config,%s)) AS value""",
                    (item["id"],leaf.query),
                ).fetchone()["value"]
            elif resource == "digital_components":
                metadata_matched |= connection.execute(
                    "SELECT to_tsvector('pg_catalog.simple',coalesce(%s,''))@@websearch_to_tsquery('pg_catalog.simple',%s) AS value",
                    (item.get("file_name"),leaf.query),
                ).fetchone()["value"]
        component_source = "components" if resource == "records" else "content"
        if component_source in sources and resource in {"records","digital_components"}:
            if resource=="records":
                file_rows=connection.execute(
                    """SELECT component.id,component.file_name,component.mime_type,component.content_status
                         FROM digital_components component
                        WHERE component.record_id=%s AND component.content_status='available'
                          AND current_user_can_record_component_operation(component.record_id,'record.component.view','record.component.view')
                          AND to_tsvector('pg_catalog.simple',coalesce(component.file_name,''))
                              @@websearch_to_tsquery('pg_catalog.simple',%s)
                        ORDER BY component.id LIMIT 4""",(item["id"],leaf.query),
                ).fetchall()
                for row in file_rows:
                    if row["id"] not in components and len(components)<3:
                        components[row["id"]]={**row,
                                               "snippet":None,"leaf_ids":[leaf_id],
                                               "match_count_is_capped":len(file_rows)>3}
            rows = connection.execute(
                """SELECT component.id,component.file_name,component.mime_type,component.content_status,
                          ts_rank_cd(chunk.search_vector,websearch_to_tsquery(chunk.text_search_config,%s)) AS score,
                          ts_headline(chunk.text_search_config,chunk.extracted_text,
                              websearch_to_tsquery(chunk.text_search_config,%s),
                              'StartSel=⟦,StopSel=⟧,MaxWords=35,MinWords=12,MaxFragments=1') AS snippet
                     FROM digital_components component
                     JOIN digital_component_search_documents document ON document.digital_component_id=component.id
                     JOIN digital_component_search_chunks chunk ON chunk.digital_component_id=component.id
                    WHERE component.id=CASE WHEN %s='digital_components' THEN %s ELSE component.id END
                      AND component.record_id=CASE WHEN %s='records' THEN %s ELSE component.record_id END
                      AND document.status IN ('indexed','processing') AND document.indexed_at IS NOT NULL
                      AND document.content_set_id=component.active_content_set_id
                      AND current_user_can_record_component_operation(component.record_id,'record.component.view','record.component.view')
                      AND chunk.search_vector@@websearch_to_tsquery(chunk.text_search_config,%s)
                    ORDER BY score DESC,component.id,chunk.chunk_no LIMIT 12""",
                (leaf.query,leaf.query,resource,item["id"],resource,item.get("id"),leaf.query),
            ).fetchall()
            for row in rows:
                if row["id"] not in components and len(components) < 3:
                    components[row["id"]] = {"id":row["id"],"file_name":row["file_name"],
                                              "mime_type":row["mime_type"],"content_status":row["content_status"],
                                              "snippet":row["snippet"],"leaf_ids":[leaf_id],
                                              "match_count_is_capped":len(rows)>=12}
                elif row["id"] in components and leaf_id not in components[row["id"]]["leaf_ids"]:
                    components[row["id"]]["leaf_ids"].append(leaf_id)
                if row["id"] in components and not components[row["id"]].get("snippet"):
                    components[row["id"]]["snippet"]=row["snippet"]
    return {"relevance": score, "metadata_matched": bool(metadata_matched),
            "matching_components": list(components.values())}


def _relevance_expression(
    resource: str, leaves: list[tuple[str, Any]], *, protect_component_scores: bool = False,
    batch_permissions: bool = False,
) -> tuple[sql.Composable,list[Any]]:
    terms: list[sql.Composable]=[]; parameters: list[Any]=[]
    for _, leaf in leaves:
        sources=leaf.sources or list(FULL_TEXT_SOURCES[resource])
        if resource=="records" and "metadata" in sources:
            terms.append(sql.SQL("coalesce((SELECT ts_rank_cd(d.search_vector,websearch_to_tsquery(d.text_search_config,%s)) FROM authorized_record_search_documents d WHERE d.record_id=resource.id),0)")); parameters.append(leaf.query)
        if resource=="records" and "components" in sources:
            active = sql.SQL("")
            if protect_component_scores:
                active = sql.SQL(
                    " AND EXISTS (SELECT 1 FROM digital_components c WHERE c.id=s.digital_component_id"
                    " AND c.active_content_set_id=s.content_set_id)"
                )
            component_score = sql.SQL(
                "coalesce((SELECT max(ts_rank_cd(k.search_vector,websearch_to_tsquery(k.text_search_config,%s))) "
                "FROM digital_component_search_documents s JOIN digital_component_search_chunks k "
                "ON k.digital_component_id=s.digital_component_id WHERE s.record_id=resource.id "
                "AND s.status IN ('indexed','processing') AND s.indexed_at IS NOT NULL{}),0)"
            ).format(active)
            if protect_component_scores:
                permission = ("page_access.can_view_component" if batch_permissions else
                              "current_user_can_record_component_operation("
                              "resource.id,'record.component.view','record.component.view')")
                component_score = sql.SQL("CASE WHEN " + permission + " THEN {} ELSE 0 END").format(component_score)
            terms.append(component_score)
            parameters.append(leaf.query)
        if resource=="aggregations":
            terms.append(sql.SQL("coalesce((SELECT ts_rank_cd(d.search_vector,websearch_to_tsquery(d.text_search_config,%s)) FROM authorized_aggregation_search_documents d WHERE d.aggregation_id=resource.id),0)")); parameters.append(leaf.query)
        if resource=="digital_components" and "content" in sources:
            terms.append(sql.SQL("coalesce((SELECT max(ts_rank_cd(k.search_vector,websearch_to_tsquery(k.text_search_config,%s))) FROM digital_component_search_chunks k WHERE k.digital_component_id=resource.id),0)")); parameters.append(leaf.query)
        if resource=="digital_components" and "metadata" in sources:
            terms.append(sql.SQL("ts_rank_cd(to_tsvector('pg_catalog.simple',coalesce(resource.file_name,'')),websearch_to_tsquery('pg_catalog.simple',%s))")); parameters.append(leaf.query)
    return (sql.SQL(" + ").join(terms) if terms else sql.SQL("0.0")),parameters


def record_destination_clause(alias: str, *, digital_only: bool = False) -> str:
    # Aliases are internal constants, never request input.
    if alias not in {"resource", "a"}:
        raise ValueError("unsupported destination alias")
    return f"""current_user_can_aggregation_operation({alias}.id,'record.create','aggregation.add_record')
        AND EXISTS (SELECT 1 FROM user_role_assignments assignment
          JOIN roles role ON role.id=assignment.role_id
          WHERE assignment.user_id=current_user_id() AND role.org_unit_id={alias}.owning_org_unit_id
            AND assignment.valid_from<=CURRENT_TIMESTAMP
            AND (assignment.valid_until IS NULL OR CURRENT_TIMESTAMP<assignment.valid_until)
            AND role_effectively_active(role.id))
        AND NOT EXISTS (WITH RECURSIVE ancestors AS (
          SELECT id,parent_aggregation_id,date_closed FROM aggregations WHERE id={alias}.id
          UNION ALL SELECT parent.id,parent.parent_aggregation_id,parent.date_closed
            FROM aggregations parent JOIN ancestors child ON parent.id=child.parent_aggregation_id)
          SELECT 1 FROM ancestors WHERE date_closed IS NOT NULL)""" + (
              f" AND {alias}.medium IN ('digital','mixed')" if digital_only else "")


def _audit_actor_candidates(expression: SearchExpression | None):
    """Necessary raw predicates only; the authorized predicate still decides matches.

    Unsupported branches mean TRUE, never FALSE. In particular, null/negated
    actor tests must not exclude redacted envelopes whose projected actors are null.
    """
    if expression is None:
        return None
    if expression.field is not None:
        if (expression.field in {"actor_user_id", "actor_name", "actor_email"}
                and expression.operator in TEXT_OPERATORS | {"eq", "in", "gt", "gte", "lt", "lte"}):
            return _compile_comparison(expression, SEARCH_FIELDS["event_history"],
                                       table_alias="audit_candidate")
        return None
    children = expression.and_ or expression.or_
    if children is None:
        return None
    compiled = [_audit_actor_candidates(child) for child in children]
    if expression.or_ and any(child is None for child in compiled):
        return None
    compiled = [child for child in compiled if child is not None]
    if not compiled:
        return None
    operator = sql.SQL(" OR " if expression.or_ else " AND ")
    return (sql.SQL("({})").format(operator.join(child[0] for child in compiled)),
            [value for child in compiled for value in child[1]])



def _filters_disposition(expression):
    if expression is None:return False
    return expression.field=='disposition_status' or any(_filters_disposition(child) for child in (expression.and_ or expression.or_ or [])) or _filters_disposition(expression.not_)


def _resource_visibility(resource,expression):
    kind='record' if resource=='records' else 'aggregation'
    live=f"current_user_can_view_{kind}(resource.id)"
    if not _filters_disposition(expression):return sql.SQL(live)
    return sql.SQL("("+live+" OR (resource.disposition_status=10 AND disposition_private.retained_access('"+kind+"',resource.id,false)))")

def search_rows(
    connection: Connection,
    table: str,
    request: SearchRequest,
    *, endpoint: str | None = None,
    include_system_roles: bool = False,
    localized_sort_language: str | None = None,
    eligible_classifications: bool = False,
    record_creation: bool = False,
    digital_only: bool = False,
    display_filter: str | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    settings = settings_cache.for_connection(connection)
    audit_cap = settings["AUDIT_TRAIL_SEARCH_RESULT_LIMIT"]
    result_cap = audit_cap if table == "event_history" else max_results
    if table == "event_history" and request.offset >= audit_cap:
        raise HTTPException(status_code=422, detail={
            "code": "audit_result_cap", "message_key": "audit.filter.results_capped",
            "params": {"limit": audit_cap},
        })
    if max_results is not None and request.offset >= max_results:
        raise HTTPException(status_code=422, detail={"code": "advanced_search_result_limit_exceeded"})
    if _full_text_leaves(request.where) and not settings["FULL_TEXT_SEARCH_ENABLED"]:
        raise HTTPException(status_code=503, detail={
            "code": "full_text_search_disabled",
            "message": "Full-text search is temporarily disabled.",
        })
    fields = SEARCH_FIELDS[table]
    visibility = {
        "aggregations": _resource_visibility("aggregations",request.where),
        "records": _resource_visibility("records",request.where),
        "digital_components": sql.SQL(
            "EXISTS (SELECT 1 FROM records visible_record WHERE visible_record.id=resource.record_id "
            "AND current_user_can_list_record_components(visible_record.id))"
        ),
        "roles": None if include_system_roles else sql.SQL("NOT is_system"),
    }.get(table)
    clauses: list[sql.Composable] = []
    if record_creation:
        if table != "aggregations":
            raise ValueError("record destinations require aggregations")
        clauses.append(sql.SQL(record_destination_clause("resource", digital_only=digital_only)))
    if eligible_classifications:
        if table != "classifications":
            raise ValueError("classification eligibility requires classifications")
        clauses.append(sql.SQL(
            "resource.is_terminal AND "
            "classification_scheme_is_eligible(resource.classification_scheme_id) AND "
            "classification_is_effectively_active(resource.id) AND "
            "EXISTS (SELECT 1 FROM effective_classification_retention_rule(resource.id))"
        ))
    parameters: list[Any] = []
    positive_leaves = _full_text_leaves(request.where)
    all_leaves = _full_text_leaves(request.where, positive=True) + _full_text_leaves(request.where, positive=False)
    _validate_indexable(connection, all_leaves)
    if request.include and not positive_leaves:
        raise _invalid("full_text_matches requires a positive full_text expression")
    if request.where is not None:
        expression, parameters = _compile_expression(
            request.where, fields, resource=table, depth=1, condition_counter=[0]
        )
        clauses.append(expression)
        if table == "event_history":
            candidate = _audit_actor_candidates(request.where)
            if candidate is not None:
                clauses.append(sql.SQL(
                    "resource.id IN (SELECT audit_candidate.id FROM event_history audit_candidate WHERE {})"
                ).format(candidate[0]))
                parameters.extend(candidate[1])
    if visibility is not None:
        clauses.append(visibility)
    if display_filter:
        columns = (
            sql.SQL("resource.record_number, resource.title, resource.medium, "
                    "parent.aggregation_number, parent.title")
            if table == "records" else
            sql.SQL("resource.aggregation_number, resource.title, resource.medium")
        )
        clauses.append(sql.SQL("concat_ws(' ', {}) ILIKE %s ESCAPE '\\'").format(columns))
        parameters.append(f"%{_escape_like(display_filter)}%")
    where_clause = (
        sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses)
        if clauses else sql.SQL("")
    )

    sort_fields: list[tuple[str, str]] = []
    for item in request.sort:
        if item.field == "_relevance":
            if not positive_leaves:
                raise _invalid("_relevance requires a positive full_text expression")
        elif item.field not in fields:
            raise _invalid(f"sort field '{item.field}' is not allowed")
        if item.field in {field for field, _ in sort_fields}:
            raise _invalid(f"sort field '{item.field}' is duplicated")
        sort_fields.append((item.field, item.direction))
    if not sort_fields:
        sort_fields.extend([("occurred_at", "desc"), ("id", "desc")] if table == "event_history"
                           else [("_relevance", "desc"), ("id", "asc")] if positive_leaves else [("id", "asc")])
    elif "id" not in {field for field, _ in sort_fields}:
        sort_fields.append(("id", "asc"))

    table_identifier = sql.Identifier({
        "event_history": "authorized_event_history",
        "aggregations": "authorized_aggregations_for_search",
        "records": "authorized_records_for_search",
    }.get(table, table))
    source = _search_from(table_identifier, table, request.where)
    if display_filter and table == "records":
        source += sql.SQL(
            " LEFT JOIN aggregations parent ON parent.id = resource.aggregation_id "
            "AND current_user_can_view_aggregation(parent.id)"
        )
    count_query = sql.SQL("SELECT count(*) AS total FROM {}{}").format(
        source, where_clause
    )
    if result_cap is not None:
        count_query = sql.SQL(
            "SELECT count(*) AS total FROM (SELECT 1 FROM {}{} LIMIT {}) {}"
        ).format(source, where_clause, sql.Literal(min(result_cap + 1, 9223372036854775807)),
                 sql.Identifier("audit_count" if table == "event_history" else "bounded_count"))
    total = connection.execute(count_query, parameters).fetchone()["total"]
    truncated = result_cap is not None and total > result_cap
    page_limit = request.limit
    if result_cap is not None:
        total = min(total, result_cap)
        page_limit = min(page_limit, result_cap - request.offset)

    relevance,relevance_parameters=_relevance_expression(table,positive_leaves)
    language_candidates = []
    if localized_sort_language:
        language_candidates.append(localized_sort_language)
        if "-" in localized_sort_language:
            language_candidates.append(localized_sort_language.split("-", 1)[0])

    def sort_expression(field: str) -> sql.Composable:
        if field == "_relevance":
            return relevance
        canonical = sql.SQL("resource.{}").format(sql.Identifier(field))
        if display_filter is not None and fields[field].type is FieldType.TEXT:
            return sql.SQL("lower({})").format(canonical)
        if field != "name" or not language_candidates or table not in {
            "org_units", "roles", "users",
        }:
            return canonical
        translated_candidates = [
            sql.SQL("NULLIF(resource.translations -> {} ->> {}, '')").format(
                sql.Literal(language_tag), sql.Literal(field),
            )
            for language_tag in language_candidates
        ]
        return sql.SQL("lower(COALESCE({}, {}))").format(
            sql.SQL(", ").join(translated_candidates), canonical,
        )

    order_clause = sql.SQL(", ").join(
        sql.SQL("{} {}").format(sort_expression(field), sql.SQL(direction.upper()))
        for field, direction in sort_fields
    )
    result_query = sql.SQL("SELECT resource.*,({})::double precision AS _fts_relevance FROM {}{} ORDER BY {} LIMIT %s OFFSET %s").format(
        relevance,
        source,
        where_clause,
        order_clause,
    )
    items = list(
        connection.execute(
            result_query, [
                *relevance_parameters,
                *parameters,
                *(relevance_parameters if any(field == "_relevance" for field, _ in sort_fields) else []),
                page_limit,
                request.offset,
            ]
        ).fetchall()
    )
    items = redact_hidden_relationships(connection, table, items)
    for item in items:
        # This internal array enables effective_hold_id filtering but must not
        # disclose hold identities through ordinary resource search results.
        item.pop("effective_hold_ids", None)
        score = item.pop("_fts_relevance", 0.0)
        if "full_text_matches" in request.include:
            item["_search"] = _attribution(connection, table, item, positive_leaves, score)
    result = {
        "items": items,
        "total": total,
        "limit": request.limit,
        "offset": request.offset,
        "returned": len(items),
    }
    if result_cap is not None:
        result.update(result_cap=result_cap, truncated=truncated)
    if all_leaves:
        if table == "records":
            pending = connection.execute(
                """SELECT EXISTS(SELECT 1 FROM digital_component_search_documents document
                     WHERE document.status IN ('pending','processing','stale')
                       AND current_user_can_view_record(document.record_id)
                       AND EXISTS(SELECT 1 FROM records pending_record WHERE pending_record.id=document.record_id AND (pending_record.disposition_status NOT IN (10,11,12) OR disposition_private.can_manage()))
                       AND current_user_can_record_component_operation(
                           document.record_id,'record.component.view','record.component.view')) AS value"""
            ).fetchone()["value"]
            result["index_freshness"] = {"has_pending_content": bool(pending)}
        elif table == "aggregations":
            result["index_freshness"] = {"has_pending_content": False}
    if request.debug:
        received = request.model_dump(mode="json", by_alias=True, exclude_unset=True, exclude_none=True)
        result["_debug"] = _debug(connection, endpoint or f"/api/v1/{table.replace('_','-')}/search",
                                  received, _canonical_request(table, request))
    return result


def _condition_count(expression: SearchExpression | None) -> int:
    if expression is None:
        return 0
    if expression.field is not None or expression.full_text is not None:
        return 1
    if expression.not_ is not None:
        return _condition_count(expression.not_)
    return sum(_condition_count(child) for child in (expression.and_ or expression.or_ or []))


def _cursor_encode(value: dict[str, Any]) -> str:
    raw=json.dumps(value,separators=(",",":"),sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _cursor_decode(value: str) -> tuple[UUID, UUID, int, str | None]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        decoded = json.loads(raw)
        position = decoded["position"]
        result_filter = decoded["filter"]
        if type(position) is not int or not 0 <= position <= SEARCH_RESULT_LIMIT_MAXIMUM:
            raise ValueError
        if result_filter not in (None, "record", "aggregation"):
            raise ValueError
        return UUID(decoded["search_id"]), UUID(decoded["tab_id"]), position, result_filter
    except (ValueError, TypeError, KeyError, AttributeError) as exception:
        raise _invalid("invalid global-search page token") from exception


def _indexed_text_ids(
    table: str, id_column: str, query: str, configurations: tuple[str, ...],
) -> tuple[sql.Composable, list[str]]:
    source = sql.SQL("SELECT {} AS id FROM {} WHERE ").format(
        sql.Identifier(id_column), sql.Identifier(table),
    )
    configs = [sql.SQL("{}::regconfig").format(sql.Literal(config)) for config in configurations]
    # A fixed configuration lets PostgreSQL use the GIN index on search_vector.
    predicates = [
        sql.SQL("(text_search_config = {} AND search_vector @@ websearch_to_tsquery({}, %s))").format(
            config, config,
        )
        for config in configs
    ]
    # One common-config branch allows a BitmapOr for selective terms and one
    # sequential scan for corpus-wide terms, rather than a full scan per language.
    branches = [source + sql.SQL(" OR ").join(predicates)]
    # Preserve matching for rows written with other installed configurations.
    branches.append(source + sql.SQL(
        "text_search_config NOT IN ({}) AND search_vector @@ "
        "CASE text_search_config "
        "WHEN 'pg_catalog.english'::regconfig THEN (SELECT english FROM search_query) "
        "WHEN 'pg_catalog.arabic'::regconfig THEN (SELECT arabic FROM search_query) "
        "ELSE (SELECT parsed FROM other_search_queries WHERE config = text_search_config) END"
    ).format(sql.SQL(", ").join(configs)))
    return sql.SQL(" UNION ALL ").join(branches), [query] * len(configs)


def _indexed_global_candidates(
    resource: str, query: str, sources: list[str], structured_filter=None,
) -> tuple[sql.Composable, list[Any]]:
    ctes: list[sql.Composable] = []
    candidates: list[sql.Composable] = []
    parameters: list[Any] = []
    match_flags = "components" in sources and "metadata" in sources
    if "metadata" in sources:
        kind = "record" if resource == "records" else "aggregation"
        metadata, metadata_parameters = _indexed_text_ids(
            f"{kind}_search_documents", f"{kind}_id", query, ("pg_catalog.simple",),
        )
        ctes.append(sql.SQL("metadata_matches AS MATERIALIZED ({})").format(metadata))
        candidates.append(sql.SQL("SELECT id FROM metadata_matches"))
        parameters.extend(metadata_parameters)
    if "components" in sources:
        chunks, chunk_parameters = _indexed_text_ids(
            "digital_component_search_chunks", "digital_component_id", query,
            ("pg_catalog.simple", "pg_catalog.english", "pg_catalog.arabic"),
        )
        # A metadata match already qualifies the record. Find additional file
        # matches only for other records; still score ALL permitted active file
        # chunks later, including those on metadata hits (not just text matches).
        # The one-time guard skips the broad chunk match scan entirely when
        # every record already matches metadata, without capping any candidates.
        file_guard = sql.SQL("true")
        record_guard = sql.SQL("true")
        if match_flags:
            file_guard = sql.SQL("""EXISTS (
                SELECT 1 FROM records remaining
                WHERE NOT EXISTS (SELECT 1 FROM metadata_matches metadata WHERE metadata.id=remaining.id)
            )""")
            record_guard = sql.SQL("""NOT EXISTS (
                SELECT 1 FROM metadata_matches metadata WHERE metadata.id=component.record_id
            )""")
        ctes.append(sql.SQL("""
            matching_files AS NOT MATERIALIZED (
                SELECT id FROM (
                SELECT id FROM digital_components
                WHERE to_tsvector('pg_catalog.simple', coalesce(file_name, ''))
                      @@ websearch_to_tsquery('pg_catalog.simple', %s)
                UNION
                SELECT id FROM ({}) AS matching_chunks
                ) file_candidates WHERE ({})
            ),
            -- Keep correlated content identities out of join selectivity:
            -- treating the two equalities as independent estimated one row
            -- for a corpus-wide match and selected quadratic nested loops.
            -- OFFSET 0 preserves this boundary while streaming its rows.
            matching_component_rows AS NOT MATERIALIZED (
                SELECT component.record_id AS id,
                       document.status IN ('indexed', 'processing')
                       AND document.indexed_at IS NOT NULL
                       AND document.content_set_id = component.active_content_set_id AS searchable
                FROM matching_files file
                JOIN digital_components component ON component.id = file.id
                JOIN digital_component_search_documents document ON document.digital_component_id = component.id
                WHERE ({})
                OFFSET 0
            ),
            component_matches AS NOT MATERIALIZED (
                SELECT DISTINCT id FROM matching_component_rows WHERE searchable
            )
        """).format(chunks, file_guard, record_guard))
        candidates.append(sql.SQL("SELECT id FROM component_matches"))
        parameters.extend((query, *chunk_parameters))
    candidate_name = "text_candidate_ids" if structured_filter is not None else "candidate_ids"
    # Keep match flags with each unique record ID. Rejoining both match sets
    # after authorization duplicates work and loses useful cardinality facts.
    candidate_query = sql.SQL("""
        SELECT id,true AS metadata_match,false AS component_match FROM metadata_matches
        UNION ALL
        SELECT id,false,true FROM component_matches
    """) if match_flags else sql.SQL(" UNION ").join(candidates)
    ctes.append(sql.SQL("{} AS MATERIALIZED ({})").format(
        sql.Identifier(candidate_name), candidate_query))
    if structured_filter is not None:
        clause, arguments = _compile_expression(
            structured_filter, SEARCH_FIELDS[resource], resource=resource, depth=1, condition_counter=[0],
        )
        source = _search_from(sql.Identifier(f"authorized_{resource}_for_search"), resource, structured_filter)
        ctes.append(sql.SQL("""candidate_ids AS MATERIALIZED (
            SELECT candidate.* FROM {} JOIN text_candidate_ids candidate ON candidate.id=resource.id
            WHERE {})""").format(source, clause))
        parameters.extend(arguments)
    ctes.append(sql.SQL(visibility_ctes(
        candidate_resource=resource, component_access="components" in sources, match_flags=match_flags,
    )))
    return sql.SQL(", ").join(ctes) + sql.SQL(", "), parameters


def _indexed_global_ranking(resource, leaf, limit, structured_filter=None):
    sources = _full_text_sources(resource, leaf.query, leaf.sources)
    ctes, parameters = _indexed_global_candidates(resource, leaf.query, sources, structured_filter)
    # A row-dependent configuration otherwise reparses the same phrase for
    # every document/chunk. Materialize the common configurations once.
    ctes = sql.SQL("""search_query AS MATERIALIZED (
        SELECT %s::text AS phrase,
               websearch_to_tsquery('pg_catalog.simple', %s) AS simple,
               websearch_to_tsquery('pg_catalog.english', %s) AS english,
               websearch_to_tsquery('pg_catalog.arabic', %s) AS arabic
    ), other_search_queries AS MATERIALIZED (
        SELECT config.oid::regconfig AS config,
               websearch_to_tsquery(config.oid::regconfig, search_query.phrase) AS parsed
        FROM pg_catalog.pg_ts_config config CROSS JOIN search_query
        WHERE config.oid NOT IN ('pg_catalog.simple'::regconfig,
                                'pg_catalog.english'::regconfig, 'pg_catalog.arabic'::regconfig)
    ), """) + ctes
    parameters = [leaf.query] * 4 + parameters
    def parsed_query(alias):
        return sql.SQL("""CASE {}.text_search_config
            WHEN 'pg_catalog.simple'::regconfig THEN (SELECT simple FROM search_query)
            WHEN 'pg_catalog.english'::regconfig THEN (SELECT english FROM search_query)
            WHEN 'pg_catalog.arabic'::regconfig THEN (SELECT arabic FROM search_query)
            ELSE (SELECT parsed FROM other_search_queries WHERE config = {}.text_search_config) END""").format(
                sql.Identifier(alias), sql.Identifier(alias))
    joins = []
    matches = []
    scores = []
    if "components" in sources:
        # Use the same maximum over active chunks as the original rank. The batch
        # ACL must authorize component evidence even for a metadata match.
        ctes += sql.SQL("""
            eligible_components AS MATERIALIZED (
                SELECT candidate.id, document.digital_component_id,
                       component.active_content_set_id = document.content_set_id AS current_content
                  FROM authorized_records candidate
                  JOIN digital_component_search_documents document ON document.record_id = candidate.id
                  JOIN digital_components component ON component.id = document.digital_component_id
                 WHERE candidate.can_view_component AND document.status IN ('indexed','processing')
                   AND document.indexed_at IS NOT NULL
            ),
            eligible_component_ids AS MATERIALIZED (
                SELECT digital_component_id FROM eligible_components WHERE current_content
            ),
            component_scan_strategy AS MATERIALIZED (
                -- ACL selectivity is not available in table statistics. Use
                -- the actual permitted set to choose indexed or bulk retrieval.
                -- This is a scan decision, never a limit on candidates/results.
                SELECT count(*) > greatest(1000, (
                    SELECT greatest(reltuples,0) * 0.05 FROM pg_class
                    WHERE oid='digital_components'::regclass
                )) AS bulk FROM eligible_component_ids
            ),
            -- Narrow the hash input before joining wide chunk vectors. Otherwise
            -- hash batching spills entire vectors even though the result is small.
            -- Stream the single-use scores; OFFSET 0 keeps vectors out of later joins.
            scored_component_chunks AS NOT MATERIALIZED (
                SELECT chunk.digital_component_id, ts_rank_cd(chunk.search_vector, {}) AS score
                FROM digital_component_search_chunks chunk
                WHERE NOT (SELECT bulk FROM component_scan_strategy)
                  AND chunk.digital_component_id = ANY (ARRAY(
                      SELECT digital_component_id FROM eligible_component_ids))
                UNION ALL
                SELECT chunk.digital_component_id, ts_rank_cd(chunk.search_vector, {}) AS score
                FROM (
                    SELECT digital_component_id,search_vector,text_search_config
                    FROM digital_component_search_chunks OFFSET 0
                ) chunk
                WHERE (SELECT bulk FROM component_scan_strategy)
                  AND chunk.digital_component_id IN (
                      SELECT digital_component_id FROM eligible_component_ids)
                OFFSET 0
            ), component_scores AS (
                SELECT candidate.id, max(chunk.score) AS score
                FROM eligible_components candidate
                JOIN scored_component_chunks chunk USING (digital_component_id)
                GROUP BY candidate.id
            ),
        """).format(parsed_query("chunk"), parsed_query("chunk"))
        joins.append(sql.SQL("LEFT JOIN component_scores component USING (id)"))
        if "metadata" in sources:
            matches.append(sql.SQL("(candidate.can_view_component AND candidate.component_match)"))
        else:
            matches.append(sql.SQL("candidate.can_view_component"))
    if "metadata" in sources:
        kind = "record" if resource == "records" else "aggregation"
        if "components" in sources:
            # Do not carry full metadata vectors through the file-score join.
            ctes += sql.SQL("""metadata_scores AS NOT MATERIALIZED (
                SELECT candidate.id, ts_rank_cd(metadata.search_vector, {}) AS score
                FROM authorized_records candidate
                JOIN record_search_documents metadata ON metadata.record_id=candidate.id
                OFFSET 0
            ), """).format(parsed_query("metadata"))
            joins.append(sql.SQL("LEFT JOIN metadata_scores metadata USING (id)"))
            scores.append(sql.SQL("coalesce(metadata.score, 0)"))
            matches.append(sql.SQL("candidate.metadata_match"))
        else:
            joins.append(sql.SQL("LEFT JOIN {} metadata ON metadata.{} = candidate.id").format(
                sql.Identifier(f"{kind}_search_documents"), sql.Identifier(f"{kind}_id"),
            ))
            scores.append(sql.SQL("coalesce(ts_rank_cd(metadata.search_vector, {}), 0)").format(parsed_query("metadata")))
            matches.append(sql.SQL("true"))
    if "components" in sources:
        scores.append(sql.SQL("coalesce(component.score, 0)"))
    statement = sql.SQL("""
        WITH RECURSIVE {} ranked AS (
            SELECT candidate.id, ({})::double precision AS score
            FROM {} candidate {}
            WHERE {}
        )
        SELECT * FROM ranked ORDER BY score DESC, id ASC LIMIT %s
    """).format(
        ctes, sql.SQL(" + ").join(scores), sql.Identifier(f"authorized_{resource}"),
        sql.SQL(" ").join(joins), sql.SQL(" OR ").join(matches),
    )
    return statement, [*parameters, limit]


def _global_ranking_statement(connection, resource, expression, limit):
    leaves = _full_text_leaves(expression)
    if not leaves:
        raise _invalid("global-search branches require a positive full_text expression")
    _validate_indexable(connection, leaves)
    if expression.full_text is not None:
        return _indexed_global_ranking(resource, expression.full_text, limit)
    if expression.and_ and not _filters_disposition(expression):
        text_nodes = [node for node in expression.and_ if node.full_text is not None]
        other_nodes = [node for node in expression.and_ if node.full_text is None]
        if len(text_nodes) == 1 and not any(
            _full_text_leaves(node) or _full_text_leaves(node, positive=False) for node in other_nodes
        ):
            return _indexed_global_ranking(
                resource, text_nodes[0].full_text, limit,
                SearchExpression.model_validate({"and": other_nodes}) if other_nodes else None,
            )
    relevance, relevance_parameters = _relevance_expression(resource, leaves, protect_component_scores=True)
    table = sql.Identifier("authorized_records_for_search" if resource == "records" else "authorized_aggregations_for_search")
    visibility = _resource_visibility(resource, expression)
    source = _search_from(table, resource, expression)
    projection = sql.SQL("resource.id, ({})::double precision AS score").format(relevance)
    clause, parameters = _compile_expression(
        expression, SEARCH_FIELDS[resource], resource=resource, depth=1, condition_counter=[0],
    )
    statement = sql.SQL("""
        SELECT {} FROM {} WHERE ({}) AND ({})
        ORDER BY score DESC, id ASC LIMIT %s
    """).format(projection, source, visibility, clause)
    return statement, [*relevance_parameters, *parameters, limit]


def _global_current_rows(connection, resource, expression, candidate_ids):
    if _filters_disposition(expression):
        return _global_retained_current_rows(connection, resource, expression, candidate_ids)
    leaves = _full_text_leaves(expression)
    relevance, relevance_parameters = _relevance_expression(
        resource, leaves, protect_component_scores=True, batch_permissions=True,
    )
    clause, clause_parameters = _compile_expression(
        expression, SEARCH_FIELDS[resource], resource=resource, depth=1,
        condition_counter=[0], batch_permissions=True,
    )
    kind = "record" if resource == "records" else "aggregation"
    table = sql.Identifier(f"authorized_{resource}_for_search")
    source = _search_from(table, resource, expression)
    columns = ("id,record_number,title,security_level_id,description,aggregation_id,"
               "date_originated,is_vital,on_effective_hold" if resource == "records" else
               "id,aggregation_number,title,date_opened,security_level_id,description,"
               "is_vital,on_effective_hold")
    statement = sql.SQL("""
        WITH RECURSIVE page_record_ids AS MATERIALIZED (SELECT unnest(%s::bigint[]) AS id),
             page_aggregation_ids AS MATERIALIZED (SELECT unnest(%s::bigint[]) AS id),
             {permissions}
        SELECT {columns}, ({relevance})::double precision AS score
        FROM {source} JOIN {authorized} page_access ON page_access.id=resource.id
        WHERE ({clause})
    """).format(permissions=page_permission_ctes(),
                columns=sql.SQL(",").join(sql.Identifier("resource", column) for column in columns.split(",")), relevance=relevance,
                source=source, authorized=sql.Identifier(f"authorized_{resource}"), clause=clause)
    return connection.execute(statement, [
        candidate_ids if kind == "record" else [], candidate_ids if kind == "aggregation" else [],
        *relevance_parameters, *clause_parameters,
    ], prepare=False).fetchall()


def _global_retained_current_rows(connection, resource, expression, candidate_ids):
    leaves = _full_text_leaves(expression)
    relevance, relevance_parameters = _relevance_expression(resource, leaves, protect_component_scores=True)
    table = sql.Identifier("authorized_records_for_search" if resource == "records" else "authorized_aggregations_for_search")
    visibility = _resource_visibility(resource, expression)
    source = _search_from(table, resource, expression)
    clause, clause_parameters = _compile_expression(
        expression, SEARCH_FIELDS[resource], resource=resource, depth=1, condition_counter=[0],
    )
    # Restrict the current authorization and match checks to IDs from the saved list.
    statement = sql.SQL("""
        SELECT current_match.*
        FROM unnest(%s::bigint[]) AS saved(id)
        JOIN LATERAL (
            SELECT resource.*, ({})::double precision AS score
            FROM {}
            WHERE resource.id = saved.id AND ({}) AND ({})
            OFFSET 0
        ) AS current_match ON true
    """).format(relevance, source, visibility, clause)
    return connection.execute(statement, [candidate_ids, *relevance_parameters, *clause_parameters]).fetchall()


def _global_page_offset(hit_count, page_number, page_size):
    return min(page_number - 1, max(0, hit_count - 1) // page_size) * page_size


def _rank_global_search(connection, branches, result_cap, result_filter, page_size, page_number):
    statements = []
    parameters = []
    for kind, (resource, expression) in branches.items():
        statement, arguments = _global_ranking_statement(connection, resource, expression, result_cap + 1)
        statements.append(sql.SQL("SELECT {} AS kind, id, score FROM ({}) AS branch").format(
            sql.Literal(kind), statement,
        ))
        parameters.extend(arguments)
    filter_clause = sql.SQL("") if result_filter is None else sql.SQL("WHERE kind = %s")
    statement = sql.SQL("""
        WITH ranked AS MATERIALIZED (
            SELECT kind, id, score FROM ({}) AS combined
            ORDER BY score DESC, kind, id LIMIT %s
        ),
        filtered AS MATERIALIZED (
            SELECT kind, id, score FROM (
                SELECT kind, id, score FROM ranked ORDER BY score DESC, kind, id LIMIT %s
            ) AS capped
            {}
        ),
        selected_page AS MATERIALIZED (
            SELECT kind, id FROM filtered
            ORDER BY score DESC, kind, id LIMIT %s
            OFFSET (SELECT LEAST(%s - 1, GREATEST(count(*) - 1, 0) / %s) * %s FROM filtered)
        )
        SELECT ranked.kind, ranked.id, ranked.score, COALESCE(record.details, aggregation.details) AS details
        FROM ranked
        LEFT JOIN selected_page page ON page.kind = ranked.kind AND page.id = ranked.id
        LEFT JOIN LATERAL (
            SELECT to_jsonb(detail) AS details
            FROM (
                SELECT resource.id, record_number, title, security_level_id, description,
                       aggregation_id, date_originated, is_vital, on_effective_hold
                FROM authorized_records_for_search resource
                WHERE page.kind = 'record' AND resource.id = page.id
                OFFSET 0
            ) detail
        ) record ON true
        LEFT JOIN LATERAL (
            SELECT to_jsonb(detail) AS details
            FROM (
                SELECT resource.id, aggregation_number, title, date_opened, security_level_id,
                       description, is_vital, on_effective_hold
                FROM authorized_aggregations_for_search resource
                WHERE page.kind = 'aggregation' AND resource.id = page.id
                OFFSET 0
            ) detail
        ) aggregation ON true
        ORDER BY ranked.score DESC, ranked.kind, ranked.id
    """).format(sql.SQL(" UNION ALL ").join(statements), filter_clause)
    parameters.extend((result_cap + 1, result_cap))
    if result_filter is not None:
        parameters.append(result_filter)
    parameters.extend((page_size, page_number, page_size, page_size))
    # Selectivity varies dramatically by phrase; never reuse a generic prepared
    # plan that estimates a common term as a rare one (or vice versa).
    rows = connection.execute(statement, parameters, prepare=False).fetchall()
    hits = [{"type": row["kind"], "id": row["id"], "score": row["score"]} for row in rows[:result_cap]]
    page = [
        (row["kind"], {**row["details"], "score": row["score"]})
        for row in rows if row["details"] is not None
    ]
    return hits, page, len(rows) > result_cap


def _expired_global_search() -> HTTPException:
    return HTTPException(status_code=410, detail={"code": "global_search_expired"})


def _save_global_search(connection, hits, truncated, session_id, user_id, tab_id, fingerprint, requires_tab_id, idle_minutes):
    search_id = uuid4()
    stored = connection.execute("""
        INSERT INTO global_search_results
            (session_id, tab_id, user_id, requires_tab_id, search_id, fingerprint, hits, truncated, started_at, expires_at)
        SELECT id, %s, user_id, %s, %s, %s, %s, %s, transaction_timestamp(),
               clock_timestamp() + LEAST(%s::double precision * 60,
                   extract(epoch FROM LEAST(expires_at, absolute_expires_at) - clock_timestamp())) * interval '1 second'
        FROM login_sessions
        WHERE id = %s AND user_id = %s AND revoked_at IS NULL
          AND LEAST(expires_at, absolute_expires_at) > clock_timestamp()
        ON CONFLICT (session_id, tab_id) DO UPDATE
        SET search_id = EXCLUDED.search_id, fingerprint = EXCLUDED.fingerprint, hits = EXCLUDED.hits,
            requires_tab_id = EXCLUDED.requires_tab_id,
            truncated = EXCLUDED.truncated, started_at = EXCLUDED.started_at, expires_at = EXCLUDED.expires_at
        WHERE global_search_results.started_at <= EXCLUDED.started_at
        RETURNING search_id
    """, (tab_id, requires_tab_id, search_id, fingerprint, Jsonb(hits), truncated, idle_minutes, session_id, user_id)).fetchone()
    if stored is None:
        raise _expired_global_search()
    return search_id


def _read_global_search(connection, session_id, user_id, tab_id, search_id, fingerprint, supplied_tab_id, idle_minutes):
    saved = connection.execute("""
        UPDATE global_search_results AS saved
        SET expires_at = clock_timestamp() + LEAST(%s::double precision * 60,
            extract(epoch FROM LEAST(login.expires_at, login.absolute_expires_at) - clock_timestamp())) * interval '1 second'
        FROM login_sessions AS login
        WHERE saved.session_id = login.id AND saved.session_id = %s AND saved.user_id = %s
          AND login.user_id = saved.user_id AND login.revoked_at IS NULL
          AND LEAST(login.expires_at, login.absolute_expires_at, saved.expires_at) > clock_timestamp()
          AND saved.tab_id = %s AND saved.search_id = %s AND saved.fingerprint = %s
          AND (NOT saved.requires_tab_id OR %s)
        RETURNING saved.hits, saved.truncated
    """, (idle_minutes, session_id, user_id, tab_id, search_id, fingerprint, supplied_tab_id)).fetchone()
    if saved is None:
        raise _expired_global_search()
    return saved["hits"], saved["truncated"]


def _global_search_page(connection, branches, hits, position, limit):
    page = []
    batch_size = limit + 1
    while position < len(hits):
        batch = hits[position:position + batch_size]
        visible = {}
        for kind, (resource, expression) in branches.items():
            ids = [hit["id"] for hit in batch if hit["type"] == kind]
            if ids:
                visible.update({
                    (kind, row["id"]): row
                    for row in _global_current_rows(connection, resource, expression, ids)
                })
        for hit in batch:
            row = visible.get((hit["type"], hit["id"]))
            if row is not None:
                if len(page) == limit:
                    return page, position
                page.append((hit["type"], row))
            position += 1
        # When access changes have opened gaps, avoid checking one skipped row per query.
        batch_size = max(batch_size, 50)
    return page, None


def _global_search_item(kind, row, detail):
    if kind == "record":
        return {"type": kind, "record": {
            "id": row["id"], "record_number": row["record_number"], "title": row["title"],
            "security_level_id": row["security_level_id"], "description": row["description"],
            "aggregation_id": row["aggregation_id"], "aggregation_number": detail["aggregation_number"],
            "date_originated": row["date_originated"], "is_vital": row["is_vital"],
            "on_effective_hold": row["on_effective_hold"],
        }, "matched_record_metadata": detail["metadata_matched"],
            "matching_components": detail["matching_components"], "score": row["score"],
            "record_capabilities": {key: detail[key] for key in ("list_components", "has_previewable_component")}}
    return {"type": kind, "aggregation": {
        "id": row["id"], "aggregation_number": row["aggregation_number"], "title": row["title"],
        "date_opened": row["date_opened"], "security_level_id": row["security_level_id"],
        "description": row["description"], "is_vital": row["is_vital"], "on_effective_hold": row["on_effective_hold"],
    }, "snippet": detail["snippet"], "score": row["score"]}


def global_search_rows(
    connection: Connection, request: GlobalSearchRequest, *, session_id: int | None = None, user_id: int | None = None,
) -> dict[str, Any]:
    settings = settings_cache.for_connection(connection)
    if not settings["FULL_TEXT_SEARCH_ENABLED"]:
        raise HTTPException(status_code=503, detail={
            "code": "full_text_search_disabled",
            "message": "Full-text search is temporarily disabled.",
        })
    if session_id is None or user_id is None:
        raise HTTPException(status_code=401, detail="authentication required")
    if _condition_count(request.record_where) + _condition_count(request.aggregation_where) > MAX_SEARCH_CONDITIONS:
        raise _invalid(f"global search may contain at most {MAX_SEARCH_CONDITIONS} combined conditions")
    branches = {
        kind: (resource, expression)
        for kind, resource, expression in (
            ("record", "records", request.record_where),
            ("aggregation", "aggregations", request.aggregation_where),
        )
        if expression is not None
    }
    received = request.model_dump(mode="json", by_alias=True, exclude_unset=True, exclude_none=True)
    canonical = {
        f"{kind}_where": _canonical_request(resource, SearchRequest(where=expression))["where"]
        for kind, (resource, expression) in branches.items()
    }
    canonical.update(result_types=sorted(request.result_types), limit=request.limit)
    result_cap = settings["SEARCH_RESULT_LIMIT"]
    idle_minutes = settings["GLOBAL_SEARCH_CACHE_IDLE_MINUTES"]
    fingerprint = hashlib.sha256(json.dumps(
        [canonical, result_cap, idle_minutes,
         settings.versions["SEARCH_RESULT_LIMIT"], settings.versions["GLOBAL_SEARCH_CACHE_IDLE_MINUTES"]],
        ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode()).hexdigest()
    tab_id = request.tab_id
    search_id = request.search_id
    result_filter = request.result_filter
    position = 0
    page_number = request.page or 1
    if request.cursor:
        token_search, token_tab, position, token_filter = _cursor_decode(request.cursor)
        if (tab_id is not None and tab_id != token_tab) or (search_id is not None and search_id != token_search):
            raise _expired_global_search()
        if result_filter is not None and result_filter != token_filter:
            raise _expired_global_search()
        search_id, tab_id, result_filter = token_search, token_tab, token_filter
    initial = search_id is None
    supplied_tab_id = request.tab_id is not None
    if initial:
        tab_id = tab_id or uuid4()
        hits, page, truncated = _rank_global_search(
            connection, branches, result_cap, result_filter, request.limit, page_number,
        )
        search_id = _save_global_search(
            connection, hits, truncated, session_id, user_id, tab_id, fingerprint, supplied_tab_id, idle_minutes,
        )
    else:
        hits, truncated = _read_global_search(
            connection, session_id, user_id, tab_id, search_id, fingerprint, supplied_tab_id, idle_minutes,
        )
    totals = None
    if initial and request.include_totals:
        totals = {resource: sum(hit["type"] == kind for hit in hits) for kind, (resource, _) in branches.items()}
    filtered = [hit for hit in hits if result_filter is None or hit["type"] == result_filter]
    if request.page is not None:
        position = _global_page_offset(len(filtered), page_number, request.limit)
        page_number = position // request.limit + 1
    if initial:
        end = position + len(page)
        next_position = end if len(filtered) > end else None
    else:
        page, next_position = _global_search_page(connection, branches, filtered, position, request.limit)
    details = page_details(connection, page, {
        kind: _full_text_leaves(expression) for kind, (_, expression) in branches.items()
    }) if page else {}
    items = [_global_search_item(kind, row, details[kind, row["id"]]) for kind, row in page]
    next_cursor = _cursor_encode({
        "search_id": str(search_id), "tab_id": str(tab_id), "position": next_position, "filter": result_filter,
    }) if next_position is not None else None
    pending=connection.execute(
        """SELECT EXISTS(SELECT 1 FROM digital_component_search_documents document
             JOIN digital_components component ON component.id=document.digital_component_id
            WHERE document.status IN ('pending','processing','stale')
              AND current_user_can_view_record(document.record_id)
                       AND EXISTS(SELECT 1 FROM records pending_record WHERE pending_record.id=document.record_id AND (pending_record.disposition_status NOT IN (10,11,12) OR disposition_private.can_manage()))
              AND current_user_can_record_component_operation(document.record_id,'record.component.view','record.component.view')) AS value"""
    ).fetchone()["value"]
    result={"items":items,"next_cursor":next_cursor,"search_id":str(search_id),"truncated":truncated,"result_cap":result_cap,
            "index_freshness":{"has_pending_content":pending}}
    if request.page is not None:
        result["page"] = page_number
    if totals is not None:
        result["totals"] = totals
    if request.debug:
        result["_debug"]=_debug(connection,"/api/v1/full-text-search",received,{**canonical, "include_totals": totals is not None})
    return result
