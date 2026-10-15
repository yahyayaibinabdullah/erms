# Controlled destruction templates

Four editable, bilingual Arabic-first Word defaults implement destruction-process §§10.1, 11, 14.1, 16 and 17.4. Generated artifacts are PDF. There are no signature or seal blocks.

## Editing and validation

Use Changa for all text. Keep Arabic paragraphs RTL and English/data paragraphs LTR; retain the Arabic-first title and RTL tables. Keep the documented placeholders unchanged. Word may split a placeholder across runs; the validator supports that. Preserve each repeating row, with its opening and closing markers and all row fields together in the same table row. Do not put a mandatory scalar field in a repeating row. Table headers repeat when a report spans pages.

Placeholders use `{{name}}`. A row repeats using `{{#groups}}` … `{{/groups}}` (request), `{{#proposals}}` … `{{/proposals}}` (execution), or `{{#aggregations}}` … `{{/aggregations}}` (preparation). The certificate has no repeating group. Markers may occupy separate paragraphs within that row. Do not nest repeating groups. Zero rows removes the prototype; the request snapshot builder rejects empty approved membership. Counts are nonnegative whole numbers. Required scalar values must be present and nonblank; missing locations use **غير محدد / Not specified**, and an inapplicable physical confirmation must explicitly say so.

Templates must be valid DOCX, not renamed files or macro-enabled documents. External relationships, active/embedded objects, tracked changes, DTDs and arbitrary Word field instructions are rejected. Page and total-page fields are supported. Images embedded in the DOCX are retained. Template package expansion and PDF size use the existing API `MAX_RENDITION_SIZE_BYTES`; conversion uses `DOCUMENT_CONVERSION_TIMEOUT_SECONDS` and `LIBREOFFICE_BINARY`.

## Versions and generation

Repository defaults are immutable versioned assets, verified against `defaults.json`. Their reference is `default.v1:<sha256>`. A later default must use a new version while retaining this file. These files are not runtime upload destinations. No schema or migration invokes a seed.

Authorized Records Officers and Records Managers use job workspace controls to download the current template, inspect/download retained revisions, and upload a new organization-wide revision. Every accepted upload gets its own database row and `revision:<id>:<sha256>` reference, original filename, exact bytes/checksum, user, acting role, user actor type, source job and upload time. The latest revision applies to subsequent generation in all jobs; a concurrent stale upload must refresh. File Administrators and Unit Managers cannot revise templates.

Action services own approvals/execution and supply complete server-owned snapshots. The private generator fills the selected current revision, renders the resulting Word layout with LibreOffice and verifies embedded Changa. It saves PDF bytes, exact template reference/checksum, snapshot and snapshot checksum, renderer details and generation/retry key through governed artifact storage. A committed retry returns the original artifact even after a new upload; changed retry inputs conflict. The caller owns the outer transaction, so a later action failure rolls back its artifact too. Preview, download and future email attachments use those saved PDF bytes, never a fresh render. Earlier PDFs and revisions remain unchanged.

## Placeholder inventory

### Request for destruction

File: `request-for-destruction.default.v1.docx`. Type: `destruction_request`.

| Scalar placeholder | Meaning |
| --- | --- |
| `{{authority.name}}` | External authority name |
| `{{job.number}}` | Destruction job number |
| `{{job.id}}` | Internal job identifier |
| `{{job.type}}` | Destruction type |
| `{{job.owner}}` | Owning organizational unit |
| `{{job.officer}}` | Assigned Records Officer |
| `{{job.created_at}}` | Job creation date |
| `{{generated_at}}` | Document generation date |
| `{{counts.roots}}` | Governing root aggregations |
| `{{counts.descendant_aggregations}}` | Descendant aggregations |
| `{{counts.records}}` | Records |
| `{{counts.physical}}` | Physical items |
| `{{counts.digital}}` | Digital items |
| `{{counts.mixed}}` | Mixed items |
| `{{review.file_administrator}}` | File Administrator review summary |
| `{{review.unit_manager}}` | Unit Manager review summary |
| `{{review.records_manager}}` | Records Manager approval summary |
| `{{review.round}}` | Approval review round |
| `{{form.version}}` | Form version |
| `{{membership.checksum}}` | Approved membership checksum |

Repeating row: `{{#groups}}` … `{{/groups}}`.

| Row placeholder | Meaning |
| --- | --- |
| `{{group.classification_code}}` | Classification code |
| `{{group.classification_title}}` | Classification title |
| `{{group.rule_source}}` | Retention rule source |
| `{{group.final_disposition}}` | Effective final disposition |
| `{{group.current_years}}` | Current period in years |
| `{{group.intermediate_years}}` | Intermediate period in years |
| `{{group.roots}}` | Governing root aggregations |
| `{{group.descendant_aggregations}}` | Descendant aggregations |
| `{{group.records}}` | Records |
| `{{group.physical}}` | Physical items |
| `{{group.digital}}` | Digital items |
| `{{group.mixed}}` | Mixed items |

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

File: `proposal-execution-report.default.v1.docx`. Type: `proposal_execution_report`.

| Scalar placeholder | Meaning |
| --- | --- |
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
| `{{proposal.id}}` | Proposal identifier |
| `{{proposal.action}}` | Action |
| `{{proposal.target}}` | Target resource |
| `{{proposal.proposer}}` | Original proposer |
| `{{proposal.result}}` | Execution result |
| `{{proposal.executor}}` | Executor and acting role |
| `{{proposal.reason}}` | Applied reason and its source |
| `{{proposal.removed_units}}` | Units removed because of this proposal |
| `{{proposal.history}}` | Preserved proposal history references |

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

Request rows group governing roots by terminal classification and effective retention values. Classification rules and local overrides remain separate; differing override values get separate rows. Root/descendant/record and physical/digital/mixed counts come from the exact source membership snapshot.

Preparation rows list every physical/mixed aggregation, including descendants below digital parents, sorted by terminal classification. Row descendant counts exclude that aggregation itself, include its descendant records, and may overlap other rows. Classification and whole-report totals count each aggregation/record once instead of adding those overlapping row summaries. Assigned/current locations follow existing inheritance rules. The full membership/location/count source snapshot is retained with each generated version.

Execution rows retain each proposal result, original proposer, executing Manager and acting role, applied reason/source, removed complete units and preserved change-history references. Certificate fields use the real approved external destruction number and completed-job integrity value; no external number is minted here.

`tools/build_disposition_templates.py` is the authoring source for these initial defaults. Do not run it over released defaults to revise production layouts; use the revision workflow or create a separately versioned repository default.
