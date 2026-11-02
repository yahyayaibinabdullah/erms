# Full-text search local setup

This is the complete macOS checklist for a new contributor. Python
`requirements.txt` files do not install Java, Tesseract, its language packs,
Poppler, LibreOffice, or PostgreSQL. Message capture additionally requires
veraPDF and Java: follow [the local tooling guide](local-tooling.md) after
cloning and [the upgrade note](upgrades/message-capture-validator.md) when
syncing an existing fork. veraPDF is a capture requirement, not a requirement
for every application feature.

1. Install Homebrew if it is not already available:

   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

2. Install the native dependencies:

   ```bash
   brew install postgresql@18 openjdk@17 tesseract tesseract-lang poppler
   brew install --cask libreoffice
   ```

   Put the PostgreSQL 18 client first on the current shell's path:

   ```bash
   export PATH="$(brew --prefix postgresql@18)/bin:$PATH"
   ```

   Add the same export to `~/.zprofile` if it should persist for future
   terminals. Docker is not required when the configured PostgreSQL server is
   already reachable; the local launcher uses Docker only as a fallback for
   its default database URL.

3. Make Homebrew's Java 17 installation visible to macOS Java launchers:

   ```bash
   sudo ln -sfn "$(brew --prefix openjdk@17)/libexec/openjdk.jdk" \
     /Library/Java/JavaVirtualMachines/openjdk-17.jdk
   ```

4. Verify every native dependency before proceeding:

   ```bash
   /usr/libexec/java_home -v 17
   java -version
   tesseract --version
   tesseract --list-langs | grep -E '^(ara|eng)$'
   pdfinfo -v
   pdftoppm -v
   "/Applications/LibreOffice.app/Contents/MacOS/soffice" --version
   "$(brew --prefix postgresql@18)/bin/psql" --version
   ```

   The Tesseract language check must print both `ara` and `eng`.

5. Clone the repository and enter it:

   ```bash
   git clone <repository-url>
   cd erms
   ```

6. Install the pinned complete Apache Tika distribution:

   ```bash
   backend/services/text_indexer/install-tika.sh
   ```

   The installer downloads the official Tika 4.0.0 archive, verifies its
   committed SHA-512 checksums, requires `tika-pipes-fork-parser`, and installs
   it under the Git-ignored `vendor/tika/` directory.

7. Create the full-stack local environment:

   ```bash
   cp .env.example .env
   ```

   Set the local `DATABASE_URL` and confirm these values:

   ```ini
   LIBREOFFICE_BINARY=/Applications/LibreOffice.app/Contents/MacOS/soffice
   TEXT_INDEXER_TIKA_HOME=vendor/tika
   TEXT_INDEXER_API_URL=http://127.0.0.1:8000
   TEXT_INDEXER_API_KEY=
   TEXT_INDEXER_API_KEY_FILE=.secrets/text-indexer-api-key
   TEXT_INDEXER_ENABLED=true
   TEXT_INDEXER_CLAIM_BATCH_SIZE=1
   TEXT_INDEXER_PROCESS_COUNT=2
   ```

8. Start PostgreSQL 18 if it is not already running:

   ```bash
   brew services start postgresql@18
   ```

9. Initialize a new empty database from the canonical schema. Do not run
   migrations after initializing from the latest schema:

   ```bash
   set -a
   source .env
   set +a
   "$(brew --prefix postgresql@18)/bin/psql" \
     "$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/schema.sql \
  -f database/seeds/000_required_reference_data.sql \
  -f database/baseline.sql
   ```

   For an existing database, inspect `schema_migrations` and apply only missing
   migrations in filename order through migration 017.

10. Start the full local stack:

    ```bash
    ./run-local-stack.sh
    ```

    The launcher installs Python dependencies, provisions the loopback-only
    indexer service identity and protected key, starts the API, indexer and UI,
    starts the API-owned indexing/credential maintenance watch process, and
    waits for the indexer to register. The maintenance process runs one bounded
    pass immediately and then every
    `CONTENT_INDEXING_CLEANUP_INTERVAL_SECONDS` (3600 seconds by default). It is
    stopped with the stack and is monitored like the other managed processes.
    Set `CONTENT_INDEXING_MAINTENANCE_ENABLED=false` only when another scheduler
    already owns cleanup for the same database. Unless
    `TEXT_INDEXER_WORKER_ID` is explicitly set, each launcher invocation uses a
    unique local worker ID so an immediate restart cannot collide with the
    preceding process's ten-minute active-registration window.

    The local launcher starts one text-indexer supervisor service. With
    `TEXT_INDEXER_PROCESS_COUNT=2`, that supervisor starts two worker child
    processes. Each child claims one document at a time, so at most two
    documents are extracted concurrently. Set the count to `1` on a
    memory-constrained laptop; raise it only when the machine can accommodate
    another Tika/OCR process and its configured memory ceiling.

    **Local example — normal development:** keep the committed default
    `TEXT_INDEXER_PROCESS_COUNT=2`. One `run-local-stack.sh` invocation starts
    one supervisor plus two children, and up to two documents are extracted at
    once.

    **Local example — memory-constrained laptop:** set
    `TEXT_INDEXER_PROCESS_COUNT=1` in `.env`. The same command starts one
    supervisor plus one child, and documents are extracted serially. Do not
    change `TEXT_INDEXER_CLAIM_BATCH_SIZE=1` in either scenario.

    For PDFs, the worker prefers an adequate native text layer and invokes OCR
    only for scanned or text-poor content. If a text-rich, high-page-count PDF
    repeatedly reaches `TEXT_INDEXER_EXTRACTION_TIMEOUT_SECONDS`, do not merely
    raise the timeout: confirm that the current worker is running, restart it,
    and retry one component from **Text Indexers → Health → Failure
    diagnostics**. The operations guide documents this failure pattern and its
    verification steps in **Text-rich PDF repeatedly reports `timeout`**.

    The local stack provisions one loopback-only Text Indexers service account
    and one protected API key for the complete local text-indexer service. All
    child workers share that credential and receive distinct runtime worker
    IDs; it does not create an account or key per child. This is the local
    equivalent of one production server/pool using one dedicated account. A
    second independently deployed indexer server should normally use a
    separate account and key created through **Administration → Text
    Indexers**, not a copy of the auto-provisioned local credential.

    An empty `TEXT_INDEXER_API_KEY` selects that local provisioning flow. If a
    developer supplies an issued `wti_...` value explicitly, the launcher uses
    it and does not provision or replace a credential.

11. Verify the rollout state:

    ```bash
    curl -s http://127.0.0.1:8000/health
    ```

    Both `full_text_search_enabled` and
    `content_indexing_scheduling_enabled` must be `true`.
    In the UI, an administrator with `identity.text_indexers.administer` can
    open **Administration → Text Indexers → Health** to confirm worker and
    indexing readiness, refresh the snapshot, and queue idempotent backfill
    batches of 1–500 existing components.

12. Open `http://127.0.0.1:8080`, upload an English or Arabic document, wait
    for indexing, and search for text contained inside it.

Search/indexing policy and Audit Trail result caps are database-owned. Configure
them through Administration Settings after bootstrap; environment assignments no
longer enable scheduling or search. The removed WebUI flag has no authority.
See [application-settings-upgrade.md](application-settings-upgrade.md) for the
reviewed 34-key upgrade and [configuration-authority-inventory.json](configuration-authority-inventory.json)
for ownership, defaults, consumers, service templates and restart requirements.
