#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ENV_FILE="${PROJECT_DIR}/.env"

case "${1:-}" in
    up|down|status|restart)
        exec python3 "${PROJECT_DIR}/tools/local_stack_control.py" "$@"
        ;;
    ""|__managed|__logging) ;;
    *) echo "Usage: $0 [up|down|status|restart] (no mode: foreground)" >&2; exit 2 ;;
esac

# Install the log pipe before taking the process-lifetime lock. The reader must
# not inherit that lock, or it could delay restart after the launcher exits.
if [[ " $* " != *" __logging "* ]]; then
    umask 077
    mkdir -p "${PROJECT_DIR}/.runtime/local-stack"
    chmod 700 "${PROJECT_DIR}/.runtime/local-stack"
    if [[ "${1:-}" == __managed ]]; then
        exec > >(python3 -u "${PROJECT_DIR}/tools/local_stack_log.py" \
            "${PROJECT_DIR}/.runtime/local-stack/stack.log") 2>&1
    else
        exec > >(python3 -u "${PROJECT_DIR}/tools/local_stack_log.py" \
            "${PROJECT_DIR}/.runtime/local-stack/stack.log" --console) 2>&1
    fi
fi

# Serialize launchers before provisioning rotates the shared indexer key.
# The kernel releases this lock on exit, including an unexpected termination.
if [[ "${ERMS_LOCAL_STACK_LOCK_PID:-}" != "$$" ]]; then
    exec python3 "${PROJECT_DIR}/tools/local_stack_lock.py" \
        "${PROJECT_DIR}/.cache/local-stack.lock" bash "${BASH_SOURCE[0]}" "$@" __logging
fi
unset ERMS_LOCAL_STACK_LOCK_PID

umask 077
mkdir -p "${PROJECT_DIR}/.runtime/local-stack"
chmod 700 "${PROJECT_DIR}/.runtime/local-stack"
python3 "${PROJECT_DIR}/tools/local_stack_control.py" _register "$$"

# Reconcile before loading defaults, under the launcher lock. Existing values
# (including deliberately empty values) remain untouched.
python3 "${PROJECT_DIR}/tools/reconcile_local_env.py"

# Load project-local defaults before resolving the stack configuration. Keep
# values explicitly exported by the invoking environment authoritative, which
# matches the override=False behavior used by the API and web UI.
if [[ -f "${PROJECT_ENV_FILE}" ]]; then
    INHERITED_EXPORTED_ENVIRONMENT="$(export -p)"
    ALLEXPORT_WAS_ENABLED=false
    if [[ "$-" == *a* ]]; then
        ALLEXPORT_WAS_ENABLED=true
    fi
    set -a
    # shellcheck disable=SC1090
    source "${PROJECT_ENV_FILE}"
    if [[ "${ALLEXPORT_WAS_ENABLED}" == false ]]; then
        set +a
    fi
    eval "${INHERITED_EXPORTED_ENVIRONMENT}"
    unset INHERITED_EXPORTED_ENVIRONMENT ALLEXPORT_WAS_ENABLED
fi

# Optional feature prerequisite, checked even when services are reused.
# This reads the resolved environment and never blocks unrelated features.
python3 "${PROJECT_DIR}/tools/check_local_pdf_validator.py"

readonly STACK_DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:5433/erms}"
readonly STACK_DB_CONTAINER="${ERMS_LOCAL_DB_CONTAINER:-erms-postgres-local}"
readonly STACK_DB_VOLUME="${ERMS_LOCAL_DB_VOLUME:-erms-postgres-local-data}"
readonly STACK_DB_IMAGE="${ERMS_LOCAL_DB_IMAGE:-postgres:18-alpine}"
readonly STACK_DB_PORT="${ERMS_LOCAL_DB_PORT:-5433}"
readonly STACK_API_URL="${WEBUI_API_URL:-http://127.0.0.1:8000}"
readonly STACK_UI_URL="${ERMS_LOCAL_UI_URL:-http://127.0.0.1:8080}"
readonly STACK_INDEXER_ENABLED="${TEXT_INDEXER_ENABLED:-false}"
readonly STACK_INDEXER_SECRET_FILE="${TEXT_INDEXER_API_KEY_FILE:-${PROJECT_DIR}/.secrets/text-indexer-api-key}"
# A worker ID identifies one live process incarnation. Reusing the fixed local
# name during the API's ten-minute active-registration window is correctly
# rejected as split brain. Give each launcher invocation its own default while
# preserving an explicitly configured deployment ID.
readonly STACK_INDEXER_WORKER_ID="${TEXT_INDEXER_WORKER_ID:-local-stack-indexer-$$}"
readonly STACK_INDEXER_PROCESS_COUNT="${TEXT_INDEXER_PROCESS_COUNT:-2}"
readonly STACK_INDEXING_MAINTENANCE_ENABLED="${CONTENT_INDEXING_MAINTENANCE_ENABLED:-true}"

API_PID=""
UI_PID=""
INDEXER_PID=""
INDEXING_MAINTENANCE_PID=""
CONTENT_CLEANUP_PID=""
SESSION_CLEANUP_PID=""
DISPOSITION_ELIGIBILITY_PID=""
DISPOSITION_COMMUNICATIONS_PID=""
DISPOSITION_DESTRUCTION_PID=""
readonly MAILDEV_OWNER="local-stack-$$"
MANAGED_MAILDEV=false
MANAGED_DATABASE=false

cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM

    local worker_pid
    if [[ -n "${SESSION_CLEANUP_PID}" ]] && kill -0 "${SESSION_CLEANUP_PID}" 2>/dev/null; then
        kill "${SESSION_CLEANUP_PID}" 2>/dev/null || true
        wait "${SESSION_CLEANUP_PID}" 2>/dev/null || true
    fi
    if [[ -n "${CONTENT_CLEANUP_PID}" ]] && kill -0 "${CONTENT_CLEANUP_PID}" 2>/dev/null; then
        kill "${CONTENT_CLEANUP_PID}" 2>/dev/null || true
        wait "${CONTENT_CLEANUP_PID}" 2>/dev/null || true
    fi
    for worker_pid in "${DISPOSITION_ELIGIBILITY_PID}" "${DISPOSITION_COMMUNICATIONS_PID}" "${DISPOSITION_DESTRUCTION_PID}"; do
        if [[ -n "${worker_pid}" ]] && kill -0 "${worker_pid}" 2>/dev/null; then
            kill "${worker_pid}" 2>/dev/null || true
            wait "${worker_pid}" 2>/dev/null || true
        fi
    done
    if [[ -n "${INDEXING_MAINTENANCE_PID}" ]] && kill -0 "${INDEXING_MAINTENANCE_PID}" 2>/dev/null; then
        kill "${INDEXING_MAINTENANCE_PID}" 2>/dev/null || true
        wait "${INDEXING_MAINTENANCE_PID}" 2>/dev/null || true
    fi
    if [[ -n "${INDEXER_PID}" ]] && kill -0 "${INDEXER_PID}" 2>/dev/null; then
        kill "${INDEXER_PID}" 2>/dev/null || true
        wait "${INDEXER_PID}" 2>/dev/null || true
    fi
    if [[ -n "${UI_PID}" ]] && kill -0 "${UI_PID}" 2>/dev/null; then
        kill "${UI_PID}" 2>/dev/null || true
        wait "${UI_PID}" 2>/dev/null || true
    fi
    if [[ -n "${API_PID}" ]] && kill -0 "${API_PID}" 2>/dev/null; then
        kill "${API_PID}" 2>/dev/null || true
        wait "${API_PID}" 2>/dev/null || true
    fi
    if [[ "${MANAGED_MAILDEV}" == true ]]; then
        "${PROJECT_DIR}/run-maildev.py" down --owner "${MAILDEV_OWNER}" || true
    fi
    if [[ "${MANAGED_DATABASE}" == true ]]; then
        echo "Stopping local PostgreSQL container (data remains in ${STACK_DB_VOLUME})"
        docker stop "${STACK_DB_CONTAINER}" >/dev/null 2>&1 || true
    fi
    python3 "${PROJECT_DIR}/tools/local_stack_control.py" _stopped "$$" || true
    exit "${exit_code}"
}
trap cleanup EXIT INT TERM

for command_name in curl psql; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
        echo "${command_name} is required to run the local stack." >&2
        exit 1
    fi
done

database_ready() {
    psql "${STACK_DATABASE_URL}" -v ON_ERROR_STOP=1 -Atc "SELECT 1" >/dev/null 2>&1
}

HTTP_PROBE_ERROR=""
http_ready() {
    # Readiness is a direct service check. User curl configuration or proxy
    # settings must not route a loopback/private endpoint through a proxy.
    if HTTP_PROBE_ERROR="$(curl -q --noproxy '*' --fail --silent --show-error \
        --max-time 2 "$1" --output /dev/null 2>&1)"; then
        HTTP_PROBE_ERROR=""
        return 0
    fi
    return 1
}

wait_for_database() {
    local attempt
    for attempt in $(seq 1 45); do
        if database_ready; then
            return 0
        fi
        sleep 1
    done
    echo "PostgreSQL did not become ready within 45 seconds." >&2
    return 1
}

wait_for_indexer() {
    local attempt
    local registered_count
    local worker_prefix
    local sql_worker_prefix
    worker_prefix="${STACK_INDEXER_WORKER_ID}-${INDEXER_PID}-"
    sql_worker_prefix="${worker_prefix//\'/\'\'}"
    for attempt in {1..60}; do
        if [[ -n "${INDEXER_PID}" ]] && ! kill -0 "${INDEXER_PID}" 2>/dev/null; then
            wait "${INDEXER_PID}" || true
            echo "The managed text-indexer stopped before becoming ready." >&2
            exit 1
        fi
        registered_count="$(psql "${STACK_DATABASE_URL}" -v ON_ERROR_STOP=1 -At \
            -c "SELECT count(*) FROM text_indexing_workers
                 WHERE active_until>=CURRENT_TIMESTAMP
                   AND worker_id LIKE '${sql_worker_prefix}%'" 2>/dev/null || true)"
        if [[ "${registered_count}" == "${STACK_INDEXER_PROCESS_COUNT}" ]]; then
            echo "Text indexer is ready (${STACK_INDEXER_PROCESS_COUNT} worker processes; base ID ${STACK_INDEXER_WORKER_ID})."
            return
        fi
        sleep 1
    done
    echo "Text indexer did not become ready within 60 seconds." >&2
    exit 1
}

wait_for_http() {
    local name="$1"
    local url="$2"
    local attempt
    for attempt in $(seq 1 60); do
        if http_ready "${url}"; then
            return 0
        fi
        if (( attempt == 1 || attempt % 10 == 0 )); then
            echo "Waiting for ${name}: ${HTTP_PROBE_ERROR:-HTTP readiness check failed}." >&2
        fi
        sleep 1
    done
    echo "${name} did not become ready at ${url} within 60 seconds." >&2
    echo "Last ${name} probe: ${HTTP_PROBE_ERROR:-HTTP readiness check failed}." >&2
    return 1
}

start_database() {
    if database_ready; then
        echo "Using PostgreSQL already available through DATABASE_URL."
        return
    fi

    readonly DEFAULT_LOCAL_URL="postgresql://postgres:postgres@127.0.0.1:${STACK_DB_PORT}/erms"
    if [[ "${STACK_DATABASE_URL}" != "${DEFAULT_LOCAL_URL}" ]]; then
        echo "DATABASE_URL is not reachable: ${STACK_DATABASE_URL}" >&2
        echo "Automatic PostgreSQL startup is limited to the default local-stack URL." >&2
        exit 1
    fi
    if ! command -v docker >/dev/null 2>&1; then
        echo "Docker is required only when the configured local PostgreSQL database is unavailable." >&2
        exit 1
    fi
    if ! docker info >/dev/null 2>&1; then
        echo "Docker is not running and PostgreSQL is not reachable." >&2
        exit 1
    fi

    if docker container inspect "${STACK_DB_CONTAINER}" >/dev/null 2>&1; then
        echo "Starting existing local PostgreSQL container."
        docker start "${STACK_DB_CONTAINER}" >/dev/null
    else
        echo "Creating local PostgreSQL container and persistent volume."
        docker run --detach \
            --name "${STACK_DB_CONTAINER}" \
            --env POSTGRES_USER=postgres \
            --env POSTGRES_PASSWORD=postgres \
            --env POSTGRES_DB=erms \
            --publish "127.0.0.1:${STACK_DB_PORT}:5432" \
            --volume "${STACK_DB_VOLUME}:/var/lib/postgresql/data" \
            --volume "${PROJECT_DIR}/database/schema.sql:/docker-entrypoint-initdb.d/001-schema.sql:ro" \
            --volume "${PROJECT_DIR}/database/seeds/000_required_reference_data.sql:/docker-entrypoint-initdb.d/002-reference-data.sql:ro" \
            --volume "${PROJECT_DIR}/database/baseline.sql:/docker-entrypoint-initdb.d/003-baseline.sql:ro" \
            "${STACK_DB_IMAGE}" >/dev/null
    fi
    MANAGED_DATABASE=true
    wait_for_database
}

export DATABASE_URL="${STACK_DATABASE_URL}"
export WEBUI_API_URL="${STACK_API_URL}"

start_database

# Read-only, per-target readiness before any affected service/worker starts or
# is reused. No import or private-file rewrite occurs on startup.
"${PROJECT_DIR}/backend/services/api/.venv/bin/python" \
    "${PROJECT_DIR}/tools/migrate_application_settings.py" --check \
    --database-url "${STACK_DATABASE_URL}" --source-env "${PROJECT_ENV_FILE}"

# All three workers use the current disposition schema. Check before starting
# any of them; never apply migrations automatically from a local launcher.
if [[ "$(psql "${STACK_DATABASE_URL}" -v ON_ERROR_STOP=1 -Atc \
    "SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE version='071_remove_destruction_release_gates')")" != t ]]; then
    echo "Apply pending database migrations through 071 before starting disposition workers." >&2
    exit 1
fi

python3 "${PROJECT_DIR}/tools/local_stack_preflight.py" \
    --api-url "${STACK_API_URL}" --api-host "${API_HOST:-0.0.0.0}" --api-port "${API_PORT:-8000}" \
    --ui-url "${STACK_UI_URL}" --ui-host "${WEBUI_HOST:-0.0.0.0}" --ui-port "${WEBUI_PORT:-8080}"

echo "Synchronizing missing Arabic translation drafts (existing translations remain unchanged)."
# Use the launcher's resolved target and the existing guarded seed workflow.
# This is local-launcher behavior only, not API startup or automatic publication.
PYTHONPATH="${PROJECT_DIR}" "${PROJECT_DIR}/backend/services/api/.venv/bin/python" \
    "${PROJECT_DIR}/database/seeds/004_seed_generated_arabic_ui_translations.py" --missing-only

echo "Starting or reusing local MailDev (implicit TLS and MCP)."
# The helper serializes ownership with startup. A reused instance retains its
# existing owner, so cleanup cannot stop a separately started/restarted service.
MANAGED_MAILDEV=true
"${PROJECT_DIR}/run-maildev.py" up --owner "${MAILDEV_OWNER}"

echo "Starting API-owned segmented-content cleanup worker."
PYTHONPATH="${PROJECT_DIR}" "${PROJECT_DIR}/backend/services/api/.venv/bin/python" -u \
    -m backend.services.api.content_cleanup --watch &
CONTENT_CLEANUP_PID=$!

echo "Starting API-owned login-session cleanup worker."
PYTHONPATH="${PROJECT_DIR}" "${PROJECT_DIR}/backend/services/api/.venv/bin/python" -u \
    -m backend.services.api.session_cleanup --watch &
SESSION_CLEANUP_PID=$!

if [[ "${STACK_INDEXING_MAINTENANCE_ENABLED}" == true ]]; then
    echo "Starting API-owned text-indexing maintenance worker."
    PYTHONPATH="${PROJECT_DIR}" "${PROJECT_DIR}/backend/services/api/.venv/bin/python" \
        -m backend.services.api.text_indexing_maintenance cleanup --watch &
    INDEXING_MAINTENANCE_PID=$!
else
    echo "Text-indexing maintenance is explicitly disabled (CONTENT_INDEXING_MAINTENANCE_ENABLED=${STACK_INDEXING_MAINTENANCE_ENABLED})."
fi

if http_ready "${STACK_API_URL}/health"; then
    echo "Using API already running at ${STACK_API_URL}."
else
    echo "Starting FastAPI service."
    "${PROJECT_DIR}/run-api.sh" &
    API_PID=$!
    wait_for_http "API" "${STACK_API_URL}/health"
fi

if [[ "${STACK_INDEXER_ENABLED}" == true ]]; then
    export TEXT_INDEXER_API_URL="${STACK_API_URL}"
    export TEXT_INDEXER_API_KEY
    export TEXT_INDEXER_WORKER_ID="${STACK_INDEXER_WORKER_ID}"
    export TEXT_INDEXER_PROCESS_COUNT="${STACK_INDEXER_PROCESS_COUNT}"
    if [[ -n "${TEXT_INDEXER_API_KEY:-}" ]]; then
        echo "Using the explicitly supplied text-indexer API key."
    else
        echo "Provisioning loopback-only text-indexer identity."
        PYTHONPATH="${PROJECT_DIR}" "${PROJECT_DIR}/backend/services/api/.venv/bin/python" \
            -m backend.services.api.provision_local_text_indexer \
            --api-url "${STACK_API_URL}" --secret-file "${STACK_INDEXER_SECRET_FILE}"
        TEXT_INDEXER_API_KEY="$(tr -d '\r\n' < "${STACK_INDEXER_SECRET_FILE}")"
    fi
    echo "Starting managed text-indexer."
    "${PROJECT_DIR}/run-text-indexer.sh" &
    INDEXER_PID=$!
    wait_for_indexer
else
    echo "Text indexer is explicitly disabled (TEXT_INDEXER_ENABLED=${STACK_INDEXER_ENABLED})."
fi

if http_ready "${STACK_UI_URL}"; then
    echo "Using web UI already running at ${STACK_UI_URL}."
else
    echo "Starting NiceGUI web frontend."
    "${PROJECT_DIR}/run-webui.sh" &
    UI_PID=$!
    wait_for_http "Web UI" "${STACK_UI_URL}"
fi

echo "Starting disposition eligibility, communications and destruction/completion workers."
PYTHONPATH="${PROJECT_DIR}" "${PROJECT_DIR}/backend/services/api/.venv/bin/python" -u \
    -m backend.services.api.disposition.eligibility --watch --batch-size 100 --interval-seconds 60 &
DISPOSITION_ELIGIBILITY_PID=$!
PYTHONPATH="${PROJECT_DIR}" "${PROJECT_DIR}/backend/services/api/.venv/bin/python" -u \
    -m backend.services.api.disposition.communications --watch --batch-size 100 --interval-seconds 30 &
DISPOSITION_COMMUNICATIONS_PID=$!
PYTHONPATH="${PROJECT_DIR}" "${PROJECT_DIR}/backend/services/api/.venv/bin/python" -u \
    -m backend.services.api.disposition.destruction_worker --watch --batch-size 1 --interval-seconds 5 &
DISPOSITION_DESTRUCTION_PID=$!

echo
echo "ERMS local stack is ready:"
echo "  Web UI:  ${STACK_UI_URL}"
echo "  API:     ${STACK_API_URL}"
echo "  API docs:${STACK_API_URL}/docs"
echo "  Disposition: eligibility, communications and destruction/completion workers are managed"
echo "  Content: segmented-content cleanup is running"
echo "  Sessions: login-session cleanup is running"
echo "  MailDev: mailbox/MCP URLs printed above; logs in .runtime/maildev/"
if [[ -n "${INDEXING_MAINTENANCE_PID}" ]]; then
    echo "  Cleanup: API-owned indexing/credential maintenance is running"
fi
echo "Press Ctrl-C to stop services started by this script."

python3 "${PROJECT_DIR}/tools/local_stack_control.py" _ready "$$" \
    --api-url "${STACK_API_URL}" --ui-url "${STACK_UI_URL}" \
    --process "api=${API_PID}" --process "webui=${UI_PID}" \
    --process "text-indexer=${INDEXER_PID}" --process "indexing-maintenance=${INDEXING_MAINTENANCE_PID}" \
    --process "content-cleanup=${CONTENT_CLEANUP_PID}" --process "session-cleanup=${SESSION_CLEANUP_PID}" \
    --process "disposition-eligibility=${DISPOSITION_ELIGIBILITY_PID}" \
    --process "disposition-communications=${DISPOSITION_COMMUNICATIONS_PID}" \
    --process "disposition-destruction=${DISPOSITION_DESTRUCTION_PID}"

while true; do
    if ! kill -0 "${SESSION_CLEANUP_PID}" 2>/dev/null; then
        wait "${SESSION_CLEANUP_PID}" || true
        echo "The managed login-session cleanup worker stopped unexpectedly." >&2
        exit 1
    fi
    if ! kill -0 "${CONTENT_CLEANUP_PID}" 2>/dev/null; then
        wait "${CONTENT_CLEANUP_PID}" || true
        echo "The managed segmented-content cleanup worker stopped unexpectedly." >&2
        exit 1
    fi
    for worker_pid in "${DISPOSITION_ELIGIBILITY_PID}" "${DISPOSITION_COMMUNICATIONS_PID}" "${DISPOSITION_DESTRUCTION_PID}"; do
        if ! kill -0 "${worker_pid}" 2>/dev/null; then
            wait "${worker_pid}" || true
            echo "A managed disposition worker stopped unexpectedly (PID ${worker_pid}); stopping the local stack." >&2
            exit 1
        fi
    done
    if [[ -n "${API_PID}" ]] && ! kill -0 "${API_PID}" 2>/dev/null; then
        wait "${API_PID}" || true
        echo "The API process stopped unexpectedly." >&2
        exit 1
    fi
    if [[ -n "${UI_PID}" ]] && ! kill -0 "${UI_PID}" 2>/dev/null; then
        wait "${UI_PID}" || true
        echo "The web UI process stopped unexpectedly." >&2
        exit 1
    fi
    if [[ -n "${INDEXER_PID}" ]] && ! kill -0 "${INDEXER_PID}" 2>/dev/null; then
        wait "${INDEXER_PID}" || true
        echo "The managed text-indexer stopped unexpectedly." >&2
        exit 1
    fi
    if [[ -n "${INDEXING_MAINTENANCE_PID}" ]] && ! kill -0 "${INDEXING_MAINTENANCE_PID}" 2>/dev/null; then
        wait "${INDEXING_MAINTENANCE_PID}" || true
        echo "The API-owned text-indexing maintenance worker stopped unexpectedly." >&2
        exit 1
    fi
    sleep 1
done
