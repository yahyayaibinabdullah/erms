"""Resolve explicit type references together before compiling a structured search."""

from dataclasses import dataclass, field
import re

from fastapi import HTTPException
from psycopg import sql

from .dashboard_visibility import AUTHORITY_CTES

MAX_SEARCH_DEPTH = 5
MAX_SEARCH_CONDITIONS = 50
MAX_IN_VALUES = 100

FIELD_PATH = re.compile(
    r"type\.([1-9][0-9]{0,18})\.field\.([1-9][0-9]{0,18})", re.ASCII
)
ID_MAX = 2**63 - 1
MEMBERSHIP = {"eq", "ne", "in", "not_in", "is_null", "is_not_null"}
RANGE = {"gt", "gte", "lt", "lte", "between"}
TEXT = {"contains_ci", "starts_with_ci", "ends_with_ci", "matches_ci"}
COLUMNS = {
    name: name + "_value"
    for name in ("text", "integer", "decimal", "boolean", "date", "datetime")
}
COLUMNS["single_choice"] = "choice_id"
FORBIDDEN = "saved_search_type_forbidden"
MISSING = "search_type_reference_unavailable"


def reference_error(reason):
    key = (
        "saved_search.error.type_forbidden"
        if reason == FORBIDDEN
        else "saved_search.error.reference_unavailable"
    )
    return HTTPException(
        403 if reason == FORBIDDEN else 422, detail={"code": reason, "message_key": key}
    )


def invalid(message):
    return HTTPException(422, detail=message)


def stable_id(value):
    if type(value) is not int or not 0 < value <= ID_MAX:
        raise invalid("Type and choice references require a positive integer ID")
    return value


def field_path(name):
    match = FIELD_PATH.fullmatch(name)
    if match is None:
        raise invalid("Invalid type-specific field reference")
    return tuple(stable_id(int(v)) for v in match.groups())


@dataclass
class References:
    types: set = field(default_factory=set)
    fields: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)
    assignment: bool = False


def references(where, sorts):
    result = References()

    def leaf(name, op, value):
        if (name == "type_id" or (name and name.startswith("type."))) and op in {
            "in",
            "not_in",
        }:
            if not isinstance(value, list) or not 1 <= len(value) <= MAX_IN_VALUES:
                raise invalid(f"operator '{op}' requires 1 to {MAX_IN_VALUES} values")
        if name == "type_id":
            result.assignment = True
            if op not in MEMBERSHIP:
                raise invalid("Unsupported assigned-type operator")
            if op not in {"is_null", "is_not_null"}:
                values = (
                    value
                    if op in {"in", "not_in"} and isinstance(value, list)
                    else [value]
                )
                result.types.update(stable_id(v) for v in values)
        elif name and name.startswith("type."):
            owner, fid = field_path(name)
            result.fields[name] = owner, fid
            result.types.add(owner)
            if op and op not in {"is_null", "is_not_null"}:
                result.values.setdefault(name, []).extend(
                    value if isinstance(value, list) else [value]
                )

    # The same traversal handles the stored v1 JSON and a submitted request.
    nodes = [(where, 1)] if where is not None else []
    conditions = 0
    while nodes:
        node, depth = nodes.pop()
        if depth > MAX_SEARCH_DEPTH:
            raise invalid(
                f"search expressions may be nested at most {MAX_SEARCH_DEPTH} levels"
            )
        if isinstance(node, dict):
            name, op, value = node.get("field"), node.get("operator"), node.get("value")
            children = node.get("and") or node.get("or") or []
            negative = node.get("not")
        else:
            name, op, value = node.field, node.operator, node.value
            children = node.and_ or node.or_ or []
            negative = node.not_
        if negative is not None:
            nodes.append((negative, depth + 1))
        elif children:
            nodes.extend((child, depth + 1) for child in children)
        else:
            conditions += 1
            if conditions > MAX_SEARCH_CONDITIONS:
                raise invalid(
                    f"searches may contain at most {MAX_SEARCH_CONDITIONS} conditions"
                )
            leaf(name, op, value)
    for item in sorts:
        name = item["field"] if isinstance(item, dict) else item.field
        if name.startswith("type."):
            leaf(name, None, None)
        elif name == "type_id":
            raise invalid("Sort by a type-specific field or primary metadata")
    return result


def catalogue(connection, kind, refs):
    """One lookup for all requested types, fields and selected options in this kind."""
    types, fields, choices = set(), set(), set()
    for ref in refs:
        types.update(ref.types)
        fields.update(fid for _, fid in ref.fields.values())
        choices.update(
            v
            for vs in ref.values.values()
            for v in vs
            if type(v) is int and 0 < v <= ID_MAX
        )
    if not types:
        return {}
    rows = connection.execute(
        f"""WITH RECURSIVE {AUTHORITY_CTES}
        SELECT t.id,t.version, (EXISTS (SELECT FROM effective_roles WHERE is_information_governance)
           OR EXISTS (SELECT FROM accessible_types a WHERE a.kind=t.kind AND a.type_id=t.id)) AS allowed,
           f.id AS field_id,f.data_type,
           ARRAY(SELECT id FROM resource_field_choices c WHERE c.field_id=f.id AND c.id=ANY(%s::bigint[])) choices
        FROM resource_types t LEFT JOIN resource_type_fields f ON f.type_id=t.id AND f.kind=t.kind
           AND f.id=ANY(%s::bigint[]) WHERE t.kind=%s AND t.id=ANY(%s::bigint[])""",
        (list(choices), list(fields), kind, list(types)),
    ).fetchall()
    result = {}
    for row in rows:
        entry = result.setdefault(
            row["id"],
            {"allowed": row["allowed"], "version": row["version"], "fields": {}},
        )
        if row["field_id"] is not None:
            entry["fields"][row["field_id"]] = row
    return result


def restriction(ref, entries):
    if any(t in entries and not entries[t]["allowed"] for t in ref.types):
        return FORBIDDEN
    if not ref.types <= entries.keys():
        return MISSING
    for name, (owner, fid) in ref.fields.items():
        definition = entries[owner]["fields"].get(fid)
        if definition is None:
            return MISSING
        if definition["data_type"] == "single_choice" and any(
            stable_id(v) not in definition["choices"] for v in ref.values.get(name, [])
        ):
            return MISSING
    return None


def resolve(connection, resource, request):
    ref = references(request.where, request.sort)
    if not ref.types and not ref.assignment:
        return {}, ()
    if resource not in ("records", "aggregations"):
        raise invalid("Type references require a record or aggregation query")
    entries = catalogue(connection, resource[:-1], [ref])
    reason = restriction(ref, entries)
    if reason:
        raise reference_error(reason)
    fields = {
        name: entries[t]["fields"][f]["data_type"]
        for name, (t, f) in ref.fields.items()
    }
    if ref.assignment:
        fields["type_id"] = "integer"
    # A new choice order changes the ranked list even though its saved JSON is identical.
    versions = tuple(
        (item.field, entries[ref.fields[item.field][0]]["version"])
        for item in request.sort
        if fields.get(item.field) == "single_choice"
    )
    return fields, versions


def sort_sql(name, direction, *, natural=False):
    from .code_ordering import expression
    _, fid = field_path(name)
    term = expression(sql.SQL("{}.sort_value").format(sql.Identifier(f"type_sort_{fid}")), natural)
    return sql.SQL("{} {} NULLS LAST").format(
        term, sql.SQL(direction.upper())
    )


def sort_joins(resource, sorts, fields):
    joins = sql.SQL("")
    for name in sorts:
        if not name.startswith("type."):
            continue
        owner, fid = field_path(name)
        dtype = fields[name].type.value
        choice = dtype == "single_choice"
        term = sql.SQL("c.display_order") if choice else literal_column(dtype)
        choices = (
            sql.SQL(" JOIN resource_field_choices c ON c.id=v.choice_id")
            if choice
            else sql.SQL("")
        )
        joins += sql.SQL(
            " LEFT JOIN (SELECT v.resource_id, {} AS sort_value FROM {} v {} "
            "WHERE v.type_id={} AND v.field_id={}) {} ON {}.resource_id=resource.id"
        ).format(
            term,
            sql.Identifier(resource[:-1] + "_type_values"),
            choices,
            sql.Literal(owner),
            sql.Literal(fid),
            sql.Identifier(f"type_sort_{fid}"),
            sql.Identifier(f"type_sort_{fid}"),
        )
    return joins


def literal_column(dtype):
    return sql.SQL("(v.value).{}").format(sql.Identifier(COLUMNS[dtype]))
