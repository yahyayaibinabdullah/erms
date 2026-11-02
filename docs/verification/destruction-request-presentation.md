# Destruction request presentation

Approved scope: destruction-process §11.2–11.3, DEST-07 and DEST-46;
administration-settings Disposition presentation amendment. The request details
are followed by an **Aggregations section**, not an appendix. List roots only,
with a running serial number followed by number/title, originated From Year/To Year, classification number, subtree
record total and assigned physical/mixed location. Do not list records or
sub-aggregations individually. Empty roots show zero and Not specified years;
digital roots have no physical assigned location. Whole-job bounds/counts cover
all records without summing overlapping child totals. Use the application
working timezone and inherited locations; do not substitute creation/current
location fields.

Implementation: document_snapshots captures scoped membership, accumulates
subtree counts/years bottom-up and emits only root rows. External request
creation rechecks years/rows after rendering under existing workflow/resource
locks before saving. Source snapshots retain approved facts; presentation
policy/timezone are separate provenance, preserving old approval fingerprints.
User preference mode uses the generating actor's preference; retries of saved documents preserve their captured language. Organization override and contact settings are captured in generated
fields. Existing immutable request returns bypass regeneration after settings,
preference or template changes. No access rules, tasks or privileges changed.

The default DOCX omits destruction type, internal ID, job-created date,
descendant count, review round and checksum. Internal integrity data remains
stored. Transfer documents are unaffected. The document has portrait details
and a new landscape section with repeating headers and eight readable columns, beginning with continuous serial numbering (1, 2, 3, …).
Changa is embedded in generated PDFs. The repository authoring source and
manifest are updated. Request version names remain provisional; the owner will
choose when to consolidate the accepted draft as v1 and remove previous drafts.

Verification: database-backed tests use fresh disposable databases only. The
full request/settings suite passed 109 cases, including generation/external
routing, contact/name fallback and overrides, Manager language modes,
preference/setting changes with exact saved-request reuse, root-only nested
record counts/date/timezone/location checks, template upload/download/history,
malformed/unsafe templates and a real 120-row PDF retaining its final row.
The final layout/presentation subset passed 47 cases in a second disposable DB.
Both databases were dropped. The shared Settings page, task and screen suite
passed 252 English/Arabic cases. Live isolated Settings previews verified both
language choices and RTL controls without saving live values. Rendered
Arabic-first, Arabic-value and English-value two-page samples were visually
checked with bundled Changa. Ten English keys and Arabic drafts were merged
without replacing existing wording/provenance; no administrator export was
promoted. Drafts require human review before publication.

Local activation: migration 088 applied without changing existing document
checksums/template references. Missing-only Arabic seeding preserved all 3,913
existing translations and added ten unpublished drafts. The managed stack was
restarted healthy. A final six-case presentation rerun passed after adopting
the existing curated Arabic authority name; its disposable database was also
dropped. No contact values, SMTP settings, issued documents or email attempts
were created/changed to exercise these controls. No administrator export was
promoted and no new environment variables were introduced.

27 October follow-up: the option is now **User’s preferred language**, with
“Use the preferred language of the user generating the destruction request.”
It reads the generating actor's preference rather than the approving Manager's.
The persisted `manager_preference` value remains compatible; no setting/data
migration is required. Already saved requests retain their captured presentation.
The root listing begins with `aggregation.serial_number`, numbered continuously
from 1 over the sorted root rows and across page breaks. The section title is
bilingual: “الملفات المطلوب إتلافها” / “Aggregations requested for destruction”. Repository DOCX, builder, contract and checksum manifest
are reconciled.

Verification: 78 request/presentation/template/external tests, three final
layout/catalogue checks and two English/Arabic Settings tests passed. Both
uniquely named disposable databases were dropped. The DOCX was rendered and
both pages visually inspected with embedded Changa; the 120-root PDF test
verified pagination through the final row. English and Arabic active-key,
placeholder and terminology checks passed. Two existing contextual definitions
and their unreviewed machine-generated Arabic drafts changed; no keys were
added or removed, and no administrator export was promoted. Missing-only demo
seeding found no untranslated keys; only those two superseded, unpublished,
unreviewed generated values were corrected. Reviewed/published/manual values
were preserved. Arabic drafts await human review. The managed local stack was
restarted successfully; issued PDFs were not rewritten.

The approved simpler listing heading is now **الملفات المطلوب إتلافها /
Aggregations requested for destruction**. Builder, checked-in DOCX, checksum
manifest, specification and template guide agree. The existing layout assertion
passed in a fresh disposable database (dropped afterward); both pages of the
refreshed demo-settings PDF were visually checked. This is document-template
wording only; no WebUI catalogue keys changed and no issued request was rewritten.

Proposal execution report follow-up: the working report default is v2 (v1
retained). The document contract now supports two independent repeat groups,
validated separately: reviewed roots and executed proposals. Organization name
and language use the same Disposition presentation settings as requests.
Reviewed-root rows include removed roots and subtree originated-year/count and
assigned-location details. Executed-proposal rows use saved result attribution,
readable action/result/reasons and named relationship endpoints; raw technical
references remain in snapshot provenance. No workflow or authorization rule is
changed, and preview rendering never replaces a saved report or replays changes.

Report verification completed: the broad template/approval/external run passed
117 cases and exposed four storage/retry failures caused by adding presentation
metadata inside the protected source execution. That addition was removed;
`source` remains exactly equal to the saved approval execution. A final focused
14-case run passed, including all four storage/retry failures, full supported
proposal-type execution, retained v1, independent groups, a real 40-root/40-proposal
multi-page PDF, removed-all-roots reporting and Manager Only duty labels. Both
disposable databases were dropped. The demo preview contains one reviewed root
and both saved relationship-removal results, with organization and localized
user/role/type values. All three pages were rendered/visually inspected using
embedded Changa. No WebUI keys or environment settings changed; catalogue and
environment-template checks pass. Demo was used read-only for previews; issued
reports and execution history were not rewritten.

Generated record title follow-up: the central artifact save path uses the
existing contract's human-readable Arabic/English document name and job number,
selected using the generating user's enabled language preference. This covers
requests, execution/preparation reports and worker-generated digital certificates.
The worker already acts as its requesting user. Title/language are added to
artifact provenance without changing the protected source snapshot. Component
filenames, PDF bytes and uploaded evidence titles are unaffected. Exact retries
retain original titles, and existing records are not automatically renamed.

Title verification: the broader artifact/report/certificate run passed 24 cases;
two new tests initially read provenance from the command-result envelope rather
than the saved artifact, and one older assertion expected provenance to contain
only its original source key. Those assertions were corrected to inspect the
saved provenance and expect the captured title/language. The final four-case
run passed (all four generated types in both languages, real record creation
and retry preservation in each language, and configured report destination).
Both disposable databases were dropped. Uploaded evidence regression checks,
worker certificate completion/retry and saved report reuse passed. No active UI
message keys, Arabic artifacts, settings, migrations or environment variables
changed; existing bilingual contract labels are reused for generated titles.

Approved scope refinement: the execution report now lists only roots targeted
by saved executed proposals and additional roots removed because of them,
including cascading removals. Unaffected roots without executed proposals are
omitted. The heading is **الملفات المتأثرة بالمقترحات المنفّذة / Aggregations
affected by executed proposals**. The destruction request's complete remaining
root list is unchanged. Eight focused report/template checks passed, covering
cascading removals, omitted unaffected roots, zero-proposal reports, removed-all
jobs and saved report retries; the disposable database was dropped. The refreshed
DT-2026-1 demo preview still contains one affected root and both relationship
removals; all three pages were inspected. Separately, three exact-title checks
passed for **إستمارة إتلاف DT-2026-1**, English titles and unchanged proposal report
titles; that disposable database was dropped too. No existing issued artifact
or stored record title was rewritten.

Organization header follow-up: both working templates use a shared bold
16-point organization-name header, with Arabic complex-script bold enabled and
normal wrapping. The existing unset-name fallback was verified from a job owned
by a descendant department: the root organization name is Arabic in Arabic
mode, English in English mode, and Arabic-first bilingual in bilingual mode;
missing translations use the canonical name. Eight checks passed, including
configured overrides and all template contracts; the disposable database was
dropped. Both refreshed demo PDFs and long bilingual-name DOCX samples were
rendered and inspected on all pages without clipping. Page counts remain two
for the request and three for the execution-report example. No demo settings or
issued documents were changed, and no UI catalogue keys or environment settings
were added.

Serial alignment fix: a repeat-start marker occupied its own paragraph above
the serial number; replacing only the marker text left that paragraph's line
height behind. The filler now removes control-only marker paragraphs while
retaining required cell structure and paragraphs with visible embedded content.
Both working template builders explicitly set data-cell vertical alignment to
top. Eight checks passed, covering first-paragraph serial placement, top cell
alignment, all default contracts, split-run substitution and independent repeat
groups. The disposable database was dropped. Both demo previews were refreshed
read-only and all five pages inspected: serials now align with the top of the
other cells. Existing issued PDFs remain unchanged. No user-facing wording,
catalogue keys or environment settings changed.

27 October — Digital Destruction Certificate working v2

The certificate now shares the request's prominent organization/contact header,
Disposition language policy, job year bounds and numbered root-only aggregation
section: number/title, earliest/latest record year, classification, subtree
record count and assigned physical/mixed location before destruction. It retains
external destruction number, approved request reference, execution/completion
facts, medium counts, physical proof and the §16 integrity value. Internal job
ID/type/creation date, descendant counts and raw scope IDs are omitted from the
default layout. Current names replace raw user IDs in visible confirmation;
permanent executor names remain historical when an account was renamed.

`certificate_presentation.py` reads approved request identification and permanent
proof, not destroyed content. New requests capture root-to-row mapping inside
snapshot source presentation; this is outside strict display-row placeholders.
Only actual destroyed roots are selected, latest approved facts take precedence,
and legacy complete-scope rows are reused only when root scopes match. Missing
historical fields remain unspecified. Root titles/numbers in this evidence are
necessary identification under common disposition §14.2; this does not retain
all former record metadata or add a destroyed-resource search permission/flag.
No schema or migration change was required. Issued PDFs are untouched.

The repository keeps certificate v1 and adds provisional v2, its deterministic
builder and manifest checksum. A real synthetic bilingual PDF rendered as two
pages (portrait details, landscape root table); both pages were visually checked.
The first integration run exposed strict template-row key validation, fixed by
moving the internal mapping into source presentation. A serial-cell test also
incorrectly treated Word row properties as a cell; it now explicitly selects
`w:tc` elements, preserving its alignment/paragraph assertions. Tests ran only
in disposable databases, with cleanup recorded by the runner.

Final certificate verification: 46 template cases passed in the initial run;
the affected completion/serial cases were corrected and 12 passed in disposable
`erms_messaging_test_acl_dc948b82939e43498b1b1d82b3b15efb` (its remaining failure
was the unchanged-source assertion). Preserving that helper's original capture
source while putting runtime request identification in `source.presentation`
resolved it. The source regression and seven request-presentation cases then
passed in `erms_messaging_test_acl_d94f2a5f7c904506ab0ccb75bcfae605`.
All disposable databases from these runs, including the two earlier diagnostic
runs, were dropped cleanly. The 66 distinct template/completion/request cases
are covered by the final passing evidence across those runs. Python compilation,
manifest validation, environment-template and whitespace checks passed. No
persistent job, certificate, approval history or destroyed resource was changed
for testing; the synthetic PDF lives only under ignored `.runtime/`.
