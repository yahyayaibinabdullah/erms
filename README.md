# Wathiq / ERMS

Wathiq provides records management with an independently deployed FastAPI API
and NiceGUI WebUI.

For local development, start with [local setup](docs/full-text-search-local-setup.md)
and the [WebUI README](frontend/webui/README.md). Run `./run-local-stack.sh` from
the repository root to start the local services.

With no argument it runs in the foreground and Ctrl-C stops its managed
services. Use `./run-local-stack.sh up` to start in the background, `status`
to check health, `down` to stop, and `restart` to stop/start with the current
environment. Logs append to `.runtime/local-stack/stack.log`, with a timestamp,
milliseconds and UTC offset on each new line. See
[local lifecycle commands](docs/local-tooling.md#local-stack-lifecycle).
The stack also starts MailDev (implicit TLS and MCP) and the three separate disposition workers
(eligibility, communications and destruction/completion), stopping them on
Ctrl-C. A previously running managed MailDev instance is reused and left running
on exit; otherwise the stack stops the MailDev instance it started. The API alone
does not start these services. Apply migrations through 071 first;
see [worker operations](docs/operations.md#142-worker-startup-and-verification).
It also starts and supervises segmented-content cleanup, login-session cleanup
and indexing maintenance (unless explicitly disabled), using their database
policy defaults. Production runs these as separate services or schedules.

For local email testing, run `./run-maildev.py up` (MailDev 3, a compatible
Node.js runtime and OpenSSL required). It starts implicit-TLS SMTP on port 1025,
the [mailbox](http://127.0.0.1:1080/) and [MCP](http://127.0.0.1:1080/mcp), and
generates a private local certificate under gitignored `.runtime/maildev/`.
Use `down`, `status` or `restart` to manage it. See
[local MailDev setup](docs/local-tooling.md#local-maildev-with-tls-and-mcp)
for certificate trust, SMTP settings, runtime selection and logs.

Message capture (**Save record**) requires local veraPDF and Java. These tools
are intentionally excluded from Git and must be installed on each colleague's
machine. See [local tooling and installation](docs/local-tooling.md) and the
[message capture upgrade note](docs/upgrades/message-capture-validator.md).
The local stack reports a missing validator with the setup command while
allowing other features to start.

For production, begin with the complete [service inventory and setup order](docs/deployment.md#production-service-inventory).
See [deployment documentation](docs/deployment.md) for deployment requirements
and [database instructions](database/README.md) for schema and migrations.
