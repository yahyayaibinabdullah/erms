#!/usr/bin/env bash
set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly DATABASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly PROJECT_DIR="$(cd "${DATABASE_DIR}/.." && pwd)"
readonly API_DIR="${PROJECT_DIR}/backend/services/api"
readonly API_VENV="${ERMS_API_VENV:-${API_DIR}/.venv}"
readonly TEST_REQUIREMENTS="${API_DIR}/requirements-test.txt"
readonly TEST_DEPENDENCY_STAMP="${API_VENV}/.test-requirements-checksum"
readonly CONTAINER_NAME="erms-postgres-test-$$"
readonly POSTGRES_IMAGE="${POSTGRES_TEST_IMAGE:-postgres:18-alpine}"
readonly POSTGRES_USER="erms_test"
readonly POSTGRES_PASSWORD="erms_test_password"
readonly POSTGRES_DB="erms_test"
readonly LIFECYCLE_MIGRATION_DB="erms_lifecycle_migration_test_$$"
readonly HOLDS_MIGRATION_DB="erms_holds_migration_test_$$"
readonly ADVANCED_SEARCH_MIGRATION_DB="erms_advanced_search_migration_test_$$"
readonly I18N_MIGRATION_DB="erms_i18n_migration_test_$$"
readonly I18N_CATALOGUE_MIGRATION_DB="erms_i18n_catalogue_migration_test_$$"
readonly I18N_ENTITY_MIGRATION_DB="erms_i18n_entity_migration_test_$$"
readonly I18N_HARDENING_MIGRATION_DB="erms_i18n_hardening_migration_test_$$"
readonly HISTORICAL_SCHEMA="$(mktemp "${TMPDIR:-/tmp}/erms-historical-schema.XXXXXX.sql")"
readonly PRE_HOLDS_SCHEMA="$(mktemp "${TMPDIR:-/tmp}/erms-pre-holds-schema.XXXXXX.sql")"
readonly PRE_ADVANCED_SEARCH_SCHEMA="$(mktemp "${TMPDIR:-/tmp}/erms-pre-advanced-search-schema.XXXXXX.sql")"
readonly PRE_I18N_SCHEMA="$(mktemp "${TMPDIR:-/tmp}/erms-pre-i18n-schema.XXXXXX.sql")"
readonly PRE_I18N_CATALOGUE_SCHEMA="$(mktemp "${TMPDIR:-/tmp}/erms-pre-i18n-catalogue-schema.XXXXXX.sql")"
readonly PRE_I18N_ENTITY_SCHEMA="$(mktemp "${TMPDIR:-/tmp}/erms-pre-i18n-entity-schema.XXXXXX.sql")"
readonly PRE_I18N_HARDENING_SCHEMA="$(mktemp "${TMPDIR:-/tmp}/erms-pre-i18n-hardening-schema.XXXXXX.sql")"
LIFECYCLE_MIGRATION_DB_CREATED=false
HOLDS_MIGRATION_DB_CREATED=false
ADVANCED_SEARCH_MIGRATION_DB_CREATED=false
I18N_MIGRATION_DB_CREATED=false
I18N_CATALOGUE_MIGRATION_DB_CREATED=false
I18N_ENTITY_MIGRATION_DB_CREATED=false
I18N_HARDENING_MIGRATION_DB_CREATED=false

cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM
    if [[ "${LIFECYCLE_MIGRATION_DB_CREATED}" == true ]]; then
        if ! docker exec "${CONTAINER_NAME}" dropdb --force --if-exists \
            --username "${POSTGRES_USER}" "${LIFECYCLE_MIGRATION_DB}" >/dev/null; then
            echo "Failed to drop disposable database ${LIFECYCLE_MIGRATION_DB}" >&2
            exit_code=1
        fi
    fi
    if [[ "${HOLDS_MIGRATION_DB_CREATED}" == true ]]; then
        if ! docker exec "${CONTAINER_NAME}" dropdb --force --if-exists \
            --username "${POSTGRES_USER}" "${HOLDS_MIGRATION_DB}" >/dev/null; then
            echo "Failed to drop disposable database ${HOLDS_MIGRATION_DB}" >&2
            exit_code=1
        fi
    fi
    if [[ "${ADVANCED_SEARCH_MIGRATION_DB_CREATED}" == true ]]; then
        if ! docker exec "${CONTAINER_NAME}" dropdb --force --if-exists \
            --username "${POSTGRES_USER}" "${ADVANCED_SEARCH_MIGRATION_DB}" >/dev/null; then
            echo "Failed to drop disposable database ${ADVANCED_SEARCH_MIGRATION_DB}" >&2
            exit_code=1
        fi
    fi
    if [[ "${I18N_MIGRATION_DB_CREATED}" == true ]]; then
        if ! docker exec "${CONTAINER_NAME}" dropdb --force --if-exists \
            --username "${POSTGRES_USER}" "${I18N_MIGRATION_DB}" >/dev/null; then
            echo "Failed to drop disposable database ${I18N_MIGRATION_DB}" >&2
            exit_code=1
        fi
    fi
    if [[ "${I18N_CATALOGUE_MIGRATION_DB_CREATED}" == true ]]; then
        if ! docker exec "${CONTAINER_NAME}" dropdb --force --if-exists --username "${POSTGRES_USER}" "${I18N_CATALOGUE_MIGRATION_DB}" >/dev/null; then
            echo "Failed to drop disposable database ${I18N_CATALOGUE_MIGRATION_DB}" >&2; exit_code=1
        fi
    fi
    if [[ "${I18N_ENTITY_MIGRATION_DB_CREATED}" == true ]]; then
        if ! docker exec "${CONTAINER_NAME}" dropdb --force --if-exists --username "${POSTGRES_USER}" "${I18N_ENTITY_MIGRATION_DB}" >/dev/null; then
            echo "Failed to drop disposable database ${I18N_ENTITY_MIGRATION_DB}" >&2; exit_code=1
        fi
    fi
    if [[ "${I18N_HARDENING_MIGRATION_DB_CREATED}" == true ]]; then
        if ! docker exec "${CONTAINER_NAME}" dropdb --force --if-exists --username "${POSTGRES_USER}" "${I18N_HARDENING_MIGRATION_DB}" >/dev/null; then
            echo "Failed to drop disposable database ${I18N_HARDENING_MIGRATION_DB}" >&2; exit_code=1
        fi
    fi
    rm -f "${HISTORICAL_SCHEMA}" "${PRE_HOLDS_SCHEMA}" "${PRE_ADVANCED_SEARCH_SCHEMA}" "${PRE_I18N_SCHEMA}" "${PRE_I18N_CATALOGUE_SCHEMA}" "${PRE_I18N_ENTITY_SCHEMA}" "${PRE_I18N_HARDENING_SCHEMA}"
    docker rm --force "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    exit "${exit_code}"
}
trap cleanup EXIT INT TERM

if [[ ! -x "${API_VENV}/bin/python" ]]; then
    python3 -m venv "${API_VENV}"
fi

readonly CURRENT_TEST_CHECKSUM="$(cksum "${API_DIR}/requirements.txt" "${TEST_REQUIREMENTS}")"
INSTALLED_TEST_CHECKSUM=""
if [[ -f "${TEST_DEPENDENCY_STAMP}" ]]; then
    INSTALLED_TEST_CHECKSUM="$(<"${TEST_DEPENDENCY_STAMP}")"
fi

if [[ "${CURRENT_TEST_CHECKSUM}" != "${INSTALLED_TEST_CHECKSUM}" ]]; then
    "${API_VENV}/bin/python" -m pip install --disable-pip-version-check \
        --requirement "${TEST_REQUIREMENTS}"
    printf '%s\n' "${CURRENT_TEST_CHECKSUM}" >"${TEST_DEPENDENCY_STAMP}"
fi

docker run \
    --detach \
    --rm \
    --name "${CONTAINER_NAME}" \
    --tmpfs /var/lib/postgresql:rw,noexec,nosuid,size=1g \
    --env POSTGRES_USER="${POSTGRES_USER}" \
    --env POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
    --env POSTGRES_DB="${POSTGRES_DB}" \
    --publish 127.0.0.1::5432 \
    "${POSTGRES_IMAGE}" >/dev/null

for attempt in $(seq 1 30); do
    if docker exec "${CONTAINER_NAME}" \
        pg_isready --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" >/dev/null 2>&1; then
        break
    fi

    if [[ "${attempt}" -eq 30 ]]; then
        docker logs "${CONTAINER_NAME}"
        echo "PostgreSQL did not become ready in time" >&2
        exit 1
    fi

    sleep 1
done

readonly HOST_PORT="$(docker port "${CONTAINER_NAME}" 5432/tcp | sed 's/.*://')"
readonly DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${HOST_PORT}/${POSTGRES_DB}"
readonly LIFECYCLE_MIGRATION_DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${HOST_PORT}/${LIFECYCLE_MIGRATION_DB}"
readonly HOLDS_MIGRATION_DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${HOST_PORT}/${HOLDS_MIGRATION_DB}"
readonly ADVANCED_SEARCH_MIGRATION_DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${HOST_PORT}/${ADVANCED_SEARCH_MIGRATION_DB}"
readonly I18N_MIGRATION_DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${HOST_PORT}/${I18N_MIGRATION_DB}"
readonly I18N_CATALOGUE_MIGRATION_DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${HOST_PORT}/${I18N_CATALOGUE_MIGRATION_DB}"
readonly I18N_ENTITY_MIGRATION_DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${HOST_PORT}/${I18N_ENTITY_MIGRATION_DB}"
readonly I18N_HARDENING_MIGRATION_DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${HOST_PORT}/${I18N_HARDENING_MIGRATION_DB}"

docker exec "${CONTAINER_NAME}" createdb \
    --username "${POSTGRES_USER}" "${LIFECYCLE_MIGRATION_DB}"
LIFECYCLE_MIGRATION_DB_CREATED=true
psql "${LIFECYCLE_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on \
    --file "${SCRIPT_DIR}/lifecycle_migration_before.sql"
psql "${LIFECYCLE_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on \
    --file "${DATABASE_DIR}/migrations/004_normalize_user_management_lifecycle.sql"
psql "${LIFECYCLE_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on \
    --file "${SCRIPT_DIR}/lifecycle_migration_after.sql"
docker exec "${CONTAINER_NAME}" dropdb --force \
    --username "${POSTGRES_USER}" "${LIFECYCLE_MIGRATION_DB}"
LIFECYCLE_MIGRATION_DB_CREATED=false

PYTHONPATH="${PROJECT_DIR}" "${API_VENV}/bin/python" -c 'from tools.historical_schema import historical_schema; print(historical_schema(), end="")' >"${HISTORICAL_SCHEMA}"

awk '
    /^-- Legal holds: persistence and non-bypassable policy enforcement\.$/ { skipping=1; next }
    skipping && /^COMMIT;$/ { skipping=0; next }
    !skipping { print }
' "${HISTORICAL_SCHEMA}" >"${PRE_HOLDS_SCHEMA}"
docker exec "${CONTAINER_NAME}" createdb \
    --username "${POSTGRES_USER}" "${HOLDS_MIGRATION_DB}"
HOLDS_MIGRATION_DB_CREATED=true
psql "${HOLDS_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on --file "${PRE_HOLDS_SCHEMA}"
psql "${HOLDS_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on --command \
    "INSERT INTO users(name,email) VALUES ('Pre-holds user','pre-holds@test.invalid')"
psql "${HOLDS_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on \
    --file "${DATABASE_DIR}/migrations/005_add_legal_holds_foundation.sql"
psql "${HOLDS_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on \
    --file "${DATABASE_DIR}/migrations/006_correct_legal_hold_authorization.sql"
psql "${HOLDS_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on \
    --file "${DATABASE_DIR}/migrations/007_add_global_hold_membership_management.sql"
psql "${HOLDS_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on \
    --file "${DATABASE_DIR}/migrations/008_rename_hold_membership_to_held_items.sql"
psql "${HOLDS_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on \
    --file "${DATABASE_DIR}/migrations/009_preserve_relationship_truth_for_search.sql"
psql "${HOLDS_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on --command \
    "DO \$\$ BEGIN IF (SELECT count(*) FROM users WHERE email='pre-holds@test.invalid')<>1 OR to_regclass('public.holds') IS NULL OR NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version='005_add_legal_holds_foundation') OR NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version='006_correct_legal_hold_authorization') OR NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version='007_add_global_hold_membership_management') OR NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version='008_rename_hold_membership_to_held_items') OR NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version='009_preserve_relationship_truth_for_search') OR NOT EXISTS(SELECT 1 FROM privileges WHERE code='holds.held_items.manage_all') THEN RAISE EXCEPTION 'migration verification failed'; END IF; END \$\$"
docker exec "${CONTAINER_NAME}" dropdb --force \
    --username "${POSTGRES_USER}" "${HOLDS_MIGRATION_DB}"
HOLDS_MIGRATION_DB_CREATED=false

awk '
    /^-- Advanced Search Phase 1 begins\.$/ { skipping=1; next }
    skipping && /^COMMIT;$/ { print; skipping=0; next }
    !skipping { print }
' "${HISTORICAL_SCHEMA}" >"${PRE_ADVANCED_SEARCH_SCHEMA}"
docker exec "${CONTAINER_NAME}" createdb \
    --username "${POSTGRES_USER}" "${ADVANCED_SEARCH_MIGRATION_DB}"
ADVANCED_SEARCH_MIGRATION_DB_CREATED=true
psql "${ADVANCED_SEARCH_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on \
    --file "${PRE_ADVANCED_SEARCH_SCHEMA}"
psql "${ADVANCED_SEARCH_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on \
    --file "${DATABASE_DIR}/migrations/018_add_advanced_search_phase1.sql"
psql "${ADVANCED_SEARCH_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on \
    --file "${DATABASE_DIR}/migrations/030_rename_saved_search_admin_privilege.sql"
psql "${ADVANCED_SEARCH_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on --command \
    "DO \$\$ BEGIN IF to_regclass('public.saved_searches') IS NULL OR to_regclass('public.saved_search_role_grants') IS NULL OR to_regclass('public.saved_search_org_unit_grants') IS NULL OR NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version='018_add_advanced_search_phase1') OR NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version='030_rename_saved_search_admin_privilege') OR NOT EXISTS(SELECT 1 FROM privileges WHERE code='search.saved_search.administer') OR EXISTS(SELECT 1 FROM privileges WHERE code='search.saved_search.administrator') OR (SELECT count(*) FROM profiles profile JOIN profile_privileges membership ON membership.profile_id=profile.id JOIN privileges privilege ON privilege.id=membership.privilege_id WHERE profile.code IN ('INFO_GOV_MGR','INFO_GOV_OFFICER') AND privilege.code IN ('search.saved_search.administer','search.saved_search.delete'))<>4 THEN RAISE EXCEPTION 'advanced-search migration verification failed'; END IF; END \$\$"
docker exec "${CONTAINER_NAME}" dropdb --force \
    --username "${POSTGRES_USER}" "${ADVANCED_SEARCH_MIGRATION_DB}"
ADVANCED_SEARCH_MIGRATION_DB_CREATED=false

awk '
    /^-- Internationalization and user preferences Phase 1 begins\.$/ { skipping=1; next }
    skipping && /^COMMIT;$/ { print; skipping=0; next }
    !skipping { print }
' "${HISTORICAL_SCHEMA}" >"${PRE_I18N_SCHEMA}"
docker exec "${CONTAINER_NAME}" createdb --username "${POSTGRES_USER}" "${I18N_MIGRATION_DB}"
I18N_MIGRATION_DB_CREATED=true
psql "${I18N_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on --file "${PRE_I18N_SCHEMA}"
psql "${I18N_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on --file "${DATABASE_DIR}/migrations/019_add_internationalization_foundation.sql"
psql "${I18N_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on --command \
    "DO \$\$ BEGIN IF to_regclass('public.supported_languages') IS NULL OR to_regclass('public.user_preferences') IS NULL OR NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version='019_add_internationalization_foundation') OR NOT EXISTS(SELECT 1 FROM privileges WHERE code='localization.administer' AND is_reserved) OR (SELECT count(*) FROM supported_languages WHERE language_tag IN ('en','ar'))<>2 THEN RAISE EXCEPTION 'internationalization migration verification failed'; END IF; END \$\$"
docker exec "${CONTAINER_NAME}" dropdb --force --username "${POSTGRES_USER}" "${I18N_MIGRATION_DB}"
I18N_MIGRATION_DB_CREATED=false

awk '
    /^-- Internationalization Phase 2 message catalogue begins\.$/ { skipping=1; next }
    skipping && /^COMMIT;$/ { print; skipping=0; next }
    !skipping { print }
' "${HISTORICAL_SCHEMA}" >"${PRE_I18N_CATALOGUE_SCHEMA}"
docker exec "${CONTAINER_NAME}" createdb --username "${POSTGRES_USER}" "${I18N_CATALOGUE_MIGRATION_DB}"
I18N_CATALOGUE_MIGRATION_DB_CREATED=true
psql "${I18N_CATALOGUE_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on --file "${PRE_I18N_CATALOGUE_SCHEMA}"
psql "${I18N_CATALOGUE_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on --file "${DATABASE_DIR}/migrations/020_add_ui_message_catalogue.sql"
psql "${I18N_CATALOGUE_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on --command \
    "DO \$\$ BEGIN IF to_regclass('public.ui_message_definitions') IS NULL OR to_regclass('public.ui_message_translations') IS NULL OR NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version='020_add_ui_message_catalogue') THEN RAISE EXCEPTION 'internationalization catalogue migration verification failed'; END IF; END \$\$"
docker exec "${CONTAINER_NAME}" dropdb --force --username "${POSTGRES_USER}" "${I18N_CATALOGUE_MIGRATION_DB}"
I18N_CATALOGUE_MIGRATION_DB_CREATED=false

awk '
    /^-- Internationalization Phase 4 multilingual entity metadata begins\.$/ { skipping=1; next }
    skipping && /^COMMIT;$/ { print; skipping=0; next }
    !skipping { print }
' "${HISTORICAL_SCHEMA}" >"${PRE_I18N_ENTITY_SCHEMA}"
docker exec "${CONTAINER_NAME}" createdb --username "${POSTGRES_USER}" "${I18N_ENTITY_MIGRATION_DB}"
I18N_ENTITY_MIGRATION_DB_CREATED=true
psql "${I18N_ENTITY_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on --file "${PRE_I18N_ENTITY_SCHEMA}"
psql "${I18N_ENTITY_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on --file "${DATABASE_DIR}/migrations/021_add_multilingual_entity_metadata.sql"
psql "${I18N_ENTITY_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on --command \
    "DO \$\$ BEGIN IF NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version='021_add_multilingual_entity_metadata') OR EXISTS(SELECT 1 FROM (VALUES ('classification_schemes'),('classifications'),('users'),('roles'),('org_units'),('security_levels')) expected(table_name) WHERE NOT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND information_schema.columns.table_name=expected.table_name AND column_name='translations')) THEN RAISE EXCEPTION 'multilingual entity migration verification failed'; END IF; END \$\$"
docker exec "${CONTAINER_NAME}" dropdb --force --username "${POSTGRES_USER}" "${I18N_ENTITY_MIGRATION_DB}"
I18N_ENTITY_MIGRATION_DB_CREATED=false

awk '
    /^-- Internationalization Phase 5 search and hardening begins\.$/ { skipping=1; next }
    skipping && /^COMMIT;$/ { print; skipping=0; next }
    !skipping { print }
' "${HISTORICAL_SCHEMA}" >"${PRE_I18N_HARDENING_SCHEMA}"
docker exec "${CONTAINER_NAME}" createdb --username "${POSTGRES_USER}" "${I18N_HARDENING_MIGRATION_DB}"
I18N_HARDENING_MIGRATION_DB_CREATED=true
psql "${I18N_HARDENING_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on --file "${PRE_I18N_HARDENING_SCHEMA}"
psql "${I18N_HARDENING_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on --file "${DATABASE_DIR}/migrations/022_harden_internationalized_search.sql"
psql "${I18N_HARDENING_MIGRATION_DATABASE_URL}" --set ON_ERROR_STOP=on --command \
    "DO \$\$ BEGIN IF NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version='022_harden_internationalized_search') OR to_regclass('public.users_translation_text_trgm_idx') IS NULL OR NOT EXISTS(SELECT 1 FROM pg_extension WHERE extname='pg_trgm') THEN RAISE EXCEPTION 'internationalization hardening migration verification failed'; END IF; END \$\$"
docker exec "${CONTAINER_NAME}" dropdb --force --username "${POSTGRES_USER}" "${I18N_HARDENING_MIGRATION_DB}"
I18N_HARDENING_MIGRATION_DB_CREATED=false

psql "${DATABASE_URL}" --set ON_ERROR_STOP=on --file "${DATABASE_DIR}/schema.sql" \
    --file "${DATABASE_DIR}/seeds/000_required_reference_data.sql" \
    --file "${DATABASE_DIR}/baseline.sql"
psql "${DATABASE_URL}" --set ON_ERROR_STOP=on \
    --file "${DATABASE_DIR}/migrations/031_allow_governed_security_changes_on_closed_resources.sql"
psql "${DATABASE_URL}" --set ON_ERROR_STOP=on --command \
    "DO \$\$ BEGIN IF NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version='031_allow_governed_security_changes_on_closed_resources') THEN RAISE EXCEPTION 'security-level closed-resource migration verification failed'; END IF; END \$\$"
"${SCRIPT_DIR}/check_security_schema_parity.sh" "${DATABASE_URL}" "${DATABASE_DIR}/schema.sql"
psql "${DATABASE_URL}" --set ON_ERROR_STOP=on \
    --file "${SCRIPT_DIR}/organizational_ownership_invariants.sql"
psql "${DATABASE_URL}" --set ON_ERROR_STOP=on \
    --file "${SCRIPT_DIR}/full_text_search_phase1.sql"
psql "${DATABASE_URL}" --set ON_ERROR_STOP=on --file "${SCRIPT_DIR}/core_records_management.sql"
psql "${DATABASE_URL}" --set ON_ERROR_STOP=on --file "${SCRIPT_DIR}/legal_holds.sql"
psql "${DATABASE_URL}" --set ON_ERROR_STOP=on --file "${SCRIPT_DIR}/event_history.sql"
psql "${DATABASE_URL}" --set ON_ERROR_STOP=on --file "${SCRIPT_DIR}/user_management.sql"
psql "${DATABASE_URL}" --set ON_ERROR_STOP=on --file "${SCRIPT_DIR}/content_storage_and_concurrency.sql"
env DATABASE_URL="${DATABASE_URL}" DEFAULT_WORKING_TIMEZONE="Asia/Dubai" \
    TEXT_INDEXER_CREDENTIAL_HISTORY_RETENTION_DAYS="365" PYTHONPATH="${PROJECT_DIR}" \
    "${API_VENV}/bin/python" -m pytest "${API_DIR}/tests"
"${SCRIPT_DIR}/backup_restore_authorization.sh" "${DATABASE_URL}" "${CONTAINER_NAME}"

"${API_VENV}/bin/python" "${DATABASE_DIR}/seeds/import_mutamathilah.py" \
    --database-url "${DATABASE_URL}"
psql "${DATABASE_URL}" --set ON_ERROR_STOP=on <<'SQL'
DO $$
DECLARE
    scheme_id bigint;
    correlation_count integer;
BEGIN
    SELECT id INTO STRICT scheme_id
      FROM classification_schemes
     WHERE code = 'USCR-SHJ'
       AND title = 'النظام الموحد للوثائق المتماثلة لإمارة الشارقة'
       AND description = 'Unified Scheme for Common Records of the Emirate of Sharjah'
       AND date_published IS NULL;

    IF (SELECT count(*) FROM classifications WHERE classification_scheme_id=scheme_id) <> 345 THEN
        RAISE EXCEPTION 'Mutamathilah import classification count mismatch';
    END IF;
    IF (SELECT count(*) FROM classifications WHERE classification_scheme_id=scheme_id AND is_terminal) <> 254 THEN
        RAISE EXCEPTION 'Mutamathilah import terminal count mismatch';
    END IF;
    IF EXISTS (
        SELECT 1 FROM classifications
        WHERE classification_scheme_id=scheme_id
          AND (description IS NULL OR btrim(description) = '')
    ) THEN
        RAISE EXCEPTION 'Mutamathilah English description mapping is incomplete';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM classifications
        WHERE classification_scheme_id=scheme_id
          AND code = '1000'
          AND title = 'التنظيم العام للجهة'
          AND description = 'General Organization of the Entity'
    ) THEN
        RAISE EXCEPTION 'Mutamathilah Arabic title and English description mapping is incorrect';
    END IF;
    SELECT count(DISTINCT correlation_id) INTO correlation_count
      FROM event_history
     WHERE metadata->>'seed' = '025_seed_mutamathilah_classification_scheme';
    IF correlation_count <> 1 THEN
        RAISE EXCEPTION 'Mutamathilah events do not share one correlation id';
    END IF;
    IF (
        SELECT count(*) FROM event_history
        WHERE metadata->>'seed' = '025_seed_mutamathilah_classification_scheme'
          AND source = 'seeding'
          AND actor_type = 'automated_process'
    ) <> 600 THEN
        RAISE EXCEPTION 'Mutamathilah audit provenance count mismatch';
    END IF;
END;
$$;
SQL
"${API_VENV}/bin/python" "${DATABASE_DIR}/seeds/import_mutamathilah.py" \
    --database-url "${DATABASE_URL}"

echo "Core records management database and API tests passed."
