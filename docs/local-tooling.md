# Local tooling setup

This repository intentionally keeps machine-specific tools and editor state out of Git.

## Local stack services

### Local stack lifecycle

```bash
./run-local-stack.sh          # foreground; Ctrl-C stops managed services
./run-local-stack.sh up       # background; waits for startup health
./run-local-stack.sh status   # launcher, managed processes, API/UI and MailDev health
./run-local-stack.sh down     # graceful shutdown of services started by the stack
./run-local-stack.sh restart  # stop then start with this invocation's environment
```

Successful `up`, `restart` and healthy `status` output includes the API, WebUI,
MailDev inbox and MCP URLs. MailDev URLs use its recorded web port, including
any custom port selected through `run-maildev.py`.

No mode retains the existing foreground workflow and also copies console output
to `.runtime/local-stack/stack.log`. Background mode sends combined API, WebUI,
worker and launcher output to that same append-only file. Lifecycle events go to
`lifecycle.log`; `state.json` stores launcher/process identities and API/UI URLs,
and `control.lock` serializes mutating lifecycle commands. Status remains
available while startup is in progress. The private directory is mode
`0700` and gitignored; logs are not automatically rotated. Avoid sharing raw logs
because application errors can include operational information.

Every new stack-log line is prefixed with an ISO 8601 timestamp including
milliseconds and the machine's UTC offset, for example
`[2026-10-20T12:34:56.123+04:00] Starting FastAPI service.` This records when the
launcher receives the line; any original service timestamp remains in the
message. Traceback/JSON continuation lines and shutdown output are timestamped
too. Foreground console output uses the same prefix. Logging changes take effect
on the next `up`/`restart`; existing undated history is preserved because its
individual line times cannot be reconstructed.

`up` reuses an already healthy stack, including one started in the foreground.
`down` can also stop that recorded foreground stack. It signals only the recorded
launcher after checking PID/start identity; the launcher's normal cleanup stops
its services. Independently running API, WebUI, PostgreSQL and MailDev instances
that were reused remain running. Do not delete runtime state while the stack
runs. A stale PID never authorizes signalling an unrelated replacement process.

`status` exits 0 only when the recorded launcher is ready, its managed processes
are alive, API/UI respond and MailDev passes its TLS/mailbox/MCP checks. Stopped,
starting or unhealthy returns 1. `up` waits up to 240 seconds for health; startup
failure attempts normal shutdown and returns nonzero. `down` waits up to 45
seconds, then reports a failure rather than forcibly killing other processes.
No command applies migrations or changes database application settings.

Environment changes take effect on the next start/restart. These commands use the
same `.env` and exported-environment precedence as foreground mode. A reused
external API keeps its own environment. Stop a separately running service yourself
if you intend the stack to replace it. The process-lifetime lock still prevents
two stack launchers from running together.

If another application owns a default port, startup fails before MailDev or
backend workers start, naming the conflicting port and the paired settings to
change. An unrelated HTTP service is not reused merely because it returns 200.
For example, when ports 8000/8080 belong to other applications:

```bash
API_PORT=18000 WEBUI_API_URL=http://127.0.0.1:18000 \
WEBUI_PORT=18080 ERMS_LOCAL_UI_URL=http://127.0.0.1:18080 \
./run-local-stack.sh up
```

Choose free ports on your machine and use the same overrides for `restart`, or
deliberately configure these existing settings in your private `.env`. Readiness
probes bypass curl configuration/proxies and log HTTP/connection failures rather
than silently retrying. Background startup surfaces preflight errors directly.

### Service inventory

`./run-local-stack.sh` starts/reuses PostgreSQL, the API, WebUI and MailDev,
and starts these independent backend workers for the selected database:

| Worker | Local startup |
| --- | --- |
| `backend.services.api.content_cleanup` | Always; database cleanup policy defaults |
| `backend.services.api.session_cleanup` | Always; database retention, batch and interval defaults |
| `backend.services.api.text_indexing_maintenance cleanup` | Enabled by default; existing `CONTENT_INDEXING_MAINTENANCE_ENABLED=false` disables it |
| `backend.services.api.disposition.eligibility` | Always; 100-item batches, 60-second interval |
| `backend.services.api.disposition.communications` | Always; 100-item batches, 30-second interval |
| `backend.services.api.disposition.destruction_worker` | Always; one-item batches, 5-second interval |
| REST text indexer | When `TEXT_INDEXER_ENABLED=true`; configured child process pool |

The launcher supervises its worker processes and stops them on exit. A worker
exit stops the stack rather than leaving a partially running stack. Use only
one local stack, and stop independently launched copies or service units for
the same database first. The API alone does not start these workers. Existing
API/WebUI services and separately managed MailDev instances remain running when
the launcher exits. Production uses the
[deployment guide](deployment.md#production-service-inventory) and separate
service units or scheduled alternatives.

## PDF validation

Message capture (**Save record** for a message) requires the independent
veraPDF CLI and its Java runtime. Other application features do not require
veraPDF. Both PDF/A-2u and PDF/UA-1 validation must succeed before capture can
commit. Missing tooling does not disable ordinary messaging or prevent startup.

Each colleague must install these tools locally after cloning or syncing a fork:
`.local-tools/` is deliberately ignored by Git. Python requirements and database
migrations do not install the validator. Wathiq capture acceptance verification
used veraPDF 1.30.2; see [deployment requirements](deployment.md).

From the repository root, run:

```bash
bash tools/install-local-tools.sh
```

This helper prints manual installation instructions and exits with status 1
until the expected executable exists. It does not download or install software.

1. Install a Java runtime supported by your veraPDF package. The macOS Java 17
   setup is in [local setup](full-text-search-local-setup.md).
2. Download a stable Greenfield installer from the
   [official veraPDF installation guide](https://docs.verapdf.org/install/).
3. Extract the installer archive, run its `vera-install` launcher on macOS/Linux
   (`vera-install.bat` on Windows), and choose the repository's
   `.local-tools/verapdf` as the installation directory. Include the CLI/startup
   scripts. Extracting an installer archive alone does not install the CLI.
4. Confirm the executable and Java runtime work:

   ```bash
   java -version
   ./.local-tools/verapdf/verapdf --version
   ```

5. Set this in the root `.env` (or use an absolute executable path):

   ```dotenv
   MESSAGING_PDF_VALIDATOR=.local-tools/verapdf/verapdf
   ```

If your package installs its launcher at a different location, use that exact
path. An explicitly configured path takes precedence; there is no silent
fallback to another installation. If the variable is absent, capture uses
`verapdf` on PATH.

`run-local-stack.sh` checks the resolved environment after loading `.env`, even
when it reuses an existing API. A missing/non-executable validator or failing
`--version` check prints a warning, the helper command and the affected feature.
The probe has a ten-second timeout and continues startup; it does not validate
a PDF or replace the independent checks performed for every capture. Restart
an existing API after changing its environment.

For a standalone check, export the same setting and run:

```bash
MESSAGING_PDF_VALIDATOR=.local-tools/verapdf/verapdf python3 tools/check_local_pdf_validator.py
```

The standalone checker does not load `.env`; it uses its process environment.
See the [upgrade note](upgrades/message-capture-validator.md).

## Local editor state

The repo also ignores `.kile.jsonc` and any local editor state files so they do not get committed.

The Git ignore rules already cover:

- `.local-tools/`
- `.kile.jsonc`
- `kile.jsonc`

These settings are meant to remain local to each machine, not to be shared in the source repository.

### macOS renderer library path

If WeasyPrint reports that it cannot load GObject/Pango despite Homebrew
libraries being installed, configure the installed library directory in `.env`:

```dotenv
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
```

Use the actual Homebrew library directory on your machine and restart the API.
This follows the official WeasyPrint missing-library troubleshooting guidance:
https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#missing-library

## Local MailDev with TLS and MCP

`./run-local-stack.sh` also starts the three disposition workers independently
of the API, plus segmented-content and login-session cleanup using their
database policy defaults. Indexing maintenance also starts unless explicitly
disabled with the existing `CONTENT_INDEXING_MAINTENANCE_ENABLED=false` option;
the text indexer itself starts when `TEXT_INDEXER_ENABLED=true`.
It supervises these workers and stops them on exit. Stop manually launched
worker copies before using it. To trust
MailDev in the API and its managed communications worker, launch the stack with
`SSL_CERT_FILE="$PWD/.runtime/maildev/localhost.pem" ./run-local-stack.sh`.
The stack starts MailDev automatically before the API and workers, generating
its certificate on first use. It reuses a healthy instance already managed by
`run-maildev.py` and leaves that instance running on exit. If it starts a new
instance, it stops that instance on exit. A failed MailDev startup stops stack
startup. This does not change database SMTP settings or an already running
API's environment. MailDev can also be managed separately using the commands
below. The stack does
not apply migrations; migration 071 must already be installed. See
[worker operations](operations.md#142-worker-startup-and-verification).

Run from the project root on macOS/Linux (Python 3.10+, OpenSSL supporting
`req -addext`, and MailDev 3 with a compatible Node.js runtime required):

```bash
npm install -g maildev@3
./run-maildev.py up
./run-maildev.py status
./run-maildev.py restart
./run-maildev.py down
```

The launcher does not install dependencies. MailDev must advertise `--mcp` and
`--incoming-secure`. If it fails its startup probe, inspect
`.runtime/maildev/maildev.log`. For example, the installed MailDev 3 dependency
chain fails under Node 20.13.1 with `ERR_REQUIRE_ESM`; a compatible newer Node
works. Select the runtime explicitly when PATH points at an incompatible one:

```bash
./run-maildev.py up --node /opt/homebrew/bin/node
```

Use the path on your own machine. `--maildev /path/to/maildev` selects another
MailDev installation. The resolved MailDev script is executed with the selected
Node runtime. Options are retained in local state for subsequent `up` and
`restart`; use `restart` with options to change a running instance.

Default endpoints (also printed by `up`, `restart` and a healthy `status`):

- Mailbox: <http://127.0.0.1:1080/>
- MCP Streamable HTTP: <http://127.0.0.1:1080/mcp>
- SMTP: `localhost:1025`, **implicit TLS** from the first byte, no SMTP authentication.

Only SMTP uses TLS; mailbox and MCP use HTTP on loopback. Both servers bind to
`127.0.0.1`. No outgoing relay is configured. Inherited `MAILDEV_*` settings and
ancestor MailDev configuration files are excluded so an existing relay or bind
configuration cannot leak into this instance. The tool does not read `.env`.
MCP clients can inspect and modify captured local mail; use synthetic test data.

If a port is occupied, the launcher refuses to start and does not stop its owner:

```bash
./run-maildev.py up --smtp-port 11025 --web-port 11080
```

Configure the matching **database-backed Application Configuration** settings
for deliberate local development: `SMTP_HOST=localhost`, `SMTP_PORT=1025` (or
the selected port), `SMTP_SECURITY=implicit_tls`, `SMTP_AUTH_ENABLED=false`,
and an appropriate test sender address. A username/password is unnecessary.
The launcher itself never reads or writes the database or changes SMTP settings.

### Certificate trust and local files

On first startup the launcher generates a self-signed RSA certificate, valid
for 365 days, for `localhost`, `127.0.0.1` and `::1`. It stores the certificate
and private key at `.runtime/maildev/localhost.pem` and `localhost.key`, reuses
them on restart, sets the key to mode `0600` and the service directory to `0700`.
The entire root `.runtime/` is gitignored. No system trust store is changed.

ERMS verifies SMTP certificates. Trust the generated certificate **in each
local sending process**, including a separately launched communications worker.
Python/OpenSSL supports the standard process setting `SSL_CERT_FILE`; for example:

```bash
SSL_CERT_FILE="$PWD/.runtime/maildev/localhost.pem" ./run-api.sh
SSL_CERT_FILE="$PWD/.runtime/maildev/localhost.pem" python -m backend.services.api.disposition.communications --help
```

Use the worker's documented invocation after checking `--help`. Restart an
already running sender with this environment. This is a local process override,
not a new ERMS setting, and may replace that process's default CA file; use a
combined CA bundle if that process also needs other certificate authorities.
Do not disable certificate or hostname validation. To rotate an expired local
certificate, run `down`, remove **both** `localhost.pem` and `localhost.key`,
run `up`, then restart trusting clients. An incomplete pair is rejected rather
than silently replaced.

`.runtime/maildev/maildev.log` appends server stdout/stderr and certificate
creation output; `lifecycle.log` records starts, stops and failures. These logs
are not rotated automatically. Captured mail persists under `mail/`, capped at
1,000 messages (oldest removed by MailDev); treat it as disposable local data.
`state.json` records PID, process identity and selected runtime/ports;
it also records a lifecycle owner token when started by the local stack. The
helper's `--owner` option lets stack cleanup stop only its own instance, even
if someone subsequently restarts MailDev separately.
`control.lock` serializes lifecycle commands. `down` only signals the exact
recorded process and preserves mail, keys, configuration and logs. Do not delete
runtime state while the service runs. To reset local mail/logs, stop first and
remove the corresponding files. `status` exits 0 only when the owned process,
verified TLS SMTP, mailbox and MCP initialization are healthy; stopped or
unhealthy returns nonzero. Startup failures also return nonzero.

Launcher safety checks run without a database or external services:
`python3 -m pytest tools/tests/test_maildev_launcher.py -q`.
Local integration verification on 20 October 2026 covered SMTP delivery with
certificate validation, mailbox capture, MCP initialization, idempotent
up/down, restart mail persistence, key reuse and occupied-port refusal.
