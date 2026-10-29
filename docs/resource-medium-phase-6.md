# Resource medium, vital status, review and location — Phase 6

Phase 6 hardens the approved implementation for operations and production-like
data volumes. It does not add a review workflow, notifications, warehouse
management, or non-empty medium conversion at that phase. The later approved
[compatible medium-change amendment](resource-medium-compatible-changes.md)
now permits compatible changes without cascading conversion.

## Database and migration assurance

Fresh databases are created from `database/schema.sql` alone. The local
development database was rebuilt from that canonical schema and its data was
restored separately with triggers disabled during loading. Historical migration
files were retired after validation because there are no other development or
production databases requiring an upgrade path. Seed import is tested twice to
verify compatibility and idempotency. Backup and restore are exercised after
the API suite.

PostgreSQL remains the final authority for future-only review dates, governed
location changes, medium hierarchy, physical-record component restrictions,
and vital deletion protection. Focused tests attempt review-date, location and
deletion mutations through direct SQL so application-layer authorization cannot
mask a missing database invariant.

## Performance

The canonical schema includes partial indexes for scheduled-review queries:

- `(date_of_next_review, id)` on aggregations and records;
- `(owning_org_unit_id, date_of_next_review, id)` on aggregations and records.

Only rows with a non-null review date occupy these indexes. They support the
dashboard's due-date ordering and organizational-unit restriction without
penalizing holdings that have no scheduled review.

Dashboard clients continue to use the single `GET /api/v1/dashboard/summary`
request. Complete counts are returned separately from bounded previews; clients
must not issue one request per card or infer totals from preview length.

## Operational policy

Administrators should grant `aggregation.location.change`,
`aggregation.vital_status.change`, `record.vital_status.change`,
`aggregation.review_date.change`, and `record.review_date.change` only to
profiles responsible for governed custody decisions. Each action still needs
the corresponding effective ACL permission unless the established
information-governance bypass applies. Reasons are mandatory and retained in
immutable history.

Next-review dates are not ordinary editable metadata after creation. Both open
and closed resources use the dedicated review-date command, which requires its
matching privilege and ACL permission (subject to the established governance
bypass), a non-blank reason, and a null or strictly future value. The command
records `REVIEW_DATE_CHANGED`; it schedules review and does not claim that a
review was completed.

`REVIEW_WARNING_WINDOW_DAYS` and `DASHBOARD_REVIEW_PREVIEW_LIMIT` should be
chosen together: widening the window increases total matches, while the preview
limit controls response and rendering cost. Counts remain complete regardless
of the preview limit.

## Accessibility and client behavior

Interfaces identify assigned location, current location and next review using
text labels rather than color alone. Overdue/upcoming cards provide headings,
numeric totals and dated entries. API validation messages remain authoritative;
clients should present their accessible `message` text and must not rely on
disabled controls for enforcement.

Review reminders provide a **View all** route backed by
`GET /api/v1/dashboard/reviews?state=overdue|upcoming`; clients should use this
endpoint rather than reconstructing the dashboard's organizational-unit scope.
Resource lists, browse details and full details identify scheduled dates as
**Overdue** or **Upcoming**.

Location reads expose the effective assigned/current value and the visible
aggregation from which each value is inherited. Record details describe these
as inherited aggregation locations; records do not have independent location
fields. Before changing an aggregation location, clients call the location
preview command and show affected descendant aggregations and records.

Governed vital-status, review-date and location commands emit their named
domain event only. The generic row-level `UPDATE` history event is suppressed
for that same mutation so event history does not report the action twice.
