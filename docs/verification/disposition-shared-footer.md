# Shared task footer — 30 October 2026

Approved design: **Shared footer** from the task Save/discard mockups. Contract:
Destruction Process revision 1.13, sections 6.4 and 6.6.1.

| Requirement | Implementation and verification |
| --- | --- |
| Save from all task tabs | `DraftControls` mounts outside the retained tab panels using native `ui.page_sticky(position='bottom', expand=True)`; the same Save command is available in Current task, Aggregations and Evidence |
| Review the full pending set | Review changes shows queued creations, revisions and withdrawals plus changed Review comments, using mounted task state and no extra request |
| Discard an individual draft | Current task, aggregation-scoped disclosure and global review offer Discard draft; counts update immediately without a write; withdrawal review names the saved target/type |
| Clear persistence boundary | Add draft proposal / Update draft proposal queue changes; Save changes persists the complete existing atomic payload; submission and decisions remain in Current task |
| Accurate footer state | One count per queued proposal change, plus one for edited comments; All changes saved and disabled Save/Review when empty |
| Safe requests and failures | Busy guards prevent concurrent saves/discard/edit; failures retain drafts, show the specific error in footer and open dialog, and reuse the command ID on exact retry; dialogs close only after successful Save |
| Preserve context | Server-filtered page 2, size 10, query and state remain unchanged after Save; browser Save retained Aggregations and scroll Y **253.5 → 253.5**; Evidence also remains selected after dialog Save |
| Scope and lifetime | No Save footer on read-only/unclaimed tasks; it belongs to the mounted task, disappears with its page, and ignores abandoned results; existing permissions and workflow transitions remain authoritative |

## Validation

**340 passing frontend checks** cover the footer, task forms, pending proposal
overlays, proposal presentation/details, history, automatic role selection,
physical tasks and external tasks. No database-backed test suite was run. Tests
and browser interactions used in-memory API fixtures; no business data was
changed by verification.

The live preview rendered the actual NiceGUI job screen and Wathiq stylesheet,
including the application's existing status footer. At 1280×720 the native task
footer is 63px high and ends at y=686, exactly where the 34px application footer
starts. At 390×844 in both LTR and RTL, it wraps to 111px and ends at y=810,
again directly above the application footer. Both buttons remain within the
viewport. The review card is 342px wide with equal client/scroll width and
reachable Close/Save actions. The aggregation-scoped dialog likewise uses a
bounded card, scrolling body and separate action footer.

NiceGUI's documented PageSticky position/expand options and native card, row,
column and button components solve the layout. No custom positioning CSS or
raw Quasar layout fallback was needed. A responsive page spacer keeps the last
content clear of the bar. Wathiq tables retain their light-blue headers,
typography, action treatment and existing server pagination.

Draft review adds **zero API requests**. Save uses the existing atomic command
and bounded refreshes without rebuilding the page or introducing a cache.
Repeated tab entry refreshes supporting lists while retaining pending work;
deleted/inactive page checks prevent late repainting.

Python compilation, catalogue references/stale-key detection, ordered coverage,
blank/placeholder/markup checks, approved terminology, provenance preservation,
catalogue hash and `git diff --check` pass. No API contract, schema, migration,
privilege, environment variable or environment template changed.

## Translation artifacts and demo

Eleven new keys were added to the English and canonical Arabic catalogues:
Save changes, Review changes, all-saved status, singular/plural unsaved counts,
Discard draft, Add/Update draft proposal, empty pending-work state, shared Save
hint and the draft-added notification. **3,967** active keys have matching
lexicographic order. All **3,956** prior Arabic item objects, including wording
and provenance, remain unchanged. No administrator export was promoted.

The explicit Arabic seed utility was run with `--missing-only`. Audit records
confirm only the eleven newly introduced, unreviewed source-copy rows were
filled; **4,009** pre-existing Arabic rows were untouched. A second official seed
was a no-op. All eleven new translations remain unpublished drafts needing
human review. See [demo preservation](disposition-shared-footer/demo-translations.json).

The managed local stack was restarted to apply the change to demo. API and WebUI
health returned HTTP 200. The owned preview and browser tab were closed.

## Evidence

- [English footer](disposition-shared-footer/footer-ltr.png)
- [English review/discard dialog](disposition-shared-footer/review-ltr.png)
- [Arabic footer](disposition-shared-footer/footer-rtl.png)
- [Arabic review](disposition-shared-footer/review-rtl.png)
- [English phone footer](disposition-shared-footer/footer-mobile-ltr.png)
- [Arabic phone footer](disposition-shared-footer/footer-mobile-rtl.png)
- [Arabic phone review](disposition-shared-footer/review-mobile-rtl.png)
- [Verification data](disposition-shared-footer/verification.json)
