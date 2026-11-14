# Full-text search implementation traceability

**Specification:** `specs/full-text-search.md`, approved revision 0.44
**Maintained from:** Phase 0  
**Current delivery state:** Phases 0–5 implemented and verified locally; production rollout execution is an environment operation

Approved specification revision 0.25 and migration 015 restore
`roles.is_system` for consistency with the built-in-profile discriminator. On
roles and profiles alike, `is_system` means implementation-owned, not System
Administrator.

This is the normative requirement-to-implementation-to-verification matrix
required by specification section 1.1. A passing test alone does not change a
row to `verified`; the cited behavior and evidence must satisfy the approved
requirement. `approved_deferred` may be used only with an explicit approved
specification revision in Notes.

## 1. Complete normative-section allocation

The 13 November 2026 cache-maintenance amendment to §10.3 is implemented by
`session_cleanup.py`, the two database registry settings, migration 110 and the
API/cleanup systemd units. Bounded expiry deletion, distinct schedules and locks,
live settings, migration parity, shutdown, and deployment dependencies are
verified in [the cleanup report](verification/search-cache-cleanup-2026-11-13.md).
That report preserves the earlier API-coupled lifecycle evidence. Revision 0.40
supersedes its production lifecycle: independent boot/restart, database-scoped
session-lock leadership on the job connection, standby exclusion, graceful/crash
and connection-loss takeover, and tandem local-stack ownership are traced to
`session_cleanup.py`, both systemd units, `run-local-stack.sh`,
`test_search_cache_cleanup.py`, `test_search_cleanup_deployment.py`, the existing
local-stack lifecycle regressions and `tools/linux_search_cleanup/verify.py`.
Current execution evidence is in
[the independent-worker report](verification/search-cleanup-independent-2026-11-13.md).

This inventory prevents requirements outside the acceptance-criteria table
from disappearing during phased delivery.

| Specification section | Concise requirement inventory | Planned phase(s) | Current status |
| --- | --- | --- | --- |
| 1.1 | Maintain this matrix; inventory before each phase; reconcile both directions at every exit and finally; use disposable DB evidence | 0–5 | verified |
| 2.1–2.2 | Separate weighted record, aggregation, file-name and body sources; exclude prohibited fields | 1, 3 | verified |
| 2.3 | Tika primary extraction, English/Arabic OCR, isolated service, bounded preview/extraction separation | 0, 2 | verified |
| 2.4 | Extend the controlled JSON grammar without exposing SQL/configuration selection | 3 | verified |
| 2.5 | Privileged, opt-in, sanitized API-level diagnostics only | 1, 3, 4 | verified |
| 2.6 | Enforce the initial format allowlist and Phase 0 quality/language gates | 0, 2 | verified |
| 3 | Deliver only listed scope; exclude listed non-scope | 1–5 | verified |
| 4 | Enforce all 14 content identity, eligibility, stale-index, authorization and lease domain rules | 1–3 | verified |
| 5, 5.1–5.4 | API trust boundary; opaque-key service identities; route isolation; lease-scoped classified-content access | 1–2 | verified |
| 6.1–6.9 | Create current, chunk, job, attempt, staging, transition and credential models with stated constraints | 1–2 | verified |
| 7 | Normalize hostile text; confidence-aware per-chunk language policy; explicit built-in configurations; bounded OCR | 0–2 | verified |
| 8.1–8.5 | Deployable indexer, launcher/local stack, internal REST, processing sequence and configured limits | 0, 2 | verified |
| 9.1–9.4 | Component/record forced reindex, statuses, privilege plus ordinary authorization, truthful UI states | 1, 3 | verified |
| 10.1–10.6 | Grammar, combined SQL, global endpoint/results, authorization-before-ranking and safe diagnostics | 1, 3 | verified |
| 11, 11.1–11.4 | Responsive Wathiq header/results, service-key administration and off-by-default diagnostics UI | 3–4 | verified |
| 12 | Preserve lifecycle/deletion/freshness invariants; backfill and reconciliation | 1–3 | verified |
| 13 | Required domain events, safe operational history, metrics and health semantics | 1–3 | verified |
| 14 | Parser isolation, credential/lease secrecy, dependency/resource defenses, safe SQL/rendering/backups | 1–5 | verified |
| 15 | Execute Phases 0–5 with entry inventories and exit reconciliation | 0–5 | verified |
| 16 | Satisfy FTS-01 through FTS-65 with cited evidence | 0–5 and performance gate | verified |

## 2. Phase 0 detailed matrix

| Requirement | Planned phase | Implementation evidence | Verification evidence | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| P0-01 — §1.1: maintain traceability from Phase 0 onward | 0 | `docs/full-text-search-implementation-traceability.md` | Section-allocation, acceptance and Phase 0 matrices reviewed at exit | verified | Continues through every later phase |
| P0-02 — §1.1: enumerate phase requirements from the complete specification | 0 | Sections 1 and 2 of this document | `docs/full-text-search-phase-0-reconciliation.md` §2 | verified | Includes §2.3, §2.6, §7, §8.5, §15 and relevant acceptance rows |
| P0-03 — §15 Phase 0: approved representative English/Arabic corpus for every supported format | 0 | `examples/samples/docs/manifest.csv`; `phase0-formats/`; `phase0-edge-manifest.json`; spec §2.6 | `validation-summary.json`; benchmark supplementary-format results | verified | Initial allowlist is now explicit in revision 0.22 |
| P0-04 — §15 Phase 0: native, scanned, image, corrupt, protected, large and adversarial fixtures | 0 | `phase0-scanned-pdf/`, `phase0-corrupt/`, `phase0-protected/`, `phase0-oversized/`, `phase0-adversarial/` | Manifest hashes plus benchmark robustness cases | verified | Archive fixtures are hostile inputs, not supported indexed formats |
| P0-05 — §§2.6, 15 and FTS-10: approve English/Arabic native and OCR quality thresholds | 0 | Spec §2.6 | `docs/full-text-search-phase-0-benchmark.md` §§3.1–3.2; machine results | verified | Native EN 100%, AR 100%; OCR EN 100%, AR 97.34% |
| P0-06 — §§7, 15 and FTS-52: choose/version local detector and verify dominant/mixed/unknown decisions | 0 | Spec §§2.6 and 7; `benchmark_phase0.py::classify` | 307-case language result: 91.53% against 90% gate | verified | Phase 2 must implement/pin the approved policy |
| P0-07 — §§7, 15 and FTS-53: confirm required PostgreSQL 18 built-in configurations and Arabic matching | 0 | Spec §7 corrected catalogue precondition; `verify_phase0_postgresql18.py` | `phase0-postgresql18-results.json`; benchmark report §4 | verified | PostgreSQL 18.6; disposable DB and cluster cleaned |
| P0-08 — §§2.3 and 15: confirm English and Arabic OCR packs | 0 | Installed Tesseract language inventory in machine results | Tesseract `eng+ara` completed 36/36 OCR cases | verified | Deployed process-sandbox validation remains Phase 2 |
| P0-09 — §§8.5 and 15: benchmark and select configured resource defaults | 0 | Spec §8.5 initial-default table | Benchmark report §§3.4 and 5 | verified | Raising defaults requires a deployment-image rerun |
| P0-10 — §1.1: Phase 0 bidirectional exit reconciliation | 0 | `docs/full-text-search-phase-0-reconciliation.md` | Reconciliation §§3–5 and evidence-link validation | verified | No approved deferrals |
| P0-11 — §1.1 and FTS-18: DB evidence uses a unique disposable database and reports cleanup | 0 | `verify_phase0_postgresql18.py` | Result records unique name and all cleanup flags true | verified | No persistent ERMS database was used |
| P0-12 — §14: hostile fixtures and bounded no-output failure baseline | 0 | Phase 0 corrupt/protected/adversarial corpus | Five parser failure cases bounded; zero extracted output | verified | Full sandbox/network/limit enforcement belongs to Phase 2 |

## 3. Acceptance-criteria delivery matrix

The phase below is the primary delivery phase. Earlier design/corpus evidence
and later rollout/final reconciliation may also apply.

| ID | Planned phase | Status | Current evidence / required future evidence |
| --- | ---: | --- | --- |
| FTS-01 | 2 | verified | Durable queue, API-owned publication and REST worker integration |
| FTS-02 | 2 | verified | Terminal idempotency and safe attempt-history integration tests |
| FTS-03 | 3 | verified | Forced component job creation, active reuse, event and status API/DB test |
| FTS-04 | 3 | verified | Transactional record component snapshot, batch counts and status test |
| FTS-05 | 2 | verified | Replacement makes published text ineligible and schedules the new identity |
| FTS-06 | 1 | verified | Weighted record metadata SQL and rank assertion |
| FTS-07 | 1 | verified | Separate aggregation metadata table/view and SQL assertion |
| FTS-08 | 3–4 | verified | Bounded attribution plus element-only marker rendering; no snippet HTML interpretation |
| FTS-09 | 3–4 | verified | SQL authorization/SYS_ADMIN non-bypass and governed canonical result navigation |
| FTS-10 | 0, 2 | verified | Production-path 18-case run: English 99.69%, Arabic 97.74% |
| FTS-11 | 2 | verified | Bounded worker corpus, page-limit and explicit OCR tests; affirmative-corruption versus retryable Tika process/fork-runtime classification regression tests |
| FTS-12 | 2 | verified | Expired-lease reclaim, generation fencing and lease-loss history test |
| FTS-13 | 2 | verified | Publication identity and content deletion cascade tests |
| FTS-14 | 1 | verified | Stored regconfig, explicit construction and both GIN EXPLAIN plans |
| FTS-15 | 4 | verified | Desktop and 390 px live-browser evidence; explicit submit, URL restore, states and zero page overflow |
| FTS-16 | 2 | verified | Safe error/history schema and metrics leakage assertions |
| FTS-17 | 1 | verified | PostgreSQL 18.6 fresh/upgrade schema parity |
| FTS-18 | 0–5 | verified | Every phase DB run used a unique disposable PostgreSQL database with reported cleanup |
| FTS-19 | 2 | verified | `SKIP LOCKED` claim and active-job uniqueness coverage |
| FTS-20 | 2 | verified | Reclaim/fencing integration test |
| FTS-21 | 2 | verified | Partial unique index plus scheduling/idempotency integration |
| FTS-22 | 2 | verified | REST-only worker, dependency self-test and deployment review |
| FTS-23 | 2 | verified | Duplicate chunk and terminal-response retry test |
| FTS-24 | 1–2 | verified | Account/key and exact live-lease authorization matrix |
| FTS-25 | 1–2 | verified | Internal-route authentication and endpoint-scope negatives |
| FTS-26 | 1 | verified | Exact service-profile and ALL_PRIVS catalogue assertions |
| FTS-27 | 2 | verified | Worker ID/token/generation/content identity lease-scope tests |
| FTS-28 | 1–2 | verified | Provisioning plus account/key expiry and revocation model |
| FTS-29 | 1–2 | verified | Digest-only persistence, display-once generation and leakage review |
| FTS-30 | 4 | verified | Service-only details surface, identity-admin API dependencies and person-account rejection |
| FTS-31 | 3–4 | verified | One-time response field, list non-retrievability, transient dialog clearing and no person password control |
| FTS-32 | 4 | verified | Generate/list/rotate/revoke API lifecycle plus Wathiq details-page states and actions |
| FTS-33 | 2 | verified | Launcher syntax and live complete-distribution self-test |
| FTS-34 | 2 | verified | Local-stack registration readiness and forced-exit supervision |
| FTS-35 | 2 | verified | Loopback provisioning and mode-0600 credential evidence |
| FTS-36 | 2, 4 | verified | Disabled-indexer behavior plus explicit incomplete-result freshness UI |
| FTS-37 | 3 | verified | Nested structured/full-text grammar API/database integration |
| FTS-38 | 3 | verified | Resource source allowlists, extra-field and non-indexable rejection tests |
| FTS-39 | 3 | verified | SQL relevance, deterministic tie-break and cursor contract tests |
| FTS-40 | 3 | verified | Namespaced capped attribution with SQL authorization and unchanged match set |
| FTS-41 | 3 | verified | Independent required global branches and mismatch rejection tests |
| FTS-42 | 3–4 | verified | API privilege enforcement/non-expansion and privilege-gated secondary UI action |
| FTS-43 | 3–4 | verified | Live sent/accepted panels show exact received and canonical API JSON |
| FTS-44 | 3–4 | verified | Central allowlist plus UI panels expose no SQL, headers, credentials or internal authorization detail |
| FTS-45 | 4 | verified | Absent without privilege by construction; privileged toggle observed off, session-local and next-request-only |
| FTS-46 | 4 | verified | Live API outage retained sent JSON and displayed accepted JSON as unavailable |
| FTS-47 | 1 | verified | Exact debug-profile grants and account restrictions |
| FTS-48 | 3 | verified | Global privilege plus view/component ACL/clearance gates, SYS_ADMIN non-bypass, capability-driven UI |
| FTS-49 | 1–2 | verified | Opaque-key route isolation and lease-scoped operations verified |
| FTS-50 | 1–2 | verified | Approved hash vector, persistence, use and logging review verified |
| FTS-51 | 2 | verified | Cleanup retention boundary and competing-leader tests |
| FTS-52 | 0, 2 | verified | Detector policy and production-worker corpus run verified |
| FTS-53 | 0, 1 | verified | PostgreSQL 18 catalogue, Arabic match, fresh schema and migration verified |
| FTS-54 | 2, 5 | verified | Opaque-key tests plus hardened Linux unit, HTTPS/secret/network deployment controls, monitoring and incident runbooks |
| FTS-55 | 0–5 | verified | Phase 0–5 inventories, exit reports, final full-spec audit and evidence-link reconciliation complete |
| FTS-56 | 5 | verified | Dedicated person-only privilege; built-in grants limited to `ALL_PRIVS`/`SYS_ADMIN`; route dependency and navigation visibility tests |
| FTS-57 | 5 | verified | Atomic account/sole-role/initial-key endpoint; multi-identity, rollback, digest-only persistence and one-time response tests |
| FTS-58 | 5 | verified | Generic mutation rejection; dedicated list/detail, lifecycle and key actions; live browser list/detail/create-dialog comparison |
| FTS-59 | 5 | verified | Dedicated health/backfill endpoints and Wathiq Health section; authorization, privacy-safe serializer, bounded idempotency, refresh and live-browser verification |
| FTS-60 | 2, 5 | verified | Runtime/default environments set claim size one and process count two; supervisor-owned child pool; generated per-run/per-slot IDs; worker and deployment guidance |
| FTS-61 | 5 | verified | Built-in role opt-in listing, read-only API guards, Wathiq Built-in presentation and Text Indexers link; disposable PostgreSQL and live-browser evidence |
| FTS-62 | 5 | pending | Current-failed-document readiness metric, separate historical count, bounded idempotent retry API/UI and preserved history; disposable PostgreSQL and live-browser evidence required |
| FTS-63 | 5 | verified | Privilege-gated current-failure groups/page, negative metadata/link authorization, current unsupported-format aggregation, and live-browser record/component navigation with highlighted component |
| FTS-64 | Global Search paging | verified | `test_global_and_advanced_search_caps_keep_browse_available`, `test_global_search_saved_list_is_bound_to_tab_and_login_and_expires`, `test_global_search_respects_component_view_for_file_names_and_indexed_text`, `test_global_search_page_batch.py` (exact evidence, fresh scores and overlapping sources), `test_search_session_concurrency.py` (real locks and revocation), and WebUI paging/display-capability tests |
| FTS-65 | Search performance | verified for the documented original maintained-data fixture; richer-text exception approved in revision 0.44 | `tools/check_search_performance.py`: current-storage native run passed 876 responses, maximum 2.4953 seconds; exact counts/ranks/order, denied access and index paths. [Benchmark history and acceptance](search-performance-benchmarks.md); [latest storage comparison and limits](verification/search-vector-storage-2026-11-14.md); [page-batching regressions](verification/search-page-batching-2026-11-13.md); [original first-scan limitation](verification/search-performance-2026-11-12.md) |
| FTS-66 | Chunk-local matching and score reuse | correctness verified; remaining latency optimization `approved_deferred` in revision 0.44 | `search.py` and `search_cache.py` retain numeric chunk, metadata and per-record scores once; `test_search_candidate_indexes.py` protects accepted multi-chunk semantics; `test_global_search_page_batch.py` compares snippet selection with the prior implementation; `tools/check_large_text_search_performance.py` verifies complete capped rankings, uncapped membership and actual score-batch loop counts. [14 November comparison](verification/search-vector-storage-2026-11-14.md): current storage passed correctness but one of 428 responses took 3.407 s; [explicit user acceptance](search-performance-benchmarks.md#decision) retains that failure and the future three-second threshold |
| FTS-67 | Physical vector storage | verified for the populated upgrade and fresh schema | Migration 112 and canonical MAIN/LZ4 policy; `test_search_vector_storage.py` compares binary values, weights/positions, matching, scores, row data and indexes, including an overflow-sized vector. Included in the 77-test native disposable regression pass. [Verification and historical performance failures](verification/search-score-reuse-2026-11-13.md); [decision to retain compression](search-performance-benchmarks.md#storage-cost) |

## 4. Approved deferrals and departures

There are no approved Phase 0 deferrals. Work explicitly assigned to Phases
1–5 is not a deferral. The invalid illustrative `to_regconfig(text)` call was
corrected in approved revision 0.22 to a portable PostgreSQL catalogue check;
this preserves rather than changes the requirement.

Specification revision 0.44 records the user's 14 November 2026 acceptance of
the current compressed-storage search baseline as good enough for now. Further
latency tuning is `approved_deferred`: the latest larger-text run's single
3.4069-second response remains a numerical failure, alongside earlier failures.
This is a performance-baseline exception only; it does not defer correctness,
permission checks or future regression gates. See the
[dedicated benchmark history and rationale](search-performance-benchmarks.md).

## 5. Phase 1 entry inventory

Phase 1 began only after this inventory was derived from the complete approved
specification. These rows are the Phase 1 completion contract; passing tests
without the cited implementation and bidirectional reconciliation is
insufficient.

| Requirement | Planned phase | Implementation evidence | Verification evidence | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| P1-01 — §§7, 15 and FTS-53: canonical schema and upgrade migration fail atomically unless PostgreSQL 18 provides built-in `simple`, `english`, and `arabic` configurations | 1 | `database/schema.sql`; migration 010 | PostgreSQL 18.6 fresh/upgrade and Arabic assertions | verified | Does not modify catalogue/default |
| P1-02 — §§2.1, 6.3 and FTS-06: one weighted current metadata-search document per record, number/title A and description B | 1 | Record metadata table/function/trigger | SQL vector and rank assertions | verified | No content extraction |
| P1-03 — §§2.2, 6.4 and FTS-07: one weighted metadata-search document per aggregation, number/title A and description B, no ancestor copying | 1 | Aggregation metadata table/function/trigger | Separate aggregation vector assertions | verified | Own fields only |
| P1-04 — §§2.1–2.2, 6.3–6.4 and FTS-14: explicit stored `regconfig`, explicit `to_tsvector`, and GIN indexes | 1 | Canonical/migration SQL | Catalogue checks and two bitmap GIN plans | verified | No session-default reliance |
| P1-05 — §§2.1, 2.2 and 4.12: metadata documents are inserted/refreshed in the resource metadata transaction and cascade on deletion | 1 | AFTER triggers and cascading FKs | Insert/update/delete SQL test | verified | No binary job behavior |
| P1-06 — §§5.1, 5.2 and 6.9: dedicated opaque service-key storage with identifier, SHA-256 secret digest, expiry, independent revocation, safe metadata and bounded retained-history cleanup | 1 | `service_account_credentials`; migration 017; `text_indexing_maintenance.py` | Schema, approved hash-vector, active-key preservation and retention-boundary tests | verified | Plaintext never stored; audit events survive row cleanup |
| P1-07 — §§5.1–5.4 and FTS-26: protected `TEXT_INDEXER_SERVICE` profile contains exactly `content.index.execute`; `ALL_PRIVS` also contains it | 1 | Protected profile/membership trigger | Exact catalogue assertion | verified | No ordinary privilege |
| P1-08 — §5.1: protected system role is service-only, non-organizational, not selectable for person accounts and not a governance custodian | 1 | System role constraints; API list/search exclusion | Person-assignment negative test | verified | Sole non-org role exception |
| P1-09 — §§5.2, 14 and FTS-24/25/49/50 Phase 1 portion: strict opaque-key parsing/hashing, constant-time verification, service-account/privilege/expiry checks and route restriction | 1 | `service_authentication.py`; middleware | 7 unit/integration tests | verified | Phase 2 adds lease checks |
| P1-10 — §§2.5, 10.6 and FTS-42/47 Phase 1 portion: add `search.query.debug` to the exact protected profiles | 1 | Privilege/profile seeds | Exact four-profile assertion | verified | Runtime diagnostics remain Phase 3 |
| P1-11 — §§10.5 and 15: metadata search uses existing authorization-safe resource relations/functions before filtering, ranking, pagination or counts | 1 | Authorized metadata views | Unauthenticated non-disclosure SQL assertion | verified | DB filtering only |
| P1-12 — §15 Phase 1: update authorization operation inventory and service-account/authentication documentation | 1 | Database/deployment/authentication/operations docs | Documentation review | verified | Phase 2 scope explicit |
| P1-13 — §§1.1, 6.8, 15 and FTS-17/18: portable canonical/migration SQL parity on uniquely named disposable PostgreSQL 18 databases with reported cleanup | 1 | Canonical schema; migration 010 | PostgreSQL 18.6 schema dumps and cleanup record | verified | No persistent DB used |
| P1-14 — §1.1 and FTS-55: reconcile every Phase 1 requirement and every material implementation behavior in both directions | 1 | Phase 1 reconciliation report | Forward/reverse review | verified | No deferrals |

## 6. Phase 2 entry inventory

Phase 2 began only after this inventory was derived from the complete approved
specification. Later-phase search grammar, reindex UI/API and results UI are not
part of this phase.

| Requirement | Planned phase | Implementation evidence | Verification evidence | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| P2-01 — §§4, 6.1–6.2: current component search state and published bounded chunks preserve exact component/record/content identity and explicit configurations | 2 | Migration 011; canonical schema; `text_indexing.py` | Focused API publication/vector test; PG18 parity | verified | Includes cascade and stale eligibility |
| P2-02 — §§4, 6.5 and FTS-19–21: durable compatible queue, active uniqueness, `SKIP LOCKED` claims, expiry recovery and generation fencing | 2 | Migration 011; `text_indexing.py` | Expiry/reclaim/obsolete-generation integration test; full API suite | verified | Database clock owns leases |
| P2-03 — §§6.6, 13 and FTS-02/12/16: append-only safe attempt history records every execution generation without content/secrets | 2 | Migration 011; terminal/lease transition code | Success and `lease_lost` history assertions; leakage review | verified | Operational, not event history |
| P2-04 — §6.7 and FTS-20/23: idempotent digest-checked staging and atomic fenced publication | 2 | Migration 011; `text_indexing.py` | Duplicate chunk and terminal retry integration test | verified | Staging is never searchable |
| P2-05 — §§4.1–4.8, 6.8, 12 and FTS-01/02/05/11/13: content activation/replacement transactionally schedules or skips and immediately excludes stale text | 2 | Scheduling trigger; publication transaction | Upload/publish/replacement-pending/cascade integration tests | verified | Failed replacement preserves only same active identity |
| P2-06 — §§5.2–5.3, 8.3 and FTS-24/25/27–29/49/50: all seven internal endpoints require service authentication plus exact live lease scope | 2 | `text_indexing.py`; service-auth middleware | 9 focused service-auth/lease integration tests | verified | No ordinary ACL bypass surface |
| P2-07 — §§5, 8.3–8.4 and FTS-22: indexer has no DB credentials and performs claim/content/chunk/terminal work only through REST | 2 | `backend/services/text_indexer/` | Import/configuration review | verified | API owns vectors/publication |
| P2-08 — §§2.3, 8.1, 14 and FTS-10/11/16/22: complete checksum-pinned official Tika 4.0.0 distribution and Pipes fork isolation; no Homebrew/Docker runtime | 2 | Worker Tika module; archive/JAR checksums; launcher | SHA-512, fork self-test and 18-case corpus | verified | Linux egress enforcement is a deployment gate |
| P2-09 — §§2.3, 2.6, 7, 8.4 and FTS-10/52: normalize/chunk hostile text and apply pinned English/Arabic/mixed language policy and OCR gates | 2 | `text.py`; `tika.py`; API config mapping | Unit tests; 99.69% English/97.74% Arabic corpus | verified | Server maps configurations |
| P2-10 — §§2.6, 7.4, 8.5 and 14: enforce approved input/output/page/embedded/recursion/time/CPU/memory/temp limits, prefer sufficient native PDF text, and use safe error codes | 2 | Worker settings; Tika/Tesseract/PDF subprocess guards; native-text density gate before PDF rendering/OCR | Page-before-extraction, native-text OCR-skip, text-poor OCR, chunk, output, timeout, temp recovery tests and scanned-PDF corpus | verified | No silent truncation; searchable native PDFs avoid needless whole-document OCR |
| P2-11 — §8.1 and FTS-33: dedicated package, dependency environment and root `run-text-indexer.sh` validate capabilities and preserve signals without exposing secrets | 2 | Worker package; pinned requirements; launcher | Syntax and live self-test | verified | Dedicated venv |
| P2-12 — §8.2 and FTS-34–36: local stack manages indexer lifecycle/readiness/disablement and real protected local credentials | 2 | Local stack and loopback provisioner | Live startup, mode-0600 key, forced-exit supervision and API cleanup | verified | Loopback development only |
| P2-13 — §§6.6–6.7, 13 and FTS-51: advisory-locked bounded API-side cleanup preserves active/published/source data and runs as one supervised process | 2 | `text_indexing_maintenance.py`; `run-local-stack.sh`; `erms-text-indexing-maintenance.service` | Retention-boundary, competing-leader, watch-loop and live launcher-supervision tests | verified | Runs immediately then hourly by default; history defaults to 365 days |
| P2-14 — §§8.2, 12: bounded resumable backfill and reconciliation enqueue missing/stale work and report drift | 2 | `text_indexing_maintenance.py` | Missing-state and idempotent second-pass integration test | verified | Indexer never scans DB |
| P2-15 — §13: privacy-safe queue/outcome/latency/OCR/size/chunk/stale/recovery/cleanup metrics and separate backlog health | 2 | Maintenance metrics command; operations docs | Bounded serializer/leakage assertion and command exercise | verified | Bounded labels only |
| P2-16 — §§8.5, 12–14: document configuration, deployment, operations, recovery, cleanup and incident controls | 2 | Deployment, operations and security runbooks | Documentation review | verified | Central operations catalogue updated |
| P2-17 — §§1.1, 15, FTS-17/18/55: canonical/migration parity and bidirectional Phase 2 reconciliation on cleaned disposable PostgreSQL 18 databases | 2 | Schema/migration; Phase 2 reconciliation report | Fresh/upgrade parity; 253 API tests; 7 SQL suites; cleanup evidence | verified | No persistent database used |

## 7. Phase 3 entry and exit inventory

| Requirement | Planned phase | Implementation evidence | Verification evidence | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| P3-01 — §§2.4, 10.1–10.2 and FTS-37/38: controlled resource-specific `full_text` leaf composes inside the existing bounded Boolean grammar | 3 | `schemas.py`; `search.py`; search grammar docs | Nested API/DB and rejection tests | verified | No raw SQL/config/tsquery surface |
| P3-02 — §§10.2, 10.4–10.5 and FTS-08/09/39/40: authorization-before-ranking, deterministic relevance, capped attribution and safe snippets | 3 | Parameterized correlated SQL and attribution queries | Ranking, marker, cap and SYS_ADMIN non-bypass tests | verified | Rendered XSS coverage remains Phase 4 |
| P3-03 — §§10.3–10.5 and FTS-41: global endpoint enforces independent matching branches, opaque query-bound page token and freshness | 3 | `global_search_rows`; `/api/v1/full-text-search` | Branch mismatch, token continuation, numbered rebuild and freshness tests; candidate-scoped ACL comparison against canonical SQL | verified | Single-leaf ranking reuses candidate access calculations |
| P3-04 — §§2.5, 10.6 and FTS-42–44: opt-in privileged diagnostics expose only received/canonical API JSON and safe identifiers | 3 | Central allowlist serializer in `search.py` | Exact body, privilege and leakage assertions | verified | Browser panel belongs to Phase 4 |
| P3-05 — §§9.1, 9.3–9.4 and FTS-03/48: component forced reindex is immediate, deduplicated while active, authorized and status-addressable | 3 | `reindexing.py`; component-card action | API/DB forced/reuse/status/event and negative privilege tests | verified | Existing published identity remains searchable |
| P3-06 — §§9.2–9.4 and FTS-04/48: record reindex transactionally refreshes metadata, snapshots components and reports independent dispositions | 3 | Migration 012 batch tables; record action | Batch counts/status/event integration test | verified | Later content uses ordinary scheduling |
| P3-07 — §§9.3–9.4, 11 and FTS-48: existing record/component UI exposes authorized reindex and truthful asynchronous/index state | 3 | `frontend/webui/app.py`; API client | 103 frontend regressions/structural tests | verified | Global results UI is Phase 4 |
| P3-08 — §§1.1, 15, FTS-17/18/55: PostgreSQL 18 canonical/migration parity, full regressions and bidirectional reconciliation | 3 | Migration 012; canonical schema; Phase 3 report | Normalized object parity; 258 API tests; focused frontend suite | verified | Disposable databases cleaned at exit |

## 8. Phase 4 entry and exit inventory

| Requirement | Planned phase | Implementation evidence | Verification evidence | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| P4-01 — §§11–11.2 and FTS-15: authenticated responsive header search submits explicitly, retains query in header/URL, renders dedicated Wathiq results, and owns its navigation lifecycle | 4 | `frontend/webui/app.py`; API client; global-result detail wrappers | 178 frontend tests including stale-discard-guard regression; desktop and 390 px browser runs; URL-refresh run | verified | Entering global results clears prior page-specific guards; Back/breadcrumb from details returns without an unrelated unsaved-changes prompt |
| P4-02 — §§10.5, 11.2 and FTS-08/09/36: governed record/aggregation cards show bounded attribution, safe highlights, freshness, matched-component previews and canonical actions | 4 | Match-only result renderer; governed metadata enrichment for attributed IDs; existing `preview_record_components` viewer | 178 frontend tests including match-only preview wiring; structural XSS assertion; API authorization tests | verified | Unmatched components are not displayed; highlighted snippets are preserved; disabled preview icons explain unavailable formats/states |
| P4-03 — §§10.3, 11.2 and FTS-15: result-type filters, explicit loading/empty/error states, opaque page tokens and automatic recovery | 4 | Result renderer and `run_global_search` | English and Arabic browser paging with forced expiry, UI interaction and API integration tests | verified | Recovery retains the submitted query, selected type and requested page |
| P4-04 — §§2.5, 10.6, 11.4 and FTS-42–46: diagnostics are privileged, off by default, session-local, exact, sanitized and failure-aware | 4 | Secondary action, disclosure and transient session state | Live opt-in/rerun/accepted/failure runs; API serializer tests | verified | Navigation clears displayed JSON |
| P4-05 — §§5.2, 11.3 and FTS-30–32: service-account details expose governed credential issue/paginated history/rotate/revoke with one-time secret handling | 4 | `user_management.py`; schemas; API client; Text Indexers details UI | Disposable-DB lifecycle, pagination/filter tests and live details comparison | verified | Five rows per page by default; person accounts cannot receive credentials |
| P4-06 — §§11.1–11.4 and FTS-15/32: live presentation follows Wathiq shell/cards/actions and is usable without horizontal page scrolling | 4 | Existing design tokens plus Phase 4 responsive CSS | Desktop screenshot comparison; 390 px `scrollWidth == innerWidth` after correction | verified | Diagnostic code surfaces wrap internally |
| P4-07 — §§1.1, 15, FTS-18/55: complete regression, disposable PostgreSQL 18 evidence and bidirectional Phase 4 reconciliation | 4 | Phase 4 tests and reconciliation report | 154 frontend tests; 261 API tests; unique DB cleanup | verified | Phase 5 rollout remains |

## 9. Phase 5 entry and exit inventory

| Requirement | Planned phase | Implementation evidence | Verification evidence | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| P5-01 — §15: deploy workers and search surfaces disabled | 5 | `.env.example`; API/UI flags; systemd unit | Feature-gate tests and configuration review | verified | Production starts with all rollout flags false |
| P5-02 — §§12, 15: enable new-content scheduling independently while retaining truthful freshness | 5 | Migration 013; canonical trigger; connection setting | Disposable PostgreSQL trigger test | verified | Disabled scheduling creates pending document but no job |
| P5-03 — §§8.5, 12–13, 15: bounded backfill and load/quality/readiness observation | 5 | `text_indexing_maintenance.py`; operations/deployment runbooks | Quality command passed EN 99.69%, AR 97.74%, marker 100%; readiness tests | verified | Readiness blocks on drift, queue, failures or stale documents |
| P5-04 — §§11, 15: enable API and header only after gates pass | 5 | Independent API and UI flags; `/health` state | API gate and UI structural tests | verified | Header is absent until explicitly enabled |
| P5-05 — §§13–15 and FTS-54: least-privilege Linux units, supervised API-owned cleanup, and documented network/secret controls | 5 | `erms-text-indexer.service`; `erms-text-indexing-maintenance.service`; process-pool/API env templates; deployment runbook | Static unit review, live local supervisor smoke test and authentication/security suites | verified | Cleanup is separate from FastAPI and extraction workers; actual firewall/application is deployment-environment work |
| P5-06 — §15: non-destructive rollback | 5 | Deployment rollback sequence | Configuration and schema review | verified | Source content retained; derived tables not dropped |
| P5-07 — §§1.1, 16 and FTS-55: final bidirectional reconciliation | 5 | This matrix; Phase 5 reconciliation report | Full-spec/acceptance/evidence-link review | verified | No unexplained omission or added product behavior |
| P5-08 — approved revision 0.26 and FTS-56–58: dedicated Text Indexers administration and privilege separation | 5 | Migration 016; `user_management.py`; API client; dedicated Wathiq list/detail UI | 271 API + 154 frontend tests on disposable PostgreSQL 18; live browser list/detail/create dialog; demo migration verification | verified | Generic identity/role mutation paths reject protected indexers |
| P5-09 — approved revision 0.27 and FTS-59: operational health and bounded backfill within Text Indexers | 5 | Dedicated health/backfill APIs; Text Indexers Health section; operations guide | 272 API + 155 frontend tests on disposable PostgreSQL 18.4; live-browser Health cards and 1–500 batch dialog | verified | Distinguishes API liveness from worker/queue readiness; temporary UI administrator removed |
| P5-10 — approved revisions 0.28–0.29 and FTS-60: process-isolated extraction concurrency | 5 | Claim/process-count configuration; supervisor and lease handling; `erms-text-indexer.service`; deployment/operations guidance | Text-indexer tests; configuration, supervisor and unit verification | verified | One service owns a restartable child pool; one claimed job per child |
| P5-11 — approved revision 0.30 and FTS-61: read-only built-in role visibility | 5 | Roles API opt-in; mutation guards; Roles list/detail UI | 273 API + 157 frontend tests on disposable PostgreSQL 18.4; live list/detail/link verification | verified | Ordinary relationship selectors retain the default built-in exclusion; temporary UI administrator removed |

## Shared tab result cache — 13 November 2026

The cache is now `search_results_cache` (migration 111 preserves the existing
UNLOGGED table in place). Global Search shares its `(session_id, tab_id)` slot
with Advanced Search, saved-search execution and aggregation/record collection
filters. Each list also checks the authenticated user, list ID and search
fingerprint. The browser supplies NiceGUI's connected `client.tab_id`; reloads
reuse it and copied/duplicated tabs receive distinct identities. Cross-screen
replacement/rebuilding, caps, SQL parity and ownership regressions are mapped in
[the Advanced Search traceability extension](advanced-search-implementation-traceability.md#shared-tab-cache-extension--13-november-2026).
The [shared-cache verification report](verification/shared-search-cache-2026-11-13.md)
records the English/Arabic browser regressions and the final 876-request
large-fixture gate (maximum 2.3503 seconds), including failed attempts,
measurement conditions and database/container cleanup. Migration 111 was
subsequently applied to demo on 13 November 2026 after explicit authorization;
all 111 migration markers and restarted local-stack health were verified.
