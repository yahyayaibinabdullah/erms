# ERMS REST API search grammar

The advanced search API uses a controlled JSON grammar. It supports nested
boolean expressions without accepting raw SQL, database table names, or
unapproved column names from clients.

## Endpoints

```text
POST /api/v1/aggregations/search
POST /api/v1/records/search
POST /api/v1/digital-components/search
POST /api/v1/event-history/search
POST /api/v1/users/search
POST /api/v1/org-units/search
POST /api/v1/roles/search
POST /api/v1/user-role-assignments/search
POST /api/v1/full-text-search
```

The ordinary `GET` collection endpoints remain available for simple equality
filters. Use the search endpoints for boolean logic, ranges, sets, null tests,
or case-insensitive text matching.

## Request structure

```json
{
  "where": { "field": "title", "operator": "contains_ci", "value": "contract" },
  "sort": [
    { "field": "date_created", "direction": "desc" }
  ],
  "limit": 100,
  "offset": 0
}
```

All properties are optional. With no `where`, all rows match. The defaults are
`limit: 100`, `offset: 0`, and ascending order by `id`. The maximum page size is
500. If a custom sort does not contain `id`, ascending `id` is automatically
added as the final key so pagination is deterministic.

The response contains the matching page and pagination metadata:

```json
{
  "items": [],
  "total": 0,
  "limit": 100,
  "offset": 0,
  "returned": 0
}
```

`total` is the number of matches before pagination, while `returned` is the
number of items in this response.

## Comparison expressions

A comparison has a field, operator, and—except for null operators—a value:

```json
{ "field": "size_in_bytes", "operator": "gte", "value": 1048576 }
```

Supported operators:

| Operator | Meaning | Value |
| --- | --- | --- |
| `eq` | Equal | One value |
| `ne` | Not equal | One value |
| `gt` | Greater than | One value |
| `gte` | Greater than or equal | One value |
| `lt` | Less than | One value |
| `lte` | Less than or equal | One value |
| `in` | Equal to any member | Array of 1–100 values |
| `not_in` | Equal to no member | Array of 1–100 values |
| `between` | Inclusive lower and upper bounds | Array containing exactly two values |
| `is_null` | Has no value | No `value` property |
| `is_not_null` | Has a value | No `value` property |
| `contains_ci` | Contains literal text, ignoring case | One string |
| `matches_ci` | Matches a case-insensitive controlled wildcard pattern (`*` = any characters, `?` = one character) | One string |
| `starts_with_ci` | Starts with literal text, ignoring case | One string |
| `ends_with_ci` | Ends with literal text, ignoring case | One string |

The three `*_ci` operators treat `%` and `_` as literal characters rather than
SQL wildcard characters. Null checks are accepted only for nullable fields.
Datetime values must be ISO 8601 timestamps with a timezone, such as
`2026-09-14T10:00:00Z`.

## Boolean expressions

### AND

Every child must match:

```json
{
  "and": [
    { "field": "aggregation_id", "operator": "eq", "value": 42 },
    { "field": "date_originated", "operator": "gte", "value": "2026-01-01T00:00:00Z" }
  ]
}
```

### OR

At least one child must match:

```json
{
  "or": [
    { "field": "title", "operator": "contains_ci", "value": "contract" },
    { "field": "description", "operator": "contains_ci", "value": "agreement" }
  ]
}
```

### NOT

The child must not match:

```json
{
  "not": {
    "field": "mime_type",
    "operator": "eq",
    "value": "application/pdf"
  }
}
```

Boolean expressions can be nested. Each expression object must contain exactly
one comparison, one `full_text` leaf, or one of `and`, `or`, and `not`. `and` and `or` arrays cannot be
empty.

## Full-text expressions

Records, aggregations, and digital components support a controlled full-text
leaf anywhere a comparison can appear:

```json
{"full_text":{"query":"\"approved budget\" expenditure -draft","sources":["metadata","components"]}}
```

The server uses parameterized `websearch_to_tsquery` with the stored explicit
text-search configuration. Clients cannot select a configuration, submit raw
`tsquery`, SQL, table names, weights, or dictionaries. Queries are limited to
500 characters and 50 whitespace-delimited tokens. A query that produces no
search nodes returns `422` with `non_indexable_full_text_query`.

| Resource | Allowed sources | Default |
| --- | --- | --- |
| Records | `metadata`, `components` | both |
| Aggregations | `metadata` | metadata |
| Digital components | `metadata`, `content` | both |

Unknown, duplicate, empty, and resource-incompatible source lists are rejected.
Other resource searches reject `full_text`.

`_relevance` is a virtual sort field available only with a positive full-text
leaf. A full-text search without an explicit sort defaults to relevance
descending and `id` ascending. The optional
`"include":["full_text_matches"]` adds a namespaced `_search` object containing
the query-local relevance value, metadata attribution, and up to three
authorized component matches with one bounded snippet each. Highlight spans
use the fixed `⟦` and `⟧` markers; they are data, not HTML. Negated leaves do
not create attribution or affect positive relevance.

## Global search

`POST /api/v1/full-text-search` accepts independent `record_where` and
`aggregation_where` branches. `result_types` must exactly match the supplied
branches; omitting a branch excludes that resource type rather than matching
every resource. The two branches share the 50-condition budget. Pages contain
at most 100 results and use the returned opaque `next_cursor`; a cursor is
rejected if reused with a different canonical query. The response also reports
whether authorized content is pending indexing.

## Privileged diagnostics

Every controlled search accepts top-level `"debug":true`. It requires
`search.query.debug`; otherwise the request fails with `403
insufficient_privilege`. Authorized responses include `_debug` with the exact
sanitized request body received, canonical API JSON after defaults and
normalization, request ID, endpoint, method, and a SHA-256 query fingerprint.
Diagnostics are absent by default and never contain SQL, plans, database
authorization predicates, headers, cookies, credentials, API/lease tokens, or
another user's query.

## Combined example

This query finds records from selected aggregations, originated during 2025,
whose title contains “contract” or whose description is null, while excluding
records with “draft” in the title:

```json
{
  "where": {
    "and": [
      {
        "field": "aggregation_id",
        "operator": "in",
        "value": [10, 20, 30]
      },
      {
        "field": "date_originated",
        "operator": "between",
        "value": [
          "2025-01-01T00:00:00Z",
          "2025-12-31T23:59:59Z"
        ]
      },
      {
        "or": [
          { "field": "title", "operator": "contains_ci", "value": "contract" },
          { "field": "description", "operator": "is_null" }
        ]
      },
      {
        "not": {
          "field": "title",
          "operator": "contains_ci",
          "value": "draft"
        }
      }
    ]
  },
  "sort": [
    { "field": "date_originated", "direction": "desc" },
    { "field": "record_number", "direction": "asc" }
  ],
  "limit": 50,
  "offset": 0
}
```

## Searchable fields

### Aggregations

`id`, `parent_aggregation_id`, `aggregation_number`, `title`, `description`,
`date_created`, `date_opened`, `date_closed`

Aggregation searches additionally accept these **filter-only** effective-rule
fields (also supported in schema-version-1 saved searches):

- `effective_retention.current_period_years`
- `effective_retention.intermediate_period_years`
- `effective_retention.final_disposition`

Periods accept nonnegative whole years with `eq`, `ne`, `gt`, `gte`, `lt`,
`lte`, `between`, `in`, and `not_in`. The action accepts `eq`, `ne`, `in`, and
`not_in` with `destruction`, `transfer_to_external_archive`,
`selective_preservation`, or `retain_as_local_archives`. These fields reject
null/text operators, Records targets, and sorting.

The governing root's local rule overrides its effective classification rule;
children use the same governing rule. Values are configured durations and
actions, resolved afresh before counts and pagination, for both open and closed
aggregations under existing visibility rules. See the
[approved extension](../specs/advanced-search-effective-retention-extension.md).

### Records

`id`, `aggregation_id`, `record_number`, `title`, `description`, `date_created`,
`date_originated`

### Digital components

`id`, `record_id`, `component_order`, `file_name`, `date_created`,
`date_originated`, `mime_type`, `size_in_bytes`, `checksum_algo`,
`checksum_value`

### Event history

`id`, `occurred_at`, `transaction_id`, `entity_type`, `entity_id`, `operation`,
`actor_user_id`, `actor_name`, `actor_email`, `actor_type`, `source`,
`request_id`, `correlation_id`, `reason`

### Users

`id`, `name`, `email`, `external_id`, `status`, `date_created`,
`date_deactivated`, `date_suspended`

### Organizational units

`id`, `parent_org_unit_id`, `code`, `name`, `description`, `status`,
`date_created`, `date_deactivated`

### Roles

`id`, `org_unit_id`, `supervisor_role_id`, `code`, `name`, `description`,
`status`, `date_created`, `date_deactivated`

### User-role assignments

`id`, `user_id`, `role_id`, `date_assigned`, `valid_from`,
`valid_until`

The same ordinary field allowlists apply to sorting; filter-only fields are
excluded. Case-insensitive text operators are
valid only for text fields. Null operators are valid only for nullable fields.

## Safety and complexity limits

- Values are always sent to PostgreSQL as parameters.
- Fields, tables, operators, and sort directions come from server-side allowlists.
- A query can contain at most 50 comparison or full-text conditions.
- Boolean expressions can be nested at most five levels.
- An `in` or `not_in` array can contain at most 100 values.
- A request can contain at most 10 sort fields.
- A response can contain at most 500 items.
- Invalid queries return HTTP `422 Unprocessable Entity`.
