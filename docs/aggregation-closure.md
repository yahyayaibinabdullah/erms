# Aggregation closure

## Purpose

Closing an aggregation freezes the records-management content in that branch of
the aggregation hierarchy. The freeze is an integrity rule, not merely a UI
convention: PostgreSQL enforces it for API calls, background work, and direct
SQL writes.

## Effective closure

An aggregation is **effectively closed** when its own `date_closed` is set or
when any ancestor has `date_closed` set. The nearest closed aggregation is the
closure source shown by the UI.

- Closing a root aggregation closes its complete descendant tree.
- Closing a child closes that child and its descendants only. Parents,
  siblings, and their other branches remain open.
- Closure is inherited dynamically; descendant rows do not receive copied
  closure dates.
- A child's own closure remains in effect if a closed ancestor is reopened.
- `date_closed` cannot be in the future and cannot precede `date_opened`.
- A directly closed aggregation may be reopened only by clearing its
  `date_closed`. An inherited closure cannot be cleared on the descendant; the
  closed ancestor must be reopened. Reopening a branch has no effect on a
  descendant that also has its own direct closure.
- Reopening requires a non-blank reason. API clients supply it in the
  `X-Change-Reason` header; the web UI collects it in the Reopen dialog.

## Closing vital or held aggregations

These rules apply to the ordinary **Close** action, independently of
disposition acceleration:

| Protection | Does it prevent closing? |
| --- | --- |
| Vital status on the aggregation or its descendants | No |
| Effective legal hold without **Preserve resource metadata and state** | No |
| Applicable effective hold with **Preserve resource metadata and state** | Yes |

The user still needs the normal close permission, a valid closing date and
compliance with the existing closure integrity rules. Closing preserves vital
status and every hold assignment. It does not remove their protections against
disposition or make the aggregation immediately eligible: ordinary retention
starts at closure and must complete, unless explicitly accelerated.

See [Legal Holds §5](../specs/legal-holds.md#5-enhanced-resource-state-preservation)
and [the accelerated eligibility scenario](operations.md#1421-accelerated-eligibility-with-protections).

## Operations prohibited in an effectively closed branch

The database rejects the following operations with a conflict error:

- creating a record in the branch;
- changing or deleting a record, including moving it into or out of the branch;
- adding, changing, reordering, replacing, or deleting a digital component;
- inserting, replacing, or deleting the component's stored binary content;
- creating a child aggregation under the branch;
- moving an aggregation into or out of the branch; and
- deleting an aggregation in the branch.
- changing any aggregation metadata in the branch, including its number,
  title, description, opening date, parent, or closure date.

Record-draft files remain temporary and may be assembled independently. A
draft cannot be committed into an effectively closed aggregation; the final
transaction is rejected without creating a partial record.

## Operations still permitted

Closure does not hide information. Users may read and search aggregations and
records, view or download digital components, and inspect event history. The
only mutation permitted is clearing a directly closed aggregation's
`date_closed` to reopen it; no other field may change in that operation.

The web UI marks direct and inherited closure, disables metadata editing,
provides a Reopen action only for directly closed aggregations, requires the
user to explain the change, removes the component uploader,
and disables component reorder/removal controls while leaving view, download,
and event-history actions available. New-record aggregation selection excludes
effectively closed destinations. Database enforcement remains authoritative in
case another client uses stale data.

The successful update produces the normal immutable `UPDATE` event for the
aggregation. Its `changed_fields` includes `date_closed`, and its `reason`
contains the supplied reopening reason. The API rejects a reopen without a
reason before changing the aggregation, so non-web clients cannot bypass this
audit requirement.

## Concurrency and integrity

Migration `006_enforce_closed_aggregations.sql` installs trigger functions on
aggregations, records, digital components, and PostgreSQL blob storage. Mutation
checks traverse the ancestor chain and lock it in stable identifier order so a
concurrent close/reparent operation cannot race a content change.
Migration `007_freeze_closed_aggregation_metadata.sql` extends that enforcement
to aggregation metadata while preserving the narrowly defined direct-reopen
operation.

## Future authorization exception

There is deliberately no administrator bypass today; system administrators are
subject to the same freeze. The authorization subsystem will later add an
explicit privilege-controlled exception. An override must require a reason and
must be recorded in the immutable event history. It must not be implemented as
a hidden client flag or by disabling the database triggers.
