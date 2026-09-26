from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import re
import base64
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from psycopg import Connection, sql
from pydantic import TypeAdapter, ValidationError

from .schemas import GlobalSearchRequest, SearchExpression, SearchRequest
from .crud import redact_hidden_relationships
from .config import boolean_environment


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


def _compile_expression(
    expression: SearchExpression,
    fields: dict[str, SearchField],
    *,
    resource: str,
    depth: int,
    condition_counter: list[int],
    component_alias: str | None = None,
    component_absent: bool = False,
) -> tuple[sql.Composable, list[Any]]:
    if depth > MAX_SEARCH_DEPTH:
        raise _invalid(f"search expressions may be nested at most {MAX_SEARCH_DEPTH} levels")

    if expression.field is not None:
        condition_counter[0] += 1
        if condition_counter[0] > MAX_SEARCH_CONDITIONS:
            raise _invalid(f"searches may contain at most {MAX_SEARCH_CONDITIONS} conditions")
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
                    "AND current_user_can_record_component_operation("
                    "search_component.record_id,'record.component.view','record.component.view') "
                    "AND ({}))"
                ).format(comparison), parameters
            return _compile_comparison(
                expression,
                {expression.field: component_field[0]},
                table_alias=component_alias,
                column_name=component_field[1],
            )
        return _compile_comparison(expression, fields)

    if expression.full_text is not None:
        condition_counter[0] += 1
        if condition_counter[0] > MAX_SEARCH_CONDITIONS:
            raise _invalid(f"searches may contain at most {MAX_SEARCH_CONDITIONS} conditions")
        query = expression.full_text.query
        if len(re.findall(r"\S+", query)) > MAX_FULL_TEXT_TOKENS:
            raise _invalid(f"full-text queries may contain at most {MAX_FULL_TEXT_TOKENS} tokens")
        allowed = FULL_TEXT_SOURCES.get(resource)
        if allowed is None:
            raise _invalid(f"full_text is not supported for {resource}")
        sources = expression.full_text.sources or list(allowed)
        if len(sources) != len(set(sources)) or any(source not in allowed for source in sources):
            raise _invalid(f"invalid full-text sources for {resource}")
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
                    "AND current_user_can_record_component_operation(ftc.record_id,'record.component.view','record.component.view') "
                    "AND (to_tsvector('pg_catalog.simple',coalesce(ftc.file_name,''))@@websearch_to_tsquery('pg_catalog.simple',%s) "
                    "OR ftk.search_vector@@websearch_to_tsquery(ftk.text_search_config,%s)))"
                )); parameters.extend((query, query))
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
            component_absent=component_absent,
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
            component_absent=component_absent,
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
            "AND current_user_can_record_component_operation("
            "search_component.record_id,'record.component.view','record.component.view') "
            "AND ({}))"
        ).format(combined)
        # Preserve ordinary Boolean meaning when a mixed alternative can be
        # satisfied entirely by record predicates and the record has no
        # authorized components. Component leaves evaluate false in that
        # branch; otherwise one authorized component must satisfy the whole
        # enclosing All scope.
        without_component, without_parameters = _compile_expression(
            expression, fields, resource=resource, depth=depth,
            condition_counter=[0], component_absent=True,
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
                    """SELECT component.id,component.file_name FROM digital_components component
                        WHERE component.record_id=%s AND component.content_status='available'
                          AND current_user_can_record_component_operation(component.record_id,'record.component.view','record.component.view')
                          AND to_tsvector('pg_catalog.simple',coalesce(component.file_name,''))
                              @@websearch_to_tsquery('pg_catalog.simple',%s)
                        ORDER BY component.id LIMIT 4""",(item["id"],leaf.query),
                ).fetchall()
                for row in file_rows:
                    if row["id"] not in components and len(components)<3:
                        components[row["id"]]={"id":row["id"],"file_name":row["file_name"],
                                               "snippet":None,"leaf_ids":[leaf_id],
                                               "match_count_is_capped":len(file_rows)>3}
            rows = connection.execute(
                """SELECT component.id,component.file_name,
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
                                              "snippet":row["snippet"],"leaf_ids":[leaf_id],
                                              "match_count_is_capped":len(rows)>=12}
                elif row["id"] in components and leaf_id not in components[row["id"]]["leaf_ids"]:
                    components[row["id"]]["leaf_ids"].append(leaf_id)
                if row["id"] in components and not components[row["id"]].get("snippet"):
                    components[row["id"]]["snippet"]=row["snippet"]
    return {"relevance": score, "metadata_matched": bool(metadata_matched),
            "matching_components": list(components.values())}


def _relevance_expression(resource: str, leaves: list[tuple[str, Any]]) -> tuple[sql.Composable,list[Any]]:
    terms: list[sql.Composable]=[]; parameters: list[Any]=[]
    for _, leaf in leaves:
        sources=leaf.sources or list(FULL_TEXT_SOURCES[resource])
        if resource=="records" and "metadata" in sources:
            terms.append(sql.SQL("coalesce((SELECT ts_rank_cd(d.search_vector,websearch_to_tsquery(d.text_search_config,%s)) FROM authorized_record_search_documents d WHERE d.record_id=resource.id),0)")); parameters.append(leaf.query)
        if resource=="records" and "components" in sources:
            terms.append(sql.SQL("coalesce((SELECT max(ts_rank_cd(k.search_vector,websearch_to_tsquery(k.text_search_config,%s))) FROM digital_component_search_documents s JOIN digital_component_search_chunks k ON k.digital_component_id=s.digital_component_id WHERE s.record_id=resource.id AND s.status IN ('indexed','processing') AND s.indexed_at IS NOT NULL),0)")); parameters.append(leaf.query)
        if resource=="aggregations":
            terms.append(sql.SQL("coalesce((SELECT ts_rank_cd(d.search_vector,websearch_to_tsquery(d.text_search_config,%s)) FROM authorized_aggregation_search_documents d WHERE d.aggregation_id=resource.id),0)")); parameters.append(leaf.query)
        if resource=="digital_components" and "content" in sources:
            terms.append(sql.SQL("coalesce((SELECT max(ts_rank_cd(k.search_vector,websearch_to_tsquery(k.text_search_config,%s))) FROM digital_component_search_chunks k WHERE k.digital_component_id=resource.id),0)")); parameters.append(leaf.query)
        if resource=="digital_components" and "metadata" in sources:
            terms.append(sql.SQL("ts_rank_cd(to_tsvector('pg_catalog.simple',coalesce(resource.file_name,'')),websearch_to_tsquery('pg_catalog.simple',%s))")); parameters.append(leaf.query)
    return (sql.SQL(" + ").join(terms) if terms else sql.SQL("0.0")),parameters


def search_rows(
    connection: Connection,
    table: str,
    request: SearchRequest,
    *, endpoint: str | None = None,
) -> dict[str, Any]:
    if _full_text_leaves(request.where) and not boolean_environment("FULL_TEXT_SEARCH_ENABLED", True):
        raise HTTPException(status_code=503, detail={
            "code": "full_text_search_disabled",
            "message": "Full-text search is temporarily disabled.",
        })
    fields = SEARCH_FIELDS[table]
    visibility = {
        "aggregations": sql.SQL("current_user_can_view_aggregation(resource.id)"),
        "records": sql.SQL("current_user_can_view_record(resource.id)"),
        "digital_components": sql.SQL(
            "EXISTS (SELECT 1 FROM records visible_record WHERE visible_record.id=resource.record_id "
            "AND current_user_can_list_record_components(visible_record.id))"
        ),
        "roles": sql.SQL("NOT is_system"),
    }.get(table)
    clauses: list[sql.Composable] = []
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
    if visibility is not None:
        clauses.append(visibility)
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
        sort_fields.extend([("_relevance", "desc"), ("id", "asc")] if positive_leaves else [("id", "asc")])
    elif "id" not in {field for field, _ in sort_fields}:
        sort_fields.append(("id", "asc"))

    table_identifier = sql.Identifier({
        "event_history": "authorized_event_history",
        "aggregations": "authorized_aggregations_for_search",
        "records": "authorized_records_for_search",
    }.get(table, table))
    count_query = sql.SQL("SELECT count(*) AS total FROM {} resource{}").format(
        table_identifier, where_clause
    )
    total = connection.execute(count_query, parameters).fetchone()["total"]

    relevance,relevance_parameters=_relevance_expression(table,positive_leaves)
    order_clause = sql.SQL(", ").join(
        sql.SQL("{} {}").format(relevance if field == "_relevance" else sql.SQL("resource.{}").format(sql.Identifier(field)), sql.SQL(direction.upper()))
        for field, direction in sort_fields
    )
    result_query = sql.SQL("SELECT resource.*,({})::double precision AS _fts_relevance FROM {} resource{} ORDER BY {} LIMIT %s OFFSET %s").format(
        relevance,
        table_identifier,
        where_clause,
        order_clause,
    )
    items = list(
        connection.execute(
            result_query, [
                *relevance_parameters,
                *parameters,
                *(relevance_parameters if any(field == "_relevance" for field, _ in sort_fields) else []),
                request.limit,
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
    if all_leaves:
        if table == "records":
            pending = connection.execute(
                """SELECT EXISTS(SELECT 1 FROM digital_component_search_documents document
                     WHERE document.status IN ('pending','processing','stale')
                       AND current_user_can_view_record(document.record_id)
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


def _cursor_decode(value: str) -> dict[str, Any]:
    try:
        raw=base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        decoded=json.loads(raw)
        if set(decoded)!={"fingerprint","score","type","id"}:
            raise ValueError
        return decoded
    except (ValueError,TypeError,json.JSONDecodeError) as exception:
        raise _invalid("invalid global-search cursor") from exception


def _global_branch(
    connection: Connection,resource: str,expression: SearchExpression,
    limit: int,after: dict[str,Any] | None,
) -> list[dict[str,Any]]:
    leaves=_full_text_leaves(expression)
    if not leaves:
        raise _invalid("global-search branches require a positive full_text expression")
    _validate_indexable(connection,leaves)
    clause,clause_parameters=_compile_expression(
        expression,SEARCH_FIELDS[resource],resource=resource,depth=1,condition_counter=[0],
    )
    relevance,relevance_parameters=_relevance_expression(resource,leaves)
    table=sql.Identifier("authorized_records_for_search" if resource=="records" else "authorized_aggregations_for_search")
    visibility=sql.SQL("current_user_can_view_record(resource.id)") if resource=="records" else sql.SQL("current_user_can_view_aggregation(resource.id)")
    outer=sql.SQL("")
    outer_parameters: list[Any]=[]
    branch_type="record" if resource=="records" else "aggregation"
    if after:
        # Global order is score DESC, type ASC, id ASC. Apply its exact
        # continuation tuple independently to each authorized SQL branch.
        if branch_type>after["type"]:
            outer=sql.SQL("WHERE score<=%s") ; outer_parameters=[after["score"]]
        elif branch_type<after["type"]:
            outer=sql.SQL("WHERE score<%s") ; outer_parameters=[after["score"]]
        else:
            outer=sql.SQL("WHERE score<%s OR (score=%s AND id>%s)")
            outer_parameters=[after["score"],after["score"],after["id"]]
    query=sql.SQL(
        "WITH matched AS (SELECT resource.*,({})::double precision AS score FROM {} resource "
        "WHERE ({}) AND ({})) SELECT * FROM matched {} ORDER BY score DESC,id ASC LIMIT %s"
    ).format(relevance,table,visibility,clause,outer)
    return list(connection.execute(
        query,[*relevance_parameters,*clause_parameters,*outer_parameters,limit+1],
    ).fetchall())


def global_search_rows(connection: Connection, request: GlobalSearchRequest) -> dict[str, Any]:
    if not boolean_environment("FULL_TEXT_SEARCH_ENABLED", True):
        raise HTTPException(status_code=503, detail={
            "code": "full_text_search_disabled",
            "message": "Full-text search is temporarily disabled.",
        })
    if _condition_count(request.record_where)+_condition_count(request.aggregation_where)>MAX_SEARCH_CONDITIONS:
        raise _invalid(f"global search may contain at most {MAX_SEARCH_CONDITIONS} combined conditions")
    received=request.model_dump(mode="json",by_alias=True,exclude_unset=True,exclude_none=True)
    canonical=request.model_dump(mode="json",by_alias=True,exclude_none=True)
    canonical.pop("cursor",None); canonical.pop("debug",None)
    canonical["result_types"]=sorted(canonical["result_types"])
    if request.record_where is not None:
        canonical["record_where"]=_canonical_request("records",SearchRequest(where=request.record_where))["where"]
    if request.aggregation_where is not None:
        canonical["aggregation_where"]=_canonical_request("aggregations",SearchRequest(where=request.aggregation_where))["where"]
    fingerprint="sha256:"+hashlib.sha256(json.dumps(canonical,ensure_ascii=False,separators=(",",":"),sort_keys=True).encode()).hexdigest()
    after=_cursor_decode(request.cursor) if request.cursor else None
    if after and after["fingerprint"]!=fingerprint:
        raise _invalid("global-search cursor does not belong to this query")
    merged=[]
    if request.record_where is not None:
        branch=_global_branch(connection,"records",request.record_where,request.limit,after)
        leaves=_full_text_leaves(request.record_where)
        for record in branch:
            score=record.pop("score")
            search=_attribution(connection,"records",record,leaves,score)
            aggregation=connection.execute(
                """SELECT aggregation_number FROM aggregations
                    WHERE id=%s AND current_user_can_view_aggregation(id)""",(record.get("aggregation_id"),),
            ).fetchone()
            merged.append({"type":"record","record":{
                "id":record["id"],"record_number":record["record_number"],"title":record["title"],
                "aggregation_id":record.get("aggregation_id"),
                "aggregation_number":aggregation["aggregation_number"] if aggregation else None,
                "date_originated":record.get("date_originated"),
                "is_vital":record.get("is_vital",False),
                "on_effective_hold":record.get("on_effective_hold",False),
            },"matched_record_metadata":search["metadata_matched"],
                "matching_components":search["matching_components"],"score":search["relevance"],
                "_id":record["id"]})
    if request.aggregation_where is not None:
        branch=_global_branch(connection,"aggregations",request.aggregation_where,request.limit,after)
        leaves=_full_text_leaves(request.aggregation_where)
        for aggregation in branch:
            score=aggregation.pop("score")
            search=_attribution(connection,"aggregations",aggregation,leaves,score)
            leaf=_full_text_leaves(request.aggregation_where)[0][1]
            snippet=connection.execute(
                """SELECT ts_headline('pg_catalog.simple',concat_ws(' ',aggregation_number,title,description),
                           websearch_to_tsquery('pg_catalog.simple',%s),
                           'StartSel=⟦,StopSel=⟧,MaxWords=35,MinWords=12,MaxFragments=1') AS value
                     FROM aggregations WHERE id=%s AND current_user_can_view_aggregation(id)""",
                (leaf.query,aggregation["id"]),
            ).fetchone()["value"]
            merged.append({"type":"aggregation","aggregation":{
                "id":aggregation["id"],"aggregation_number":aggregation["aggregation_number"],
                "title":aggregation["title"],"date_opened":aggregation.get("date_opened"),
                "is_vital":aggregation.get("is_vital",False),
                "on_effective_hold":aggregation.get("on_effective_hold",False),
            },"snippet":snippet,"score":search["relevance"],
                "_id":aggregation["id"]})
    merged.sort(key=lambda item:(-item["score"],item["type"],item["_id"]))
    if after:
        key=(-float(after["score"]),after["type"],int(after["id"]))
        merged=[item for item in merged if (-item["score"],item["type"],item["_id"])>key]
    page=merged[:request.limit]
    more=len(merged)>request.limit
    next_cursor=None
    if more and page:
        last=page[-1]
        next_cursor=_cursor_encode({"fingerprint":fingerprint,"score":last["score"],
                                    "type":last["type"],"id":last["_id"]})
    for item in page: item.pop("_id",None)
    pending=connection.execute(
        """SELECT EXISTS(SELECT 1 FROM digital_component_search_documents document
             JOIN digital_components component ON component.id=document.digital_component_id
            WHERE document.status IN ('pending','processing','stale')
              AND current_user_can_view_record(document.record_id)
              AND current_user_can_record_component_operation(document.record_id,'record.component.view','record.component.view')) AS value"""
    ).fetchone()["value"]
    result={"items":page,"next_cursor":next_cursor,
            "index_freshness":{"has_pending_content":pending}}
    if request.debug:
        result["_debug"]=_debug(connection,"/api/v1/full-text-search",received,canonical)
    return result
