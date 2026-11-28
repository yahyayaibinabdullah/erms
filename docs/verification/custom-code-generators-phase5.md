# Custom Code Generators: Phase 5 Verification

**Authority:** Approved specification revision 0.5 and implementation plan
revision 0.14. **Date:** 27 November 2026. **Status:** Complete; final catalogue
and regression checks are recorded with phase 6.

The administration listing, settings dialog, five-value preview/simulator,
history and separate counter controls are implemented. This report records
verification; it does not close the separate phase 4 performance gate.
All changes remain local and uncommitted.

## Implementation

Settings → Code generation uses Wathiq's shared paginated table, native NiceGUI
controls and the existing settings-management privilege. Listing filters use
their submitted values while paging. Type and Text-field selectors use bounded
server searches and retain selected identities. Name is required; create reason
is optional and edit reason is required. Version conflicts retain entered
settings and require an explicit reload before another edit.

Previews send one request for all five values to the shared server renderer.
Input changes immediately invalidate old results; request revisions discard late
responses and dialog closure abandons them. Simulated contexts and dates never
allocate real counters. History uses the existing authorized event timeline
and immutable historical names. The separate counter dialog reads paginated
scope/period counters and performs reasoned, versioned forward adjustments.

Reference-cache regression testing found an older in-flight GET could be reused
after a mutation. The shared API client now advances its data revision before
and after writes; fresh reads cannot join an older request, and older responses
cannot repopulate the reference cache. Preview POSTs remain explicitly pure
reads. This adds no configuration cache or privilege.

## Automated evidence

Logs are retained in `.runtime/custom-code-generators/phase5/`:

- `existing-settings-regression.log`: 52 passed.
- `dialog-interactions-corrected.log`: 12 passed after fixing the new test's
  incorrect assumption about the initial pattern. The interrupted initial run
  is retained separately.
- `expanded-dialog-and-audit.log`: 35 passed, including administration,
  controller and existing settings/audit interactions.
- `shared-audit-and-selectors.log`: 20 passed, including shared English/Arabic
  audit rendering and historical-name/large-integer presentation.
- `reference-freshness-and-creation.log`: 84 passed. The retained
  `reference-refresh-race-before.log` demonstrates the race before its fix.
- `selector-direction-api.log`: 3 API tests passed in a fresh disposable
  database. These cover allowed/denied descending selectors, retained selected
  rows, complete traversal of 125 types/fields and the separate history
  privilege. Actual SQL, plans and timings are retained under
  `.runtime/custom-code-generators/administration-metrics/`. Database
  `erms_messaging_test_acl_77fad0c14d334c5c9e78212132074e45` was dropped.
- `catalogue-registered-messages.log`: contextual references are complete and
  current after registering the explicit static message map. The initial
  checker failure is retained in `catalogue-coverage.log`.
- `latest-ui-regression.log`: **156 passed in 13.83 seconds**, covering
  administration interactions, the shared audit UI, existing
  settings/controller flows, API-client freshness and creation/retry controls.
- `warnings-and-audit-regression.log`: **157 passed in 16.95 seconds**, including
  the added independent-pattern advisory and localized audit field summaries.
- `independent-pattern-api.log`: **29 passed in 73.24 seconds**, including the
  conservative advisory, self-exclusion while editing, disabled/unbound targets,
  allowed/denied administration and unchanged real counters. Disposable database
  `erms_messaging_test_acl_2c8970d3ca0e410b8d359bce577be6e4` was dropped.

## Live API and browser evidence

The fixed-fixture runner initialized the canonical schema in disposable database
`erms_webui_test_5ce474d907f848dc8815a9834e432fb8`, launched its own API/WebUI
on loopback and used a synthetic administrator. English/LTR and Arabic/RTL
checks used the in-app browser, including the normal 686-pixel viewport and a
temporary 1,366-pixel desktop viewport. The override was reset and the temporary
tab closed afterward. No persistent application database was used.

Observed outcomes:

- A named record-number generator with start 10 and increment 10 previewed
  `R-2026-10`, `R-2026-20`, `R-2026-30`, `R-2026-40`, `R-2026-50`.
- The annual transition showed three values on 31 December 2026, followed by
  `R-2027-10` and `R-2027-20` on 1 January 2027; the first new-year row was
  marked restarted.
- Saving without a creation reason succeeded and displayed the name, target,
  pattern and enabled status in the listing. History showed the creation event
  and captured name. Attempting an edit without a reason retained the dialog
  and displayed validation feedback.
- The real counter list remained empty after those previews.
- An unsaved monthly, owning-unit-scoped configuration simulated contexts
  A, A, B before month end and A, B after it. Each unit started at 10; A's
  second value was 20. Both restarted at 10 on 1 December. A reasoned save
  updated the listing.
- After changing only the disposable administrator's language preference,
  the Arabic dialog produced the same codes and sequence, with Arabic scope
  and restart labels. The preview table inherited `direction: rtl`, all five
  headers aligned right, and its rendered width equalled its scroll width
  (486 pixels). The standard light-blue headers, borders and row actions
  appeared in the listing and preview. No layout/CSS workaround was added.

Some scripted clicks issued during Quasar's closing/tab transitions did not
activate the next control. Inspecting the selected tab and current dialog state
before proceeding resolved this; no server exception or code fix was required.
Evidence is in
`.runtime/local-stack/code-generators-phase5-20261127-run2/{api,webui,seed}.log`.
The runner stopped its owned services cleanly; `lifecycle.json` records
`database_dropped: true`.

The first browser fixture attempt rejected an unsupported draft quality flag.
The 140 newly generated code-generation drafts now use the documented
`needs_human_review` flag. Wording was preserved. The failed fixture database
`erms_webui_test_52b4269fe91b46888cd8731e25137f9b` was dropped too; its seed log
is retained under the corresponding `run1` directory.

## Final live acceptance

The final owned browser stack used disposable database
`erms_webui_test_8d5954a1475543078d0c8d8ee406178a` and synthetic data only.
The in-app browser exercised administration; native Chrome and its standard
file picker exercised uploaded-document replacement. The browser file-transfer
adapter twice stalled without completing an upload; those attempts did not
establish application success. Switching to the native file picker completed
the actual workflow. The temporary viewport override was reset. The stack
stopped cleanly and its lifecycle records successful database cleanup.

- A named primary record-number generator previewed `R-10` through `R-50`
  using start 10 and increment 10. Keyboard Enter ran the preview. Saving with
  no creation reason succeeded.
- The typed selector offered Contract and its Text field Contract number;
  the Integer field Amount was excluded. Its pattern used both
  `{ORG_UNIT_CODE}` and `{ROLE_CODE}`. Same-scope preview produced
  `C-ORG-A-ROLE-A-10` through `-50`; split scopes A, A, B, A, B produced serials
  10, 20, 10, 30, 20. Increasing the maximum from the field's 64 characters to
  65 showed validation and removed the old valid preview rows.
- The placeholder menu exposed all eleven tokens. Inserting Year with the
  keyboard appended `{YYYY}`; restoring the pattern did not allocate anything.
- Renaming Contract numbers to Contract references required a reason. History
  displayed the updated name alongside the original creation name and readable
  field labels. Names at the time of each event were retained.
- Uploading `copied-R-10.txt` saved a numberless draft with the exact uploaded
  bytes and no counter allocation. Suggesting R-10 remained non-consuming.
  A competing authorized manual creation then took R-10. Final creation showed
  the conflict and the document-correction instruction; it retained R-10, its
  generator origin, title and original component checksum. Counter changes
  rolled back.
- Explicitly accepting the replacement R-20 changed the field. Removing the
  old component and uploading `copied-R-20.txt`, then creating, saved exactly
  R-20 and typed value `C-WEBUI-TEST-admin-10`. Downloading the final component
  matched the corrected file byte for byte. No old component remained.
- Next numbers showed 30. Advancing it to 100 required a reason and updated
  the displayed counter. A later attempted change to 90 was rejected; the
  live next number remained 100. A missing reason was also rejected.

Machine-readable draft, conflict, completed-resource, component and counter
evidence is retained under
`.runtime/custom-code-generators/phase5/browser-files/`. Automated real-API
coverage of direct single/separate/combined drops, draft-opening drops,
capture, retries and their failure paths is recorded in phases 3 and 6;
native drag gestures are not claimed as manual browser evidence.

The desktop dialog initially inherited Quasar's 560-pixel minimized-dialog cap,
which overrode the utility maximum-width class. After inspecting computed
styles and the NiceGUI Dialog API, the existing application pattern
`ui.dialog().props('full-width')` removed that cap. No CSS override was added.
At 1,280 pixels the card measured 1,232 pixels. At 375 pixels it measured
327 pixels, with a 295-pixel single-column settings grid and no card overflow.
English and Arabic were both checked. The Arabic preview table inherited RTL
and all five headers aligned right; its own horizontal scrolling retained all
columns at narrow widths. Tab-transition animation briefly moved the panel;
the settled layout was inspected before acceptance.

Screenshots: `.runtime/custom-code-generators/phase5/arabic-generator-preview.jpg`
and `arabic-generator-narrow.jpg`. Both use the final full-width dialog.

## Translation preservation

The catalogues contain 4,337 active keys in identical sorted order, including
141 new code-generation draft translations. The separately user-approved
search-limit correction retains its prior text and provenance; the other
4,195 original entries remain unchanged. Preservation and quality-flag evidence
is retained in `translation-preservation.json` and
`review-flag-correction.json`. Source drafts remain unpublished. Publication in
the disposable browser fixture supplied Arabic visual QA only.

The additional key provides the independent-pattern advisory. It was merged by
message key without replacing existing wording or historical provenance.
Final coverage, terminology, placeholder, provenance and hash checks, together
with integrated creation/load/upgrade and performance results, belong to the
phase 6 report. Arabic drafts still require human review and publication.
