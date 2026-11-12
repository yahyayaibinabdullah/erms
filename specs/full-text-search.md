# Full-Text Content Search — Implementation Specification

**Status:** Approved
**Project:** ERMS / Wathiq  
**Prepared:** 24 September 2026  
**Revision:** 0.35 — Accurate extractor failure classification

### Revision history

| Revision | Date | Change |
| --- | --- | --- |
| 0.35 | 25 September 2026 | Reserved `corrupt` for affirmative malformed-content evidence and required Tika process, JVM, fork-initialization and local-communication failures to be reported as retryable `extractor_unavailable` outcomes |
| 0.34 | 25 September 2026 | Added current-failure diagnostics, permission-aware record/component links, and an aggregate list of currently unsupported formats to Text Indexers Health |
| 0.33 | 25 September 2026 | Separated currently failed search documents from retained failed-job history in Health/readiness and added a privilege-gated bounded retry action for current failures |
| 0.32 | 25 September 2026 | Required the local stack and production deployment artifacts to run one supervised API-owned indexing/credential maintenance process with an hourly default interval |
| 0.31 | 25 September 2026 | Added explanatory text for the protected text-indexer service role, server-side credential-history pagination, and bounded automatic cleanup of revoked and expired credential rows after configurable retention |
| 0.30 | 25 September 2026 | Made built-in roles visible as read-only entries in ordinary Roles administration and linked the text-indexer role to its dedicated workflow |
| 0.29 | 25 September 2026 | Defined one text-indexer service per deployment as a supervisor-owned process pool controlled by `TEXT_INDEXER_PROCESS_COUNT`, with one claimed job per child process and generated unique worker IDs |
| 0.28 | 25 September 2026 | Fixed each text-indexer process to one claimed job at a time and required extraction concurrency to use independently supervised worker processes with unique IDs |
| 0.27 | 25 September 2026 | Added a dedicated privilege-gated Text Indexers Health section exposing privacy-safe worker, queue, failure, drift, stale-document, lease-recovery and rollout-readiness state |
| 0.26 | 25 September 2026 | Replaced generic service-account provisioning with a dedicated Text Indexers administration workflow and dedicated `identity.text_indexers.administer` privilege granted by default only to `ALL_PRIVS` and `SYS_ADMIN` |
| 0.25 | 25 September 2026 | Restored `roles.is_system` for consistency with built-in `profiles.is_system`; clarified that it denotes implementation-owned authorization objects, not the System Administrator role |
| 0.24 | 25 September 2026 | Renamed the protected non-organizational role discriminator from `is_system` to `is_platform_role` to avoid confusion with the System Administrator role |
| 0.23 | 24 September 2026 | Required the complete checksum-pinned official Apache Tika binary distribution with Pipes fork isolation; prohibited Homebrew Tika and Docker as indexer runtime dependencies |
| 0.22 | 24 September 2026 | Recorded the approved Phase 0 format allowlist, extraction/OCR/language quality gates, benchmark-derived initial limits, detector decision, and valid PostgreSQL 18 configuration precondition SQL |
| 0.21 | 24 September 2026 | Approved as the normative product and engineering contract |
| 0.1 | 24 September 2026 | Initial proposed full-text content-search design |
| 0.2 | 24 September 2026 | Added separately provisioned non-interactive indexer identities, a service-only indexing privilege, workload credentials, endpoint restrictions, and related verification requirements |
| 0.3 | 24 September 2026 | Added header/results screen designs and clarified lease-scoped access across ACLs and security levels, credential audiences, and optional local credential storage |
| 0.4 | 24 September 2026 | Added the service-account details-page design for generating, revealing once, rotating, listing, and revoking text-indexer API keys |
| 0.5 | 24 September 2026 | Defined the dedicated text-indexer launcher, configuration, health behavior, and integration with `run-local-stack.sh` |
| 0.6 | 24 September 2026 | Embedded the conceptual search-results, service-account credential-management, and one-time API-key reveal screen designs |
| 0.7 | 24 September 2026 | Made full-text matching a first-class controlled JSON search predicate that can be combined with structured field filters and Boolean expressions |
| 0.8 | 24 September 2026 | Added an opt-in, privileged UI/API facility for inspecting the exact sanitized search request and server-validated canonical JSON query |
| 0.9 | 24 September 2026 | Replaced JWT/mTLS/workload-identity alternatives with one opaque API-key design and made forced-reindex and query-debug profile grants explicit |
| 0.10 | 24 September 2026 | Added a concrete API-key, database-row, request-header, hashing, and verification example |
| 0.11 | 24 September 2026 | Assigned automatic indexing-history and staging cleanup to a dedicated API-side database maintenance process rather than the text-indexer service |
| 0.12 | 24 September 2026 | Linked indexing history, staging, and temporary-file cleanup into the centralized operational cleanup catalogue |
| 0.13 | 24 September 2026 | Required confidence-aware language detection and mixed-language handling, and renamed the forced-reindex privilege to `record.component.reindex` to match the established component privilege namespace |
| 0.14 | 24 September 2026 | Confirmed the `record.component.reindex`/`content.index.execute` privilege split, documented the opaque-API-key security posture and required controls, and required verified use of PostgreSQL's built-in Arabic text-search configuration |
| 0.15 | 24 September 2026 | Declared this specification normative and required phase-exit and final requirement-to-implementation-to-test reconciliation; recorded approval to use PostgreSQL 18's built-in Arabic configuration unchanged |
| 0.16 | 24 September 2026 | Documented LibreOffice PDF preview support for Markdown, MSG, EML and HTML, while deferring bounded Python fallbacks and preserving Tika as the normative extraction path |
| 0.17 | 24 September 2026 | Replaced direct LibreOffice MSG preview conversion with timeout-bounded `extract-msg` plain-text extraction into inert UTF-8 HTML before PDF conversion; full-text indexing remains Tika-based |
| 0.18 | 24 September 2026 | Added bounded standard-library MIME decoding for EML preview and LibreOffice preview allowlisting for TXT and XML; full-text indexing remains Tika-based |
| 0.19 | 24 September 2026 | Replaced direct LibreOffice XML import with a bounded encoding-aware, escaped XML source view before PDF conversion; full-text indexing remains Tika-based |
| 0.20 | 24 September 2026 | Added preview-only detection and A4 landscape one-page-wide normalization for XLSX worksheets wider than their printable area; authoritative files and indexing remain unchanged |

## 1. Purpose

This specification defines system-wide full-text search over governed Wathiq
resources. It covers asynchronous extraction and indexing of digital-component
content, weighted indexing of record and aggregation metadata, explicit
reindexing, header search, authorization-safe results, operational controls,
and verification.

The feature extends the existing controlled JSON search grammar. Full-text
predicates can be combined in one expression tree with the existing equality,
range, set, null, controlled wildcard, and Boolean predicates. The dedicated
global-search endpoint and header UI are convenience surfaces over the same
grammar rather than a second incompatible query language.

### 1.1 Normative status and implementation traceability

Once approved, this specification is the normative product and engineering
contract for the feature. The words **shall**, **must**, **must not**,
**required**, and the decisions and acceptance criteria in this document are
binding requirements. A delivery phase may implement only its assigned subset,
but phasing does not weaken, silently defer, replace, or remove any requirement.
Any product-level departure, substitution, new behavior, or deferral requires
an explicit specification revision approved by the product owner before the
departing implementation is accepted.

Implementation shall maintain
`docs/full-text-search-implementation-traceability.md` from Phase 0 onward. Its
matrix shall contain, at minimum:

| Field | Required content |
| --- | --- |
| Requirement | Acceptance ID where one exists, plus the exact specification section and concise requirement text |
| Planned phase | The phase responsible for delivering it |
| Implementation evidence | Concrete schema, migration, backend, worker, UI, configuration, or documentation file and symbol/object references |
| Verification evidence | Concrete automated test names and any required corpus, security-review, operational, or live-browser evidence |
| Status | `not_started`, `in_progress`, `implemented`, `verified`, or `approved_deferred` |
| Notes | Approved specification revision for any deferral or departure; ordinary omissions cannot be labelled deferred |

Before a phase begins, its requirements shall be enumerated from the complete
specification—not only from the acceptance-criteria table. Before that phase is
declared complete, a phase-exit reconciliation shall verify both directions:

1. every requirement assigned to the phase maps to implementation and
   proportionate verification evidence, with no unexplained omission; and
2. every material implementation behavior maps back to an approved requirement,
   with no invented privilege, workflow, state, API contract, or UI behavior.

The phase-exit report shall list unresolved requirements and approved deferrals
explicitly. A phase cannot be declared complete merely because its tests pass.
Database-backed evidence must use the repository's required uniquely named
disposable database and report cleanup success or failure.

After the final phase, a full-specification reconciliation shall repeat this
check across every normative section and acceptance criterion, including work
delivered in earlier phases. The feature is complete only when every applicable
matrix row is `verified`, every approved deferral has either been implemented
and verified or remains explicitly approved for a later specification, fresh
schema/migration parity is proven, and no implementation behavior lacks an
approved requirement. The final traceability document is part of the delivery,
not optional project notes.

## 2. Product decisions

### 2.1 Record metadata is included

**Decision: yes.** Record number, title, and description shall be searchable in
addition to digital-component content. Users commonly know a record by its
title or identifier rather than by words inside its files. Metadata and content
shall remain separate indexed sources so that:

- metadata changes do not cause file extraction;
- ranking can give metadata stronger weight than body text; and
- results can explain whether the match came from record metadata, one or more
  components, or both.

The initial weights are:

| Source | Weight |
| --- | --- |
| Record number | A |
| Record title | A |
| Digital-component file name | B |
| Record description | B |
| Extracted component body text | D |

Dates, checksums, storage keys, internal IDs, lifecycle state, security labels,
audit data, and authorization data shall not be placed in the full-text vector.
They remain available through structured search where applicable.

### 2.2 Aggregation metadata is included

**Decision: yes.** Aggregation number, title, and description shall be
searchable. Aggregations shall appear as their own result type, not as synthetic
records and not as inherited text on every descendant record. Copying ancestor
metadata into every record would create misleading matches and expensive
cascading reindexing after an aggregation edit.

The unified results page shall group or clearly label **Aggregations** and
**Records**. A matching record result may contain matching digital components.
An aggregation result navigates to the existing aggregation detail page; a
record result navigates to the existing record detail page.

Aggregation number and title use weight A; description uses weight B.

### 2.3 Extraction technology

**Decision: use Apache Tika as the primary extraction service, with Tesseract
OCR enabled for supported images and image-only PDF pages.** Tika detects media
types from bytes and provides a common extraction interface for PDF, Microsoft
Office, OpenDocument, RTF, plain text, HTML, email, and many other formats. It
also integrates with Tesseract when OCR is configured.

LibreOffice shall remain available for preview rendition and may be a bounded
fallback for a deliberately tested allowlist of legacy office formats that Tika
cannot parse satisfactorily. It shall not be the primary text extractor.
LibreOffice conversion alone does not OCR images or scanned PDFs, and its text
export filters do not offer one consistent extraction contract across document,
spreadsheet, and presentation formats.

Preview rendition is separate from extraction. The application preview path
supports Markdown (`.md`), Outlook Message (`.msg`), Internet Message (`.eml`),
HTML (`.html`), plain text (`.txt`) and XML (`.xml`) through PDF conversion. MSG uses a timeout-bounded
`extract-msg` subprocess to escape message metadata and the plain-text body
into inert UTF-8 HTML before LibreOffice conversion. EML uses the same bounded
path with Python's standard email parser to decode MIME and transfer encoding,
prefer plain text and reduce HTML-only messages to visible inert text. XML
preview detects its declared encoding and renders the escaped source without
parsing entities or applying stylesheets. Wide XLSX worksheets are detected
from used column widths and normalized only in a temporary preview copy to A4
landscape and one page wide. Other Python preview fallbacks are
deferred: a future implementation may use
Python-Markdown followed by controlled WeasyPrint rendering,
subject to the sanitization, resource isolation, external-resource denial,
attachment and Arabic/RTL requirements in the segmented-content storage
specification. Tika remains the normative indexing text-extraction mechanism
for these formats.

The extractor shall run in a separately deployable backend service rooted at
`backend/services/text_indexer/`. The underscore is intentional so the
directory is also a valid Python package. The service may run on the API host
or on one or more separate servers. It communicates with
`backend/services/api` only through authenticated internal REST endpoints and
has no direct PostgreSQL credentials or database connectivity.

Each text-indexer instance runs Tika and Tesseract in a sandboxed worker process
with no general outbound network access, a read-only runtime, a private
temporary directory, and explicit CPU, memory, input-size, output-size,
page-count, embedded-object-count, recursion-depth, and wall-time limits.
Untrusted documents must never be parsed by a long-lived API or text-indexer
Python process.

The runtime shall use the complete official Apache Tika binary distribution,
including its adjacent libraries and `tika-pipes-fork-parser` implementation,
with a pinned version and verified published checksum. It shall invoke Tika's
Pipes fork mode so parsing occurs in a disposable, resource-bounded child JVM.
Running a thin standalone JAR, relying on Homebrew's Tika packaging, embedding
Tika in the Python process, or requiring Docker/container execution is
prohibited. Local development and deployed indexers use the same distribution
layout and fork-isolation semantics. The configured distribution may be
provisioned by the deployment system or installed into the indexer's dedicated
runtime directory; it must never be downloaded implicitly while processing a
job.

The first deployment shall install only required Tika parsers and Tesseract
language packs. English and Arabic are required initial OCR languages. OCR
language selection shall be configurable; adding a language pack is an
operational change, not a schema change.

### 2.4 Full text extends the controlled JSON grammar

**Decision: full-text matching is a new expression leaf in the existing search
grammar, not a separate filter language.** A record search can therefore ask,
for example, for records in selected aggregations, originating within a date
range, whose metadata or component content matches a full-text query. Boolean
`and`, `or`, and `not` continue to compose the complete expression.

The existing resource-specific field allowlists remain authoritative. Adding a
full-text leaf does not permit clients to submit SQL, table/column names,
PostgreSQL text-search configurations, weights, dictionaries, or raw `tsquery`
syntax.

### 2.5 Search diagnostics are explicit and privileged

**Decision: authorized support/development users may opt in to seeing the exact
search request sent to the backend and the validated canonical JSON query used
by the API.** Diagnostics are hidden and disabled by default, including for a
user who possesses the privilege. Enabling them does not change the query,
ranking, result set, or authorization policy.

Diagnostics expose the controlled API contract, not database internals. They
must never expose SQL text, bound SQL parameters as a separate database trace,
query plans, table/view names not already public in the API contract, hidden
authorization predicates, session cookies, bearer/API keys, CSRF tokens,
database credentials, lease tokens, or results the user cannot otherwise see.

### 2.6 Initial format allowlist and Phase 0 quality gates

The initial extraction allowlist is PDF; DOC and DOCX; XLS and XLSX; PPT and
PPTX; ODT, ODS and ODP; RTF; UTF-8 plain text and CSV; HTML; XML; Markdown;
EML; MSG; PNG; JPEG; and TIFF. Detection remains byte-based: an extension or
submitted MIME type alone never makes content eligible for a parser. Archive
formats and embedded objects are not indexed in the initial release. A format
outside this allowlist is `unsupported` until an approved specification
revision adds its corpus and security evidence.

The Phase 0 corpus establishes these minimum release quality gates:

| Measurement | Minimum |
| --- | ---: |
| English native-text word recall | 98% |
| Arabic native-text word recall | 95% |
| English OCR word recall | 90% |
| Arabic OCR word recall | 75% |
| Unique-marker retrieval for native text and OCR | 95% |
| Dominant English/Arabic and mixed/unknown language-policy decision accuracy | 90% |
| Corrupt/protected fixture bounded termination with no extracted-content publication | 100% |

Word recall is measured against normalized ground truth after Unicode and
whitespace normalization; punctuation-only differences do not count as lost
words. OCR gates are evaluated separately by language on 300-DPI-equivalent
fixtures. A corpus run fails when an aggregate falls below its gate or when
one supported format has a systemic zero-extraction failure hidden by the
aggregate. Phase 0 evidence is recorded in
`docs/full-text-search-phase-0-benchmark.md`; Phase 2 must repeat the gates with
the approved official binary distribution and deployed process sandbox before
rollout.

The approved local language detector is `lingua-language-detector` 2.1.1,
restricted to English and Arabic models and operated without network access.
The decision layer requires at least 40 alphabetic characters, at least 80%
detector confidence, at least 90% supported-script coverage, and a dominant
Latin-or-Arabic script share above the corpus-calibrated mixed-language
boundary. Short, numeric, code-like, unsupported-script, low-confidence, and
mixed inputs use `pg_catalog.simple`. The exact mixed-language boundary is a
versioned index-configuration value, not a client setting, and must continue
to meet the Phase 0 decision-accuracy gate when corpus composition changes.

## 3. Scope

This feature includes:

- automatic indexing of each available digital component's active content;
- a separately deployable `backend/services/text_indexer/` service and the
  internal REST contract through which any number of instances obtain work;
- PostgreSQL-backed content today and the existing storage-provider interface
  as the boundary for future S3-backed content;
- record and aggregation metadata indexing;
- immutable indexing-attempt history and current indexing state;
- component-level and record-level forced reindex actions;
- a global header search entry point and dedicated results page;
- a backwards-compatible `full_text` leaf in the controlled JSON search grammar
  for combined structured and content queries;
- optional privilege-gated search diagnostics for inspecting the JSON request
  issued by the UI and the canonical JSON accepted by the API;
- relevance ranking, match attribution, snippets, pagination, and explicit
  indexing/failure states;
- authorization filtering before result data is returned;
- database, worker, API, UI, security, and operational tests; and
- metrics, cleanup, recovery, and deployment documentation.

This feature does not include semantic/vector embeddings, fuzzy spelling,
synonyms, faceted search, searching draft uploads, searching superseded content,
audio/video transcription, handwriting recognition, translation, searching
inside encrypted/password-protected documents, or S3 implementation.

## 4. Domain rules

1. Only the active, verified content set of an `available` digital component is
   eligible for indexing and search.
2. A component search document belongs to exactly one digital component, one
   record, and one active content set. The relationships use foreign keys, not
   an unenforced polymorphic identifier.
3. The content identity is the active content set's checksum algorithm and
   checksum value. A storage location or blob row ID is not a content identity.
4. Normal scheduling skips a component when the same content identity,
   extraction configuration version, index configuration version, and extractor
   version have already completed successfully.
5. A user-requested reindex is forced: it creates a new attempt even when the
   identity is unchanged. The current searchable version remains live until the
   replacement succeeds.
6. Replacing or deleting content makes an index for the former active content
   set ineligible immediately. Stale text must never remain searchable while a
   replacement is queued or being processed.
7. A failed extraction never destroys the last index for the same still-active
   content identity. Failure is visible in state and history.
8. Indexing changes do not change the record/component business `version`,
   originated date, lifecycle state, or content checksum.
9. Search results and snippets disclose no resource, component, count, or text
   that the current principal is not authorized to view.
10. Extracted text and snippets are governed content. They receive the same
    database, backup, retention, deletion, and access protections as the source
    component and must not be written to ordinary application logs or event
    history.
11. Draft content and incomplete, failed, quarantined, deleted, staged, or
    superseded content sets are not indexed.
12. Search is eventually consistent. Metadata indexing is transactionally
    refreshed with metadata changes; binary-content extraction is asynchronous.
13. Text-indexer services never connect directly to the ERMS database. The API
    owns all queue transitions, source-content access, validation, vector
    construction, and result publication.
14. At most one unexpired lease may authorize work for a particular indexing
    job. A stale or superseded lease can never publish output, even if its
    original worker finishes later.

## 5. Service architecture

The feature has three deployment roles:

```text
Wathiq UI / reindex request
            |
            v
backend/services/api  <---->  PostgreSQL queue, state, chunks and history
            ^
            | authenticated internal REST; no shared filesystem required
            |
   +--------+----------------+
   |                         |
text-indexer instance A   text-indexer instance B ... N
   |                         |
Tika + Tesseract          Tika + Tesseract
```

`backend/services/api` remains the trust and consistency boundary. It creates
jobs in the same transaction that activates or replaces content, atomically
leases jobs, streams authorized source bytes, accepts bounded extracted-text
chunks, builds PostgreSQL vectors, and publishes results. A text-indexer is a
replaceable compute client: it detects/extracts text and reports a result, but
it cannot decide which content set is active or make database changes itself.

Each instance has a stable configured `worker_id` unique to that running
instance and advertises its extractor version, configuration version,
supported formats, OCR languages, and processing limits when claiming work.
The API does not assign an incompatible job to an instance. Worker identity is
diagnostic; possession of the current random lease token is what authorizes a
heartbeat, content stream, staged result, or completion.

Internal endpoints use ordinary HTTPS and a dedicated service identity with an
opaque Wathiq API key. The solution does not require JWTs, client certificates,
mutual TLS, a public-key infrastructure, or private-key lifecycle management.
The normal reverse proxy/server certificate used for HTTPS protects the API key
in transit. An interactive user session, the `record.component.reindex` privilege, or
knowledge of a job ID does not grant access to internal worker endpoints. The
API key permits entry only to the internal text-indexing route group; the job
lease then limits access to one exact unit of work.

This authentication design is the approved baseline for deployments in which
the API and text-indexer communicate within a controlled, segmented network.
It is a bearer-credential design: possession of a valid key is sufficient to
authenticate as its service account until that credential expires or is
revoked. HTTPS protects the credential and component content in transit, but
does not protect a key copied from a compromised indexer host, deployment
system, process environment, backup, or log. The secure network is therefore
defence in depth and is not itself an authentication mechanism.

The baseline is considered proportionate only when all of these controls are
enforced:

- HTTPS is mandatory end to end and the indexer validates the API server's
  certificate and host name; disabling certificate verification is prohibited;
- HTTP is disabled or redirected before any credential can be accepted, and
  TLS termination plus any internal proxy hop remain within the trusted
  deployment boundary;
- every environment and independently administered indexer deployment or pool
  has a distinct credential; development, test, staging, and production keys
  are never shared;
- keys have cryptographically random 256-bit secrets, bounded expiry,
  independent revocation, rotation with a deliberately bounded overlap, and
  safe last-used/audit metadata;
- the complete key is injected through the deployment's protected secret
  mechanism, never committed to source control, an image, ordinary
  configuration, backup output, command line, URL, metric, trace, or log;
- network policy permits indexers to reach only the necessary internal API and
  restricts the internal text-indexing routes from untrusted networks;
- middleware accepts the credential only for
  `/api/v1/internal/text-indexing/*`, requires an active service account and
  `content.index.execute`, applies rate limits, and emits redacted security
  telemetry;
- job ID, current lease token, lease generation, expected component/content
  identity, size limits, and state transition are authorized separately on
  every content-read and result-write operation; and
- credential authentication failures, unusual request rates, revocations,
  expiry, and worker activity are monitored without recording secrets or
  extracted content.

The opaque key is not the sole protection for sensitive content: least
privilege, route isolation, lease fencing, content-identity checks, network
segmentation, process sandboxing, resource limits, and auditing form the rest
of the control set. Mutual TLS or a managed workload-identity system remains a
future hardening option if indexers later cross an untrusted network, run under
unrelated administrative control, or become subject to a requirement for
proof-of-possession credentials. Such a change is not required by this
baseline and requires a separately approved specification revision.

### 5.1 Non-interactive text-indexer service accounts

Every deployed text-indexer instance or trusted group of identically operated
instances shall authenticate as an explicitly provisioned Wathiq service
account. Anonymous workers, shared human accounts, person-account sessions,
database accounts, and the API server's own runtime identity are prohibited.

The stored account shall have:

- `users.account_type = 'service'`;
- `status = 'active'` while the deployment is authorized;
- a unique, descriptive name and immutable external identifier that identifies
  the deployment, such as its environment and indexer pool;
- no interactive password, temporary password, browser login session, password
  reset path, or MFA recovery path; and
- one dedicated role/profile assignment containing only the new global
  privilege `content.index.execute`.

`content.index.execute` authorizes use of the internal text-indexing worker
contract only. It does not authorize the public reindex operations, global
search, ordinary record or aggregation APIs, content download/view endpoints,
audit access, user administration, authorization administration, or direct
database access. The internal endpoints shall additionally require
`account_type = 'service'`; assigning the privilege to a person account must
not make those endpoints usable by that person.

The canonical privilege catalogue shall define:

| Code | Account restriction | Purpose |
| --- | --- | --- |
| `content.index.execute` | Active service accounts only | Claim leased indexing jobs and, within the scope of the current lease, heartbeat, retrieve that job's exact source content, stage extracted chunks, and report terminal status |

The canonical seed shall create a protected profile named **Text Indexer
Service** with code `TEXT_INDEXER_SERVICE` containing exactly
`content.index.execute`. The privilege must also be added to the protected
`ALL_PRIVS` compatibility profile to preserve the catalogue invariant, but
internal indexing endpoints still reject person accounts and credentials with
the wrong credential type. No record, aggregation, component, audit, search, identity,
organization, security, classification, governance, or hold privilege is added
to `TEXT_INDEXER_SERVICE`.

The human and service privileges are intentionally distinct and approved as:

| Privilege | Principal | Meaning |
| --- | --- | --- |
| `record.component.reindex` | Authorized person account | Request a forced reindex of one component or all eligible components in one record, subject to the additional resource authorization and clearance gates in section 9.4 |
| `content.index.execute` | Active text-indexer service account only | Execute the lease-scoped internal extraction protocol; it cannot request arbitrary reindexing or use ordinary content APIs |

Provisioning and managing text-indexer identities uses the dedicated **Text
Indexers** administration API and UI and requires the global privilege
`identity.text_indexers.administer`. The canonical seed grants this privilege
only to the protected `ALL_PRIVS` and `SYS_ADMIN` profiles. It is not granted
to `INFO_GOV_MGR`, `INFO_GOV_OFFICER`, or `TEXT_INDEXER_SERVICE`; custom
profiles receive it only through an explicit authorization-administration
change.

The dedicated create operation atomically creates an active non-interactive
service account, assigns the protected `text-indexer-service` role as its sole
role, and issues its initial server-generated API key. The administrator
supplies a descriptive deployment/pool name, immutable unique external
identifier, credential name, and expiry. Multiple identities are supported for
environment and pool separation. A failed account, assignment, or credential
step rolls back the complete operation.

Generic user and role administration must not create, mutate, delete, or alter
the protected assignment of a text-indexer identity. Text-indexer account
status and credential lifecycle are managed only through the dedicated
workflow. The protected role/profile remains implementation-owned and is not
selectable in ordinary role-assignment controls.

If the existing UI/API cannot safely create the protected role/profile
assignment without also granting organizational resource access, the migration
shall create a protected system role for this sole purpose. The role is
identified by `roles.is_system`, consistently with built-in profiles; this
denotes an implementation-owned role and does not mean the ordinary System
Administrator role. That role is not an
organizational custodian, does not satisfy access-continuity requirements, and
must not be selectable for person accounts. This exception must be represented
explicitly in schema and authorization rules rather than simulated with a
broad ordinary role.

### 5.2 Opaque API keys and endpoint authentication

The authentication subsystem shall add one simple non-interactive mechanism:
a high-entropy opaque API key issued by Wathiq for a service account. The key is
not a JWT and contains no claims. It is an unstructured secret with a non-secret
lookup identifier, conceptually:

```text
wti_<credential_identifier>.<random_secret>
```

The full key is displayed once. The API stores the identifier and a one-way
hash of the random secret, never the plaintext. The indexer sends it through
the standard header:

```http
Authorization: Bearer wti_<credential_identifier>.<random_secret>
```

Dedicated authentication middleware is mounted only on
`/api/v1/internal/text-indexing/*`. Public and unrelated internal routes do not
accept this credential type at all. This route restriction replaces the
earlier, unnecessarily abstract "audience" concept. Authentication checks the
key hash, credential status and expiry, service-account type and status, and
`content.index.execute` before evaluating a job lease.

#### 5.2.1 Concrete credential example

The following is an illustrative credential and must never be configured as a
real key:

```text
wti_01J8Z6M4K7Q2N9V5T3R8C1D0PX.m8GQ1zvF4Kj2Nw6Yx9P_s3Bc7Hd0La5RtUeViAoCqMk
```

It consists of:

```text
prefix                 wti_
credential identifier  01J8Z6M4K7Q2N9V5T3R8C1D0PX
separator              .
random secret           m8GQ1zvF4Kj2Nw6Yx9P_s3Bc7Hd0La5RtUeViAoCqMk
```

The `wti_` prefix identifies a Wathiq text-indexer key and prevents it from
being confused with another credential type. The credential identifier is
unique and non-secret. It permits one indexed database lookup and may appear in
the administration UI, security events, and safe operational diagnostics. The
random secret is generated by a cryptographically secure random generator from
at least 32 random bytes (256 bits) and encoded as unpadded Base64url. A 32-byte
secret produces 43 Base64url characters.

The API returns the complete value only once when the administrator generates
or rotates a key. The text-indexer stores that complete value in its protected
deployment secret or environment configuration:

```ini
TEXT_INDEXER_API_KEY=wti_01J8Z6M4K7Q2N9V5T3R8C1D0PX.m8GQ1zvF4Kj2Nw6Yx9P_s3Bc7Hd0La5RtUeViAoCqMk
```

It presents the complete value on every internal request:

```http
POST /api/v1/internal/text-indexing/jobs/claim
Authorization: Bearer wti_01J8Z6M4K7Q2N9V5T3R8C1D0PX.m8GQ1zvF4Kj2Nw6Yx9P_s3Bc7Hd0La5RtUeViAoCqMk
Content-Type: application/json
```

The API hashes only the exact ASCII bytes of the presented Base64url
random-secret substring—not the `wti_` prefix, identifier, separator, decoded
random bytes, or complete bearer value—with SHA-256. For the illustrative
secret above, the stored digest is:

```text
f4380efd724ea87ca6cfe53ce595e038aaaad28c1fe58fac23d6234f3b1611fe
```

The corresponding database row is conceptually:

```text
id                     184
service_user_id        37
credential_identifier  01J8Z6M4K7Q2N9V5T3R8C1D0PX
secret_hash            f4380efd724ea87ca6cfe53ce595e038aaaad28c1fe58fac23d6234f3b1611fe
status                 active
date_created           2026-09-24T10:30:00Z
expires_at             2026-12-24T10:30:00Z
last_used_at           2026-09-24T11:42:00Z
date_revoked           NULL
created_by_user_id     4
revoked_by_user_id     NULL
```

The database never stores the random secret or complete bearer value. A salt or
password-strengthening hash is unnecessary for this field because the secret
is not human-chosen and has at least 256 bits of cryptographic entropy; unlike a
password, it is not vulnerable to a practical dictionary or brute-force attack.
The implementation must reject shorter or malformed secrets rather than hash
them. Password credentials continue to use their existing password-specific
hashing policy and are not affected by this decision.

For each request, the API:

1. requires the `Bearer` scheme and `wti_` prefix;
2. parses exactly one identifier/secret separator and applies strict length and
   Base64url character limits before database access;
3. looks up the credential by its non-secret identifier;
4. verifies that the credential is active and unexpired and that its service
   account is active;
5. hashes the presented random secret with SHA-256 and compares the digest to
   `secret_hash` using a constant-time comparison;
6. verifies `account_type = 'service'` and `content.index.execute`;
7. applies rate limiting and records safe authentication telemetry; and
8. proceeds to the separate job-ID, lease-token, and lease-generation checks.

The `Authorization` header and complete API key are redacted before all request,
error, tracing, and proxy logging. Rotation creates a new identifier, random
secret, digest, and row; it never overwrites the old row's digest. The old key
remains independently revocable and auditable during any approved overlap.

Credential possession alone does not authorize content access. After service
authentication, job-scoped authorization also requires the exact current job
ID, lease token, and lease generation. Thus the effective authorization is:

```text
active service account
AND valid unexpired text-indexer API key
AND content.index.execute
AND current unexpired lease for this exact job generation
```

The lease is the narrowly scoped capability that permits access to content
regardless of the source record's ordinary ACL and security level. The service
account therefore receives no `record.view`, `record.component.view`, ACL grant,
or blanket security clearance. The API may release only the exact content set
named by the lease, and the service may not enumerate records or components.
This controlled internal exception shall be documented in the authorization
operation inventory.

Credentials shall be individually identifiable, time-bounded, rotatable with
an overlap period, revocable without deleting the service account, and never
returned again after issuance. API keys and lease tokens must not appear in source control, database
history, application logs, metrics, URLs, or error responses. Disabling or
suspending the service account, revoking its role/profile assignment, removing
the privilege, or revoking the credential takes effect on the next request;
existing leases are then unusable and expire for safe reclamation.

Production deployments should provision a distinct account and credentials per
indexer pool or host so one deployment can be revoked and audited independently.
Multiple processes may intentionally share one pool account, but each claim
still supplies a unique runtime `worker_id`. Sharing one credential across
development, test, staging, and production is prohibited.

Credential creation, rotation, revocation, account status changes, and
role/profile changes are immutable security events. Successful worker requests
are operational telemetry tied to service user ID, credential identifier,
worker ID, job ID, and request/correlation ID; they do not create one governed
event-history row per heartbeat or chunk. Authentication failures and attempts
to use the API key on a disallowed route are recorded through the existing
security-event mechanism without recording secrets.

### 5.3 ACL and security-level treatment

The `TEXT_INDEXER_SERVICE` profile does **not** grant a general bypass of ACLs,
security levels, or ordinary API authorization. It grants no ability to list,
search, open, preview, or download an arbitrary record or component.

Nevertheless, the indexing workflow must process every eligible component,
including highly restricted content. It does this through a narrowly bounded
system-operation exception in the internal API:

1. the trusted API/database scheduler determines that a specific content set is
   eligible and creates a job;
2. an authenticated indexer with `content.index.execute` obtains an exclusive
   lease for that job;
3. the lease authorizes retrieval only of that exact content-set ID and
   checksum, without applying an interactive user's ACL or clearance test;
4. the service cannot choose another component, enumerate resources, follow a
   relationship to other content, or use the lease on an ordinary endpoint;
   and
5. the resulting index remains protected by the source resource's normal ACL
   and security-level checks when people search.

Thus, the indexing **operation** has controlled access across classification
levels, but the service **profile** is not a reusable authorization bypass. This
distinction confines unavoidable plaintext access to a server-created unit of
work and permits immediate fencing, revocation, and auditing. The indexer
runtime and its administrators are consequently inside Wathiq's trusted
content-processing boundary and must be approved to handle the highest
classification present in that deployment.

### 5.4 Why separate API-key storage is required

The `service_account_credentials` table stores these API keys because existing
`user_credentials` are
interactive passwords for person accounts, while `login_sessions` are browser
sessions; weakening either model to accommodate background services would mix
different lifecycles and make least-privilege enforcement harder. A separate
table provides independently revocable credentials, expiry, route restriction, rotation
overlap, credential-level audit identity, and one-way secret storage without
giving a service account an interactive password.

## 6. Data model

The implementation uses separate current-state, chunk, and immutable-history
tables. Chunking is required because extracted documents can be very large,
PostgreSQL `tsvector` values are bounded, and useful snippets should identify a
small region rather than return an entire document.

### 6.1 `digital_component_search_documents`

One row represents current indexing state for one digital component.

| Column | Type | Rules |
| --- | --- | --- |
| `digital_component_id` | `bigint` | Primary key; FK to `digital_components(id)` with `ON DELETE CASCADE` |
| `record_id` | `bigint` | Required; FK to `records(id)` with `ON DELETE CASCADE` |
| `content_set_id` | `bigint` | Nullable until scheduled; FK to `digital_component_content_sets(id)` |
| `content_checksum_algo` | `text` | Nullable; copied from the active content set |
| `content_checksum_value` | `text` | Nullable; copied from the active content set |
| `status` | `text` | `pending`, `processing`, `indexed`, `unsupported`, `failed`, or `stale` |
| `detected_mime_type` | `text` | Nullable; extractor result, distinct from submitted MIME type |
| `detected_language` | `text` | Nullable; normalized BCP 47 language tag when one language is confidently dominant; null for unknown or mixed content |
| `extractor_name` | `text` | Nullable |
| `extractor_version` | `text` | Nullable |
| `extraction_config_version` | `text` | Required |
| `index_config_version` | `text` | Required |
| `indexed_at` | `timestamptz` | Nullable |
| `last_attempt_at` | `timestamptz` | Nullable |
| `last_error_code` | `text` | Nullable; stable safe code, no extracted content |
| `last_error_summary` | `text` | Nullable; bounded and sanitized |
| `date_updated` | `timestamptz` | Required |

The database must verify that `content_set_id`, when present, belongs to the
same component. `record_id` is retained for efficient authorization and result
grouping; triggers or worker writes must keep it equal to the component's
record. Moving a component between records is not currently a supported domain
operation.

An index supports `(status, date_updated, digital_component_id)` for state
reconciliation. Another supports `(record_id, digital_component_id)`.

### 6.2 `digital_component_search_chunks`

One successfully extracted component has zero or more ordered text chunks.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `bigserial` | Primary key |
| `digital_component_id` | `bigint` | Required; FK to current search document with `ON DELETE CASCADE` |
| `chunk_no` | `integer` | Zero-based; unique with component ID |
| `page_from` / `page_to` | `integer` | Nullable; positive when the format supplies page positions |
| `extracted_text` | `text` | Required, normalized, size bounded per chunk |
| `search_vector` | `tsvector` | Required; built with an explicitly stored configuration |
| `text_search_config` | `regconfig` | Required |

A GIN index shall cover `search_vector`. The worker shall split on page or
structural boundaries where available and then on a configurable character
limit. It shall reject or truncate only under an explicit configured maximum
total extracted-text policy and record that condition in history. Silent
truncation is prohibited.

`extracted_text` is retained to produce safe snippets. It is never returned in
full by the search API. Cleanup removes chunks transactionally when their
component is permanently deleted or their source content becomes ineligible.

### 6.3 `record_search_documents`

One row per record stores weighted metadata only:

```text
record_id (PK/FK), search_vector, text_search_config, indexed_at,
index_config_version
```

The vector combines record number and title at weight A and description at
weight B. A GIN index covers `search_vector`. It is refreshed in the same
transaction as relevant record metadata changes and deleted by cascade.

### 6.4 `aggregation_search_documents`

One row per aggregation stores weighted aggregation number/title/description
using the weights in section 2.2. Its lifecycle and indexing match the record
metadata table. Ancestor or descendant metadata is not copied into the vector.

### 6.5 `content_indexing_jobs`

This table is the durable coordination mechanism shared by every API process
and text-indexer instance. It contains one row per executable indexing job.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `bigserial` | Primary key |
| `digital_component_id`, `record_id`, `content_set_id` | `bigint` | Required foreign keys for the requested source generation |
| `content_checksum_algo/value` | `text` | Required immutable expected identity |
| `trigger` | `text` | Same trigger values as indexing history |
| `priority` | `smallint` | Bounded; manual work may precede backfill without starving it |
| `status` | `text` | `queued`, `leased`, `succeeded`, `failed`, `unsupported`, `cancelled`, or `skipped` |
| `not_before` | `timestamptz` | Required; implements retry backoff |
| `lease_owner` | `text` | Nullable worker ID |
| `lease_token` | `uuid` | Nullable, random and replaced on every claim/reclaim |
| `lease_expires_at` | `timestamptz` | Nullable |
| `lease_generation` | `bigint` | Required, starts at zero and increments on every claim |
| `attempt_no` | `integer` | Required; increments on every claim |
| `extraction_config_version`, `index_config_version` | `text` | Required |
| `required_capabilities` | `jsonb` | Bounded server-created requirements, not arbitrary client policy |
| `queued_at`, `started_at`, `completed_at`, `date_updated` | `timestamptz` | Lifecycle timestamps |

A partial unique index prevents more than one active job for the same
component, content set, and configuration tuple while `status` is `queued` or
`leased`. Normal scheduling uses `INSERT ... ON CONFLICT` against that identity,
so concurrent upload finalization, reconciliation, and reindex requests cannot
create redundant work. After a job is terminal, a forced reindex may create a
new job for the same tuple.

The claim operation is one short database transaction inside the API. It uses a
common-table expression to select compatible eligible rows ordered by priority,
`not_before`, and ID with `FOR UPDATE SKIP LOCKED`, then updates and returns
those rows as `leased`, with a new cryptographically random `lease_token`, an
incremented `lease_generation`, and a database-clock lease expiry. Consequently:

- concurrent claims never return the same live job;
- a slow claim does not block another API process from claiming different rows;
- no database lock remains held while a file is downloaded or extracted;
- an expired lease is eligible for atomic reclaim with a new token/generation;
  and
- an old worker can finish computation but cannot publish after reclaim because
  its lease token and generation no longer match.

The API implements the claim as the equivalent of the following parameterized
statement. The API generates each random token; the example shows a single-job
claim for clarity:

```sql
WITH candidate AS (
    SELECT id
    FROM content_indexing_jobs
    WHERE not_before <= CURRENT_TIMESTAMP
      AND (
          status = 'queued'
          OR (status = 'leased' AND lease_expires_at < CURRENT_TIMESTAMP)
      )
      AND capabilities_are_compatible(required_capabilities, :worker_capabilities)
    ORDER BY priority DESC, not_before, id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE content_indexing_jobs AS job
SET status = 'leased',
    lease_owner = :worker_id,
    lease_token = :new_random_token,
    lease_generation = job.lease_generation + 1,
    lease_expires_at = CURRENT_TIMESTAMP + :lease_duration,
    attempt_no = job.attempt_no + 1,
    started_at = COALESCE(job.started_at, CURRENT_TIMESTAMP),
    date_updated = CURRENT_TIMESTAMP
FROM candidate
WHERE job.id = candidate.id
RETURNING job.*;
```

`capabilities_are_compatible` is conceptual notation: the production query
shall use validated relational columns or bounded JSON predicates supported by
appropriate indexes, not a client-defined SQL function or expression. Batch
claims use the same pattern with a bounded `LIMIT` and a distinct server-created
token per returned row.

Worker heartbeats conditionally extend a lease only when job ID, owner, token,
generation, `leased` status, and unexpired lease all match. Completion and
failure transitions use the same compare-and-set predicate. Zero affected rows
means `lease_lost`; the worker discards local output and must not retry a commit
under the obsolete token.

Queue indexes cover eligible claim ordering and expired-lease recovery without
scanning terminal history. Terminal jobs may be archived/purged after their
corresponding attempt history exists.

### 6.6 `content_indexing_attempts`

This append-only operational history records every automatic and forced
attempt, including skips whose reason is operationally useful.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `bigserial` | Primary key |
| `digital_component_id` | `bigint` | Nullable FK with `ON DELETE SET NULL` |
| `record_id` | `bigint` | Nullable FK with `ON DELETE SET NULL` |
| `content_set_id` | `bigint` | Nullable FK with `ON DELETE SET NULL` |
| `content_checksum_algo/value` | `text` | Required for a content attempt |
| `trigger` | `text` | `upload`, `replacement`, `manual_component`, `manual_record`, `backfill`, `retry`, or `config_change` |
| `requested_by_user_id` | `bigint` | Nullable FK with `ON DELETE SET NULL`; present for manual requests |
| `job_id` | `bigint` | Nullable FK to the originating job |
| `worker_id` | `text` | Nullable diagnostic instance identity |
| `lease_generation` | `bigint` | Nullable; identifies the claimed execution |
| `status` | `text` | `processing`, `succeeded`, `failed`, `unsupported`, `cancelled`, `lease_lost`, or `skipped` |
| `attempt_no` | `integer` | Required, positive |
| `queued_at`, `started_at`, `completed_at` | `timestamptz` | Lifecycle timestamps |
| `extractor_name/version` | `text` | Nullable |
| `extraction_config_version` | `text` | Required |
| `index_config_version` | `text` | Required |
| `characters_extracted`, `chunks_created` | `bigint` / `integer` | Nullable non-negative metrics |
| `ocr_used` | `boolean` | Required, default false |
| `error_code`, `error_summary` | `text` | Nullable, bounded and sanitized |
| `request_id`, `correlation_id` | `text` | Nullable tracing values |

History must not contain extracted text, snippets, blob bytes, passwords,
commands, stack traces, or unbounded third-party parser messages. Operational
retention is configurable and defaults to 365 days, after which completed
attempts may be purged in bounded batches. Current search documents and chunks
are not governed by this history-retention period.

Purging is automatic but is **not** performed by
`backend/services/text_indexer`. Text-indexers have no direct database access
and their internal API key authorizes extraction job operations only. Granting
them history-deletion authority would unnecessarily broaden the service trust
boundary.

A dedicated API-side database maintenance process owns cleanup:

```bash
python -m backend.services.api.text_indexing_maintenance cleanup --dry-run
python -m backend.services.api.text_indexing_maintenance cleanup --batch-size 500
python -m backend.services.api.text_indexing_maintenance cleanup --watch
```

Production runs either one `--watch` process or scheduled one-shot executions.
The cleanup loop must not run independently inside every FastAPI web worker. It
uses the API's database configuration, a PostgreSQL advisory lock to prevent
competing cleanup leaders, short transactions, bounded keyset batches, and
database time for retention comparisons.

Configuration includes:

```text
CONTENT_INDEXING_HISTORY_RETENTION_DAYS=365
CONTENT_INDEXING_CLEANUP_INTERVAL_SECONDS=3600
CONTENT_INDEXING_CLEANUP_BATCH_SIZE=500
TEXT_INDEXER_CREDENTIAL_HISTORY_RETENTION_DAYS=365
```

The cleanup process may delete only:

- terminal attempt-history rows whose `completed_at` is older than the
  retention cutoff;
- terminal job rows whose retained attempt/history requirements have been
  satisfied and whose completion is older than the applicable cutoff; and
- abandoned result-staging chunks for terminal jobs or expired lease
  generations after a shorter documented staging-retention period.

It must never delete queued or leased jobs, current search documents, published
search chunks, active result staging for a valid lease, audit/event history, or
source content. Each run rechecks terminal status and cutoff under row locking
immediately before deletion so a race cannot remove active work.

Failures are logged and surfaced in operational health/metrics without
advancing or hiding the affected rows. Cleanup records aggregate counts and
oldest retained timestamps, never extracted text. A dry run reports bounded
eligible counts without deleting anything. `run-local-stack.sh` starts and
supervises exactly one `cleanup --watch` process by default and stops it with
the stack. Production provides
`backend/services/api/deploy/erms-text-indexing-maintenance.service`, which runs
the same API-owned process independently of FastAPI and the text-indexer
service. An environment with an existing scheduler may invoke the one-shot
command instead, but must not also enable the continuous service.

The centralized inventory, invocation summary, configuration list, and links
to all other backend cleanup services are maintained in the
[ERMS Operational Tools Catalogue](../docs/operations.md#3-central-cleanup-service-inventory).

One history row is created for every claimed execution generation, so a crashed
worker followed by a successful reclaim produces two truthful attempts without
duplicating the job or published index.

### 6.7 `content_indexing_result_chunks`

This staging table receives bounded extracted-text chunks for a leased job. Its
rows contain `job_id`, `lease_generation`, `chunk_no`, optional page range,
normalized extracted text, detected language/configuration, and safe metrics.
The unique key is `(job_id, lease_generation, chunk_no)`.

Staging supports documents whose result does not fit safely in one HTTP request.
Chunk uploads are idempotent: repeating the same numbered chunk with the same
digest succeeds; conflicting bytes for that number are rejected. Every upload
is accepted only under the current lease compare-and-set check. Staging rows
are not searchable.

On completion, the API locks the job row, validates the token/generation and
lease, verifies that all declared chunks and their digests are present, and
rechecks the active content-set identity. In one transaction it builds the
`tsvector` values using server-selected configurations, replaces the component's
published chunks, updates current state, records success, marks the job
terminal, and deletes staging rows. If any predicate fails, nothing is
published. Expired/terminal staging rows are removed by bounded cleanup.

### 6.8 Content transition trigger/outbox

Upload finalization and replacement shall transactionally create a durable
indexing request after activating the new content set. Metadata-only queue state
is stored in PostgreSQL; no in-memory queue is authoritative. The transaction
must also mark the former search document `stale` or otherwise make its chunks
ineligible to the search query before commit.

The schema and the upgrade migration shall contain portable PostgreSQL SQL
only. `database/schema.sql` shall contain the complete latest structure without
invoking the migration.

### 6.9 `service_account_credentials`

A dedicated table stores opaque service API-key metadata separately from
browser login sessions and person-account password credentials:

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `bigserial` | Primary key |
| `service_user_id` | `bigint` | Required FK to `users(id)` with `ON DELETE CASCADE`; application/database enforcement requires `account_type = 'service'` |
| `credential_identifier` | `text` | Required, unique, non-secret lookup identifier |
| `secret_hash` | `text` | Required one-way hash; never stores plaintext |
| `status` | `text` | `active` or `revoked` |
| `date_created`, `expires_at`, `last_used_at`, `date_revoked` | `timestamptz` | Lifecycle timestamps; expiry is required |
| `created_by_user_id`, `revoked_by_user_id` | `bigint` | Nullable actor FKs retained for security-event traceability |

Indexes support active lookup by credential identifier and bounded expiry
cleanup. `last_used_at` updates are rate-limited or aggregated so every
heartbeat does not create avoidable write contention. The table stores no JWT,
certificate, public/private key pair, or general-purpose API scope. All keys in
this table are accepted only by the internal text-indexing route middleware.

## 7. Text processing and language policy

The extractor outputs Unicode plain text. The worker shall normalize Unicode
consistently, remove control characters except meaningful whitespace, preserve
word boundaries, and cap pathological repeated whitespace. It shall not alter
or overwrite the authoritative file.

The initial text-search policy is:

- run automatic language identification on normalized extracted text, using a
  locally deployed, version-pinned detector with no external-network calls;
- detect language per chunk when sufficient text is available, and derive the
  component-level `detected_language` only when one language is confidently
  dominant; short, numeric, code-like, unknown, and genuinely mixed content
  must not be forced into a language;
- record the detector name/version, detected language, and bounded confidence
  or decision class in indexing diagnostics so that a detector change is
  reproducible and auditable;
- use an explicitly configured PostgreSQL text-search configuration on every
  `to_tsvector` and query conversion call; never rely on the database/session
  default;
- use language-specific configurations only where the deployment has approved
  and tested them;
- use `pg_catalog.simple` as the safe fallback for unknown, low-confidence,
  short, code-like, or mixed-language chunks;
- store the configuration used on each search document/chunk;
- query each configuration represented by eligible result rows, rather than
  applying an English stemmer to all content; and
- changing language-detector model/version/thresholds, tokenization,
  dictionaries, stop words, weights, chunking, or OCR language policy
  increments `index_config_version` or
  `extraction_config_version` and schedules a controlled rebuild.

Language detection selects only from the server-approved mapping of detected
languages to installed PostgreSQL configurations; it never accepts a database
configuration name from a document or client. English maps to
`pg_catalog.english` and Arabic maps to `pg_catalog.arabic`. The approved
database baseline is PostgreSQL 18, which
provides the Arabic configuration and its `pg_catalog.arabic_stem` Snowball
dictionary as built-in catalogue objects, so Wathiq shall use them directly
rather than create, copy, replace, or alter them. Unknown and mixed-language
chunks use `pg_catalog.simple`. Mixed-language documents may therefore
contain chunks indexed under different configurations, and each chunk stores
the configuration actually used. Search converts the user's query for every
distinct eligible configuration involved and combines the matches without
exposing configuration selection to the client.

Both `database/schema.sql` and the full-text-search upgrade migration shall
perform an installation precondition check equivalent to:

```sql
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_ts_config AS config
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = config.cfgnamespace
        WHERE namespace.nspname = 'pg_catalog'
          AND config.cfgname = 'simple'
    ) OR NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_ts_config AS config
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = config.cfgnamespace
        WHERE namespace.nspname = 'pg_catalog'
          AND config.cfgname = 'english'
    ) OR NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_ts_config AS config
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = config.cfgnamespace
        WHERE namespace.nspname = 'pg_catalog'
          AND config.cfgname = 'arabic'
    ) THEN
        RAISE EXCEPTION
            'Required PostgreSQL text-search configurations are unavailable';
    END IF;
END
$$;
```

The migration and canonical schema must fail atomically with a clear
compatibility error when a required built-in configuration is missing. They
must not silently substitute `simple` for Arabic, modify `pg_catalog`, install
operating-system files, or change `default_text_search_config`. Application SQL
always passes a schema-qualified configuration explicitly. Fresh-schema and
migration tests shall additionally assert that representative Arabic words are
tokenized by `pg_catalog.arabic`, that Arabic document and query construction
use the same configuration, and that the stored `regconfig` resolves to the
built-in object.

OCR language selection is related but separate. Language cannot reliably be
detected before OCR has produced text, so file metadata, script detection, and
the configured English/Arabic OCR policy select the initial OCR languages.
Language identification then runs on the resulting text and selects the
PostgreSQL search configuration. A low-confidence result must fall back to
`simple`; it must not silently apply an incorrect stemmer.

OCR is used for supported image formats. For PDFs, native embedded text is
preferred; OCR is invoked only when configured heuristics identify an
image-only or insufficient-text page. This avoids duplicate text and needless
CPU use. OCR confidence, where available, may be recorded as a metric but shall
not be exposed as factual document metadata.

Archive/container recursion and embedded-object extraction are disabled in the
initial release unless individual formats are later approved. Indexing hidden
attachments unintentionally could disclose content the UI does not present as
a distinct governed component.

## 8. Text-indexer service behavior

### 8.1 Deployment

Run any number of independent text-indexer service instances. They poll the
API's internal claim endpoint; only the API performs PostgreSQL row claiming.
Instances need network access only to the internal API and locally configured
Tika/Tesseract processes. They require neither a shared filesystem nor leader
election. A one-shot mode is useful for batch operations and a watch mode for
continuous deployment.

Conceptual commands:

```bash
python -m backend.services.text_indexer --once --batch-size 10
python -m backend.services.text_indexer --watch
```

The repository shall provide a root-level `run-text-indexer.sh` launcher,
parallel to `run-api.sh` and `run-webui.sh`. A nested generic `run.sh` is not
used because the existing root launchers are unambiguous from any working
directory. The launcher shall:

- resolve the project root from its own location;
- require Python 3.11 or newer;
- use a dedicated virtual environment at
  `backend/services/text_indexer/.venv` by default, overridable with
  `ERMS_TEXT_INDEXER_VENV`;
- install the pinned dependencies from
  `backend/services/text_indexer/requirements.txt` when their checksum changes;
- validate required configuration without printing credentials;
- change to the project root; and
- use `exec` to run `python -m backend.services.text_indexer --watch`, so
  signals and exit status reach the service directly.

The text-indexer has its own dependency file because Tika/OCR client and
extraction dependencies need not be installed in the API or web-UI runtime.
The official Tika binary distribution, Tesseract, OCR language packs, and
LibreOffice fallback are runtime dependencies checked at startup. The launcher
must fail with a clear non-secret diagnostic when required capabilities are
unavailable. The Tika check must verify the pinned version/checksum, adjacent
library layout, presence of `PipesForkParserConfig`, and successful fork-mode
self-test; a plain `tika --version` check is insufficient.

Minimum runtime configuration is:

```ini
TEXT_INDEXER_API_URL=http://127.0.0.1:8000
TEXT_INDEXER_API_KEY=<secret supplied by secret management>
TEXT_INDEXER_WORKER_ID=<unique instance identifier>
TEXT_INDEXER_PROCESS_COUNT=2
TEXT_INDEXER_POLL_INTERVAL_SECONDS=<configured value>
TEXT_INDEXER_CLAIM_BATCH_SIZE=1
TEXT_INDEXER_LEASE_HEARTBEAT_SECONDS=<less than the server lease duration>
```

The production launcher neither creates service accounts nor generates keys.
Provisioning is an explicit administrative/deployment operation, and the
opaque API key is supplied through a protected environment file or deployment
secret store.

One text-indexer service invocation is a supervisor-owned process pool.
`TEXT_INDEXER_PROCESS_COUNT` is the number of child worker processes and
defaults to `2`. Each child process shall claim and process exactly one job at
a time. The supervisor derives a unique runtime worker ID from the configured
`TEXT_INDEXER_WORKER_ID` base, the supervisor-process incarnation, and the
one-based child slot; operators configure a base ID, not individual child IDs.
If a child exits unexpectedly, the supervisor restarts that slot without
terminating healthy siblings. Stopping the service terminates the complete
pool. Implementations shall not use claim prefetching or an in-process
extraction thread pool. Operators choose the process count according to the
host's aggregate CPU and memory budget.

The service-account boundary is the deployed text-indexer service or trusted
pool, not an individual child worker. One deployed service normally uses one
dedicated Text Indexers service account and one active API key; every child
process supervised by that service shares the credential but registers with a
distinct runtime worker ID. Child processes shall not require separately
provisioned accounts or keys. Independently operated servers or pools should
use separate service accounts and keys so each deployment can be audited,
rotated, revoked, suspended, or contained without interrupting another. A
trusted group of identically operated instances may deliberately share an
account only when the shared audit and revocation boundary is acceptable.

### 8.2 Local development stack integration

The root `run-local-stack.sh` shall start the text-indexer after PostgreSQL and
the API are ready and before declaring the complete stack ready. It shall track
`TEXT_INDEXER_PID`, terminate that process during cleanup, and fail the stack if
the managed indexer exits unexpectedly, following the same lifecycle pattern as
the managed API and web UI. The readiness summary shall include **Text indexer:
running** and its worker ID; the API key is never printed.

Local development uses the real internal authentication path rather than a
hidden authentication bypass. The stack resolves credentials in this order:

1. use `TEXT_INDEXER_API_KEY` when explicitly supplied by the developer;
2. otherwise use a credential stored in a git-ignored, owner-readable local
   secret file under the project's local runtime-data directory; or
3. if no usable credential exists, invoke an API-owned local-development
   provisioning command that transactionally ensures the protected profile,
   local service account and role assignment exist, revokes an unusable prior
   local credential when necessary, generates one new key, and writes its
   one-time plaintext value directly to that protected local file.

The provisioning command is disabled unless an explicit local-development flag
is set and the API/database target is loopback/local. It refuses remote,
staging, and production-looking targets. It records normal security events,
uses the same hashed API-key table and route-restricted authentication as production, and
does not create a universal development master key. The secret file is mode
`0600`, excluded from source control, never echoed, and removed or rotated by a
documented local credential-reset command.

If the API is already running, the local stack may reuse it only after its
health/capabilities endpoint confirms that the required internal text-indexing
contract version is available. After starting the indexer, the stack waits for
that worker ID to authenticate and register through the API before reporting
readiness. A currently active registration with the same worker ID causes a
clear configuration error rather than allowing two processes to share one
runtime identity. The text-indexer does not need to expose an inbound HTTP port
on the development machine.

The indexer is enabled by default in the full local stack so upload-and-search
development exercises eventual indexing automatically. Developers may set
`ERMS_LOCAL_TEXT_INDEXER_ENABLED=false` for UI/API work that intentionally does
not require extraction; the readiness summary must then say **Text indexer:
disabled**, and search freshness states remain truthful.

Backfill and reconciliation remain API/database operations that enqueue jobs;
they may be invoked by an administrative API command or API-side maintenance
process. The text-indexer does not scan database entities.

### 8.3 Internal REST contract

The API exposes a versioned, non-interactive internal contract:

```http
POST /api/v1/internal/text-indexing/jobs/claim
POST /api/v1/internal/text-indexing/jobs/{job_id}/heartbeat
GET  /api/v1/internal/text-indexing/jobs/{job_id}/content
PUT  /api/v1/internal/text-indexing/jobs/{job_id}/chunks/{chunk_no}
POST /api/v1/internal/text-indexing/jobs/{job_id}/complete
POST /api/v1/internal/text-indexing/jobs/{job_id}/fail
GET  /api/v1/internal/text-indexing/workers/{worker_id}
```

Claim accepts worker identity/capabilities and a bounded requested count. Every
subsequent request carries the opaque lease token and generation. Content is
streamed only for that job's immutable requested content set and supports range
or resumable transfer where needed. It must never silently switch to a newer
active content set.

Heartbeat is sent well before expiry and may report bounded progress metrics.
The worker-status operation exposes only that authenticated service account's
registered worker IDs, contract/capability versions, last contact, and current
job state; it exists for deployment readiness and diagnostics, not content
access.
Network timeout responses are treated as unknown outcomes: chunk upload and
terminal operations use idempotency keys, and the worker queries/retries the
same operation rather than assuming success. Terminal responses are stable for
retries with the same idempotency key.

### 8.4 Processing sequence

For each claimed request, the worker shall:

1. claim a compatible job from the API and retain its opaque lease credentials;
2. stream the exact leased content set from the API to a bounded private
   temporary file or extraction stream without assembling the file in API
   memory;
3. verify the authoritative checksum while reading;
4. invoke the isolated extractor with declared limits while heartbeating;
5. normalize, classify language/configuration, and split the result into
   bounded chunks; the service does not construct trusted PostgreSQL vectors;
6. upload chunks idempotently under the current lease; and
7. request atomic completion, after which the API rechecks active content and
   publishes or rejects the staged result.

If the active-content check fails, the API rejects publication and marks the
job cancelled; stale output cannot win a race with content replacement.

Jobs and result uploads are idempotent. Lease expiry allows abandoned work to
be recovered after worker or network failure. Two instances may briefly compute
the same job only after a lease expires while the old instance is partitioned;
fencing guarantees that only the current lease can publish. This bounded
duplicate computation is necessary for recovery and is not redundant committed
indexing. Retries use bounded exponential backoff with a configurable maximum.
`unsupported` is terminal until content or configuration changes or a user
forces reindex. Deterministic failures such as password protection and limit
exceeded are not retried automatically.

### 8.5 Configuration defaults

All limits shall be configuration values documented in `docs/operations.md`,
including batch size, polling interval, worker lease, extraction timeout,
maximum input size, maximum extracted characters, chunk size, maximum pages,
embedded-object policy, OCR enablement/languages, retry count, attempt-history
retention, and extractor endpoint/binary location.

The Phase 0 benchmark approves these conservative initial defaults. They are
configuration values, not hard-coded parser behavior:

| Setting | Initial default |
| --- | ---: |
| Claim batch size | 4 jobs |
| Poll interval | 5 seconds |
| Worker lease / heartbeat | 300 / 60 seconds |
| Extraction wall timeout | 120 seconds per component |
| Extractor CPU / memory limit | 2 CPU / 1 GiB |
| Maximum input size | 50 MiB |
| Maximum extracted characters | 5,000,000 |
| Chunk target / hard maximum | 16,000 / 20,000 characters |
| Maximum pages | 1,000 |
| Embedded objects / archive recursion | Disabled / depth 0 |
| OCR | Enabled for supported images and insufficient-text PDF pages; `eng+ara` |
| Automatic retries | 3 transient attempts with bounded exponential backoff |
| Private temporary storage | 1 GiB per active job |

Inputs over the byte/page limits are rejected before expensive extraction when
the size is known. Output is stopped at the configured character limit and the
attempt records `limit_exceeded`; silent truncation is prohibited. Production
operators may lower these limits. Raising them requires a repeatable corpus and
resource benchmark under the intended process-sandbox CPU/memory constraints and an
operations-document update; it does not require a schema change.

## 9. Reindex operations

### 9.1 Digital component

```http
POST /api/v1/digital-components/{component_id}/reindex
```

The endpoint performs authorization and validation synchronously, then queues a
forced attempt and returns `202 Accepted` with the attempt ID and status URL.
"Immediately" means the request is durably queued without waiting for the
periodic discovery scan; extraction itself remains asynchronous so request
threads are not held by large or hostile files.

If an equivalent forced attempt for the same active content set is already
queued or processing, the endpoint returns that attempt rather than creating
unbounded duplicates. A component without available content returns `409` with
`content_not_available`. A missing component returns `404` only when revealing
its existence is permitted by the established authorization policy; otherwise
the standard concealed response applies.

### 9.2 Record

```http
POST /api/v1/records/{record_id}/reindex
```

The endpoint transactionally refreshes the record metadata index and queues one
forced attempt for every currently available digital component. It returns
`202 Accepted` with a batch ID and counts for queued, already in progress,
unsupported/no-content, and total components. Each component has its own attempt
and can succeed or fail independently. Adding/replacing content after the batch
snapshot is handled by the normal upload/replacement trigger, not silently
added to that batch.

### 9.3 Status

```http
GET /api/v1/content-indexing/attempts/{attempt_id}
GET /api/v1/content-indexing/batches/{batch_id}
```

Status responses contain safe states, timestamps, counts, and error codes, but
not extracted text or raw extractor errors.

### 9.4 UI actions and authorization

The component action menu and record detail action area display **Reindex** only
to a user authorized to view the source content and perform the corresponding
component maintenance operation under the existing policy. No new general
ability to read or mutate a record is implied by indexing.

Because manual reindex consumes exceptional compute and creates an operational
action, the implementation shall add the dedicated global privilege
`record.component.reindex` and require it in addition to `record.view`, component-content
view permission, the applicable resource ACL permission, and sufficient
clearance for the resource.

| Forced action | Required global privileges | Required resource authorization |
| --- | --- | --- |
| Reindex one digital component | `record.component.reindex`, `record.view`, `record.component.view` | `record.view` and `record.component.view` on the parent record, plus sufficient clearance |
| Reindex every component of one record | `record.component.reindex`, `record.view`, `record.component.view` | `record.view` and `record.component.view` on the record, plus sufficient clearance |

The canonical seed grants `record.component.reindex` by default to these protected
built-in profiles:

- **All privileges** (`ALL_PRIVS`);
- **System Administrator** (`SYS_ADMIN`);
- **Information Governance Manager** (`INFO_GOV_MGR`); and
- **Information Governance Officer** (`INFO_GOV_OFFICER`).

Possessing `record.component.reindex` alone is insufficient. In particular, the System
Administrator profile remains a platform role without governed-content bypass:
its holder can see and invoke a component/record reindex action only when a
separate effective role supplies `record.view`, the required component/resource
ACL permission, and sufficient security clearance. The governance profiles are
likewise subject to their existing effective-role, clearance, and resource
authorization rules. Other profiles receive the privilege only through an
explicit administrator-approved profile change.

Closure and legal hold do not prohibit reindexing because the operation does
not modify authoritative content or records-management metadata. Reindexing
must not be offered as a way to replace, repair, or bypass access to content.

The UI shows queued/processing/succeeded/failed feedback and allows navigation
away. It does not claim completion on `202`. Component indexing state and last
successful time are visible to authorized users. Record batch progress is
summarized without blocking the page.

## 10. Search API

### 10.1 Controlled grammar extension

The existing expression grammar gains this leaf form:

```json
{
  "full_text": {
    "query": "approved budget -draft",
    "sources": ["metadata", "components"]
  }
}
```

`query` is required trimmed Unicode text. It is converted by the server with
`websearch_to_tsquery` using the applicable explicit text-search
configurations. Clients cannot select `to_tsquery`, submit raw PostgreSQL query
syntax, or choose a database text-search configuration.

`sources` is optional. Its resource-specific allowlist is:

| Search resource | Allowed sources | Default |
| --- | --- | --- |
| `records` | `metadata`, `components` | Both |
| `aggregations` | `metadata` | `metadata` |
| `digital-components` | `metadata`, `content` | Both |

For records, `metadata` means the record metadata vector and `components`
means eligible content/file-name vectors belonging to that record. For digital
components, `metadata` initially means file name and `content` means extracted
body text. Other resource search endpoints reject `full_text` with HTTP `422`
until a later approved specification defines their indexed sources. Unknown,
duplicate, empty, or incompatible source values also return `422`.

A full-text leaf counts as one condition under the existing 50-condition limit.
Its query has separately configurable character and token limits. Empty,
all-stop-word, or otherwise non-indexable input returns `422` with
`non_indexable_full_text_query`; it must never degrade into an unbounded query.
All existing maximum nesting, array, sorting, pagination, parameterization, and
field-allowlist rules remain in effect.

### 10.2 Combining structured and full-text criteria

The new leaf may appear anywhere an existing comparison expression may appear,
including inside nested `and`, `or`, and `not` nodes. For example:

```http
POST /api/v1/records/search
Content-Type: application/json
```

```json
{
  "where": {
    "and": [
      {
        "field": "aggregation_id",
        "operator": "in",
        "value": [42, 57]
      },
      {
        "field": "date_originated",
        "operator": "between",
        "value": [
          "2026-01-01T00:00:00Z",
          "2026-12-31T23:59:59Z"
        ]
      },
      {
        "full_text": {
          "query": "\"approved budget\" expenditure -draft",
          "sources": ["metadata", "components"]
        }
      }
    ]
  },
  "sort": [
    {"field": "_relevance", "direction": "desc"},
    {"field": "date_originated", "direction": "desc"}
  ],
  "include": ["full_text_matches"],
  "limit": 50,
  "offset": 0
}
```

This is one database search query over authorized records. Structured
predicates restrict the candidate records and the full-text predicate tests the
selected indexed sources. Implementations may use safe SQL subqueries/CTEs, but
must not fetch one result set and intersect it in application memory.

`_relevance` is a controlled virtual sort field available only when at least
one positive full-text leaf is present. If such a search omits `sort`, the
default is `_relevance DESC, id ASC`. If the client supplies a sort without
`_relevance`, its requested business ordering is respected and `id ASC` remains
the deterministic final key. `_relevance` cannot be used as a comparison field
or returned as an unrestricted implementation value.

`include` is an optional controlled array. `full_text_matches` is valid only
when the expression contains a full-text leaf. It adds bounded match attribution
to each returned item—metadata matched, best authorized component matches, and
safe snippets—without changing which rows match. Ordinary existing clients that
omit it retain the existing resource-search response shape. When requested,
the additional information is namespaced under `_search` so it cannot collide
with current or future entity fields:

```json
{
  "items": [
    {
      "id": 91,
      "record_number": "FIN-R-001",
      "title": "Approved budget",
      "_search": {
        "relevance": 0.81,
        "metadata_matched": true,
        "matching_components": [
          {
            "id": 501,
            "file_name": "budget.pdf",
            "snippet": "…approved expenditure…"
          }
        ]
      }
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0,
  "returned": 1
}
```

`_search.relevance` is included whenever `full_text_matches` is requested, but
its numeric scale is not a stable cross-query contract.

Negated full-text clauses influence matching but do not produce snippets.
For Boolean expressions with several positive full-text leaves, attribution
identifies which leaf IDs/sources matched; the implementation shall assign
stable server-local expression identifiers rather than echo untrusted text as
keys. Ranking is based only on positive full-text clauses satisfied by the row.

### 10.3 Global search endpoint

```http
POST /api/v1/full-text-search
Content-Type: application/json
```

The global endpoint accepts the same controlled expression grammar, with
resource-specific branches because record and aggregation field allowlists are
different:

```json
{
  "record_where": {
    "and": [
      {"field": "date_originated", "operator": "gte", "value": "2026-01-01T00:00:00Z"},
      {"full_text": {"query": "approved budget", "sources": ["metadata", "components"]}}
    ]
  },
  "aggregation_where": {
    "full_text": {"query": "approved budget", "sources": ["metadata"]}
  },
  "result_types": ["records", "aggregations"],
  "limit": 25,
  "cursor": null
}
```

The header UI normally submits one full-text leaf to both branches. An advanced
client may combine each branch with structured predicates valid for that
resource. Omitting a branch excludes that result type; it does not mean "match
all." `result_types` must agree with the supplied branches. The endpoint
requires authentication and returns `422` for invalid or non-indexable
expressions. Complexity limits apply to the combined branches as well as to
each branch, preventing a caller from doubling the normal condition budget.

The server converts user input with `websearch_to_tsquery` for the applicable
explicit configurations. Raw `to_tsquery` syntax is not accepted in the
initial release. Parameter binding is mandatory.

The opaque cursor encodes the stable ordering tuple and query fingerprint.
Offset pagination is not used for deep global-search pages. The response has a
bounded page size; total counts are optional and, if returned, count only
authorized results.

An initial request may set `include_totals` to `true`. The response then
includes `totals`, keyed by the requested resource types, for all authorized
matches before the page limit. Cursor requests omit totals. The option does
not change the query fingerprint or result ordering.

### 10.4 Global result shape

```json
{
  "items": [
    {
      "type": "record",
      "record": {
        "id": 91,
        "record_number": "FIN-R-001",
        "title": "Approved budget",
        "description": "Annual budget approved by the board",
        "security_level_id": 1,
        "aggregation_id": 42,
        "aggregation_number": "FIN-2026"
      },
      "matched_record_metadata": true,
      "matching_components": [
        {
          "id": 501,
          "file_name": "budget.pdf",
          "snippet": "…approved expenditure…",
          "match_count_is_capped": false
        }
      ],
      "score": 0.81
    },
    {
      "type": "aggregation",
      "aggregation": {
        "id": 42,
        "aggregation_number": "FIN-2026",
        "title": "Annual financial administration",
        "description": "Financial planning and reporting records",
        "security_level_id": 1
      },
      "snippet": "…annual budget and expenditure…",
      "score": 0.75
    }
  ],
  "next_cursor": null,
  "index_freshness": {
    "has_pending_content": false
  }
}
```

Each authorized resource projection includes its `description` (nullable) and
`security_level_id`. Selection dialogs use these to explain the resource and
check message-level compatibility without additional per-result requests.
These fields do not relax the existing resource authorization rules.

The exact numeric score is not a stable API contract. Ranking uses PostgreSQL
cover-density ranking, configured weights, and deterministic tie-breakers.
Record metadata and component scores are combined without allowing a record
with many matching chunks to dominate solely through chunk count. At most a
configured small number of best matching components and one best snippet per
component are returned initially. The UI can open the record to see the full
component list.

Snippets are generated server-side from the matched chunk with bounded length
and a fixed allowlist of highlight markers. The client renders all text escaped
and applies highlighting without accepting arbitrary HTML from PostgreSQL or
the document.

### 10.5 Authorization

The search query must begin from the existing authorized aggregation/record
resource relations and apply the same global privilege, ACL, security clearance,
account, organization, and concealment gates as ordinary reads. Authorization
is applied in SQL before pagination, counts, ranking cutoffs, grouping, and
snippet selection. Fetching broadly and filtering in Python is prohibited.

A component is returned only when its parent record and its content are both
viewable by the current principal. An aggregation result is returned only when
that aggregation is viewable. Text-indexer workers use the service-only,
lease-scoped authorization defined in section 5; they do not use a database
identity or confer any access on interactive users.

Search requests themselves do not append governed `event_history` rows. They
may produce privacy-safe operational metrics. Existing content-view/download
events are not emitted merely because a snippet was returned.

### 10.6 Privileged search diagnostics

The canonical privilege catalogue shall add:

| Code | Purpose |
| --- | --- |
| `search.query.debug` | Request and view sanitized search-request diagnostics for searches performed by the current user |

The privilege is seeded into the protected `ALL_PRIVS`, `SYS_ADMIN`,
`INFO_GOV_MGR`, and `INFO_GOV_OFFICER` profiles.
It grants no resource visibility, ACL permission, security-level clearance,
ability to inspect another user's search, or access to SQL/database diagnostics.
The API always evaluates the search using the caller's ordinary authorization.

Every controlled search request, including the global endpoint, accepts the
optional top-level property:

```json
{
  "debug": true
}
```

It sits alongside `where`, `sort`, `include`, pagination, or the global
resource branches; it is not an expression and does not count toward grammar
complexity limits. If `debug` is absent or false, no diagnostic object is
returned. If it is true, the API requires `search.query.debug`; an unauthorized
request returns `403` with `insufficient_privilege` rather than silently
ignoring the flag.

An authorized response adds this top-level object:

```json
{
  "_debug": {
    "method": "POST",
    "endpoint": "/api/v1/records/search",
    "received_request": {
      "where": {
        "and": [
          {"field": "aggregation_id", "operator": "eq", "value": 42},
          {"full_text": {"query": "approved budget", "sources": ["metadata", "components"]}}
        ]
      },
      "sort": [{"field": "_relevance", "direction": "desc"}],
      "include": ["full_text_matches"],
      "limit": 50,
      "offset": 0,
      "debug": true
    },
    "canonical_query": {
      "where": {
        "and": [
          {"field": "aggregation_id", "operator": "eq", "value": 42},
          {"full_text": {"query": "approved budget", "sources": ["metadata", "components"]}}
        ]
      },
      "sort": [
        {"field": "_relevance", "direction": "desc"},
        {"field": "id", "direction": "asc"}
      ],
      "include": ["full_text_matches"],
      "limit": 50,
      "offset": 0
    },
    "request_id": "req_…",
    "query_fingerprint": "sha256:…"
  }
}
```

`received_request` is the sanitized JSON body accepted from the client before
server defaults are added. `canonical_query` is the validated API-level query
after defaults, normalized source ordering, deterministic tie-breakers, and
other documented grammar normalization. It remains JSON grammar—not generated
SQL, `tsquery`, an execution plan, or an authorization-policy expansion.

The response omits HTTP headers and credentials. A centralized allowlist-based
serializer constructs `_debug`; it must not serialize request objects or
framework/database state generically. Diagnostic values are limited to fields
already supplied by the caller or documented non-sensitive defaults. Error
responses may include the same sanitized request/correlation identifiers but
must not echo a rejected unbounded value beyond normal validation limits.

The client also retains the exact request body it attempted to send. The UI
labels the two views **Sent to API** and **Accepted by API** so defaults and
normalization are visible without implying that the display is a database
trace. If a network failure prevents a response, **Sent to API** remains
available and **Accepted by API** shows an unavailable state.

## 11. User interface

The application header contains a global search input centered in the usable
header area. It is available on authenticated pages at responsive sizes where
the header can contain it. On narrow screens it becomes a search icon that
opens the same input in a compact overlay; navigation and account controls must
remain usable.

The placeholder is **Search records, files and aggregations**. Pressing Enter
or activating the search icon opens a dedicated full-text results page. Search
does not run on every keystroke. The query remains in the header and URL so a
result page can be bookmarked or refreshed, subject to normal URL-history
privacy considerations.

The results page shall:

- use the established Wathiq search/result presentation rather than a raw
  default NiceGUI table;
- clearly distinguish aggregation results from record results;
- show record number/title and containing aggregation;
- show whether record metadata matched;
- list only components attributed as matches, retain their safe highlighted
  snippets, and provide governed component preview actions without enumerating
  the record's other components;
- show explicit loading, no-results, error, and partially-indexed states;
- use cursor-based **Load more** or pagination controls;
- open records and aggregations through their existing canonical navigation;
- clear any page-specific discard guard after entering global results so Back
  and breadcrumb navigation from a result detail page return normally rather
  than displaying an unrelated unsaved-changes dialog;
- never expose a direct component result detached from its record; and
- remain keyboard accessible with visible focus and descriptive labels.

"No results" must not imply that every eligible document is indexed when work
is pending or failed. A concise freshness notice may state that recently added
content is still being indexed. Failure detail is available only to users who
can view the affected component and must not expose raw parser output.

### 11.1 Header search design

The global search reuses the existing application header instead of adding a
second toolbar. On desktop it occupies the flexible center column between the
Wathiq identity/navigation area and account controls. Its maximum width keeps
the header balanced on wide screens; it contracts before either edge control.

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ [Wathiq]       [⌕  Search records, files and aggregations          ] [User]│
└────────────────────────────────────────────────────────────────────────────┘
```

The control uses the established header height, typography, focus treatment,
corner radius, and spacing. It has a white/high-contrast input surface on the
existing header color, a leading search icon, a clear control when populated,
and an accessible label. Enter submits. The control does not show live document
suggestions, result counts, recent queries, or content snippets in the initial
release, avoiding premature disclosure while typing.

At narrow responsive widths, the brand and account controls remain on the first
row and the expanded search input uses the full second row. If the established
mobile header cannot accept a second row, a search icon opens the same input in
the existing compact overlay pattern.

### 11.2 Results-page screen design

The page reuses Wathiq's application shell, breadcrumb, page heading, bordered
result surfaces, light-blue informational treatment, typography, spacing, and
canonical navigation actions. It does not introduce a raw NiceGUI `ui.table`.

![Conceptual Wathiq global search header and results page](assets/full-text-search/search-results-page.png)

*Conceptual desktop design. Final implementation must use the live Wathiq
components and design tokens identified during implementation.*

```text
Home / Search results

Search results
Results for “approved budget expenditure”

[All]  [Records · 12]  [Aggregations · 2]
─────────────────────────────────────────────────────────────────────────────
ⓘ Recently added content may still be indexing.

┌ RECORD ───────────────────────────────────────────────────── [Open record] ┐
│ Approved annual operating budget                                          │
│ FIN-R-001 · Annual financial administration                               │
├────────────────────────────────────────────────────────────────────────────┤
│ approved-budget-2026.pdf                                                   │
│ …the board approved the annual [budget expenditure] ceiling…              │
├────────────────────────────────────────────────────────────────────────────┤
│ finance-committee-minutes.docx                                             │
│ …members reviewed the [approved budget] and confirmed…                    │
└────────────────────────────────────────────────────────────────────────────┘

┌ AGGREGATION ─────────────────────────────────────────── [Open aggregation] ┐
│ Annual financial administration · FIN-2026                                │
│ Contains approved budgets, expenditure reports, and related records.      │
└────────────────────────────────────────────────────────────────────────────┘

                              [Load more results]
```

Record results are the primary cards. Their top area shows type, title, record
number, containing aggregation, whether metadata matched, and the existing
open-record action. Each matched component is a subordinate bordered row with
file name, a preview icon, and its escaped highlighted snippet. Unmatched
components are not rendered. Multiple matching chunks from one component do
not create duplicate component rows. The client may obtain authorized metadata
for those matched IDs solely to determine previewability. Preview opens the
established governed record-component viewer focused on that component;
unsupported or unavailable components retain a disabled icon with explanatory
guidance.

Aggregation results use the same surface and rhythm with a distinct type icon
and open-aggregation action. Type tabs filter the already submitted query. The
tab counts come from the initial response and stay fixed while paging. Each
tab uses its own cursor so Next requests one page for that tab. At mobile
widths actions use the established row/card navigation behavior, component
matches stack vertically, and no horizontal scrolling is required.

The rendered design must be compared in a live browser with the current Wathiq
header, search-first pages, record cards/tables, empty states, buttons, and
responsive navigation. Exact colors, icon glyphs, shadows, radii, and font
metrics come from existing design tokens/components rather than being copied
from the conceptual wireframe.

### 11.3 Dedicated Text Indexers administration and API-key management

The **Text Indexers** administration surface is separate from ordinary human
user and organizational-role administration. The navigation entry, list,
details, create, status, and credential operations require
`identity.text_indexers.administer`; users without that privilege cannot see
the entry and receive `403` from every dedicated mutation API. Person-account
pages never show API-key controls, and text-indexer identities are not editable
through ordinary user or role-assignment controls.

The dedicated details page reuses the existing identity, status, profile/role,
metadata, event-history, and navigation patterns. It explicitly labels the
identity **Service account** and **Non-interactive** so it cannot be mistaken
for a person who can sign in.

Ordinary **Roles** administration includes built-in roles in its list and
details presentation, clearly labels them **Built-in**, and exposes their
metadata and audit history read-only. It exposes no ordinary edit, assignment,
lifecycle, or deletion actions for a built-in role, and those generic API
mutation paths reject direct attempts. The built-in `text-indexer-service`
role details link authorized administrators to the dedicated **Text Indexers**
workflow. Its details explain that it is an implementation-owned role for
non-interactive processes, is assigned automatically when a Text Indexer is
created, is not a human role, and must be administered through that dedicated
workflow. Ordinary human-role selectors and assignment pickers continue to
exclude built-in roles.

The Text Indexers list shows each deployment/pool name, immutable external ID,
account status, active/total credential counts, and most recent safe last-used
time. It supports deliberate loading, empty, error, filter, and pagination
states using the established Wathiq administration-list presentation. **Add
text indexer** performs the atomic create-and-initial-key operation and proceeds
directly to the one-time reveal state.

The same administration surface contains a **Health** section backed by a
dedicated read-only endpoint requiring `identity.text_indexers.administer`.
It displays the current rollout-readiness result, active and stale registered
worker counts, queued and leased/processing job counts, failed and unsupported
job counts, oldest queued-job age, drifted and stale-document counts, expired
leases and lease-loss attempts. A manual **Refresh** action retrieves a new
database snapshot and exposes deliberate loading and error states.

The Health section also provides **Queue backfill batch**. The administrator
chooses a positive batch limit no greater than 500; the API scans at most that
many eligible missing or obsolete component indexes and idempotently queues
low-priority `backfill` jobs. It reports the number examined and the number
actually queued, never queues duplicate active work, and does not wait for
extraction to finish. Repeated bounded batches replace record-by-record manual
reindexing for pre-existing content.

The **Failed** Health indicator and rollout-readiness gate count only current
eligible `digital_component_search_documents` whose status is `failed` and
whose content/configuration identity still matches the active component.
Retained terminal failed jobs and attempts are historical operational evidence;
they are shown separately and never block readiness after a later successful
reindex. The administration surface provides **Retry failed documents** after
the cause has been corrected. Its administrator-selected batch limit is 1–500;
it idempotently creates `retry` jobs only for current failed documents without
an active queued/leased job, changes successfully queued documents to
`pending`, preserves failure history, returns examined/queued counts, and does
not wait for extraction.

The Health section contains **Failure diagnostics** for the same current,
eligible failed-document population. It groups failures by stable safe error
code and detected-or-declared MIME type and provides a server-paginated list
containing the bounded safe error summary, last-attempt time, worker ID and
attempt number. Retained historical failures are explicitly excluded. Each
failure identifies its record and digital component. Record titles/numbers,
component file names, and working navigation links are returned and rendered
only when the administrator independently passes the ordinary governed record
and component-view authorization checks; otherwise the UI shows identifiers
without disclosing governed metadata or providing a link.

The same area lists currently encountered unsupported formats, grouped by
detected-or-declared MIME type with a count and most-recent observation time.
Unsupported formats remain distinct from failed documents and do not enter the
readiness formula. This list describes current derived-document state rather
than retained historical attempts.

API liveness, indexing health and rollout readiness remain distinct. `/health`
proves API/database liveness and reports feature flags; it does not claim that
workers are active or the indexing backlog is healthy. The Text Indexers
Health section consumes only privacy-safe counts, durations and bounded status
or error-code labels. Failure diagnostics may additionally expose governed
record/component labels and links only after the ordinary record/component
authorization checks described above. It never exposes extracted text,
credentials, key hashes, lease tokens or storage/source-content locators.

The details-page API credentials section shows:

- credential display name and non-secret identifier/prefix;
- status (`Active`, `Expiring`, `Expired`, or `Revoked`);
- fixed allowed route, displayed as **Internal text-indexing API only**;
- creation time and creating administrator;
- required expiry time;
- last-used time and, when safe and available, the last worker ID;
- **Rotate** and **Revoke** actions for an active credential; and
- an explicit empty state when no credential exists.

Credential metadata is fetched with server-side pagination and the page shows
five entries by default. Administrators can filter between all credentials,
currently usable credentials, and revoked/expired history. The API accepts a
bounded page size no greater than 50 and never requires the browser to load the
complete credential history.

![Conceptual service-account API credentials page](assets/full-text-search/service-account-api-credentials.png)

*Conceptual service-account details page with the dedicated profile, privilege,
credential metadata, and management actions.*

It never shows a stored secret or secret hash. Revoked and expired entries
remain visible as security history during the configured retention period but
cannot be reactivated; an administrator must generate a new credential.
`TEXT_INDEXER_CREDENTIAL_HISTORY_RETENTION_DAYS` defaults to 365. The scheduled,
API-side text-indexing maintenance command deletes at most its configured batch
size of credential rows per run when they have been revoked for longer than the
retention period or expired longer than the retention period. It never deletes
a usable credential. Credential creation, rotation and revocation audit events
are not deleted with the credential row. A zero-day setting permits cleanup of
already revoked or expired credentials on the next maintenance run.

```text
Service account / Production Text Indexer                         [Edit]

Production Text Indexer             [Active] [Service account]
Non-interactive · Profile: Text Indexer Service

API credentials                                      [+ Generate API key]
┌────────────────────────────────────────────────────────────────────────────┐
│ Production indexer 1                                      [Active]         │
│ ID: wti_7FK2… · Internal text-indexing API only                         │
│ Created 24 Sep 2026 · Expires 24 Dec 2026 · Used 2 minutes ago           │
│                                                    [Rotate] [Revoke]        │
└────────────────────────────────────────────────────────────────────────────┘
```

**Generate API key** opens a focused dialog requiring a descriptive credential
name and expiry date. The allowed route is fixed and read-only; the administrator
cannot broaden it. Submission creates the credential and then replaces the
form with a one-time reveal state:

![Conceptual one-time API-key reveal dialog](assets/full-text-search/api-key-one-time-reveal.png)

*Conceptual one-time reveal state. The complete key is transient and cannot be
retrieved again after this dialog closes.*

```text
New API key

Copy and store this key now. It will not be shown again.
┌──────────────────────────────────────────────────────┐
│ wti_7FK2.<generated high-entropy secret>             │ [Copy]
└──────────────────────────────────────────────────────┘

[Download credential file]       [I have stored it safely]
```

The complete key is returned only in that successful creation response and is
held only in the current dialog's transient browser memory. Closing, refreshing,
navigating away, or confirming **I have stored it safely** destroys the displayed
value; neither the client nor API can retrieve it again. **Download credential
file** is optional and must warn that it writes a sensitive plaintext file to
the administrator's device. Copy/download actions do not send the secret to
analytics, logs, notifications, or event history.

Rotation creates a new credential rather than changing a stored secret. The
dialog requires the new expiry and offers either immediate revocation of the
old key or a bounded overlap-until time. The old and new identifiers are shown
as separate rows during overlap. The UI explains that deployment must switch to
the new key before the old key expires or is revoked.

Revocation requires confirmation naming the credential and warns that affected
indexer instances will fail on their next API request. It changes status to
`Revoked`; it does not delete the audit record. Deactivating or suspending the
service account disables every credential and displays that inherited state on
each row.

The credential list shall use Wathiq's standard light-blue headers, borders,
spacing, typography, action treatment, responsive card/table behavior, and
deliberate loading, empty, and error states. It must not use a raw/default
NiceGUI `ui.table`. The rendered page and reveal/rotate/revoke dialogs must be
compared with existing Wathiq User details and administrative tables in a live
browser.

### 11.4 Search-diagnostics UI

The UI exposes search diagnostics only when the authenticated principal has
`search.query.debug`. Without that privilege, the toggle, panel, copy actions,
and `debug` request property are absent rather than merely disabled.

For an authorized user, **Search diagnostics** is an off-by-default toggle in
the search-results page's secondary actions menu. Its preference is local to
the current browser/session and is not silently enabled by profile assignment.
Turning it on affects subsequent global or resource searches by adding
`"debug": true`; the current search may be rerun only after an explicit notice
that diagnostics require a new request.

When enabled, a collapsed **Search diagnostics** disclosure appears below the
search summary and above results. Expanding it shows two read-only,
syntax-highlighted JSON panels:

```text
Search diagnostics                                            [Disable]
─────────────────────────────────────────────────────────────────────────────
▾ Sent to API
  POST /api/v1/full-text-search                         [Copy JSON]
  { "record_where": { ... }, "aggregation_where": { ... }, "debug": true }

▾ Accepted by API
  Request ID: req_… · Fingerprint: sha256:…             [Copy JSON]
  { "record_where": { ... normalized defaults ... } }
```

The panel uses a bounded-height code surface with wrapping or horizontal
scrolling, preserves valid JSON indentation, and has accessible expand/collapse
and copy controls. Copying is an explicit local browser action. Query JSON is
not persisted to user preferences, event history, analytics, or ordinary
application logs. Navigating away clears the displayed diagnostics.

The same component is reused on resource search pages that issue the controlled
JSON grammar. It displays the actual endpoint and body for that search; it must
not reconstruct an approximation from visible filter widgets. Multiple API
requests caused by one global UI action are shown separately if the final
implementation does not use the single global endpoint.

## 12. Lifecycle, deletion, and freshness

- Successful upload or replacement queues indexing after activation.
- Replacement immediately excludes old chunks from queries, then publishes new
  chunks atomically on success.
- Component deletion cascades through current state and chunks. Attempt-history
  foreign keys become null while retaining safe identifiers/checksums until
  their operational retention expires.
- Record deletion cascades through record metadata indexes and component
  indexes. Aggregation deletion cascades through its metadata index subject to
  existing domain deletion rules.
- Metadata edits synchronously refresh the relevant metadata vector.
- A startup/backfill command discovers missing/stale eligible components in
  bounded keyset batches and can resume safely.
- A reconciliation pass detects queue/state drift, orphaned chunks, an indexed
  content set that is no longer active, and version mismatches.

## 13. Audit and observability

Manual component and record reindex requests append domain events
`CONTENT_REINDEX_REQUESTED` and `RECORD_CONTENT_REINDEX_REQUESTED` with actor,
request/correlation IDs, active content identity, attempt/batch IDs, and reason
`manual`. Completion details live in indexing history rather than generating an
event-history row for every worker transition.

Automatic indexing and retry activity is operational history, not user event
history. It uses source `system`. No event contains extracted text.

Required metrics include queue depth and oldest age, attempts and outcomes by
safe format/error code, extraction latency, OCR latency, bytes processed,
characters/chunks produced, stale-index count, worker lease recovery, and
temporary-storage cleanup failures. Format labels must be bounded to avoid
high-cardinality metrics. Health reporting distinguishes API health from
indexing backlog; a backlog does not make content download unavailable.

## 14. Security and robustness

The implementation shall treat every file and extracted string as hostile.
It must cover:

- process-sandbox isolation and least privilege for Tika, Tesseract, and
  LibreOffice fallback;
- no extractor endpoint exposed to untrusted networks;
- service-to-service authentication, authorization, credential rotation, and
  revocation for every internal indexing endpoint;
- rejection of person accounts, browser sessions, malformed API keys, inactive
  service accounts, expired/revoked keys, and service accounts lacking
  `content.index.execute`;
- endpoint allowlisting that prevents an indexer credential from being used on
  public record, component, search, audit, or administration APIs;
- opaque random lease tokens stored only as hashes where practical and never
  written to logs, metrics, history, or error bodies;
- pinned, patched extractor/runtime versions and dependency scanning;
- decompression-bomb, XML entity, archive recursion, embedded-object, page,
  pixel, memory, CPU, timeout, and output limits;
- a private temporary directory with cleanup on success, failure, timeout, and
  worker restart;
- checksum verification before publishing an index;
- HTML/script removal and output normalization;
- escaped result rendering and safe snippet markers;
- parameterized SQL and bounded query complexity;
- allowlist-based diagnostic serialization that cannot expose SQL, execution
  plans, credentials, hidden authorization predicates, or another user's query;
- rate limiting for search and stronger throttling for manual reindex;
- cancellation when content changes or is deleted; and
- backup/restore treatment of extracted text equivalent to source content.

Password-protected or affirmatively malformed content produces a stable
non-sensitive error code. `corrupt` is reserved for evidence that the input
document itself is malformed; an unclassified non-zero extractor exit must not
be labelled corrupt. Tika process-start, JVM, dependency, fork-parser
initialization, operating-system resource, and local fork-communication
failures produce a bounded safe `extractor_unavailable` summary and are
retryable. Network or storage-transfer failures remain `transient_io`, while
wall-clock exhaustion remains `timeout`. Wathiq shall not collect or retain
document passwords for indexing.

## 15. Delivery phases

Every phase is subject to the entry inventory and phase-exit reconciliation in
section 1.1. Completing a phase requires updating the traceability matrix with
the implementation and verification evidence produced by that phase.

### Phase 0 — corpus and decisions

Assemble approved representative English/Arabic documents for every supported
format, including native PDFs, scanned PDFs, images, corrupt files,
password-protected files, very large documents, and adversarial fixtures.
Benchmark quality and resource limits. Confirm PostgreSQL configurations and
OCR language packs.

### Phase 1 — schema and metadata search

Add canonical schema and migration objects, metadata vectors, GIN indexes,
the `content.index.execute` privilege, protected service profile/role,
service-account API-key storage, authorized
query views/functions, the `search.query.debug` privilege, and
metadata/authentication API tests. Update the authorization operation inventory
and service-account documentation.

### Phase 2 — API queue and text-indexer service

Add durable database scheduling and leasing, authenticated internal REST
endpoints, storage-provider streaming, the separately deployable
`backend/services/text_indexer/` service, isolated Tika/Tesseract integration,
staged chunk publication, fencing, retries, recovery, backfill, reconciliation,
metrics, API-owned history/staging cleanup, `run-text-indexer.sh`, local-stack
integration, and operational documentation.

### Phase 3 — APIs and reindex UI

Extend the controlled JSON grammar and the relevant resource-search endpoints,
update `docs/search-grammar.md`, add the global-search, component-reindex,
record-reindex, status, and privileged diagnostic API behavior, and add
authorized component/record actions and their states.

### Phase 4 — global header and results

Add responsive header search, the Wathiq-styled result page, and the privileged
off-by-default diagnostics panel. Compare the rendered UI in a live browser
with established Wathiq search/results patterns.

### Phase 5 — rollout

Deploy workers disabled, migrate, enable automatic indexing for new content,
run bounded backfill, observe load/quality, then enable header search. Rollback
may disable scheduling/search without deleting source content. Index tables are
rebuildable derived data, but their removal requires a later explicit migration.

## 16. Acceptance criteria and traceability

| ID | Requirement | Verification evidence |
| --- | --- | --- |
| FTS-01 | New available content is durably queued and indexed asynchronously | DB/API integration test plus worker test |
| FTS-02 | Unchanged identity and config skip normal extraction | Worker idempotency test and attempt-history assertion |
| FTS-03 | Forced component reindex creates/reuses the correct active attempt | API/DB test |
| FTS-04 | Record reindex snapshots and queues all eligible components independently | API/DB batch test |
| FTS-05 | Replacement makes old text unsearchable at activation and publishes new text atomically | Concurrency integration test |
| FTS-06 | Record number/title/description are searchable with documented weights | SQL ranking test |
| FTS-07 | Aggregation metadata appears only as aggregation results | SQL/API test |
| FTS-08 | Record results show only components attributed as matches, preserve each matched component's bounded safe highlighted snippet, and offer governed preview on those rows without enumerating unmatched components | API attribution, authorization, preview-wiring, and XSS UI tests |
| FTS-09 | Unauthorized resources, components, snippets, and counts cannot be inferred | authorization matrix and cross-user tests |
| FTS-10 | Arabic and English native text and OCR meet corpus quality thresholds approved in Phase 0 | corpus evaluation report |
| FTS-11 | Unsupported, corrupt, protected, oversized, timed-out, and malicious inputs fail safely without losing the prior valid index | worker robustness tests |
| FTS-12 | Worker crash/lease expiry is recoverable and jobs are idempotent | termination/recovery integration test |
| FTS-13 | Component/record deletion removes searchable derived text | DB cascade and API search tests |
| FTS-14 | All SQL uses explicit text-search configurations and GIN indexes are used for representative queries | schema inspection and `EXPLAIN` test |
| FTS-15 | Header/results UI has loading, empty, failure, freshness, responsive, keyboard, and pagination behavior | live-browser tests and visual comparison |
| FTS-16 | No extracted text enters logs, metrics, URLs, or event history | log/event assertions and security review |
| FTS-17 | Migration and fresh `database/schema.sql` create equivalent objects | canonical-schema parity test on disposable databases |
| FTS-18 | Database-backed tests create, initialize, use, and drop a unique disposable PostgreSQL database | test-run evidence including cleanup |
| FTS-19 | Two or more indexer instances claim distinct jobs concurrently without waiting on extraction-duration locks | concurrent API/DB integration test |
| FTS-20 | An expired worker lease can be reclaimed, and the obsolete token/generation cannot upload or publish | lease-expiry and fencing integration test |
| FTS-21 | Repeated scheduling and concurrent manual requests produce at most one active job per content/config identity | unique-index concurrency test |
| FTS-22 | The text-indexer has no database credentials and completes all work through authenticated internal REST endpoints | deployment/configuration test and security review |
| FTS-23 | Chunk and completion retries are idempotent after ambiguous network outcomes | API contract integration test |
| FTS-24 | Only an active `service` account with a valid unexpired text-indexer API key and `content.index.execute` can call internal worker endpoints | authentication/authorization matrix test |
| FTS-25 | Person sessions and indexer credentials used on public or unrelated endpoints are rejected | negative API tests |
| FTS-26 | The Text Indexer Service profile contains exactly `content.index.execute` and grants no ordinary resource, search, audit, or administration privilege | seed and catalogue parity test |
| FTS-27 | A valid worker cannot retrieve or publish content without the exact current job ID, lease token, and generation | job-scope authorization test |
| FTS-28 | Credential rotation overlap works, and account suspension, privilege removal, expiry, or credential revocation prevents the next worker request | lifecycle integration tests |
| FTS-29 | Credential and lease secrets never appear in stored events, logs, metrics, URLs, or API error bodies | security/logging test and review |
| FTS-30 | Only authorized service-account details pages expose credential controls; person accounts never do | UI and API authorization tests |
| FTS-31 | A generated or rotated key is revealed once, cannot be retrieved later, and only its identifier/status metadata remains visible | API, browser, persistence, and refresh tests |
| FTS-32 | Generate, copy/download, rotate-overlap, revoke, expiry, inherited account-disablement, and loading/empty/error states follow the specified UI behavior | live-browser workflow and visual-regression tests |
| FTS-33 | `run-text-indexer.sh` creates/updates only its dedicated runtime environment, validates capabilities/configuration, preserves signal handling, and never prints secrets | launcher integration test |
| FTS-34 | `run-local-stack.sh` starts, waits for, monitors, reports, and stops its managed indexer; an unexpected exit fails the stack | local-stack process-lifecycle test |
| FTS-35 | Automatic local credential provisioning is loopback/development-only, uses production authentication semantics, writes a mode-`0600` git-ignored secret, and refuses non-local targets | provisioning security integration test |
| FTS-36 | Disabling the local indexer is explicit and reported, while search continues to expose accurate pending-index freshness | local-stack and UI integration test |
| FTS-37 | A `full_text` leaf combines with nested structured `and`, `or`, and `not` predicates in one parameterized authorized SQL query | grammar, API, and database integration tests |
| FTS-38 | Record, aggregation, and digital-component searches enforce their documented full-text source allowlists and reject raw `tsquery`, configuration names, and invalid sources | validation and injection tests |
| FTS-39 | Relevance sorting is available only for positive full-text searches and remains deterministic with pagination | ranking and pagination tests |
| FTS-40 | `include: ["full_text_matches"]` returns only bounded authorized attribution/snippets and does not alter the matched resource set | API and authorization tests |
| FTS-41 | The global-search endpoint applies the same grammar independently to record and aggregation branches and never treats an omitted branch as match-all | API contract tests |
| FTS-42 | Only a principal with `search.query.debug` can request or see diagnostics; the privilege never expands search results or resource access | privilege and authorization matrix tests |
| FTS-43 | Diagnostics show the exact sanitized body received and the canonical API-level JSON after defaults/normalization | API contract and UI integration tests |
| FTS-44 | Diagnostic output never includes SQL, plans, database/internal authorization details, credentials, tokens, headers, or another user's query | serializer allowlist and leakage tests |
| FTS-45 | The diagnostics UI is absent without privilege and off by default with privilege; enablement is session-local and affects only subsequent explicit searches | browser tests |
| FTS-46 | Sent-request diagnostics remain available after a network failure, while accepted-query diagnostics accurately show unavailable | browser failure-path test |
| FTS-47 | `record.component.reindex` and `search.query.debug` are seeded into `ALL_PRIVS`, `SYS_ADMIN`, `INFO_GOV_MGR`, and `INFO_GOV_OFFICER` exactly as specified | privilege-seed and canonical-schema parity tests |
| FTS-48 | Forced reindex requires `record.component.reindex` plus the documented record/component global privileges, ACL permissions, and clearance; `SYS_ADMIN` alone cannot bypass governed-resource authorization | authorization matrix and UI visibility tests |
| FTS-49 | Indexer authentication uses only an opaque hashed API key over ordinary HTTPS, requires no JWT/client-certificate/PKI support, and the key is rejected outside `/api/v1/internal/text-indexing/*` | authentication and route-isolation tests |
| FTS-50 | API-key generation produces at least 256 random bits, stores only identifier and the SHA-256 digest of the exact Base64url secret substring, verifies in constant time, and redacts the complete key everywhere after one-time issuance | deterministic hash-vector, generation, persistence, authentication, rotation, and logging tests |
| FTS-51 | API-side indexing cleanup uses one advisory-locked leader and bounded batches, removes only expired terminal history/jobs or abandoned staging, preserves active and published data, and reports failures | disposable-database concurrency, retention-boundary, dry-run, and failure-path tests |
| FTS-52 | A version-pinned local detector selects only approved language-to-configuration mappings; English, Arabic, unknown, short, and mixed-language corpus cases use the documented per-chunk configuration and fallback behavior | language corpus, configuration-selection, mixed-document, and rebuild-version tests |
| FTS-53 | Fresh schema and upgrade migration require the built-in `pg_catalog.simple`, `pg_catalog.english`, and `pg_catalog.arabic` configurations without modifying catalogue objects or the database default; representative Arabic vectors and queries use the same explicit configuration | disposable PostgreSQL 18 schema/migration precondition, catalogue, tokenization, matching, and parity tests |
| FTS-54 | The opaque-key baseline enforces validated HTTPS, environment/pool-specific keys, protected secret handling, route and privilege isolation, network restrictions, lease fencing, rate limits, redacted telemetry, expiry, rotation, revocation, and monitoring | deployment, authentication, authorization, TLS-negative, secret-leakage, rate-limit, rotation, and incident-response tests/security review |
| FTS-55 | Every phase and the final delivery reconcile all applicable normative requirements in both directions through the maintained requirement-to-implementation-to-test matrix; no phase or feature is complete with an unexplained omission or unapproved implementation behavior | reviewed phase-entry inventories, phase-exit reports, final full-spec audit, traceability matrix, and evidence-link validation |
| FTS-56 | `identity.text_indexers.administer` is granted by default only to `ALL_PRIVS` and `SYS_ADMIN`; it alone gates the dedicated Text Indexers UI and management APIs while `TEXT_INDEXER_SERVICE` remains exactly `content.index.execute` | seed/parity, authorization-matrix, and navigation-visibility tests |
| FTS-57 | Dedicated creation atomically creates one active non-interactive service identity, its sole protected role assignment, and an initial one-time API key; multiple environment/pool identities are supported and partial failure leaves no account | API transaction, uniqueness, persistence, and one-time-secret tests |
| FTS-58 | Generic user/role-assignment administration cannot mutate a text-indexer identity or its protected assignment; suspension, activation, key generation, rotation, and revocation are available through the dedicated workflow with list/detail monitoring | negative API tests and live-browser workflow tests |
| FTS-59 | The privilege-gated Text Indexers Health section distinguishes API liveness from worker/queue health; shows privacy-safe readiness, worker heartbeat, backlog, failure, drift, stale-document and lease-recovery state; and can idempotently queue an administrator-bounded backfill batch of at most 500 components | API authorization/leakage/backfill tests and live-browser UI verification |
| FTS-60 | One text-indexer service supervises `TEXT_INDEXER_PROCESS_COUNT` child processes (default `2`); each child claims one job, has a generated unique worker ID, and is restarted by slot without terminating healthy siblings | configuration-default, supervisor, worker-loop and deployment tests/review |
| FTS-61 | Built-in roles are visible and clearly labelled in Roles administration but remain read-only and excluded from ordinary assignment selectors; the text-indexer role links authorized users to Text Indexers | API visibility/mutation tests and live-browser list/detail verification |
| FTS-62 | Text Indexers Health/readiness counts only currently failed eligible search documents while exposing retained failed-job history separately; an administrator can idempotently queue a bounded 1–500 retry batch for current failures without deleting history or duplicating active work | disposable-database current/history/readiness, authorization, bounds, idempotency and UI workflow tests |
| FTS-63 | Text Indexers Health provides current-failure groups and a paginated current-failure list with safe diagnostic metadata; record/component labels and links require ordinary resource-view authorization; currently unsupported formats are aggregated separately by MIME type and historical attempts are excluded | disposable-database authorization/leakage/pagination/aggregation tests and live-browser navigation/visual verification |

The feature is not complete until every acceptance criterion has implementation
and verification evidence. Database tests must follow the repository rule that
prohibits running tests against any persistent development, staging, or
production ERMS database.

## 17. Reference rationale

- Apache Tika documents a common text/metadata extraction interface across a
  broad range of formats and supports Tesseract integration for OCR:
  <https://tika.apache.org/docs/4.0.x/formats.html>
- Tesseract accepts common raster images but does not read PDF directly; PDF
  page rendering/OCR orchestration therefore belongs in Tika or another bounded
  PDF-aware layer:
  <https://tesseract-ocr.github.io/tessdoc/InputFormats.html>
- PostgreSQL documents explicit text-search configurations, `tsvector`,
  `websearch_to_tsquery`, ranking/highlighting, and GIN indexing:
  <https://www.postgresql.org/docs/current/textsearch-controls.html> and
  <https://www.postgresql.org/docs/current/textsearch-tables.html>
- PostgreSQL 18 supplies built-in language configurations and dictionaries,
  including the Arabic Snowball dictionary used by `pg_catalog.arabic`:
  <https://www.postgresql.org/docs/18/textsearch-psql.html>
