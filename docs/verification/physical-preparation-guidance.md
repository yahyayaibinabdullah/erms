# Physical preparation guidance — 2 November 2026

The readiness action is now **Check readiness for physical destruction**.
Below the preparation-report heading, a short localized note explains that the
report is used before destruction to locate and prepare physical or mixed
material, listing aggregations, classifications, owning units, locations and
counts. Destruction specification sections 14.1–14.2 record this wording.

The existing native NiceGUI label uses the same subdued helper-text treatment
as the review and history screens. No workflow, API, authorization, generation
behavior changed in this guidance update. The report-action menu was subsequently
implemented; see [report action verification](physical-report-actions.md).

## Verification

The actual physical report controls and task form were rendered with Wathiq's
stylesheet and an in-memory API fixture in the in-app browser. English and
Arabic were checked at 1280×720 and 390×844. The phone-width note has equal
client and scroll widths (326px) in both languages; the renamed button is
316px wide in English and 275px in Arabic, within the 326px content area.
Repeated language navigation retains the wording and direction. Native labels
and buttons provide the wrapping; no CSS override was needed.

Six existing physical-screen tests pass, including both language fixtures.
Catalogue reference/stale-key checks, exact ordered coverage (3,968 keys),
blank/placeholder/markup validation, the catalogue hash, the current approved
Arabic glossary checker, and `git diff --check` pass. The older bootstrap draft
validator still reports eleven unchanged pre-existing failures against its
older terminology/token rules; comparison with the pre-change artifacts
confirmed none were introduced here. No database-backed tests were run.

## Translation lifecycle

`disposition.ui.check_physical_work` keeps its stable key with the new English
definition and a revised generated Arabic draft. Its previous draft and
provenance remain recorded in generation metadata. The new key is
`disposition.ui.physical_preparation_report_hint`, with English and generated
Arabic wording. No administrator export was promoted. Every other Arabic item,
including wording and provenance, remains unchanged.

The authorized `demo` synchronization used the official seed with
`--missing-only`: one draft stored, 3,967 existing translations protected,
zero corrections/failures/missing generations. The changed source definition
marks its existing translation for review; missing-only seeding preserves its
existing wording. The revised Arabic readiness wording is in the canonical
artifact for reconciliation/review, rather than silently replacing database
wording. New and revised Arabic drafts remain unpublished for human approval.

## Evidence

- [English](physical-preparation-guidance/english.png)
- [Arabic draft preview](physical-preparation-guidance/arabic.png)
- [English phone width](physical-preparation-guidance/english-narrow.png)
- [Arabic phone width](physical-preparation-guidance/arabic-narrow.png)
