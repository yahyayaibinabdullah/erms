#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

OS_NAME="$(uname -s)"
export DEBIAN_FRONTEND=noninteractive

info() {
  printf '\n[bootstrap] %s\n' "$1"
}

require_root_or_sudo() {
  if [[ "${OS_NAME}" == "Darwin" ]]; then
    return 0
  fi
  if [[ "${EUID}" -ne 0 ]]; then
    echo "This bootstrap script needs sudo for Linux package installation." >&2
    exit 1
  fi
}

install_macos() {
  if ! command -v brew >/dev/null 2>&1; then
    info "Installing Homebrew"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null)"
  fi

  info "Installing macOS dependencies"
  brew install postgresql@18 openjdk@17 tesseract tesseract-lang poppler >/dev/null
  brew install --cask libreoffice >/dev/null 2>&1 || true

  if [[ ! -L "/Library/Java/JavaVirtualMachines/openjdk-17.jdk" ]]; then
    sudo ln -sfn "$(brew --prefix openjdk@17)/libexec/openjdk.jdk" \
      /Library/Java/JavaVirtualMachines/openjdk-17.jdk
  fi

  if ! grep -q 'brew --prefix postgresql@18' ~/.zprofile 2>/dev/null; then
    echo 'export PATH="$(brew --prefix postgresql@18)/bin:$PATH"' >> ~/.zprofile
  fi
  export PATH="$(brew --prefix postgresql@18)/bin:$PATH"
}

install_linux() {
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "This Linux bootstrap assumes apt-based distributions." >&2
    exit 1
  fi

  info "Installing Ubuntu/Debian dependencies"
  sudo apt-get update >/dev/null
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    curl unzip git ca-certificates \
    python3 python3-venv python3-pip \
    openjdk-17-jdk \
    postgresql postgresql-client \
    poppler-utils \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-ara \
    libreoffice >/dev/null
}

ensure_env_file() {
  local env_file="${PROJECT_DIR}/.env"
  local template_file="${PROJECT_DIR}/.env.example"

  if [[ ! -f "${env_file}" ]]; then
    info "Creating .env from .env.example"
    cp "${template_file}" "${env_file}"
  fi

  info "Ensuring the local .env values match the repo defaults"
  python3 - "${env_file}" "${PROJECT_DIR}" <<'PY'
import os
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
project_dir = Path(sys.argv[2])

base = {
    "DATABASE_URL": "postgresql://erms:replace-with-a-secure-password@127.0.0.1:5432/erms",
    "LIBREOFFICE_BINARY": "/Applications/LibreOffice.app/Contents/MacOS/soffice" if sys.platform == "darwin" else "/usr/bin/soffice",
    "TEXT_INDEXER_TIKA_HOME": "vendor/tika",
    "TEXT_INDEXER_API_URL": "http://127.0.0.1:8000",
    "TEXT_INDEXER_API_KEY": "",
    "TEXT_INDEXER_API_KEY_FILE": ".secrets/text-indexer-api-key",
    "TEXT_INDEXER_ENABLED": "true",
    "TEXT_INDEXER_CLAIM_BATCH_SIZE": "1",
    "TEXT_INDEXER_PROCESS_COUNT": "2",
    "CONTENT_INDEXING_SCHEDULING_ENABLED": "true",
    "FULL_TEXT_SEARCH_ENABLED": "true",
    "WEBUI_FULL_TEXT_SEARCH_ENABLED": "true",
    "MESSAGING_PDF_VALIDATOR": ".local-tools/verapdf/verapdf",
}

lines = env_path.read_text(encoding="utf-8").splitlines()
existing = {}
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        existing[key] = value

for key, value in base.items():
    if key not in existing or existing[key].strip() in {"", "replace-with-a-secure-password", "replace-with-the-issued-wti-key", "replace-with-a-unique-deployment-id"}:
        existing[key] = value

out = []
for key in list(base) + [k for k in existing if k not in base]:
    if key in existing:
        out.append(f"{key}={existing[key]}")

# Keep comments and unrelated keys in place by appending any non-template lines not managed here.
seen = set()
normalized = []
for line in out:
    key = line.split("=", 1)[0]
    if key not in seen:
        seen.add(key)
        normalized.append(line)

env_path.write_text("\n".join(normalized) + "\n", encoding="utf-8")
PY
}

ensure_postgres_client() {
  if ! command -v psql >/dev/null 2>&1; then
    echo "psql is required but missing from PATH." >&2
    exit 1
  fi
}

ensure_java() {
  if ! command -v java >/dev/null 2>&1; then
    echo "Java is required but missing from PATH." >&2
    exit 1
  fi
  java -version >/dev/null 2>&1 || {
    echo "Java is not usable on this machine." >&2
    exit 1
  }
}

ensure_tika() {
  if [[ ! -f "${PROJECT_DIR}/vendor/tika/tika-app-4.0.0.jar" ]]; then
    info "Installing Apache Tika 4.0.0"
    bash "${PROJECT_DIR}/backend/services/text_indexer/install-tika.sh"
  fi
}

ensure_verapdf() {
  if [[ ! -x "${PROJECT_DIR}/.local-tools/verapdf/verapdf" ]]; then
    info "veraPDF is not installed yet; follow the manual local-tooling steps in docs/local-tooling.md"
    echo "The stack can continue without it, but message capture validation will remain disabled until the binary is installed." >&2
  fi
}

initialize_database() {
  ensure_postgres_client

  if [[ -f "${PROJECT_DIR}/.env" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${PROJECT_DIR}/.env"
    set +a
  fi

  DATABASE_URL="${DATABASE_URL:-postgresql://erms:replace-with-a-secure-password@127.0.0.1:5432/erms}"
  if ! psql "${DATABASE_URL}" -v ON_ERROR_STOP=1 -Atc 'SELECT 1' >/dev/null 2>&1; then
    info "Initializing PostgreSQL database from database/schema.sql"
    psql "${DATABASE_URL}" -v ON_ERROR_STOP=1 -f "${PROJECT_DIR}/database/schema.sql" >/dev/null
  fi
}

start_local_stack() {
  if [[ -x "${PROJECT_DIR}/run-local-stack.sh" ]]; then
    info "Starting the local stack"
    bash "${PROJECT_DIR}/run-local-stack.sh"
  else
    echo "run-local-stack.sh is missing from the repository root." >&2
    exit 1
  fi
}

main() {
  require_root_or_sudo
  ensure_env_file

  case "${OS_NAME}" in
    Darwin)
      install_macos
      ;;
    Linux)
      install_linux
      ;;
    *)
      echo "Unsupported OS: ${OS_NAME}" >&2
      exit 1
      ;;
  esac

  ensure_java
  ensure_postgres_client
  ensure_tika
  ensure_verapdf
  initialize_database
  start_local_stack
}

main "$@"
