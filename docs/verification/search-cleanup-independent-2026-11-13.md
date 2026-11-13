# Independent Python cleanup verification — 13 November 2026

Production login-session/search-cache cleanup now runs independently of API
lifecycle. PostgreSQL session advisory lock `2026091803` elects one active
process per database. Optional copies wait as standbys. The same connection
owns the lock and executes both jobs; connection loss cannot leave an old owner
working through another connection. Existing per-job transaction locks, batch
limits, audit rules and separate schedules remain in place.

`run-local-stack.sh` continues to start, supervise and stop its own separate
cleanup process in tandem with the complete local stack. Production systemd
starts cleanup at boot and restarts failures independently of API services.

## Evidence

[Machine-readable results](search-cleanup-independent-2026-11-13.json) include
checks, service identities, database lock observations, source hashes and cleanup
confirmation. Full journals and provisioning logs remain in gitignored
`.runtime/search-cleanup-independent/`.

- **35 database-backed regressions passed**, including leadership across commit
  and rollback, lost-connection exclusion, existing retention/audit behavior,
  bounded search-cache deletion, live settings, migration parity and graceful
  worker exit. The runner created and dropped
  `erms_messaging_test_acl_237b34c0e8a941d9be0d8579b2af4d49`.
- **38 deployment/local-stack regressions passed**, including process ownership,
  worker startup, shutdown, restart and unexpected worker termination. Initial
  sandbox execution could not inspect processes or bind loopback sockets; the
  authorized rerun outside those restrictions passed.
- **12 real Linux/systemd scenarios passed in two complete runs**, each on a
  freshly initialized database. The final run began with the complete deployment
  already installed before reboot. It used Ubuntu 24.04 userspace, systemd
  255.4-1ubuntu8.18, Linux 6.10.14-linuxkit ARM64, PostgreSQL 18.7, the actual
  production service units, API runtime dependencies and two Uvicorn workers.
- Configuration authority validation passed for 126 settings. All 36 API
  environment settings remain documented and generated templates agree.
  Compilation and whitespace checks passed.

| Linux scenario | Verified result |
| --- | --- |
| Unit validation | Both packaged units pass `systemd-analyze verify` |
| Boot with API disabled | Enabled cleanup starts and acquires leadership |
| Actual deletion with API stopped | Deletes expired lists in the configured two-list test batches and preserves the active list |
| Two-worker API start/restart/stop | Cleanup invocation and ownership stay unchanged |
| Cleanup restart | API invocation stays unchanged and remains healthy |
| Two simultaneous cleanup services | One leader across commits; standby runs no jobs; leader sleeps outside a transaction |
| One-shot and dry-run alongside leader | Report standby and exit without running either job |
| Graceful leader stop | Releases ownership; standby takes over and deletes a newly expired list |
| Leader SIGKILL | Ownership is released, supervisor restarts the process, cleanup continues |
| PostgreSQL leader connection terminated | Old owner fails, a new connection owns leadership, supervised recovery occurs, API stays healthy |
| Two databases on one PostgreSQL server | Each independently elects an active cleanup worker |
| Explicit cleanup shutdown | Both processes stop and release leadership; API remains operational until explicitly stopped |

The final run observed 127 database-scoped lock snapshots, never more than one
granted owner per database. Graceful leader stop took **0.035 seconds**; standby
leadership was observed **1.036 seconds** after initiating that stop. These are
local observations, not a network-failover SLA: takeover depends on PostgreSQL
detecting connection loss plus the five-second standby retry interval.

The two competing services ran in one disposable Linux environment with separate
processes/connections and no PID-file or host-local singleton coordination.
Physical multi-server networking, network partitions and PostgreSQL replica
promotion were not tested. No search matching, ranking, permissions or page SQL
changed, so the unrelated large-data search benchmark was not rerun.

## Reproduction and fixture corrections

Use `tools/run_disposable_acl_tests.py` for the database regressions:

```bash
backend/services/api/.venv/bin/python tools/run_disposable_acl_tests.py \
  backend/services/api/tests/test_search_cache_cleanup.py \
  backend/services/api/tests/test_authentication.py \
  backend/services/api/tests/test_application_settings_phase5_authentication.py
backend/services/api/.venv/bin/python -m pytest -q \
  tools/tests/test_search_cleanup_deployment.py \
  tools/tests/test_local_stack_disposition.py \
  tools/tests/test_local_stack_control.py \
  tools/tests/test_local_stack_preflight.py
```

For Linux, follow [the disposable-host procedure](../deployment.md#separate-systemd-services)
and run `tools/linux_search_cleanup/verify.py`. Install the complete backend,
including shared `backend/services` modules and the text-indexer MIME catalogue,
plus the referenced frontend catalogues and security data. Provision the API
virtual environment with the launcher's checksum of the absolute requirements
path. Enable cleanup before boot and leave API disabled.

Preliminary attempts exposed fixture/provisioning errors: the application-settings
guard correctly rejected an unauthenticated fixture update; its deferred events
needed flushing before restoring that guard; the dependency stamp used the wrong
path; the driver raced PostgreSQL startup; and the source bundle omitted shared
backend modules. These were corrected in the disposable fixture/deployment.
The timing fixture changes only two settings in its newly initialized database,
restoring the guard transactionally. No production permission check was weakened.
A fresh database was created for each retry and every replaced database dropped.
The production worker implementation needed no changes during these corrections.

## Cleanup and deployment

All **nine Linux test databases**, including the two secondary-database probes,
were explicitly dropped. The separate API regression database was also dropped.
Both task containers, the temporary committed test image and the newly downloaded
Ubuntu image were removed. No persistent Docker volumes or BuildKit cache were
created. No pre-existing Docker resources were pruned. Final inventory matches
the initial inventory: seven images, one stopped container, three volumes and
19 build-cache records. Detailed database names and zero remaining test resources
are recorded in the JSON evidence.

No new migration, Application Setting, environment variable, translation key or
private `.env` change is required. Deployment operators must stop old cleanup
copies, update worker code and both service units, reload systemd, then re-enable
and start cleanup to replace the old API-dependent enablement link. Remove any
site-specific lifecycle coupling. Upgrade every cleanup copy together; old code
only has per-job locks. See [the upgrade procedure](../deployment.md#separate-systemd-services).
The local stack picks up the new worker on its next restart. Local `demo` and the
running development stack were not modified for this verification.
