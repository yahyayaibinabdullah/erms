# Proposal Details and Revision history — 29 October 2026

Scope: destruction revision 1.11, section 6.5; improve the proposal disclosure's
look and readability while retaining its information and authorization.

| Requirement | Implementation | Verification |
| --- | --- | --- |
| Clear current/proposed values | `proposal_details.py` renders responsive comparison panels with existing Wathiq field labels and typography; relationship endpoints are separate From/To fields | English/Arabic relationship-removal and retention examples; mobile panels stack |
| Compact metadata without losing it | Target/state remain in the header; reason stays visible; Proposal information groups original proposer/role, stage, round, dates, last reviser and background snapshot values | Existing full/partial/revised/unrevised Details assertions pass; live expansion preserves every former displayed field |
| Readable revision history in the same dialog | Native Revision history tab contains dated action/actor expansions; safe business-field changes show Before/After; other audit facts remain under Recorded information | Real recorded retention revision: 1→2 current years, 2→3 intermediate years; creation/carry-forward remain separate records |
| Lazy bounded reads and content | `ProposalRevisions` loads only on tab selection, requests 25 rows by default (10/25/50 choices), pages on the server, builds entry content on expansion and refreshes on tab re-entry | No initial history request; true offset 25; repeat-entry refresh; no nested revision dialog; inline error/empty states; closed/abandoned responses cannot repaint |
| Preserve protected information | Partial proposals retain permitted metadata and no history tab; redacted events show the existing restricted envelope; technical information keeps its existing privilege flag | Bilingual partial/redacted-envelope tests; technical disclosure initially collapsed; no proposal mutation |
| Reachable Close and responsive layout | Native NiceGUI card/flex/tab panels, bounded width/height, body scrolling and a separate footer | Desktop expanded metadata scrolls inside a 672px card; at 390×844 the card is 342px wide with no horizontal overflow and Close ends at y=808 in both directions |

Final focused task/proposal/history UI suite: **271 passed**. The tests use
in-memory NiceGUI fixtures, not a persistent database. Browser verification used
a fresh uniquely named disposable database initialized from the canonical
schema; sample proposals and a revision were added only there. No API, schema,
privilege, proposal-execution or historical-scope change was needed.

The shared readable history field registry now includes current/intermediate
periods in years and instructions. Revision comparisons explicitly preserve
cleared values as Not set. Automatically updated audit attribution is kept in
Recorded information instead of dominating the initial comparison. The original
audit records and privileged technical payloads are retained.

## Evidence

- [English Details](disposition-proposal-dialog/details-ltr.png)
- [Arabic Details](disposition-proposal-dialog/details-rtl.png)
- [English revisions](disposition-proposal-dialog/history-ltr.png)
- [Arabic revisions](disposition-proposal-dialog/history-rtl.png)
- [English mobile](disposition-proposal-dialog/mobile-ltr.png)
- [Arabic mobile](disposition-proposal-dialog/mobile-rtl.png)

## Translation artifacts

Eight new keys were added to the English and canonical Arabic catalogues:
proposal information, proposal context, Details tab, relationship From/To,
revision Before/After and Recorded information. Both catalogues contain **3,956
active keys**, in the same lexicographic order. All **3,948 pre-existing Arabic
items**, text and provenance, remain unchanged. No administrator export was
promoted or replaced; the eight additions are generated drafts needing review.

Reference/stale-key, ordered coverage, blank/placeholder/markup, artifact-hash,
new-entry provenance and approved terminology checks pass. Demo uses the
explicit `--missing-only` seed utility; new Arabic drafts remain unpublished.
See [translation preservation](disposition-proposal-dialog/demo-translations.json).

The dialog holds only its mounted UI page data, with no shared cache. Its page
and size belong to that dialog; tab entry revalidates through the existing API,
failure clears the displayed entries, and identity/language changes dispose of
the originating page. Revision tokens and dialog/tab liveness guards reject
late responses. No environment settings or templates changed.

The managed local stack was restarted to apply the redesign to demo. API and
WebUI health returned HTTP 200. The disposable preview database was dropped and
ports 18000/18080/18081 are closed. See [final verification data](disposition-proposal-dialog/verification.json).
