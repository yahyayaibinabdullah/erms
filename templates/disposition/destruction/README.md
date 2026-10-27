# Controlled destruction templates

Four editable, bilingual Arabic-first Word defaults implement destruction-process §§10.1, 11, 14.1, 16 and 17.4. Generated artifacts are PDF. There are no signature or seal blocks.

## Editing and validation

Use Changa for all text. Keep Arabic paragraphs RTL and English/data paragraphs LTR; retain the Arabic-first title and RTL tables. Keep the documented placeholders unchanged. Word may split a placeholder across runs; the validator supports that. Preserve each repeating row, with its opening and closing markers and all row fields together in the same table row. Do not put a mandatory scalar field in a repeating row. Table headers repeat when a report spans pages.

Placeholders use `{{name}}`. A row repeats using `{{#aggregations}}` … `{{/aggregations}}` (request), `{{#proposals}}` … `{{/proposals}}` and an independent `{{#aggregations}}` … `{{/aggregations}}` (execution), or `{{#aggregations}}` … `{{/aggregations}}` (preparation). The certificate repeats `{{#participants}}` … `{{/participants}}`. Markers may occupy separate paragraphs within that row. Control-only marker
paragraphs are removed while filling, so they do not leave blank lines above
serial numbers or below cell content. Data cells are aligned at the top. Do not nest repeating groups. Zero rows removes the prototype; the request snapshot builder rejects empty approved membership. Counts are nonnegative whole numbers. Required scalar values must be present and nonblank; missing locations use **غير محدد / Not specified**, and an inapplicable physical confirmation must explicitly say so.

Templates must be valid DOCX, not renamed files or macro-enabled documents. External relationships, active/embedded objects, tracked changes, DTDs and arbitrary Word field instructions are rejected. Page and total-page fields are supported. Images embedded in the DOCX are retained. Template package expansion and PDF size use the existing API `MAX_RENDITION_SIZE_BYTES`; conversion uses `DOCUMENT_CONVERSION_TIMEOUT_SECONDS` and `LIBREOFFICE_BINARY`.

## Versions and generation

Repository defaults are immutable versioned assets, verified against `defaults.json`. References include the template version and checksum. Request labels are provisional during this greenfield review; the owner will choose when to consolidate the final request as v1 and remove superseded drafts. These files are not runtime upload destinations. No schema or migration invokes a seed.

Authorized Records Officers and Records Managers use job workspace controls to download the current template, inspect/download retained revisions, and upload a new organization-wide revision. Every accepted upload gets its own database row and `revision:<id>:<sha256>` reference, original filename, exact bytes/checksum, user, acting role, user actor type, source job and upload time. The latest revision applies to subsequent generation in all jobs; a concurrent stale upload must refresh. File Administrators and Unit Managers cannot revise templates.

Action services own approvals/execution and supply complete server-owned snapshots. The private generator fills the selected current revision, renders the resulting Word layout with LibreOffice and verifies embedded Changa. It saves PDF bytes, exact template reference/checksum, snapshot and snapshot checksum, renderer details and generation/retry key through governed artifact storage. A committed retry returns the original artifact even after a new upload; changed retry inputs conflict. The caller owns the outer transaction, so a later action failure rolls back its artifact too. Preview, download and future email attachments use those saved PDF bytes, never a fresh render. Earlier PDFs and revisions remain unchanged.

Generated governed records use the document type's Arabic or English title
followed by the job number, according to the generating user's enabled preferred
language. The worker uses its requesting user's identity. This metadata title
is separate from the PDF values-language setting and the component filename.
Arabic destruction-request record titles use the exact approved wording
`إستمارة إتلاف <job number>`; this record-metadata label is separate from the PDF heading.
The saved title/language are captured in provenance; committed retries and
previously saved records retain their original titles. Uploaded evidence is
not renamed by this policy.

## Placeholder inventory

### Request for destruction

Working file: `request-for-destruction.default.v2.docx`. Type: `destruction_request`.
Its version label is provisional during this greenfield review. When the owner
approves the final layout, consolidate the request as v1 and remove superseded
request draft files/references. Do not rewrite issued PDF bytes as a side effect.
`tools/build_request_template_v2.py` is the current reproducible authoring source.

Organization/contact information appears at the top. Both the request and
execution report use a bold 16-point organization-name header. An unset
Disposition organization override uses the tenancy root organization name in
the selected document language (Arabic first in bilingual mode), with canonical
name fallback when a translation is absent. Request details use a
portrait section; the following **Aggregations section** starts on a new,
landscape page with repeating table headers. It is part of the request, not an
appendix. There is one row per active governing root only. Records and
sub-aggregations are not listed separately.

| Visible scalar placeholder | Meaning |
| --- | --- |
| `{{organization.name}}` | Disposition organization override, or tenancy root name |
| `{{organization.email}}` | Records Unit contact email |
| `{{organization.phone}}` | Records Unit contact phone |
| `{{authority.name}}` | External authority name |
| `{{job.number}}` | Destruction job number |
| `{{job.owner}}` | Owning organizational unit |
| `{{job.officer}}` | Assigned Records Officer, or Manager for Manager Only |
| `{{generated_at}}` | Generation date |
| `{{counts.roots}}` | Aggregations |
| `{{records.from_year}}` | Earliest record-originated year over the whole job |
| `{{records.to_year}}` | Latest record-originated year over the whole job |
| `{{counts.records}}` | Whole-job record count, each record counted once |
| `{{counts.physical}}`, `{{counts.digital}}`, `{{counts.mixed}}` | Medium totals |
| `{{review.file_administrator}}`, `{{review.unit_manager}}`, `{{review.records_manager}}` | Internal review summaries |
| `{{form.version}}` | Form version |

Internal job ID, destruction type, job creation date, descendant count, review
round and membership checksum remain server snapshot fields but are optional
in the template and omitted from the destruction request. Transfer-document
checksum requirements are unaffected.

Section heading: **الملفات المطلوب إتلافها / Aggregations requested for destruction**.

Repeating row: `{{#aggregations}}` … `{{/aggregations}}`.

| Row placeholder | Meaning |
| --- | --- |
| `{{aggregation.serial_number}}` | Running serial number from 1, continuous across pages |
| `{{aggregation.number}}` | Root aggregation number |
| `{{aggregation.title}}` | Root title |
| `{{aggregation.from_year}}`, `{{aggregation.to_year}}` | Earliest/latest originated year of records in the entire root subtree |
| `{{aggregation.classification_code}}` | Effective classification number |
| `{{aggregation.records}}` | Total records in root and all sub-aggregations |
| `{{aggregation.assigned_location}}` | Effective assigned location for physical/mixed roots; not applicable for digital roots |

Years use the application working timezone. Empty roots have zero records and
“Not specified” years. Missing physical/mixed locations or contact settings
also show “Not specified”. Settings under Disposition control contact details,
organization override and values language: Arabic-first bilingual by default,
or the generating user's preferred language. Saved entity translations fall
back to canonical text; free text is retained as entered. Policy, timezone and
rendered values are saved with the PDF. Sending and preview use those exact bytes.

### Digital destruction certificate

File: `digital-destruction-certificate.default.v1.docx`. Type: `digital_destruction_certificate`.

| Scalar placeholder | Meaning |
| --- | --- |
| `{{job.number}}` | Destruction job number |
| `{{job.id}}` | Internal job identifier |
| `{{job.type}}` | Destruction type |
| `{{job.owner}}` | Owning organizational unit |
| `{{job.officer}}` | Assigned Records Officer |
| `{{job.created_at}}` | Job creation date |
| `{{generated_at}}` | Document generation date |
| `{{external.destruction_number}}` | Approved external destruction number |
| `{{approved_request.reference}}` | Approved destruction request reference |
| `{{completed_at}}` | Destruction completion time |
| `{{execution.manager}}` | Executing Records Manager |
| `{{execution.scope}}` | Destruction scope |
| `{{counts.roots}}` | Governing root aggregations |
| `{{counts.descendant_aggregations}}` | Descendant aggregations |
| `{{counts.records}}` | Records |
| `{{counts.physical}}` | Physical items |
| `{{counts.digital}}` | Digital items |
| `{{counts.mixed}}` | Mixed items |
| `{{physical.confirmation}}` | Physical destruction confirmation if applicable |
| `{{integrity.value}}` | Completed job integrity value |

### Proposal execution report

File: `proposal-execution-report.default.v2.docx`. Type: `proposal_execution_report`.

| Scalar placeholder | Meaning |
| --- | --- |
| `{{organization.name}}` | Configured disposition organization name, otherwise tenancy root |
| `{{execution.count}}` | Executed proposal count, including zero |
| `{{job.number}}` | Destruction job number |
| `{{job.id}}` | Internal job identifier |
| `{{job.type}}` | Destruction type |
| `{{job.owner}}` | Owning organizational unit |
| `{{job.officer}}` | Assigned Records Officer |
| `{{job.created_at}}` | Job creation date |
| `{{generated_at}}` | Document generation date |
| `{{review.round}}` | Approval review round |
| `{{execution.manager}}` | Executing Records Manager |
| `{{execution.reference}}` | Execution reference |
| `{{membership.checksum}}` | Membership checksum |

Repeating row: `{{#proposals}}` … `{{/proposals}}`.

| Row placeholder | Meaning |
| --- | --- |
| `{{proposal.serial_number}}` | Continuous row number from 1 |
| `{{proposal.change}}` | Readable executed change; relationship endpoints/type for removals |
| `{{proposal.id}}` | Proposal identifier |
| `{{proposal.action}}` | Action |
| `{{proposal.target}}` | Target resource |
| `{{proposal.proposer}}` | Original proposer |
| `{{proposal.result}}` | Execution result |
| `{{proposal.executor}}` | Executor and acting role |
| `{{proposal.reason}}` | Applied reason and its source |
| `{{proposal.removed_units}}` | Units removed because of this proposal |
| `{{proposal.history}}` | Preserved proposal history references |

The report starts with the configured organization and job details, then a
root-aggregation listing with the same eight fields as the destruction request
(serial number, number, title, originated year bounds, classification, record
count and assigned location). It covers roots targeted by executed proposals plus any additional roots
removed as a result, including cascading removals. Unaffected roots without
executed proposals are omitted. The destruction request still lists every root
to be destroyed. It does not list descendant
aggregations or individual records. Repeating group `aggregations` uses the
same row placeholder names as the request.

The executed-proposal listing contains every saved execution result, with
continuous numbering, action/target, readable change, proposer, executor,
result, applied reason/source and removed unit names. Source execution IDs,
history references and checksums remain in the server snapshot; the default
layout omits these technical fields. Each group has independent repeating
headers. The report uses the same Disposition organization/language settings
as the request. Retained v1 downloads and previously generated reports remain
unchanged. Authoring source: `tools/build_proposal_report_v2.py`.

### Physical destruction preparation report

File: `physical-preparation-report.default.v1.docx`. Type: `physical_preparation_report`.

| Scalar placeholder | Meaning |
| --- | --- |
| `{{job.number}}` | Destruction job number |
| `{{job.id}}` | Internal job identifier |
| `{{job.type}}` | Destruction type |
| `{{job.owner}}` | Owning organizational unit |
| `{{job.officer}}` | Assigned Records Officer |
| `{{job.created_at}}` | Job creation date |
| `{{generated_at}}` | Document generation date |
| `{{report.version}}` | Report version |
| `{{membership.checksum}}` | Membership checksum |
| `{{classification.totals}}` | Classification group totals without double counting |
| `{{totals.physical_aggregations}}` | Physical aggregations |
| `{{totals.mixed_aggregations}}` | Mixed aggregations |
| `{{totals.physical_records}}` | Physical records |
| `{{totals.mixed_records}}` | Mixed records |

Section heading: **الملفات المطلوب إتلافها / Aggregations requested for destruction**.

Repeating row: `{{#aggregations}}` … `{{/aggregations}}`.

| Row placeholder | Meaning |
| --- | --- |
| `{{aggregation.classification_code}}` | Terminal classification code |
| `{{aggregation.classification_title}}` | Classification title |
| `{{aggregation.identifier}}` | Aggregation identifier |
| `{{aggregation.title}}` | Aggregation title |
| `{{aggregation.owner}}` | Owning organizational unit |
| `{{aggregation.assigned_location}}` | Assigned location |
| `{{aggregation.current_location}}` | Current location |
| `{{aggregation.descendants.physical_aggregations}}` | Physical aggregations |
| `{{aggregation.descendants.mixed_aggregations}}` | Mixed aggregations |
| `{{aggregation.descendants.physical_records}}` | Physical records |
| `{{aggregation.descendants.mixed_records}}` | Mixed records |

## Summary semantics

Request rows list governing roots only. Iterative subtree accumulation includes descendant records in each root’s count and year bounds without listing descendants. Whole-job counts include each record once. The effective assigned location follows existing inheritance, and rendering rechecks the data under workflow/resource locks before saving.

Preparation rows list every physical/mixed aggregation, including descendants below digital parents, sorted by terminal classification. Row descendant counts exclude that aggregation itself, include its descendant records, and may overlap other rows. Classification and whole-report totals count each aggregation/record once instead of adding those overlapping row summaries. Assigned/current locations follow existing inheritance rules. The full membership/location/count source snapshot is retained with each generated version.

Execution rows retain each proposal result, original proposer, executing Manager and acting role, applied reason/source, removed complete units and preserved change-history references. Certificate fields use the real approved external destruction number and completed-job integrity value; no external number is minted here.

`tools/build_disposition_templates.py` is the authoring source for these initial defaults. Do not run it over released defaults to revise production layouts; use the revision workflow or create a separately versioned repository default.


### Digital destruction certificate working v2

`digital-destruction-certificate.default.v2.docx` is authored reproducibly by
`tools/build_certificate_template_v2.py`; v1 remains downloadable. It is a
concise portrait certificate: prominent organization, bilingual title and
approval/completion statement, participant names and organizational units, and
generation date. It has no aggregation listing or repeated request metadata.

Scalar tokens: `organization.name`, `certificate.statement.ar`,
`certificate.statement.en`, `generated_at`. Statements are populated from the
job number, approved destruction number and permanent digital completion time.
The `participants` repeat row contains `participant.role`, `participant.name`
and `participant.org_unit`. Participants come from completed preparation,
approved decisions in the applicable round, and actual execution proof;
skipped stages do not create rows. Current Disposition language settings apply
to values. Internal snapshot proof and approved request linkage survive this
presentation change; issued PDFs are never replaced by a repository update.

Certificate Arabic terminology: شهادة الإتلاف الرقمي, لجنة الفرز والإتلاف,
and تطبيق وثق. Destruction job is عملية الإتلاف, distinct from a workflow task.
