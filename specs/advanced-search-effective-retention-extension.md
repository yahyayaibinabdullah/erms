# Advanced Search — Effective Retention Filters Extension

**Status:** Approved  
**Prepared:** 28 October 2026  
**Approved:** 28 October 2026  
**Extends:** [Advanced Search and Saved Searches](advanced-search.md)

Implement and verify this extension in one phase, including Arabic translations
and acceptance evidence for AS-ER-01 through AS-ER-05.

## 1. Scope and query contract

Add three structured filters to the **Aggregations** target using the existing
comparison-leaf grammar and `POST /api/v1/aggregations/search` endpoint:

| Public field | Builder label | Type and permitted operators |
| --- | --- | --- |
| `effective_retention.current_period_years` | Effective current period (years) | Nonnegative integer; `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `between`, `in`, `not_in` |
| `effective_retention.intermediate_period_years` | Effective intermediate period (years) | Nonnegative integer; same operators |
| `effective_retention.final_disposition` | Effective disposition action | Controlled value; `eq`, `ne`, `in`, `not_in` |

Disposition values remain `destruction`, `transfer_to_external_archive`,
`selective_preservation`, and `retain_as_local_archives`, displayed using the
existing localized action labels. Reject invalid values and incompatible
operators on the server as well as in client guidance.

These filters combine with existing structured and full-text conditions through
`and`, `or`, and `not`, within the existing depth, leaf-count, and set-size
limits. They are aggregation-only, filter-only fields: reject them for Records
and as sort keys. Result rows remain aggregations.

Example: current period equals 2 years **AND** intermediate period is at least
5 years **AND** disposition action is destruction.

## 2. Effective-rule semantics

Use the existing `aggregation_effective_retention_rule` resolver. For each
aggregation, find its governing root; use that root's local retention override
when present, otherwise its nearest direct or inherited classification rule.
Child aggregations therefore match using their governing root's effective rule.
All three predicates refer to the same resolved rule.

Periods mean configured whole-year durations, including zero, rather than
elapsed or remaining time. Filters apply to both open and closed aggregations
within existing search visibility rules; matching does not imply disposition
eligibility. A missing rule must never be interpreted as zero or as an action.

## 3. Implementation requirements

- Extend the existing search field catalogue, compiler, and validation. Apply
  retention predicates in PostgreSQL before counts and pagination, preserving
  current ACL, clearance, organizational, and resource-state authorization.
  Use bound values and controlled identifiers.
- Extend the Aggregations builder with numeric controls and a disposition
  dropdown supporting multiple selections for set operators. Provide English
  and Arabic catalogue entries and verify keyboard access and LTR/RTL layouts
  under the existing internationalization and WebUI performance contracts.
- Save, reopen, and execute these criteria through the existing schema-version-1
  definition. Re-execution resolves current rules and authorization, including
  changes to overrides, classification rules, and hierarchy; existing saved
  definitions retain their meaning.
- Check query plans and representative-volume performance, including total
  counts. Avoid per-result HTTP requests and fetching a complete hierarchy in
  the client. No new retention data model or full-text reindex is required;
  introduce database view/function/index migrations only where justified, with
  equivalent canonical-schema changes.

## 4. Acceptance and traceability

| ID | Minimum verification |
| --- | --- |
| AS-ER-01 | Direct and inherited classification rules, root overrides and their removal, child aggregations, and rule/hierarchy changes produce the same values as the existing effective-rule resolver. |
| AS-ER-02 | Verify all permitted operators, zero-year periods, invalid and fractional/negative values, action validation, Boolean/full-text combinations, existing complexity limits, and rejection for Records and sorting. |
| AS-ER-03 | Authorization, totals, deterministic pagination, existing result caps, and saved-search save/reopen/fresh execution remain correct. |
| AS-ER-04 | Live-browser English and Arabic/RTL checks cover the new controls, validation, repeated navigation, and freshness after retention changes; preserve curated translations and pass existing catalogue checks. |
| AS-ER-05 | Record representative query-plan/performance evidence and map these requirements to implementation and verification in the existing Advanced Search traceability document. |

Run database-backed verification only in newly created, uniquely named
disposable databases, initialized from the canonical schema or required upgrade
path and dropped after the run. Approval of this extension does not constitute
implementation or verification completion.
