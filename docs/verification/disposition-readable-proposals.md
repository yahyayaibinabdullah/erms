# Review-proposal presentation — 29 October 2026

Approved scope: destruction revision 1.10, section 6.5. The user approved all
recommended presentation changes and asked why Last revised by was empty.

| Requirement | Implementation | Verification |
| --- | --- | --- |
| Six useful listing columns | `ReviewForm.proposals_panel`: Target, Proposed change, Status, Proposed by, Reason and Actions; role beneath proposer; one round caption above the table | Bilingual real-NiceGUI assertions and English/Arabic browser screenshots |
| Describe the actual proposed effect | `proposal_presenter.py` covers all eight proposal types: named security level, relationship type/related endpoint, retention years/action, holds, vital status and job removal | Distinct same-target relationship summaries, record endpoints, zero-year retention, bounded hold labels and restricted-envelope tests |
| Correct localized relationship perspective | Proposal page joins existing type/security catalogues; forward names remain available for source→target Details, while the compact label uses the reverse name for incoming non-symmetric relationships | Four database cases cover incoming/outgoing × symmetric/directional, each in English and Arabic; security name is localized with the existing projection helper |
| Preserve metadata and explain blanks | Details retain original proposer/role, stage, round, reason, state and execution result; timestamps use Proposed at/Last revised at; no recorded revision displays Not revised | Revised/unrevised bilingual Details tests; live carried-forward proposal and newly created proposal |
| Compact actions and native styling | Existing Wathiq PageTable and native horizontal no-wrap action group, accessible tooltips/names; bounded native Details dialog | Browser measurements show all three actions on the same vertical coordinate in both languages; representative relationship row: 99px LTR / 97px RTL at 1280px viewport |
| Preserve authorization, pagination and audit history | Existing proposal visibility check and partial-metadata whitelist; summaries never use hidden value snapshots or endpoints; existing page limits and abandonment guards remain | Backend partial-redaction assertions include both added display fields; hidden endpoint still prevents Manager approval, while authorized withdrawal remains available |

Read-only diagnostics of demo job DT-2026-2 confirmed all four current round-2
proposals have null `last_revised_by_user_id` and `last_revised_at`. Each was
carried from the preceding round. Carry-forward preserves original creation and
revision metadata; it does not fabricate a revision. The blank field was expected
data presented without an explanation, not a missing recorded edit.

## Validation

- Final frontend task/proposal/history regressions: **263 passed**.
- The broader proposal API run passed **50 checks**. One older Phase 14 fixture
  still attempted final Manager approval through the ordinary review-decision
  command. It was updated to the existing protected approval operation; the final
  targeted run passed **5 checks**, including that fixture and all four new label
  cases. Together these verify all **51 distinct API checks** in the selected files.
- Earlier validation also caught invalid catalogue type metadata, an unapproved
  Arabic security-level term, a fixture's invalid relationship-type code/symmetric
  labels, and older fixtures that expected fully hidden targets or created 60
  duplicate vital proposals. The repaired fixtures follow the approved partial
  metadata contract and use 60 distinct hold proposals for real pagination.
  Production authorization, duplicate detection and workflow rules were retained.

Database runs used fresh uniquely named databases initialized from the canonical
schema. No automated test ran against demo. Browser examples were created only
in a separate disposable database, with sample security and related aggregations.

## Evidence

- [English proposal table](disposition-readable-proposals/table-ltr.png)
- [Arabic proposal table](disposition-readable-proposals/table-rtl.png)
- [English Details](disposition-readable-proposals/details-ltr.png)
- [Arabic Details](disposition-readable-proposals/details-rtl.png)

## Translation artifacts

Added 13 English/Arabic keys for the column labels, explicit dates/unrevised
state and change summaries. Both catalogues have **3,948 active keys** in matching
lexicographic order. All **3,935 existing Arabic entries**, wording and provenance,
are unchanged. No administrator export was promoted or replaced. New values are
generated drafts needing human review.

Reference/stale-key, ordered coverage, blank, placeholder, markup, artifact-hash,
new-entry provenance and all approved terminology checks pass. The explicit demo
seed uses `--missing-only`; all 13 new Arabic values remain unpublished. See
[translation preservation](disposition-readable-proposals/demo-translations.json).

No schema, environment template, privilege, execution behavior or audit-history
mutation is introduced. The existing proposal endpoint gains two permitted
display labels without extra per-row requests or a new cache. Specifications,
workflow documentation and the requirement ledger record this amendment.

The managed stack was restarted to apply the changes to demo; API and WebUI
health returned HTTP 200. All four owned disposable databases were dropped and
preview ports 18000/18080/18081 are closed. See [final verification data](disposition-readable-proposals/verification.json).
