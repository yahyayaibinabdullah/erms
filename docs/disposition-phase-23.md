# Phase 23 — integrated workflow and upgrade acceptance

Status: complete (20 October 2026). Phase 24 has not started.
No persistent database has been tested or migrated; operational release stays disabled.

## Integration corrections

The complete journeys exposed a Phase 21 finalization defect: review decisions
contain both membership and proposal snapshots, but only the membership snapshot
was minimized. The exact-value history guard correctly rejected finalization when
the proposal snapshot also needed minimization. Migration 070 and the independent
canonical schema now minimize both snapshots atomically under the existing private
finalization fence. Ordinary history writes remain rejected; event identities,
decision rationale and permanent provenance survive.

The in-app browser exposed inaccessible navigation below the desktop breakpoint:
the drawer closed while its only toggle remained inside it. A standard NiceGUI
header button now controls native drawer visibility, tracks accessible expanded
state and hides for anonymous sessions and desktop widths. Existing translated
labels are reused; desktop mini-drawer labels and chevrons also follow direction.
No custom CSS or new translation keys were introduced for this correction.

The operation-policy inventory now explicitly lists the already implemented
disposition routes. Management and limited-role task scopes remain distinct;
unknown future routes still fail classification. The approved seed inventory now
includes the existing disposition privilege and existing IGU profile grants from
migration 053. This changes documentation/inventory, not runtime permissions.

## Acceptance evidence

Detailed logs and screenshots: `docs/verification/disposition-phase-23/`.

- Fifteen canonical complete journeys passed. Standard direct/inherited/no File
  Administrator, Simplified and Records Manager Only each run with physical-only,
  digital-only and mixed units. Cases include partial Save/revision, restored
  drafts, repeated internal/external rejection, saved route despite configuration
  change, proposal execution, request email, physical confirmation, digital work,
  certificate completion/email/download and permanent snapshot minimization.
- Fifteen journeys plus nine completion/recovery tests passed after upgrading
  HEAD through migrations 069 and 070. A populated pre-configuration database
  upgraded through 050–070 matches the fresh canonical schema, functions, views
  and privileges, preserving original rows, fields, grants and events.
- All four full API shards ran in separate disposable databases. Nine initial
  failures were resolved and their corrected selectors passed in targeted runs;
  initial failed logs remain unchanged. Corrections address approved catalogue
  additions, custom security levels, application-configuration response metadata,
  canonical administrator translation provenance and the policy inventory. The
  intentionally skipped legacy physical-upgrade case passed separately on its
  required old-schema/deferred-migration path. See `api-acceptance.json`.
- All 635 WebUI/tool cases passed (634 in the final full run, with its one
  corrected preservation assertion passing in the 49-case source-check rerun);
  all 30 text-indexer tests passed. Results are recorded in `acceptance-summary.json`. The explicit full-text search test enables its
  approved disabled-by-default setting. No product defaults were changed.
- Live in-app English/Arabic verification covers Save by keyboard, partial
  reason, reload and language switching, identity isolation, real 25/25/8-row
  pagination over 58 memberships, repeated navigation and abandonment of an
  in-flight membership read. A fresh API process restores both users' drafts
  without advancing rounds. Existing Phase 22 completion/recovery/email/download
  browser evidence remains linked. Responsive navigation works in both languages
  at 390px and 1280px, with correct RTL geometry and no console warnings/errors.
- The requirement gate checks all 369 entries against existing implementation,
  named passing tests, registered evidence and every owning phase through 23.
  Missing older Phase 1/22 traceability is explicitly reconciled with current
  verification; historical runs are preserved. Phase 24 scopes remain pending.

## Translation and configuration handoff

English and Arabic retain the same 3737 active keys. Phase 23 adds/removes no
keys and promotes no administrator export. Seven explicitly invalidated,
unreviewed machine drafts were corrected to the approved glossary; their prior
wording is retained in `superseded_translations`, with correction metadata.
Every administrator-curated entry and its provenance remain unchanged. The
terminology checker distinguishes the imperative verb “record” from the glossary
noun without exempting record identifiers or other noun contexts.

All 533 existing machine candidates remain drafts requiring human review;
Phase 23 does not approve or publish them in a persistent database. Artifact import
continues to report those candidates as requiring quality attention. Browser-only render fixtures were
confined to disposable databases. Exact coverage/order, placeholders, nonblank
text, hash, provenance, stale-key and approved terminology checks pass.

No environment variable or template changed. Configuration-authority metadata
was refreshed for changed source line numbers; setting ownership is unchanged.
API environment templates still agree and document all 36 deployment settings.

## Deployment boundary and cleanup

Migration 070 follows 069 when upgrading an existing database. A new empty
database uses `database/schema.sql` alone. Physical/digital operational release
gates remain false. Controlled rollout, operator instructions and deployment
authorization belong to Phase 24.

Every test/preview database created for this phase was independently checked
absent, preview ports are closed, temporary browser tabs are closed and the
viewport override is reset. See `cleanup.json`. No commit or persistent database
migration was performed.
