"""Current attached-field ordering; no configuration cache or stored sort copy."""
from psycopg import sql

from .code_generation_store import PRIMARY_TEXT_FIELDS


def natural_fields(connection, resource, names):
    """Return requested field keys whose generator remains attached.

    Enabling affects allocation, not attachment. Renames, patterns, counter
    changes and type-population changes do not change a column's collation.
    """
    if resource not in {'records', 'aggregations'}:
        return frozenset()
    kind = resource[:-1]
    primary, typed = set(), {}
    for name in names:
        if name in PRIMARY_TEXT_FIELDS[kind]:
            primary.add(name)
        elif name.startswith('type.'):
            parts = name.split('.')
            if len(parts) == 4 and parts[2] == 'field' and parts[3].isascii() and parts[3].isdigit():
                typed[int(parts[3])] = name
    if not primary and not typed:
        return frozenset()
    rows = connection.execute("""SELECT DISTINCT primary_field,field_id FROM code_generators
        WHERE kind=%s AND (primary_field=ANY(%s) OR field_id=ANY(%s))""",
        (kind, sorted(primary), sorted(typed))).fetchall()
    return frozenset(row['primary_field'] or typed[row['field_id']] for row in rows)


def expression(term, natural):
    return sql.SQL('{} COLLATE erms_code_natural').format(term) if natural else term
