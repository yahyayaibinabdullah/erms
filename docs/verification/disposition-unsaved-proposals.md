# Unsaved proposals in Aggregations — 29 October 2026

Scope: destruction specification revision 1.12, section 6.4. An unsaved legal-hold
proposal previously remained invisible in the member's Review proposals count
until Save refreshed the server projection.

The mounted ReviewForm now associates every queued change with its governing
aggregation and overlays the existing paginated membership page. New proposals
increase its active count immediately; revisions leave the count unchanged;
queued withdrawals decrease it. A compact draft icon, with the accessible label
and tooltip **Unsaved proposal changes**, identifies the
pending work and opens the existing aggregation-scoped disclosure with its draft
target, selected values and reason. Discard, replacement and successful Save
clear the associated local metadata. A failed Save retains it. Open draft
disclosures update with the form and detach when closed.

No write is made by adding, revising, withdrawing or discarding a local draft.
Actual holds, blockers, membership and resource metadata retain their existing
Save and approval/execution boundaries. Historical memberships and redacted
counts receive no overlay. No API, schema, privilege or environment change.

| Requirement | Verification |
| --- | --- |
| A legal-hold draft appears before Save | Real NiceGUI dialog tested in English and Arabic, for a governing aggregation and a descendant; count changes 0→1 without a write |
| Draft values are accessible | Count/unsaved links disclose selected hold and reason alongside bounded saved proposals |
| Correct draft lifecycle | Repeated rendering/tab entry does not double-count; discard restores 0; failed Save retains 1; successful Save refreshes saved 1 and clears the unsaved marker |
| Revisions and withdrawals | Revision does not add a proposal; replacing it with withdrawal reduces the count; discard restores the saved count |
| Isolation | Other aggregations, restricted rows and historical membership episodes remain unaffected; an abandoned workspace cannot be repainted |
| Performance | No request for the local count update; existing 25-row member/proposal requests and PageTable navigation/late-response guards retained |

The focused task, proposal and history UI suite passed **277 checks**. Tests and
the live browser preview used in-memory API fixtures, with no database connection
or database-backed suite. The live fixture rendered the actual job screen and
proposal controls with the application's stylesheet and RTL direction helper.
Both membership and proposal tables retain Wathiq light-blue headers, standard
spacing, actions and pagination. The compact draft icon keeps the sample member
row at 78px before and after the addition in both LTR and RTL. Native draft cards reuse the existing pending
work presentation; no new layout CSS was introduced.

English and Arabic key coverage remains **3,956**, with matching sorted order.
This fix reuses existing labels; neither catalogue nor translation provenance
changed in this turn. No administrator export was promoted and no new drafts
require review. Reference/stale-key, blank, placeholder, markup, terminology,
provenance and catalogue-hash checks pass.

The managed demo stack was restarted; API and WebUI health returned HTTP 200.
The temporary preview and its browser tab were closed; port 18082 is closed.

- [English membership row](disposition-unsaved-proposals/members-ltr.png)
- [English draft disclosure](disposition-unsaved-proposals/drafts-ltr.png)
- [Arabic membership row](disposition-unsaved-proposals/members-rtl.png)
- [Arabic draft disclosure](disposition-unsaved-proposals/drafts-rtl.png)
- [Verification data](disposition-unsaved-proposals/verification.json)
