# WebUI refactor: Phase 6A — relationship-type administration

**Status:** Complete for the approved local Chrome/Edge scope. Stop for user
approval before 6B.

## Boundary

This step separates the remaining relationship-type administration entry and
view lifetime from `app.py`. The existing `resource_relationships.py` renderer,
resource relationship panels, API, database schema, wording, translations, URLs
and history behavior are outside the change. There is no new cache.

The existing shell continues to supply a narrow entry callback. Permission checks,
per-client view tokens, current identity and destination checks belong to the new
feature controller. Language metadata is read on every entry. Drawer navigation
retains its existing guard; saved-navigation restoration uses the same opener.
Record and aggregation relationship-panel tokens remain with their existing owners.

## Requirement-to-verification map

| Existing contract | Implementation boundary | Verification |
| --- | --- | --- |
| Administration requires `relationships.administer`; reading types does not confer administration | Controller entry gate; unchanged API authorization | Direct allowed/denied entry tests, restricted browser identity and API write rejection |
| Existing shell/navigation order, drawer entry, restoration, root URL and history | Host entry callback and existing navigation dispatch | Direct shell-order assertions; real-browser repeated visits/reload/history-length checks; assembled destination suite |
| Old views cannot act after replacement, departure or identity change | Per-client controller view lifetime; unchanged renderer `alive()` and page revision checks | Direct abandonment, delayed render and independent-client cases; browser held-read/navigation journey |
| Existing table, tabs, filters, sorting and bounded pagination | Unchanged `relationship_administration` and `PageTable` | Existing unit tests; real-browser second page, sort, empty search, request bounds and before/after images |
| Create/edit/delete, required English/Arabic names, translations and optimistic concurrency | Unchanged editor and API | Existing language-staging test; real-browser validation, create, edit, controlled conflict/retry, cancel/delete and fresh API readback |
| Existing appearance, RTL, focus and error presentation | Unchanged renderer, shell styles and catalogue | English/Arabic screenshots and native Tab focus; controlled read failure; browser errors |

## Baseline development

The original wrapper and renderer passed 24 focused cases. All 43 existing
assembled-application cases passed against a fresh disposable database.

Initial browser attempts exposed test assumptions, not changed application code:
synthetic codes must use underscores rather than hyphens; tab text is uppercase;
the first sort request is ascending; and API errors are shown as localized
messages rather than raw server text. The harness now observes that existing
behavior. Created rows are searched explicitly so pagination does not hide them.
The restricted API test refreshes the CSRF header after changing its identity.
All attempts and cleanup outcomes are retained. No product fix was applied.

Chrome's passing baseline preceded the test client's CSRF-header refresh; the
Edge baseline and both final runs include it. This strengthens the separate API
permission check and does not alter browser actions or screenshots. The direct
pre-extraction permission cases and restricted browser menu checks also passed.

## Verification results

| Check | Result |
| --- | --- |
| Focused controller/renderer baseline and extracted cases | 24 passed before and after; the 12 new boundary cases retain their assertions |
| Full WebUI unit suite | 1,550 passed |
| Full WebUI interaction suite | 209 passed |
| Assembled real-root / real-API suite | 43 passed before and after |
| Chrome feature browser journey | 15 check groups passed before and after |
| Edge feature browser journey | 15 check groups passed before and after |
| Visual comparison | All 17 scenes per browser match pixel-for-pixel below the unchanged animated header |
| Keyboard focus | Native Tab moves from English forward-name to reverse-name input in both languages, before and after, in both browsers |
| API requests | Relationship request counts, queries, status codes and controlled outcomes match each browser baseline |
| Runner safety and diagnostic privacy | 23 passed |
| Database cleanup | All 11 disposable databases dropped; independent catalogue check found none remaining |

The full unit and interaction suites have no failures, errors or skips. An initial
runner-check invocation named a nonexistent test file and ran no tests; the
corrected invocation passed all 23 runner checks. Its zero-test result is retained.

The final browser runs use the same frozen production source. All 141 other
direct host functions are AST-identical to the pre-6A working copy. The renderer,
shared shell/navigation/session modules, component styles and catalogue artifacts
are byte-identical. The only existing runtime file changed is `app.py`, plus the
new `relationship_types_controller.py`. Application assembly and the shell adapter
remain in the host deliberately; this is not a claim that `app.py` is fully modular.

All original screenshots are retained; only the live animated header above y72
is excluded from pixel comparison. Representative English table and Arabic editor
images were inspected. No screenshot baseline was replaced to accept a difference.
Read timings are supporting observations under shared local load: Chrome median
13.95 → 16.22 ms, maximum 86.42 → 88.35 ms; Edge median 9.775 → 16.005 ms,
maximum 56.94 → 225.8 ms. These are server-request durations, not end-to-end latency
guarantees. Each browser has 40 successful uncontrolled relationship reads before
and after, with matching queries. No extra request or cache was introduced.

All 4,071 translation keys, wording and provenance remain unchanged. Coverage,
ordering, blanks, placeholders, catalogue hash and source references pass; all
35 approved terminology mappings pass across 966 contextual uses. No artifact
was replaced or administrator export promoted, and no new translation review is
required. There are no environment-template, dependency, database-schema or API
changes. No email was sent and no Safari or MailDev setting/process was changed.

Evidence: [browser comparison](verification/webui-refactor-phase6a/browser-comparison.json),
[full suite results](verification/webui-refactor-phase6a/final-isolated/summary.json),
[source audit](verification/webui-refactor-phase6a/source-audit.json),
[translation checks](verification/webui-refactor-phase6a/translation-check.json),
[database cleanup](verification/webui-refactor-phase6a/database-cleanup.json).
Full results and screenshots are retained in the same evidence directory.

Work remains local and uncommitted on `refactor-API-python-file`. No branch,
worktree, commit, push or history operation was performed. The Phase 5 working
copy used for baseline testing matches the user's subsequently committed
`40bf384` application source. Firefox, Safari and CI remain deferred. The accepted
Phase 5 Edge observation remains recorded; it is not classified as fixed by 6A.
Phase 6B has not started and requires the user's next approval.
