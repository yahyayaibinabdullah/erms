# Request email in Current Task — 2 November 2026

Approved requirement: destruction §11.4 / DEST-35, revision 1.16.
During External approval pending, show **Send by email** beside **Preview
request** and **Download request**, with the configured recipient and latest
attempt. Sending remains deliberate and leaves the external-decision task open.

## Implementation

`external.task_form` matches the saved request's ID and destruction-request type
against the server-authorized email document projection. It reuses
`email.send_button` and `email.latest_attempt`, including their shared per-form
document state, retry UUID, busy guard, visibility-aware refresh and pending
polling. Both tabs show the same attempt; full paginated history remains in
Evidence and documents. Unauthorized documents have no task send action;
preview/download and external-decision controls remain available as before.

No API, schema, privilege, setting, cache or initial summary request was added.
The existing contextual English/Arabic keys, tooltips and no-attempt state are
reused. No catalogue wording, keys or provenance changed; no Arabic drafts need
to be generated or seeded for this change.

## Verification

287 frontend checks passed across `test_disposition_email.py`,
`test_disposition_external.py`, `test_disposition_completion.py` and
`test_disposition_tasks.py`. Request-specific coverage verifies the shared
action row, current server-projected authority, recipient/no-attempt display,
both-tab retry identity, deliberate resends, summary freshness, hidden and
abandoned polling, and retention of the active task. All run in English and
Arabic using the actual NiceGUI components and a synthetic API. Initial test
failures were assertions counting the existing proposal-list read as an email
read; those assertions now distinguish the two endpoints.

Live browser verification used actual components and Wathiq CSS with synthetic
data/transport. At 1694px, all three actions share y=584 in both languages;
Arabic action order runs from the right. Narrow layouts wrap without clipping.
A simulated send progressed from Sending to Accepted by SMTP server while the
external-decision controls remained available; switching to documents showed
the same attempt. Preview tabs and the owned server were closed afterward.
No real email was sent and no database-backed test was run.

- [English desktop](request-task-email/english.png)
- [Arabic desktop](request-task-email/arabic.png)
- [English narrow after simulated sending](request-task-email/english-narrow.png)
- [Arabic narrow](request-task-email/arabic-narrow.png)

Catalogue reference/stale-key checks and the approved Arabic terminology check
pass (928 contextual uses, 35 mappings). The maintained 3,974-key artifacts
retain exact ordering, coverage and source hash. The existing unrelated ledger
baseline findings remain outside this change; §11.4/DEST-35 implementation and
verification are recorded against the updated specification.
