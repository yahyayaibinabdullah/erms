# Independent search-cache cleanup verification — 13 November 2026

This report preserves the earlier API-coupled lifecycle verification. Its coupling
requirements are superseded by the later 13 November 2026
[independent-worker change and verification](search-cleanup-independent-2026-11-13.md).

The standalone `backend.services.api.session_cleanup` worker now runs two jobs
on independent schedules and in separate transactions. Search-cache cleanup
defaults to a 60-second delay after each pass and at most 5,000 expired lists
per pass. Login-history defaults remain 3,600 seconds, 500 sessions and 90-day
retention. These are maintenance budgets, not measured production capacity.

The new settings are database-owned, positive integers in **Search and indexing**:
`GLOBAL_SEARCH_CACHE_CLEANUP_INTERVAL_SECONDS` and
`GLOBAL_SEARCH_CACHE_CLEANUP_BATCH_SIZE`. No environment variables were added.
Migration 110 adds them to existing databases; the canonical validator and
required reference-data seed cover fresh installations. The API and worker
must be upgraded together with this migration.

## Repeatable checks

Run only through the disposable runner:

```bash
backend/services/api/.venv/bin/python tools/run_disposable_acl_tests.py \
  backend/services/api/tests/test_search_cache_cleanup.py \
  backend/services/api/tests/test_application_settings_phase5_authentication.py \
  backend/services/api/tests/test_authentication.py \
  backend/services/api/tests/test_full_text_search_phase3.py

backend/services/api/.venv/bin/python tools/run_disposable_acl_tests.py \
  backend/services/api/tests/test_search_cache_cleanup.py::test_migration_110_defaults_or_preserves_values_and_matches_canonical_validator \
  backend/services/api/tests/test_localization_catalogue.py::test_generated_arabic_artifact_is_complete_contextual_and_placeholder_safe \
  backend/services/api/tests/test_localization_catalogue.py::test_approved_arabic_terminology_matches_the_specification \
  backend/services/api/tests/test_localization_catalogue.py::test_missing_only_seed_cli_fills_absent_rows_and_preserves_existing_translation_kinds

backend/services/api/.venv/bin/python -m pytest -q tools/tests/test_search_cleanup_deployment.py
python3 tools/check_configuration_authority.py
python3 tools/sync_api_env_template.py --check
frontend/webui/.venv/bin/python frontend/webui/scripts/check_i18n_catalogue.py
frontend/webui/.venv/bin/python frontend/webui/scripts/check_approved_arabic_terminology.py
```

- First DB run: **43 passed**, including 5,002 expired lists plus an active list;
  exactly 5,000 removed in the first default batch, two in the next, active list
  preserved, dry run/idempotence, advisory-lock overlap, locked-tab skipping,
  independent timers, live settings, existing CLI overrides, separate commits,
  and real worker startup/SIGTERM exit within three seconds. This run preceded
  the additional missing-setting migration parameter below.
- Follow-up DB run: **5 passed**, covering both absent and configured settings
  during migration 110, canonical validator parity, complete Arabic coverage,
  placeholders, approved terminology and guarded missing-only seeding.
- Disposable databases
  `erms_messaging_test_acl_b5064c99c74c4eb1ba0ce4bb35dd42b3` and
  `erms_messaging_test_acl_1d4cbe18989a4a4fb95e77f82d87e571` were created for their
  respective runs and both were dropped successfully. No suite used `demo`.
- Production unit dependency regression: **1 passed**. The API starts cleanup;
  cleanup declares `PartOf`, `BindsTo` and `After` for the API, shares its API
  environment file, runs separately and restarts on failure.
- Configuration authority: 126 settings, each with one owner; all 36 API
  deployment environment keys documented and templates agree. Catalogue
  completeness/order, artifact hashes, Arabic placeholders/terminology and
  draft provenance checks passed. Four new English definitions and four Arabic
  drafts were added; existing translation text/provenance was preserved.

## Local activation and limits

Migration `110_search_cache_cleanup_settings` was applied to local `demo` after
109. Saved values were verified as 60 seconds and 5,000 lists. The managed local
stack stopped its old worker and started a new standalone worker. Its startup
log reports separate `job=search_cache` and `job=login_sessions` passes at
10:04:12 UTC+04, then another cache-only pass at 10:05:12. The stack health check
reported ready, confirming the cache timer does not rerun login cleanup every
minute. Local
startup's `--missing-only` translation sync stored four drafts, preserved 4,063
existing translations, and reported no failures or missing generation. The
drafts remain unpublished and require review.

Production systemd start/stop/restart behavior was subsequently verified in a
disposable Linux VM as detailed below. Operators still install both revised
units, daemon-reload, re-enable the cleanup unit to replace its old boot-target
link, and restart the API as documented in `docs/deployment.md`.

No matching, ranking, permission or page-result SQL changed in this maintenance
work. The large search benchmark was not rerun; its prior evidence remains in
`search-page-batching-2026-11-13.md`. The new tests verify cleanup correctness and
lifecycle rather than claiming production load capacity for the proposed defaults.

## Actual Linux lifecycle rehearsal

Verified on 13 November 2026 in a newly created Ubuntu 24.04 ARM64 VM, Linux
6.8.0-147, systemd 255.4-1ubuntu8.18, Python 3.12 and PostgreSQL
18.7-1.pgdg24.04+2. Lima 2.3.0 used macOS native virtualization, with its own
16-GiB disposable disk, no host directory mounts, and no application port
forwarding. Only its loopback SSH management connection was exposed. The
official Lima download matched its published SHA256, and the Ubuntu image
matched the template's pinned SHA256.

The source-only copy excluded `.env`, `.git` and host virtualenvs. The test used
the actual packaged API and cleanup systemd units, actual API dependencies,
canonical database initialization and normal application settings. No mocked
service command or substitute cleanup loop was used. No application/worker
implementation changes were required; the Python worker remains in use.

The driver `tools/linux_search_cleanup/verify.py` verifies eight behaviors:

1. Both packaged units pass `systemd-analyze verify`.
2. `API_WORKERS=2` starts two Uvicorn children and exactly one separate cleanup
   process, which is outside the API's process tree.
3. API restart replaces both service invocations/PIDs. The real cleanup removes
   three expired synthetic search lists and preserves the one active list.
4. API stop leaves both units inactive, both main PIDs zero and no cleanup
   process remaining.
5. API start after stop starts cleanup again.
6. Killing one API child creates a replacement child while the cleanup PID and
   invocation stay unchanged.
7. Killing the main API process triggers automatic API recovery and starts
   exactly one new cleanup process.
8. Killing cleanup triggers its automatic recovery without restarting the API.

Two complete runs passed all eight checks. The final run also rejected a wrong
disposable-host marker before starting either service. Between the passing runs,
a repeat exposed a test-observation race: a deliberately killed child briefly
remained a zombie while its command line was inspected. The driver now retries
that transient observation while still requiring two live API children. This
was a test correction, not an application change.

| Final-run observation | API main PID | Cleanup PID | Cleanup processes |
| --- | ---: | ---: | ---: |
| Start with two API workers | 9695 | 9696 | 1 |
| Explicit API restart | 9732 | 9733 | 1 |
| Explicit API stop | 0 | 0 | 0 |
| Start after stop | 9772 | 9773 | 1 |
| Replace one API child | 9772 | 9773 | 1 |
| Recover main API failure | 9889 | 9890 | 1 |
| Recover cleanup failure | 9889 | 9971 | 1 |
| Final stop | 0 | 0 | 0 |

Measured within the guest, explicit stop took 0.857 and 0.745 seconds; restart
through healthy API readiness took 2.751 and 2.754 seconds. These are service
lifecycle measurements, not search-response timings or a production SLA.

Multiple Uvicorn processes within one API service therefore do **not** create
multiple cleanup processes. Separate API deployments on different hosts can
each create one if configured that way. Deployment must still designate one
cleanup owner per database. The advisory lock prevents simultaneous cleanup
passes; it does not prevent duplicate processes or sequential extra passes.

The three test databases were `erms_linux_cleanup_2c01489a3516`,
`erms_linux_cleanup_5177a607b3aa` and `erms_linux_cleanup_0b8f1c6c4c61`.
Each was newly created and initialized for its run; each was explicitly dropped
before VM deletion. The VM was stopped/deleted and its temporary disk/SSH state,
downloaded launcher and task-created image cache were removed. The local
demo database and stack were not used for these tests.

Earlier Docker attempts never reached application tests because the existing
Docker filesystem had exhausted its inodes. Those attempts do not count as
passing lifecycle evidence. Their test images/containers/networks and ten
remaining test build-cache entries were removed, preserving all 19 older cache
records and existing user data. Docker was returned to its original stopped
state. The successful evidence comes from the independent VM.

Raw logs, journals, source hashes and first/intermediate/final JSON results are
under `.runtime/search-cleanup-vm/`. A compact final evidence file is maintained
alongside this report as `search-cache-cleanup-linux-2026-11-13.json`.
