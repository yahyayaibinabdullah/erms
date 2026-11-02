# Claim guidance and readable proposal targets

A review task in a shared queue must be claimed before proposals can be added.
The Current task section explains this requirement; the Aggregations table
retains its readable identities and displays disabled Add proposal controls with
localized claim guidance. The Claim dialog explains responsibility, exclusive
editing/completion, and that claiming does not approve proposals or advance the
job. No reason is requested.

Proposal visibility is separate. In demo, Nad can read aggregation
1141/DEMO/011/2026, but its two relationship-removal proposals reference related
aggregations she cannot read. The original full-envelope redaction hid the
readable target as well. The paginated proposal API now independently authorizes
only targets from the current page and optionally returns target_summary (number,
title) on a redacted envelope. Other proposal fields and related-resource details
remain withheld. No authorization, claimant or mutation gate is relaxed. There
are at most two bounded target reads per proposal page; no cache is introduced.

The UI uses the existing Wathiq PageTable presentation. A target cell uses bdi
for mixed-direction identities and a localized restriction explanation. Existing
proposal details/edit/withdraw controls remain hidden for redacted rows.

English and Arabic catalogues add three keys: claim_before_proposals,
claim_explanation, and restricted_proposal_details in disposition.ui. Existing
curated translations and provenance are preserved. Arabic additions are generated
drafts, pending administrator review; no administrator export is promoted.

## Verification — 26 October 2026

- 162 English/Arabic task and screen tests passed, including disabled proposal
  controls, claim explanation, readable redacted targets, pagination and return
  navigation.
- 24 proposal API/database tests passed. The new scenario checks hidden related
  content with a readable target, denied mutation before claim, and complete
  target redaction after current target access is lost. All disposable test
  databases were dropped.
- Read-only evaluation under Nad's identity in demo returned both proposal
  targets as 1141/DEMO/011/2026 with no hidden proposal facts or related IDs.
- The live local NiceGUI preview used the production job screen, PageTable and
  ReviewForm. English/LTR and Arabic/RTL both preserved target identity and
  rendered disabled Add proposal controls and the Claim explanation. Existing
  Wathiq header, spacing, action and pagination presentation was retained.
- Catalogue references, exact language coverage/order, Arabic terminology,
  environment-template consistency and git whitespace checks passed. Missing-only
  Arabic seeding stored three drafts, corrected zero, and reported zero failures
  or awaiting-generation entries; 3,879 prior translations were preserved.
  No new translations were published.
