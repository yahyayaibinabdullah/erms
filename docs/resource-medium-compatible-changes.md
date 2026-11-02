# Compatible aggregation medium changes

Approved 29 October 2026. This amendment replaces the original empty-only
restriction in [the resource-medium specification, section 8.1](../specs/resource-medium-vital-status-review-and-location.md#81-aggregation-medium-changes--approved-29-october-2026).

An authorized user can edit the medium of an open aggregation containing
records when the resulting hierarchy remains compatible. A reason is required.
The change records `MEDIUM_CHANGED`, including the actor, reason and old/new
values. Existing permissions, holds, closure rules and version checks apply.

| Contents and proposed change | Result |
| --- | --- |
| Physical records; Physical → Mixed | Allowed |
| Digital records; Digital → Mixed | Allowed |
| Only digital records; Mixed → Digital | Allowed |
| Only physical records; Mixed → Physical | Allowed |
| Any physical/mixed record; Mixed → Digital | Rejected |
| Any digital/mixed record; Mixed → Physical | Rejected |
| Physical records; Physical → Digital | Rejected |
| Digital records; Digital → Physical | Rejected |
| Empty root aggregation; any medium → any other medium | Allowed |
| Child aggregation whose medium would differ from its parent | Rejected |
| Incompatible record draft | Rejected |

Child aggregations must continue to match their parent. Mixed permits records
of any medium; Digital and Physical permit matching records only. Validation
covers the complete subtree and its drafts. Descendants, digital components
and drafts are never converted, deleted or discarded automatically.

The editor reports a specific localized error and marks Medium for medium
incompatibility. Missing reasons have their own message. Failed saves preserve
entered values; selecting another medium clears the field error. Internal SQL
and hidden resource identities are not shown.

## Implementation and upgrade

Existing PATCH contracts remain unchanged: `medium`, `If-Match`, and
`X-Change-Reason`. The replacement incompatibility code is
`aggregation_medium_contents_conflict`; existing parent, record and component
conflict codes retain their meaning. The obsolete empty-only rejection is no
longer emitted.

Apply `database/migrations/092_compatible_aggregation_medium_changes.sql` to
existing installations before restarting the API and WebUI. It replaces the
hierarchy trigger function and adds the shared compatibility predicate; it does
not rewrite resource data. It is safe to reapply. New installations use the
complete standalone `database/schema.sql`; version bookkeeping is separate in
`database/baseline.sql`.

API validation and the PostgreSQL trigger use the same predicate. Existing
parent row locks serialize record/draft/child writers against medium changes;
after waiting, validation observes the committed contents. There are no new
settings, privileges, endpoints, caches or extra frontend requests.

Synchronize the UI catalogue, then explicitly seed Arabic with
`database/seeds/004_seed_generated_arabic_ui_translations.py --missing-only`.
Five new `resource_medium.error.*` Arabic drafts require review before
publication. Existing curated translations must be retained.

## Requirement traceability

| Requirement | Implementation | Verification |
| --- | --- | --- |
| Compatible non-empty changes, no implicit conversion | `main.py::update_aggregation`; SQL `aggregation_medium_contents_compatible` | `test_compatible_medium_changes.py`: 3×3 record matrix, four pure-medium transitions, six empty-root transitions, digital contents/components unchanged, child/draft rejection |
| Preserve reason, actor and optimistic updates | Existing metadata authorization/update path and `MEDIUM_CHANGED` | Audit assertion; existing `test_api.py` medium/version/closed-resource regressions |
| Database authority and concurrent validation | `enforce_aggregation_medium_hierarchy`, parent row locks | Concurrent insert/change in both orders; migration idempotence/data preservation; canonical/migration parity |
| Clear bilingual errors and visible field feedback | `app.py::error_message`, `highlight_medium_error`, medium change listener; EN/AR catalogues | `test_medium_validation.py`; live editor verification |

See [verification evidence](verification/compatible-medium-changes.md).
