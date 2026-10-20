# ERMS Operational Tools Catalogue

**Audience:** DevOps engineers, system administrators, and release engineers  
**Last reviewed:** 20 October 2026

## 1. Purpose

This document is the single catalogue of ERMS command-line tools and background
workers intended for operational use. It identifies what each tool changes, how
it is invoked, whether it runs once or continuously, required safeguards, and
whether it is currently implemented or planned.

Feature documentation may explain why an operation exists, but deployment and
runbook procedures must link back to this catalogue. A new operational command,
scheduled worker, repair utility, or destructive environment tool must be added
here as part of the same change that introduces it.

## 2. Common operating rules

Operational tools run outside FastAPI and must not be started inside every API
worker. They use the same application environment and `DATABASE_URL` as the API
unless their section says otherwise.

Every cleanup worker must:

- support a one-shot invocation suitable for a scheduler;
- support `--dry-run` without committing changes;
- process bounded batches;
- use a dedicated PostgreSQL advisory lock so overlapping invocations are safe;
- be idempotent when re-run;
- identify itself in audit context as an `automated_process`;
- use `scheduled_job` for scheduled execution and an appropriate CLI or
  administrative source for deliberate manual execution;
- print consistently structured result counts;
- exit nonzero on failure; and
- document all configuration and retention settings here.

Only one continuous instance of a given worker is needed per logical database.
An advisory lock is still required because deployments and schedulers can
overlap during restarts.

There are two supported scheduling models:

1. Invoke the one-shot command from a deployment scheduler, Kubernetes CronJob,
   systemd timer, or equivalent. This is preferred when a scheduler is
   available.
2. Run `--watch` as one dedicated supervised process when an external scheduler
   is not available.

Do not run `--watch` from FastAPI startup or once per FastAPI worker.

## 3. Central cleanup-service inventory

This table is the authoritative project-wide index of automatic or schedulable
backend cleanup responsibilities. Every new cleanup service must be added here
with its owner, status, invocation model, retained/deleted data, configuration,
and a link to its specialized normative documentation.

| Cleanup responsibility | Owning module/service | Status | Execution model | Specialized documentation |
| --- | --- | --- | --- | --- |
| Segmented content, upload session, draft, and superseded-content cleanup | `backend.services.api.content_cleanup` | Implemented | Scheduled one shot or one supervised `--watch` process | [Segmented-content cleanup](#5-segmented-content-cleanup), [content-storage guide](content-storage.md), [storage specification](../specs/segmented-postgresql-content-storage.md#11-cleanup-and-recovery) |
| Expired and retained revoked login-session cleanup | `backend.services.api.session_cleanup` | Implemented | Scheduled one shot or one supervised `--watch` process | [Login-session cleanup](#6-login-session-cleanup), [authentication guide](authentication.md), [session-lifecycle specification](../specs/authentication-and-login-session-lifecycle.md#8-retention-and-cleanup) |
| Full-text indexing attempt/job history, abandoned result staging, and retained text-indexer credential cleanup | `backend.services.api.text_indexing_maintenance` | Implemented | Scheduled one shot or one supervised `--watch` process | [Full-text indexing cleanup](#7-full-text-indexing-history-and-staging-cleanup), [full-text-search specification](../specs/full-text-search.md#66-content_indexing_attempts) |
| Per-job text-indexer temporary-file cleanup | `backend.services.text_indexer` | Implemented | Immediate `finally` cleanup plus bounded startup recovery sweep; not a database scheduler | [Full-text indexing cleanup](#7-full-text-indexing-history-and-staging-cleanup), [security and robustness requirements](../specs/full-text-search.md#14-security-and-robustness) |

The inventory distinguishes automatic retention/temporary-data cleanup from
explicit governed deletion. Permanent deletion of a record, aggregation, user,
role, organizational unit, hold, or other domain entity is a deliberate
authorized business operation and must not be reclassified as background
cleanup merely because dependent rows cascade.

## 4. Operational tool summary

| Tool | Status | Default mode | Purpose | Specialized documentation |
| --- | --- | --- | --- | --- |
| `backend.services.api.content_cleanup` | Implemented | One shot | Remove abandoned uploads, expired drafts, and unreferenced content sets | [Section 5](#5-segmented-content-cleanup) |
| `backend.services.api.session_cleanup` | Implemented | One shot | Audit and remove expired or long-revoked login sessions | [Section 6](#6-login-session-cleanup) |
| `backend.services.api.text_indexing_maintenance cleanup` | Implemented | One shot or supervised `--watch` | Remove expired terminal indexing history/jobs, abandoned result staging, and retained revoked/expired text-indexer credentials | [Section 7](#7-full-text-indexing-history-and-staging-cleanup) |
| `backend.services.api.manage_auth` | Implemented | One shot | Bootstrap authentication and perform deliberate credential recovery | [Section 8](#8-authentication-bootstrap-and-credential-recovery) |
| Database migration commands | Implemented | One shot | Upgrade the schema exactly once per database | [Section 9](#9-database-migrations) |
| Database seed commands | Implemented | One shot | Install optional reference, demonstration, or load-test data | [Section 10](#10-optional-database-seeds) |
| `tools/migrate_application_settings.py` | Implemented | Explicit preview/apply/check | Review and migrate legacy settings independently for each database; never imports on startup | [Settings migration](#general-settings-migration-and-readiness), [rollout instructions](disposition-rollout.md#3-preview-review-apply-and-verify-local-settings-per-database) |
| `backend.services.api.application_settings_secret --init-local-key` | Implemented | Explicit one shot | Initialize a missing local API encryption-key assignment without printing or replacing an existing key | [Disposition setup](#141-initial-setup-and-configuration) |
| `backend.services.api.disposition.eligibility` | Implemented | One shot or supervised `--watch` | Evaluate bounded eligible roots and task eligibility | [Disposition workers](#142-worker-startup-and-verification) |
| `backend.services.api.disposition.communications` | Implemented | One shot or supervised `--watch` | Process queued document email and disposition reminders | [Disposition workers](#142-worker-startup-and-verification) |
| `backend.services.api.disposition.destruction_worker` | Implemented; operational release disabled | One shot or supervised `--watch` | Resume durable authorized digital work and certificate-only completion | [Disposition workers](#142-worker-startup-and-verification), [recovery](#143-recovery-and-rollback) |
| `tools/rehearse_disposition_rollout.py` | Implemented | Disposable rehearsal | Create fresh/two upgrade test databases, rehearse setup, and drop all created databases | [Phase 24 verification](disposition-phase-24.md) |
| Pre-production database reset | Planned | One shot, destructive | Recreate a not-yet-operational environment after setup or smoke testing | [Section 11](#11-pre-production-database-reset) |

## 5. Segmented-content cleanup

**Status:** Implemented
**Module:** `backend.services.api.content_cleanup`

This worker removes expired or failed upload sessions, expired record drafts and
their staged data, and superseded or failed content sets that are not active.

```bash
python -m backend.services.api.content_cleanup --dry-run --batch-size 100
python -m backend.services.api.content_cleanup --batch-size 100
python -m backend.services.api.content_cleanup \
  --watch --batch-size 100 --interval-seconds 3600
```

| Setting | Default | Meaning |
| --- | --- | --- |
| `CONTENT_CLEANUP_INTERVAL_SECONDS` | `3600` | Delay between continuous worker passes |

The worker uses a PostgreSQL advisory lock and records a `CONTENT_CLEANUP`
domain event when committed work occurs. See
[PostgreSQL segmented content storage](content-storage.md).

## 6. Login-session cleanup

**Status:** Implemented
**Module:** `backend.services.api.session_cleanup`

This worker treats `login_sessions` as transient operational security data
while preserving `event_history` as the durable authentication audit trail.

An eligible revoked session is one whose `revoked_at` is older than the
configured retention period. An eligible unrevoked expired session is one whose
first applicable idle or absolute expiry is older than the configured retention
period. Active sessions are never eligible.

Before deleting an expired session, the worker writes a `SESSION_EXPIRED` event
containing the final security-safe session snapshot. Revoked sessions must
already have the required durable revocation audit information; the worker must
verify or supply the required terminal audit event before deleting the row.
Token and CSRF secrets or hashes must never be copied into event history.

Interface:

```bash
python -m backend.services.api.session_cleanup --dry-run --batch-size 500
python -m backend.services.api.session_cleanup --batch-size 500
python -m backend.services.api.session_cleanup \
  --watch --batch-size 500 --interval-seconds 3600
```

| Setting | Initial default | Meaning |
| --- | --- | --- |
| `AUTH_SESSION_RETENTION_DAYS` | `90` | Retention after revocation or effective expiry |
| `AUTH_SESSION_CLEANUP_INTERVAL_SECONDS` | `3600` | Delay between continuous worker passes |
| `AUTH_SESSION_CLEANUP_BATCH_SIZE` | `500` | Default maximum rows processed per pass |

The implementation must use a session-cleanup-specific advisory-lock key. It
must not share the segmented-content cleanup lock because the jobs operate on
independent data and may run concurrently.

The preferred production deployment is an external scheduler running the
one-shot command. `--watch` exists for simple deployments and must run as its
own supervised service, never inside FastAPI.

The normative lifecycle, audit, retention, and cleanup requirements are in
[Authentication and Login-Session Lifecycle](../specs/authentication-and-login-session-lifecycle.md).

## 7. Full-text indexing history and staging cleanup

**Status:** Implemented in Phase 2
**Module:** `backend.services.api.text_indexing_maintenance`

This API-side database maintenance worker removes expired terminal indexing
attempt history and eligible terminal job rows after their retention period. It
also removes abandoned result-staging chunks and text-indexer API-credential
rows that have been revoked or expired longer than their retention period. It
does not run in the separately deployed text-indexer service. Active,
unexpired credentials are never eligible, and credential lifecycle audit events
remain after credential-row cleanup.

```bash
cd /absolute/path/to/erms
set -a
source .env
set +a
backend/services/api/.venv/bin/python -m backend.services.api.text_indexing_maintenance cleanup --dry-run
backend/services/api/.venv/bin/python -m backend.services.api.text_indexing_maintenance cleanup --batch-size 500
backend/services/api/.venv/bin/python -m backend.services.api.text_indexing_maintenance cleanup --watch
backend/services/api/.venv/bin/python -m backend.services.api.text_indexing_maintenance reconcile --dry-run
backend/services/api/.venv/bin/python -m backend.services.api.text_indexing_maintenance reconcile --batch-size 500
backend/services/api/.venv/bin/python -m backend.services.api.text_indexing_maintenance metrics
backend/services/api/.venv/bin/python -m backend.services.api.text_indexing_maintenance readiness
backend/services/api/.venv/bin/python -m backend.services.api.text_indexing_maintenance quality-gate \
  examples/samples/docs/phase2-worker-benchmark-results.json
```

Administrators with `identity.text_indexers.administer` can perform the common
operational checks without a terminal: open **Administration → Text Indexers**
and use the **Health** section. It shows the same privacy-safe readiness,
worker, queue, stale-data and lease-recovery signals. **Refresh** requests a new
snapshot. **Queue backfill batch** accepts a limit from 1 through 500 and runs
one idempotent low-priority reconciliation pass; it reports how many eligible
components were examined and how many jobs were queued. Repeat bounded passes
until a pass reports zero examined and zero queued, then allow workers to drain
the queue and confirm **Ready for search**. The action only queues work; it does
not wait for extraction to finish.

### Understanding the Text Indexers Health indicators

The Health section is a point-in-time operational snapshot. Its headline is
calculated as follows:

```text
blocking jobs = waiting (queued) jobs + processing (leased) jobs

Ready for search =
    drifted documents = 0
AND blocking jobs = 0
AND stale documents = 0
AND current failed documents = 0
```

If any condition in that formula is false, the headline is **Attention
required**. Active-worker count, unsupported jobs, expired leases, and
historical lease-loss attempts remain important operational signals but do not
currently enter the readiness formula. Consequently, an empty and fully
current index can report Ready for search even when no worker is active; it
will not remain current when new work arrives unless a worker is restored.

| Indicator | Meaning and interpretation |
| --- | --- |
| **Active workers** | Worker child processes whose registration has an unexpired activity window. Under the process-pool model, each healthy child registers separately and handles one job at a time. Zero is highlighted because queued work cannot drain without a worker. |
| **Stale registrations** | Persisted worker registrations whose activity window has expired, usually after a service restart, replaced child process, or lost worker. They are not active and do not process jobs. This is not a count of stale documents. |
| **Waiting** | Jobs in `queued` state that have not been leased to a worker. **Oldest** is the approximate age of the oldest queued job. A rising oldest age indicates that extraction capacity is not keeping up, workers are unavailable, or work is repeatedly deferred. |
| **Processing** | Jobs in `leased` state. A worker has exclusive time-bounded authority to process each one. With `TEXT_INDEXER_CLAIM_BATCH_SIZE=1`, this should normally be no greater than the active child-worker count; temporary differences can appear during restarts, lease recovery, or while older prefetched work drains. |
| **Failed documents** | Current eligible search documents whose latest derived-index state is `failed` for the active content/configuration identity. These block Ready for search and require investigation followed by a bounded retry after the cause is corrected. |
| **Historical failed jobs** | Retained terminal job history. It supports diagnosis and trends but does not block readiness: a later successful retry clears the current failed-document state without deleting the earlier failed job or attempt. |
| **Unsupported** | Terminal jobs whose detected format is outside the approved extraction support policy. They are reported beside failures but do not currently block the readiness formula. Review unexpected growth because it may indicate incorrectly classified or newly encountered formats. |
| **Drifted documents** | Eligible digital components whose required current derived search document is missing, points at a different active content set, or uses an obsolete extraction/index configuration. Use bounded reconciliation/backfill to schedule them. |
| **Stale documents** | Previously published search documents explicitly marked no longer current. These block readiness until current content is successfully indexed. This is distinct from drift and from stale worker registrations. |
| **Expired leases** | Jobs still recorded as leased even though their lease deadline has passed. They are current recovery candidates and should normally be reclaimed by another worker. Persistent growth suggests heartbeat, worker, API, or capacity trouble. |
| **Lease-loss attempts** | Cumulative indexing-attempt history whose worker lost authority before committing. This is historical evidence, not a count of current failed or expired jobs, and it does not by itself block readiness. Investigate a rising value rather than expecting it to return to zero. |
| **Blocking jobs** | Exactly Waiting plus Processing. The observation timestamp beneath it identifies when the snapshot was taken. Blocking jobs prevent Ready for search. |

The counts are not all disjoint and must not be added together. In particular:

- **Blocking jobs** already contains **Waiting** and **Processing**.
- A **drifted document** may already have a waiting or processing job, so drift
  must not be added to the queue to calculate outstanding documents.
- **Failed** and **Unsupported** are job states, while **Drifted** and **Stale**
  describe derived search-document state; the same component can therefore be
  represented in both kinds of metric.
- **Stale registrations** and **lease-loss attempts** are operational history,
  not additional documents awaiting extraction.

#### Why Waiting can fall while Drifted documents stays unchanged

This is expected when the jobs currently draining belong to components whose
search-document identity is already current and whose status is merely
`pending` or `processing`. Completing those jobs reduces **Waiting**,
**Processing**, and therefore **Blocking jobs**, but it does not change the
separate drift predicate.

**Drifted documents** is the population whose derived search-document state is
missing, points to a different active content set, or records an obsolete
extraction/index configuration. Those components require a reconciliation
pass before workers can drain their indexing work. They are not automatically
represented by every job already in the queue.

For example:

```text
Waiting: 1,580; Processing: 6
    = 1,586 already scheduled jobs

Drifted documents: 1,199
    = components requiring reconciliation of missing/obsolete index state
```

As the existing 1,586 jobs finish, Waiting and Blocking can decrease while the
1,199 drifted count remains unchanged. This does not mean workers are idle or
that completed jobs failed; it means they are processing a different or only
partly overlapping population.

Use **Queue backfill batch** to reconcile drift safely:

1. Choose a bounded limit from 1 through 500 and queue one batch.
2. Refresh Health. Drifted should fall by up to the number examined because
   reconciliation creates or updates the required search-document identity;
   Waiting may rise by the number of newly queued jobs.
3. Observe active workers, oldest queued age, failures, and host/database load
   before adding another batch.
4. Repeat until a batch reports zero examined and zero queued.
5. Allow Waiting and Processing to reach zero and confirm **Ready for search**.

Do not assume `drifted + waiting + processing` is the remaining document
total: the populations may overlap. If a successful backfill action reports
examined components but Drifted does not decrease after **Refresh**, treat that
as a reconciliation persistence fault and investigate rather than repeatedly
queuing more batches.

#### Investigating failed documents and unsupported formats

Open **Administration → Text Indexers → Health → Failure diagnostics** before
retrying failed documents. The diagnostic groups show the current failure
population by safe error code and detected-or-declared MIME type. The entries
below them show the latest bounded error summary, attempt time, worker and
attempt number. This population matches the current **Failed documents**
indicator; it does not include retained historical failures that later
succeeded.

Use **Record** to open the governed record or **Component** to open its Digital
components view with the affected component highlighted. These links and their
record/component names appear only when the administrator also has ordinary
permission to view that record and its components. Text-indexer administration
does not bypass records authorization.

The **Unsupported formats currently encountered** list groups current
unsupported search-document states by MIME type. It is not a list of every
unsupported attempt ever retained, and its counts must not be added to the
failed-document count. Unexpected or rapidly growing formats can indicate bad
upload metadata, a classification problem, or a legitimate format that needs a
separately approved extraction policy change.

For failures, investigate the largest error-code/MIME group first, correct its
shared dependency, content or capacity cause, then use a small bounded **Retry
failed** batch. Confirm successful indexing before increasing the retry batch.
Do not repeatedly retry `password_protected`, `corrupt`, or `limit_exceeded`
documents without changing the content or the approved policy that caused the
failure.

`corrupt` means the extractor produced affirmative evidence that the input
document itself is malformed. It must not be inferred merely from a non-zero
process exit. Tika/JVM startup, missing-runtime, fork-parser initialization,
operating-system resource and local fork-communication failures are reported
as retryable `extractor_unavailable` outcomes. Content download or storage
communication failures are `transient_io`, and extraction deadline exhaustion
is `timeout`. Correct the shared runtime or communication problem before using
**Retry failed** for those groups.

##### Text-rich PDF repeatedly reports `timeout`

A large PDF can contain a complete searchable text layer while also containing
hundreds of page images. Native Tika extraction may finish quickly, but an
incorrect unconditional OCR path can then spend the remaining deadline
rendering and OCRing every page. Typical evidence is:

- `pdfinfo` reports a high page count but a moderate file size;
- native Tika extraction produces substantial text well within
  `TEXT_INDEXER_EXTRACTION_TIMEOUT_SECONDS`;
- the indexing attempt nevertheless ends as `timeout` during PDF rendering or
  OCR; and
- repeating the job produces the same failure at approximately the configured
  deadline.

The supported worker first extracts native PDF text. It skips rendering and
OCR when the native result contains at least the greater of 200 meaningful
alphanumeric characters or 100 per page. PDFs below that conservative density
gate continue through bilingual OCR, preserving support for scanned and
text-poor documents. A resource-limit termination during PDF rendering is
reported as retryable `timeout`, not `corrupt`.

Do not start by increasing `TEXT_INDEXER_EXTRACTION_TIMEOUT_SECONDS`. The
worker also applies an independent subprocess CPU ceiling, and raising only the
wall timeout can leave the same expensive OCR work or resource-limit failure in
place. Confirm that the deployment includes the native-text OCR gate, restart
the text-indexer service, and retry one affected component. In **Failure
diagnostics**, verify that the new attempt succeeds with `ocr_used=false`
before retrying a larger batch. Only reconsider approved timeout or resource
limits when a document genuinely requires OCR and repeatable measurements in
the deployment environment justify the change.

Amber card highlighting draws attention to a current actionable condition:
zero active workers, a non-empty waiting queue, current failed documents, drifted or stale
documents, current expired leases, or blocking jobs. Processing alone is not
amber because active processing is expected. Historical lease-loss attempts
and unsupported counts are displayed as supporting context but do not turn
their cards amber unless the card's current primary condition is also present.

For failures, first identify and correct the dominant extraction, dependency,
content, or capacity cause. Then use **Retry failed documents**, choosing a
batch from 1 through 500. The action selects only current eligible failed
documents that do not already have queued/leased work, preserves their failed
job/attempt history, queues `retry` work, and changes successfully queued
documents to `pending`. Start with one representative document, verify success,
then increase bounded batches while observing worker capacity and queue age.
Do not delete history to make the Health count fall, and do not use **Queue
backfill batch** as a substitute: backfill targets missing or obsolete identity,
whereas retry targets current documents in failed state.

**Refresh** retrieves a new snapshot; it does not change queue state. **Queue
backfill batch** scans at most the selected 1–500 eligible components and
idempotently queues missing or obsolete work. The reported drift and queue
counts will change independently while reconciliation adds jobs and workers
process them.

| Setting | Initial default | Meaning |
| --- | ---: | --- |
| `CONTENT_INDEXING_HISTORY_RETENTION_DAYS` | `365` | Retain completed indexing attempt/job operational history |
| `TEXT_INDEXER_CREDENTIAL_HISTORY_RETENTION_DAYS` | `365` | Retain revoked/expired API credential metadata before bounded cleanup |
| `CONTENT_INDEXING_CLEANUP_INTERVAL_SECONDS` | `3600` | Delay between supervised watch-loop passes |
| `CONTENT_INDEXING_CLEANUP_BATCH_SIZE` | `500` | Maximum rows processed per cleanup pass |
| Abandoned staging | Immediate after terminal status, generation replacement, or lease expiry | Staging is derived and never published directly |

The worker uses its own PostgreSQL advisory-lock key, bounded batches,
short transactions, and database time. It may delete only rows that still meet
the terminal-state and retention predicates while locked. It never deletes
queued/leased jobs, a valid lease generation's active staging, current search
documents, published search chunks, source content, or event history.

`run-local-stack.sh` starts and monitors this worker automatically unless
`CONTENT_INDEXING_MAINTENANCE_ENABLED=false`. Production installations without
an external scheduler install and supervise
`backend/services/api/deploy/erms-text-indexing-maintenance.service`. Sites
using a platform scheduler run the one-shot `cleanup` command hourly instead
and do not also run the continuous service. The process uses the API host's
environment and database credentials; it is not part of the text-indexer
extraction service.

The text-indexer separately removes its mode-`0700` temporary directory in a
`finally` path after every job through Python's temporary-directory lifecycle.
At startup it examines at most `TEXT_INDEXER_TEMP_SWEEP_LIMIT` entries and
removes only owned `wathiq-index-*` entries older than
`TEXT_INDEXER_STALE_TEMP_HOURS`.
That filesystem responsibility does not grant it database cleanup authority and
does not use this API-side cleanup command.

One text-indexer service supervises a pool of child worker processes.
`TEXT_INDEXER_PROCESS_COUNT=2` starts two children, and each child claims and
processes one job at a time because `TEXT_INDEXER_CLAIM_BATCH_SIZE=1`. The
configured `TEXT_INDEXER_WORKER_ID` is a base; the supervisor appends its run
identity and child slot to produce unique API worker IDs. If one child exits,
the supervisor restarts that slot while the other child continues. Do not
increase the claim batch or add extraction threads: Tika and OCR are
resource-heavy subprocess workloads, and child processes provide the intended
failure isolation.

The normative data eligibility, safety, and verification requirements are in
[Full-Text Content Search](../specs/full-text-search.md#66-content_indexing_attempts).

Queue health is separate from API health. Alert on increasing
`oldest_queued_seconds`, sustained `failed`/`unsupported` outcomes, stale
documents, lease-loss recovery, cleanup failures, and workers whose
`active_until` has passed. Metrics contain counts, durations, sizes, OCR flags,
and bounded status/error labels only—never extracted text, file names, keys, or
lease tokens.
The API `/health` endpoint proves API/database liveness and exposes rollout
flags. The Text Indexers **Health** section and the `readiness` command prove
indexing readiness; neither substitutes for the other.

Interactive controlled searches are limited by
`SEARCH_RATE_LIMIT_PER_MINUTE` (default 600 per user). Manual component/record
reindex requests use the deliberately stronger
`MANUAL_REINDEX_RATE_LIMIT_PER_MINUTE` limit (default 60 per user). A rejected
request returns `429` with a bounded code and `Retry-After`; it creates no job.

## 8. Authentication bootstrap and credential recovery

**Status:** Implemented  
**Module:** `backend.services.api.manage_auth`

Bootstrap is permitted only for a genuinely empty user database:

```bash
python -m backend.services.api.manage_auth bootstrap \
  --name "Bootstrap Administrator" \
  --email bootstrap@erms.local
```

Reset a person account's password:

```bash
python -m backend.services.api.manage_auth reset-password user@example.org
```

Deliberate recovery can assign the reserved administrator role when an existing
organizational unit is explicitly identified:

```bash
python -m backend.services.api.manage_auth reset-password user@example.org \
  --make-system-administrator \
  --org-unit-code ROOT
```

These commands print temporary credentials once. Their output must be handled as
a secret and must not be stored in routine command logs. See
[Authentication](authentication.md).

## 9. Database migrations

**Status:** Implemented

Migrations are release operations, not background jobs. Apply them once per
logical database before application instances using the new schema are started.
Use `ON_ERROR_STOP` and the transaction instructions documented for each
migration.

See [Database setup and migrations](../database/README.md) for the authoritative
commands and ordering. Do not apply migrations automatically from every API
instance.

## 10. Optional database seeds

**Status:** Implemented

Seed scripts install optional reference, demonstration, or load-test data. They
are not migrations and do not run during application startup.

See [ERMS seed data](../database/seeds/README.md). Confirm the target database
and the seed's duplicate-data behavior before execution. Load-test seeds must
not be applied to an operational production repository.

## 11. Pre-production database reset

**Status:** Planned

This deliberately destructive procedure is for an environment that has been
provisioned and smoke-tested but has not entered operational production use. It
will drop and recreate the database from the canonical schema and required
production seeds.

It is not ordinary entity deletion and must not be available through the web
application. Its implementation must:

- require an explicit pre-production environment designation;
- display and require confirmation of the exact database host, port, and name;
- refuse known production environment designations;
- require a separate destructive confirmation flag for non-interactive use;
- recreate required schema and production seeds;
- verify the resulting schema version and bootstrap readiness; and
- produce a clear completion or failure report.

Until the tool is implemented, DevOps must use the database platform's approved
reprovisioning process rather than an ad hoc application command.

## 12. Deployment checklist for scheduled operations

For each deployed logical database:

- choose external one-shot scheduling or one dedicated `--watch` process for
  every required cleanup tool;
- configure the same `DATABASE_URL` and compatible application version used by
  the API;
- prevent secrets and temporary passwords from entering logs;
- monitor nonzero exits and repeated advisory-lock skips;
- retain worker logs according to the operational logging policy;
- test dry-run and one committed batch after deployment;
- verify that cleanup metrics advance and active rows are not selected; and
- update this catalogue whenever a tool, setting, schedule, or runbook changes.

## 13. Database growth and partitioning guidance

Partitioning is a capacity and query-planning decision, not routine preventive
maintenance. Do not partition a table merely because it is expected to grow.
A useful partition key must appear in the table's dominant predicates so
PostgreSQL can prune partitions; otherwise each query may open more indexes and
scan more child relations than the equivalent unpartitioned table. PostgreSQL
18 permits an unlimited aggregate database size but limits an individual
relation to 32 TB with the standard 8 KB block size. Practical performance,
backup, restore and maintenance limits normally arrive earlier. See the
[PostgreSQL limits](https://www.postgresql.org/docs/18/limits.html) and
[partitioning guidance](https://www.postgresql.org/docs/18/ddl-partitioning.html).

No ERMS table is partitioned by default. Introduce partitioning only through an
approved, tested schema migration after production measurements demonstrate a
specific need. The migration must preserve foreign keys, uniqueness, triggers,
authorization predicates, audit behavior, backup/restore procedures and query
plans. PostgreSQL requires a partitioned table's primary-key or unique
constraint to include every partition-key column; existing identifiers and
foreign keys therefore cannot be assumed to migrate unchanged.

### 13.1 Durable tables that may benefit

| Table | When to consider it | Recommended strategy and key | Operational reason |
| --- | --- | --- | --- |
| `event_history` | Audit history reaches tens of millions of rows, time-bounded audit queries or index maintenance degrade, or older history must move to a different storage tier | `RANGE (occurred_at)`, normally monthly or quarterly partitions; retain the existing entity, actor, request, correlation and security-operation indexes on each partition | Events are immutable, append-heavy and naturally time ordered. Time ranges support pruning, bounded maintenance and tablespace-based archival without deleting governed history. Use partitions coarse enough that complete per-entity history does not fan out across hundreds of partitions. |
| `digital_component_blobs` | The PostgreSQL blob backend remains in use and one blob relation is forecast to approach operational or relation-size limits | `HASH (content_set_id)` with a fixed, benchmarked modulus; place partitions on independently managed tablespaces when needed | Reads and deletes identify a content set, so the key permits pruning and keeps every content set's ordered segments together. Hashing distributes large TOAST values and avoids time hotspots. The migration must replace the current `id`-only primary key with partition-compatible keys and revalidate content-set cascades. |

Partitioning `digital_component_blobs` distributes storage; it does not reduce
the bytes retained. The preferred long-term answer for a very large repository
is the existing storage-provider boundary: keep governed metadata, checksums and
lifecycle state in PostgreSQL while placing authoritative bytes in an approved
object-storage backend. Before partitioning blobs, also evaluate dedicated
tablespaces, storage compression, backup throughput, restore time and whether
the PostgreSQL server should carry the binary I/O workload at all.

### 13.2 Cleanup-bounded tables should remain unpartitioned

Do not partition the following merely to make deletion faster:

- `content_upload_sessions`, staged draft content and superseded/failed content
  sets governed by `backend.services.api.content_cleanup`;
- `login_sessions` governed by `backend.services.api.session_cleanup`;
- `content_indexing_jobs`, `content_indexing_attempts`,
  `content_indexing_operations` and `content_indexing_result_chunks` governed by
  `backend.services.api.text_indexing_maintenance`; and
- revoked or expired `service_account_credentials` governed by the same
  API-owned maintenance process.

These are transient or retention-bounded operational tables. First correct
cleanup scheduling, throughput, failed batches, autovacuum or retention
configuration if their live size grows without bound. Partitioning would add
foreign-key, active-queue uniqueness and lease-state complexity while masking
an operational cleanup failure. Reconsider only if a legitimate retained
window itself contains enough rows to create measured maintenance problems.

### 13.3 Tables that should not be partitioned by the current model

| Tables | Why partitioning is normally harmful | If an individual relation approaches 32 TB |
| --- | --- | --- |
| `digital_component_search_chunks`, `digital_component_search_documents`, `record_search_documents`, `aggregation_search_documents` | Global full-text searches are not constrained by component ID or creation time. Time or hash partitioning would usually require searching every partition and every partition-local GIN index. These are current derived indexes, not archival history. | Rebuildable derived data may move to a separately scaled search tier after an approved architecture change. Hash partitioning by `digital_component_id` is acceptable only if production benchmarks prove that many smaller GIN indexes outperform the single index for global queries. Do not use time partitions for current search state. |
| `aggregations`, `records`, `digital_components`, `digital_component_content_sets` | They form the authoritative hierarchy with cascading and deferred foreign keys, globally meaningful identifiers, record-number uniqueness, ACLs and cross-hierarchy browsing/search. Ordinary queries have no universal time or hash predicate that would reliably prune partitions. | Archive closed repositories through a governed archival design, separate binary storage from metadata, or shard complete repositories/tenants into separate logical databases using a new explicit repository key. Do not partition independently related tables without a co-partitioned data model. |
| ACL/default-grant, hold, identity, role, profile and catalogue tables | Authorization and governance checks join these tables across the complete repository; they are narrow relational data and normally grow much more slowly than content or audit history. Partitioning increases authorization-plan and referential-integrity complexity without useful pruning. | Review abnormal row growth and data modelling first. At extraordinary multi-repository scale, shard complete security domains rather than partitioning individual authorization tables. |

Do not create a partitioning migration solely because a table crosses an
arbitrary byte threshold. Before approval, capture row growth, total/heap/TOAST
and index sizes, representative `EXPLAIN (ANALYZE, BUFFERS)` plans, autovacuum
duration, backup/restore measurements and the expected partition-pruning
predicate. Test creation of future partitions, default-partition monitoring,
constraint enforcement, cross-partition cascades and disaster recovery on a
production-scale disposable database.

## General settings migration and readiness

Disposition Phase 4 moves general defaults and Dashboard/selector/user-session
limits to PostgreSQL. Use the offline preview/apply/check commands in
[application settings upgrade](application-settings-upgrade.md) before starting
upgraded services. Each database is reviewed separately; the private legacy file
is preserved. The local launcher fails closed on incomplete/unreachable state.
API runtime reads have a 30-second cache and no environment fallback. Content,
authentication and search policy cutovers remain Phases 5–6.

### Phase 5 cleanup policy ownership

Content-cleanup interval and session-cleanup retention/interval/batch settings
are database-owned. Omit their CLI options to follow Administration Settings;
explicit options are per-invocation overrides. A one-shot run loads one fresh,
validated complete snapshot. A watch process uses the shared 30-second cache and
re-evaluates the policy before each pass. Initial settings-load failure stops the
worker before cleanup; a failed cache refresh may retain only its last validated
snapshot. Advisory locks, bounded batches, dry-run rollback and terminal audit
remain unchanged. Review/apply the extended migration before service startup.

### Phase 6 indexing-maintenance policy

Indexing cleanup interval/history/batch and credential-history retention are now
Administration Settings. One shot loads a fresh validated snapshot; watch mode
uses the shared 30-second cache before each pass. Explicit flags are invocation
overrides, never database updates. Workers reject incomplete legacy migration.
Search, manual reindex and indexer request rates are API database settings.
The Audit Trail cap uses one captured value for count lookahead, page bounds and
`result_cap`. Apply schema migration 051 and a reviewed 34-key preview/apply
before deployment; see application-settings-upgrade.md.

## 14. Disposition and destruction operations

This section is the operational starting point for initial setup, configuration,
worker supervision and recovery. For installation or an upgrade, first follow
[the ordered deployment instructions](disposition-rollout.md): select the database,
apply only missing schema migrations, run separate seeds, and review/apply/check
legacy settings independently for every intended database. A “runbook” simply
means those step-by-step operating instructions.

Disposition/destruction workers implement governed workflow actions; they are
not general retention cleanup services in section 3. Do not assume they accept
cleanup workers' `--dry-run` flag. Their commands below support bounded one-shot
runs and dedicated supervised watch processes. Preparing or starting services
does not authorize physical destruction or digital deletion.

### 14.1 Initial setup and configuration

Use Administration → Settings with a person holding `app.settings.manage`.
That privilege does not grant Records Officer/Manager duties. Confirm current
organizational role assignments: Officer and Manager IGU roles, owning-unit
managing role and, for Standard, the nearest configured File Administrator role.
`disposition.jobs.manage` is already granted to the approved IGU profiles and
compatibility All Privileges profile; System Administrator alone is not an IGU.
Ordinary resource authorization, role eligibility, security, holds and vital
blockers still apply. Assignment never grants content access.

Set the classification scheme and the uploaded-evidence/generated-report
classifications together. Each must be a valid terminal classification in that
scheme. Provide an authorized **open root** for each destination outside the
units being destroyed. Selection uses the current latest open root, with stable
ID tie-breaking; closing a root changes availability. Request/execution/physical
preparation reports use the report destination; external letters, physical
certificates and the digital certificate use the evidence destination. Preserve
evidence and provenance; no separate evidence-expiry deletion was approved.
Uploaded evidence/report roots must be set up before the corresponding tasks can succeed.
Unset destinations warn and block the dependent action; missing roots do not
fall back to another classification or cause partial workflow advancement.

Choose the review route (Standard default, Simplified or Records Manager Only),
authority and reminder policy in Settings. A job keeps its captured route after
the global default changes. Verify initial settings values against each reviewed
plan and their provenance in Settings; check audit reasons and safe reference
snapshots. Keep full-text/index scheduling disabled until its separate readiness
procedure is met.

SMTP host, port, TLS mode, authentication, username, sender/reply-to, timeout and
**encrypted password** are database settings. Authentication requires a username
and password. The only encryption secret in the API environment is
`APPLICATION_SETTINGS_ENCRYPTION_KEY`; share the same key among API instances
serving the same database and retain it with backups. A production shell/service
value overrides `.env`. Preserve an existing key; replacing it alone cannot
recover saved SMTP passwords. For a missing local key, the existing helper is:

```sh
backend/services/api/.venv/bin/python -m backend.services.api.application_settings_secret --init-local-key
```

The helper preserves existing assignments, including empty ones. An empty or
invalid key needs deliberate operator correction and an API restart. No
`SMTP_PASSWORD` environment assignment or extra key-file setting is introduced.
STARTTLS/implicit TLS with certificate verification are the supported SMTP
modes; a plain MailDev listener on port 1025 alone is not a production TLS
configuration. Unconfigured SMTP/key state permits startup but blocks dependent
sends safely; it must not be “fixed” by disabling transport verification.

### 14.2 Worker startup and verification

Restart API/WebUI after code/schema/dependency deployment. Local development
uses `./run-local-stack.sh` for its existing services; it checks selected-database
migration readiness without importing values. It preserves existing private
environment values and appends only missing safe deployment defaults. Do not run
that launcher against a persistent database as part of a test rehearsal.

Disposition workers have their own existing service units. On a systemd host,
install/review the checked-in units, `/etc/erms/api.env`, service account and
`/opt/erms` paths before starting them; follow deployment.md for the ordinary
API/WebUI/indexer/cleanup units. Local workers can run from separate terminals
with the same selected `DATABASE_URL`; their existing dotenv loader preserves
exported environment precedence:

```sh
backend/services/api/.venv/bin/python -m backend.services.api.disposition.eligibility --watch --batch-size 100 --interval-seconds 60
backend/services/api/.venv/bin/python -m backend.services.api.disposition.communications --watch --batch-size 100 --interval-seconds 30
backend/services/api/.venv/bin/python -m backend.services.api.disposition.destruction_worker --watch --batch-size 1 --interval-seconds 5
```

Run one command per supervised process; do not run a second local copy alongside
its service unit. Omit `--watch` for a bounded one-pass readiness probe. Startup
of the destruction/completion worker is not operational destruction approval.
Both SQL execution release functions remain **false** in the delivered schema;
this guide deliberately supplies no command to change them. Obtain separate
deployment/destruction authorization and an agreed release procedure before any
operational physical confirmation or digital deletion.

Check `/health`, sign-in, Settings readiness/provenance, destination warnings,
role/task visibility, worker output and audit evidence. Use synthetic rehearsal
material for approved acceptance; never use live records to test deletion.

| Change | Reload/restart and effect |
| --- | --- |
| Database application settings | No service restart; API general cache converges within 30 seconds. Saving invalidates the saving process; other instances expire normally. |
| Job route | Captured at job creation; edits affect subsequent jobs. |
| Artifact destination/template and email capture | Fresh committed checks at the defined operation boundary; earlier saved bytes/facts stay retained. |
| Deployment environment, API key, executable, process paths or service units | Restart/relaunch the consuming API/WebUI/indexer/worker; reload systemd units after unit edits. |
| Code, requirements, canonical template/font assets | Deploy together and restart consumers. Never overwrite retained uploaded revisions. |

### 14.3 Recovery and rollback

| Condition | Recovery |
| --- | --- |
| Migration/readiness fails | Keep writers stopped; inspect receipts, fix cause and resume missing DDL. Make a new settings preview for changed inputs/versions. Never mark migration complete manually. |
| Destination/root unavailable | Configure the correct scheme/classifications/open roots and access, refresh the task, then retry the intended action. Earlier evidence remains in its original governed location. |
| Conversion/template failure | Repair dependencies or upload an authorized valid template revision; retry the blocked action. Retained prior versions/PDFs remain unchanged. |
| SMTP failed/unknown | Inspect saved attempt status. SMTP acceptance is not inbox receipt. An uncertain attempt is not automatically replayed; use the authorized deliberate resend flow after checking the recipient. |
| Worker stops or database/storage is unavailable | Restore connectivity/dependencies, restart the dedicated worker and inspect durable progress. Preserve leases/checkpoints/receipts; do not delete rows to force a rerun. |
| Content erased but certificate failed | Use the Manager's certificate-only recovery task after fixing the destination/template/rendering issue. Retry completion, never repeat content deletion; final download/email uses the saved certificate. |
| Role/access lost or stale task | Restore the appropriate assignment/access through approved administration or use authorized task release/reassignment; refresh versions and revalidate blockers. Do not bypass authorization. |
| Termination after mixed physical destruction | Preserve digital material/status 13. An authorized IGU resolves a permitted eligible status with a reason, using the all-or-nothing bulk flow where applicable; only then admit to a matching new job. |

Code, service configuration and reversible setting changes can be rolled back
only to a schema-compatible version, with the corresponding previous configuration.
This is not a reverse-migration promise. Restore a database backup only under the
established incident/restore procedure and with coordinated writers. Physical
material and erased digital content cannot be restored by reverting code or
settings. External recipients' copies are outside application deletion control.
Do not reopen/reuse destroyed retained records or reset finalization to pretend
action did not happen. Preserve protected evidence, minimal permanent records,
identities, rationales and audit provenance.
