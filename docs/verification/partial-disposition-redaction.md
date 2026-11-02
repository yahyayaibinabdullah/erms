# Partial disposition redaction

## Approved behavior and boundaries

Destruction-process section 6.3 distinguishes resource visibility from proposal
metadata and task ownership. Proposal rows with a readable target retain type,
state, proposer and role, proposing stage/round, creation/revision/execution
timestamps and editor/role even when related facts are restricted. Their Details
button opens a read-only metadata view. An explicit server whitelist excludes
free-text reasons, current/proposed snapshots, execution payloads and protected
resource/relationship/hold identifiers. Fully unreadable targets retain only
the pre-existing redacted envelope. Claim, edit, withdrawal and approval gates
are unchanged.

The current-blocker endpoint previously required an IG management role, so Nad's
File Administrator request failed and the UI left an empty dialog after a toast.
The blocker read guard now accepts existing authorized task recipients with
current root access; it reuses the workspace authorization boundary. Eligibility
and locked mutation checks retain the management-only guard. The endpoint adds
bounded relationship rows alongside protection rows. A single offset advances
both independent ordered streams; has_more combines their look-ahead results.

Each relationship endpoint is separately authorized and labelled only when
readable. Public localized relationship-type wording and final-blocker flags
remain visible; hidden endpoint and relationship IDs remain absent. Legal-hold
metadata retains its independent visibility gate. The UI displays inline loading,
empty and retryable error states rather than an apparently empty dialog.

No operational cache, schema migration, environment variable or workflow change
is introduced. All reads use current identity/access and requested language.
Targets and endpoints are resolved in bounded batches from the current page.

## Arabic artefacts

Seven contextual disposition.ui keys are added: restricted_resource,
restricted_text, blocker_source, blocker_target, blockers_empty_all,
blockers_retry and proposal_metadata_details. Existing curated wording and provenance remain unchanged.
Generated Arabic drafts require administrator review; no export is promoted and
no translation is published by this change.

## Verification — 26 October 2026

- 101 proposal, eligibility and query API/database tests passed together on the
  final run. The uniquely named disposable database was dropped afterward.
- 166 English/Arabic task and screen tests passed, including partial metadata,
  read-only details, independently hidden endpoints, pagination, inline errors,
  retry, and explicit LTR file-number labels within RTL layouts.
- Read-only demo evaluation as Nad returned both proposals' whitelisted Arabic
  author/role metadata and both relationship blockers. Hidden related endpoint
  and relationship IDs remained null; protected facts and reasons were absent.
- The live production-component preview retained Wathiq tables and action
  tooltips. English and Arabic blocker/detail views were inspected. An observed
  bidi issue in combined Arabic endpoint labels was fixed using standard
  NiceGUI rows and separate dir=ltr number labels; no CSS workaround was needed.
- Catalogue references, maintained-language ordering/coverage, approved Arabic
  terminology, environment templates and whitespace checks passed. Missing-only
  demo seeding stored seven drafts with no failures/corrections/awaiting values,
  preserving 3,882 existing translations and publishing none.

| Requirement | Implementation | Regression evidence |
| --- | --- | --- |
| Permitted proposal metadata survives related-resource restrictions | proposals.page whitelist; ReviewForm partial row/details | test_hidden_related_resource_preserves_readable_proposal_target_before_claim; test_partial_proposal_keeps_metadata_and_read_only_details |
| Reviewer inspects blockers without IG management authority | blockers._require_read_root; read_blockers | Same API privacy scenario; eligibility/query suites |
| Hidden endpoints remain protected while blockers remain understandable | relationship_page endpoint labels; blockers_dialog | Hidden-endpoint eligibility tests; partial blocker UI test |
| Empty/error/pagination and Arabic number direction are explicit | blockers_dialog | test_blockers_dialog_shows_partial_relationships_pagination_and_inline_errors; English/Arabic live preview |
