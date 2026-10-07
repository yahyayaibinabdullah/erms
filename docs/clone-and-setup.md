# Clone and setup checklist for macOS and Linux

This is the single bootstrap checklist for a new contributor or automation agent. It is ordered so each dependency is installed before the next step, and it covers the native tooling, Python environment, PostgreSQL setup, Tika installation, local configuration, database initialization, and the first local stack start.

Use this as the authoritative setup path after a fresh clone. Do not skip steps in order.

## 1. Clone the repository

```bash
git clone <repository-url>
cd erms
```

## 2. Verify the required toolchain

The project requires:

- Python 3.11+
- Java 17
- PostgreSQL 18 client/server tooling
- Tesseract OCR with Arabic and English language packs
- Poppler utilities
- LibreOffice
- Apache Tika 4.0.0
- Local veraPDF for message capture validation

The repository's canonical setup references are:

- [README.md](../README.md)
- [docs/full-text-search-local-setup.md](full-text-search-local-setup.md)
- [docs/local-tooling.md](local-tooling.md)
- [docs/upgrades/message-capture-validator.md](upgrades/message-capture-validator.md)

## 3. Install native dependencies

### macOS

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install postgresql@18 openjdk@17 tesseract tesseract-lang poppler
brew install --cask libreoffice

sudo ln -sfn "$(brew --prefix openjdk@17)/libexec/openjdk.jdk" \
  /Library/Java/JavaVirtualMachines/openjdk-17.jdk

export PATH="$(brew --prefix postgresql@18)/bin:$PATH"
echo 'export PATH="$(brew --prefix postgresql@18)/bin:$PATH"' >> ~/.zprofile
```

### Linux (Ubuntu/Debian)

```bash
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  curl unzip git ca-certificates \
  python3 python3-venv python3-pip \
  openjdk-17-jdk \
  postgresql postgresql-client \
  poppler-utils \
  tesseract-ocr tesseract-ocr-eng tesseract-ocr-ara \
  libreoffice
```

### Verify native dependencies

```bash
/usr/libexec/java_home -v 17 2>/dev/null || true
java -version
tesseract --version
tesseract --list-langs | grep -E '^(ara|eng)$'
pdfinfo -v
pdftoppm -v
"/Applications/LibreOffice.app/Contents/MacOS/soffice" --version 2>/dev/null || true
psql --version
```

Expect:

- Java 17 is active
- Tesseract reports both `ara` and `eng`
- `psql` resolves to PostgreSQL 18 or a supported local version
- LibreOffice and Poppler are available on the PATH

## 4. Install the pinned Apache Tika distribution

This project installs a verified local Tika under `vendor/tika/` and expects it to stay out of Git.

```bash
bash backend/services/text_indexer/install-tika.sh
```

The installer verifies the archive checksum and installs Tika 4.0.0 under the repository-local `vendor/tika/` directory.

## 5. Create the local environment file from the repo template

The local development environment is created from the repo root template:

```bash
cp .env.example .env
```

This `.env` file is the working local config for the repo. The service-specific templates [.env.example.api](../.env.example.api) and [.env.example.text_indexer](../.env.example.text_indexer) are deployment examples for the API and text-indexer services; they are not copied over the root `.env` unless you are intentionally configuring a separate service deployment.

Then set the values in `.env` to the local machine configuration. At minimum, update these keys before starting the stack:

```ini
DATABASE_URL=postgresql://erms:replace-with-a-secure-password@127.0.0.1:5432/erms
LIBREOFFICE_BINARY=/Applications/LibreOffice.app/Contents/MacOS/soffice
TEXT_INDEXER_TIKA_HOME=vendor/tika
TEXT_INDEXER_API_URL=http://127.0.0.1:8000
TEXT_INDEXER_API_KEY=
TEXT_INDEXER_API_KEY_FILE=.secrets/text-indexer-api-key
TEXT_INDEXER_ENABLED=true
TEXT_INDEXER_CLAIM_BATCH_SIZE=1
TEXT_INDEXER_PROCESS_COUNT=2
CONTENT_INDEXING_SCHEDULING_ENABLED=true
FULL_TEXT_SEARCH_ENABLED=true
WEBUI_FULL_TEXT_SEARCH_ENABLED=true
MESSAGING_PDF_VALIDATOR=.local-tools/verapdf/verapdf
```

On macOS, if LibreOffice is installed via Homebrew cask, the binary will usually be:

```ini
LIBREOFFICE_BINARY=/Applications/LibreOffice.app/Contents/MacOS/soffice
```

On Linux, use the system binary path if necessary, for example:

```ini
LIBREOFFICE_BINARY=/usr/bin/soffice
```

## 6. Set up PostgreSQL and its tools

### macOS with Homebrew

```bash
brew services start postgresql@18
```

Create a local user/database if needed:

```bash
createuser -s postgres 2>/dev/null || true
createdb erms 2>/dev/null || true
```

If the local Postgres server is already running, confirm it with:

```bash
psql -h 127.0.0.1 -p 5432 -U postgres -l
```

### Linux

```bash
sudo service postgresql start
sudo -u postgres createuser --superuser "$USER" 2>/dev/null || true
createdb erms 2>/dev/null || true
```

### Initialize the canonical database schema

The repo initializes a fresh database from the canonical schema, not from migrations:

```bash
set -a
source .env
set +a

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/schema.sql
```

If the `DATABASE_URL` in `.env` is not already a reachable local PostgreSQL instance, update it before running the schema import.

## 7. Install the local PDF validator for message capture

Message capture is optional for normal local usage, but it is required for the Save record PDF validation flow.

From the repository root:

```bash
bash tools/install-local-tools.sh
```

Then install veraPDF for your platform under `.local-tools/` so the CLI exists at:

```text
.local-tools/verapdf/verapdf
```

Update `.env` with:

```ini
MESSAGING_PDF_VALIDATOR=.local-tools/verapdf/verapdf
```

Verify:

```bash
java -version
.local-tools/verapdf/verapdf --version
```

## 8. Install the Python runtime dependencies

The API and WebUI manage their own virtual environments.

```bash
./run-api.sh
./run-webui.sh
```

These scripts create the required `.venv` directories if needed and install the pinned dependencies from the project requirements files.

## 9. Start the full local stack

From the repository root:

```bash
./run-local-stack.sh
```

This launcher:

- ensures the local environment is loaded from `.env`
- checks the local PDF validator
- starts or reconnects to PostgreSQL
- starts the API
- starts the UI
- starts the text-indexer services when enabled
- initializes the indexing maintenance worker when configured

## 10. Verify the local stack

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8080 | head
```

Check that:

- API health responds successfully
- WebUI serves the app on port 8080
- Database is reachable and the schema is initialized
- Tika is installed and configured
- Optional PDF validation is active for message capture

## 11. One-shot automation for an agent

For a non-interactive agent, use the repository bootstrap script:

```bash
bash tools/bootstrap-local-dev.sh
```

The script is designed to work in order and will:

1. detect macOS vs Linux
2. install the required system packages
3. ensure Java 17 and PostgreSQL tools are present
4. create `.env` from `.env.example` if needed
5. install Apache Tika 4.0.0 from the repo script
6. initialize the database from `database/schema.sql` if needed
7. check the local veraPDF validator configuration
8. launch the stack

If the machine is already partially configured, the script should exit cleanly and continue only when a required step is missing.

## 12. Keep local-only files out of Git

The repository intentionally ignores machine-specific local tooling and editor state:

- `.local-tools/`
- `.kilo/`
- `.kile.jsonc`
- `kile.jsonc`
- `.env`
- `.secrets/`

Do not commit local installations or generated runtime state.
