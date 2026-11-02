# Disposition history presentation — 29 October 2026

Approved scope: disposition revision 1.16, “Readable disposition history” and
review-round context; destruction revision 1.9, sections 5.2 and 6.

## Implementation and traceability

| Requirement | Implementation | Evidence |
| --- | --- | --- |
| One job-history row per recorded action, including resubmissions, decisions, membership changes, saves and other workflow commands | `history_actions.py` groups by recorded command identity within transaction/actor/source/request, chooses a recorded business outcome and pages actions on the server | `test_disposition_history_actions.py`: resubmission, separate commands, deterministic action pages and HTTP contracts |
| Preserve every original audit row and inspect resulting changes and carried proposals | The raw history API remains the default; `grouped=true` adds summaries; `/history/{event_id}/events` provides original events in bounded pages; `history.py` loads details only on expansion | Two carried proposals plus five submission row changes and routing are retained; a 123-event action stays one summary and details page in batches of 50 |
| Preserve authorization and redaction | The existing workspace gate and `authorized_event_history` supply every displayed fact; raw correlation selects action/page IDs server-side; restricted events retain their original redacted envelopes inside an action | Job, actor, source and request isolation; unavailable historical relationship produces a redacted proposal event; no protected endpoint, actor, reason or snapshot in summaries/details; authorization is refreshed after endpoint access changes |
| Explain distinct changes | Shared `event_label` uses event-time before/after facts for round submission/update, stage changes, task creation/completion and approved/returned review decisions; expanded tables identify affected proposal type and aggregation | Bilingual contextual-label and subject tests; existing global audit/completion dialog tests |
| Earlier comments available during subsequent review | `ReviewForm` reuses the existing bounded round-summary component, collapsed and without its eager return-notice fetch | Bilingual no-initial-history-request tests and live review-task verification |
| Correct navigation, freshness and layout | Existing Wathiq `PageTable`, native NiceGUI dialog/expansion and page-liveness guards; initial job/task identity is persisted before tab interaction | Repeated navigation and abandonment tests; English/Arabic screenshots; language reload retains selected task |

No cache, new privilege, workflow transition, schema migration or audit-data
rewrite is introduced. Ambiguous legacy events are not guessed into an action.
The global Audit Trail and proposal/note revision histories retain individual
events with the same contextual labels.

## Verification

- API history, query, progress and review regressions: **56 passed** in a new
  disposable PostgreSQL database; database dropped after the run.
- Frontend history, review, progress, task and navigation regressions:
  **270 passed**. The final initial-identity regression also passed in English
  and Arabic for both job and task views (**4 passed**).
- New action details remain collapsed on opening, load one server page on
  expansion, and ignore a response delivered after the dialog closes.
- Final focused history API regressions: **9 passed** after moving the
  existing authorization projection behind server pagination. Counts include
  restricted envelopes, as the existing raw event count does; no protected
  facts are used as displayed labels. Summary and detail pages each obtain
  their rows and total in one query; a now-empty later page alone needs a
  fallback count. No identity/language-shared history cache is added.
  Summary rows also omit full membership/proposal snapshots; contextual labels
  use a small scalar whitelist and complete facts load only in the original
  event detail page, including actions containing a single event.
- The isolated browser fixture has two review rounds, a rejection and two
  proposals carried to round 2. Only one row is shown per submission; the
  expanded second submission contains all eight original events.

Initial verification caught missing metadata on the new catalogue definitions
and a fixture that recreated a unique role. Both were corrected before the
passing runs, and both disposable databases were dropped. Language switching
also exposed an existing task-navigation identity omission: the initial view
now records its job/task IDs before any tab/filter interaction.

## Translation artifacts

Added ten English/Arabic keys: seven contextual audit-change labels and three
history-disclosure/affected-item labels. Both maintained catalogues have
**3,934 active keys**, sorted by complete message key. All **3,924 prior Arabic
items**, their wording and provenance are unchanged. No administrator export
was promoted. New Arabic values are generated drafts requiring human review.

Catalogue reference/stale-key, exact ordered coverage, blank, placeholder,
markup, new-entry provenance, artifact-hash and all approved terminology checks
passed. English wording uses “audit entry” to distinguish an audit row from a
governed record/document. No environment templates or settings changed.

## Live evidence

- [English action list](disposition-history-actions/history-ltr.png)
- [English action changes](disposition-history-actions/changes-ltr.png)
- [English earlier comments](disposition-history-actions/comments-ltr.png)
- [Arabic action list](disposition-history-actions/history-rtl.png)
- [Arabic action changes](disposition-history-actions/changes-rtl.png)
- [Arabic earlier comments](disposition-history-actions/comments-rtl.png)

The initial `full-width` dialog configuration overrode the intended card width
and filled almost the entire desktop viewport. Following the user's width
correction, the action dialog uses the established NiceGUI card `.style()`
sizing pattern: half the viewport width, a 640-pixel reading minimum where space
permits, and a viewport limit with 16-pixel side margins on narrow screens.
No Quasar override or global layout CSS was needed.

Live measurements confirmed 640 pixels at a 1,280-pixel viewport in English and
Arabic, and 960 pixels at a 1,920-pixel viewport. At 390 pixels the card is 358
pixels wide, retaining both side margins. The expanded Wathiq table stays within
the card without horizontal overflow; native vertical scrolling retains access
to all changes. All 36 focused bilingual history checks passed again. No text,
translation artifacts, data or API behavior changed for this sizing correction.
The managed stack was restarted to apply the correction to demo; API and WebUI
health returned HTTP 200. The additional disposable preview database was
dropped and its ports closed. See [width verification](disposition-history-actions/dialog-width-verification.json).

- [Compact English dialog](disposition-history-actions/dialog-width-ltr.png)
- [Compact Arabic dialog](disposition-history-actions/dialog-width-rtl.png)
- [Expanded English details](disposition-history-actions/dialog-expanded-width-ltr.png)
- [Expanded Arabic details](disposition-history-actions/dialog-expanded-width-rtl.png)
- [Small-screen details](disposition-history-actions/dialog-width-mobile.png)

Authored comments and affected-item cells retain native `dir=auto`; an English
comment in the RTL table was confirmed to compute LTR.

## Demo deployment and preservation

The managed local stack is running with the change. Its first restart stopped
at a transient MailDev `--help` preflight timeout; retrying the managed `up`
operation restored all services while retaining lifecycle ownership checks.
No unrelated service was stopped and no environment setting changed.

Read-only verification under `fym@sa.gov.ae`'s existing permissions confirms
rounds 1 and 2 are separate action entries. Round 2 expands to all **10 original
events**, including **4 carried proposals**. Jobs, memberships, tasks, rounds,
decisions, comments, proposals and the digest of all **150 disposition audit
entries** are unchanged. See [verification data](disposition-history-actions/demo.json).

All **3,977 older Arabic translation rows** are exactly unchanged. The ten new
keys already had untouched English source-copy drafts following catalogue
synchronization; the explicit `--missing-only` utility filled only those drafts
from the checked-in Arabic artifact. They remain generated, unreviewed and
unpublished. No administrator wording or publication was overwritten.

Profiling caught redundant authorization over the complete job history before
paging. The final query groups correlation internally, pages IDs first, then
uses `authorized_event_history` for every displayed summary/detail row. Counts
and rows share one query in the normal case. The demo summary improved from
about 9.5 seconds to 1.8 seconds, with the existing authorization rules intact.
All final nine API history regressions and 36 bilingual history UI checks
passed after the corresponding changes; database runs used new disposable
databases and each was dropped.

All **12 owned disposable databases** are absent, preview ports 18000/18080/18081
are closed, and demo API/WebUI health checks returned HTTP 200.
See [cleanup evidence](disposition-history-actions/cleanup.json).
