# Local stack shutdown and restart — 2 November 2026

Approved behavior: `down` stops every captured process owned by the stack,
including service children and reloaders; `restart` completes that shutdown
before starting replacements. Reused external services remain untouched.

## Change and safeguards

- `run-local-stack.sh` replaces serial, unbounded parent-process waits with the
  controller's `_cleanup` hook. It supplies only service PIDs actually started
  by that launcher. Direct-parent checks and recorded identity checks validate
  those roots. Foreground Ctrl-C and background commands use the same cleanup.
- `tools/local_stack_control.py` captures matching service trees before sending
  signals, retaining child identities after a parent exits. Discovery continues
  while stopping to include children started by a racing reloader. It sends
  TERM first, allows ten seconds, then KILL only to remaining matching owned
  processes and verifies exit for three seconds. Each signal rechecks identity.
  It never kills a process group or selects processes by occupied ports/names.
- Shutdown records persist in private runtime state. A short separate state
  lock merges updates from the shell and controller without holding locks
  through process waits. A second interrupt cannot interrupt the shell's
  cleanup trap. Direct child waits only run after verified process exit.
- The controller allows normal launcher cleanup for fifteen seconds, then can
  recover matching recorded survivors from an older stuck launcher or a dead
  launcher. That fallback permits five seconds of graceful termination before
  forced cleanup. The existing launcher deadline remains 45 seconds. A failure
  prevents replacement startup. Both background startup and foreground
  registration refuse to overwrite earlier live ownership records.
- Status reports recorded survivors even after the launcher exits. Existing
  MailDev owner-token checks, PostgreSQL reuse/ownership, process-lifetime lock,
  environment precedence and startup migration checks remain in place.

## Automated verification

The four local tooling regression modules passed **39 checks** after the
runtime changes. A final focused run passed **five checks**, including the four
down/restart survivor cases with additional orphan-status assertions and one
new foreground-registration guard: **40 distinct checks** in total.

```bash
backend/services/api/.venv/bin/python -m pytest -q \
  tools/tests/test_local_stack_control.py \
  tools/tests/test_local_stack_disposition.py \
  tools/tests/test_local_stack_log.py \
  tools/tests/test_local_stack_preflight.py

backend/services/api/.venv/bin/python -m pytest -q \
  tools/tests/test_local_stack_control.py \
  -k 'commands_clean_survivors or foreground_registration'
```

Coverage includes stubborn reloader trees and grandchildren, early parent exit,
released listening sockets, forced termination, PID reuse immediately before a
forced signal, dead-launcher survivors, down/restart ordering, refusal to start
after cleanup failure, foreground interrupt cleanup of a TERM-ignoring worker
and child, protection of an untracked service in the same process group,
existing reused-MailDev protection, timestamped logging and startup preflight.
All fixtures use disposable processes, fake services and loopback sockets;
none connects to an ERMS database. Fixture processes are cleaned up afterward.
Shell syntax, Python compilation and `git diff --check` also pass.

## Live managed-stack verification

The new controller successfully restarted the older real launcher. Its old
launcher and all **16 captured service processes** were confirmed gone before
accepting the new healthy stack. The updated shell's own `down` then succeeded:
its launcher and all **16 captured service processes** exited, state became
`stopped`, and API/WebUI ports 8000/8080 were released. The stack was brought
back up and health-checked after verification. Operational evidence remains
under gitignored `.runtime/shutdown-verification/` and local-stack logs.

No environment variable, example environment file, schema, application setting,
translation catalogue or systemd unit change is required. The running stack
has the updated launcher; colleagues obtain it on their next pull/start.
