#!/usr/bin/env bash
set -Eeuo pipefail

readonly DATABASE_URL="$1"
readonly SCHEMA_FILE="$2"
readonly CLEAN_DATABASE="erms_security_schema_clean_$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
readonly CLEAN_URL="${DATABASE_URL%/*}/${CLEAN_DATABASE}"
readonly TEMPORARY_DIRECTORY="$(mktemp -d)"

cleanup_parity() {
    local status=$?
    if ! dropdb --if-exists --force --maintenance-db="${DATABASE_URL}" "${CLEAN_DATABASE}" >/dev/null; then
        echo "Failed to drop disposable database ${CLEAN_DATABASE}" >&2
        status=1
    fi
    rm -rf "${TEMPORARY_DIRECTORY}"
    exit "${status}"
}
trap cleanup_parity EXIT

createdb --maintenance-db="${DATABASE_URL}" "${CLEAN_DATABASE}"
psql "${CLEAN_URL}" --set ON_ERROR_STOP=on --file "${SCHEMA_FILE}" >/dev/null

read -r -d '' SIGNATURE_SQL <<'SQL' || true
SELECT 'column|' || table_name || '|' ||
       column_name || '|' ||
       data_type || '|' || is_nullable
FROM information_schema.columns
WHERE table_schema='public'
  AND (table_name IN (
       'security_levels','privileges','profiles','profile_privileges','privilege_dependencies',
       'organizational_ownership_assignment_runs','organizational_ownership_root_assignments'
  ) OR (
       table_name IN ('aggregations','records','roles','record_drafts')
       AND column_name IN ('security_level_id','profile_id','is_information_governance','owning_org_unit_id')))
UNION ALL
SELECT 'constraint|' || c.relname || '|' || con.conname || '|' || pg_get_constraintdef(con.oid, true)
FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid
JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public'
  AND c.relname IN ('security_levels','privileges','profiles','profile_privileges','privilege_dependencies','aggregations','records','roles','record_drafts','organizational_ownership_assignment_runs','organizational_ownership_root_assignments')
  AND (c.relname IN ('security_levels','privileges','profiles','profile_privileges','privilege_dependencies','organizational_ownership_assignment_runs','organizational_ownership_root_assignments')
       OR con.conname LIKE '%security_level%' OR con.conname LIKE '%profile%'
       OR con.conname LIKE '%owning_org_unit%')
UNION ALL
SELECT 'index|' || tablename || '|' || indexname || '|' || indexdef
FROM pg_indexes
WHERE schemaname='public'
  AND tablename IN ('security_levels','privileges','profiles','profile_privileges','privilege_dependencies','aggregations','records','roles','record_drafts','organizational_ownership_assignment_runs','organizational_ownership_root_assignments')
  AND (tablename IN ('security_levels','privileges','profiles','profile_privileges','privilege_dependencies','organizational_ownership_assignment_runs','organizational_ownership_root_assignments')
       OR indexname LIKE '%security_level%' OR indexname LIKE '%profile%' OR indexname LIKE '%governance%'
       OR indexname LIKE '%owner_%_number_browse%')
UNION ALL
SELECT 'view|organizational_ownership_diagnostics|' || pg_get_viewdef('organizational_ownership_diagnostics'::regclass, true)
WHERE to_regclass('public.organizational_ownership_diagnostics') IS NOT NULL
UNION ALL
SELECT 'trigger|' || c.relname || '|' || t.tgname || '|' || pg_get_triggerdef(t.oid, true)
FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE NOT t.tgisinternal AND n.nspname='public'
  AND c.relname IN ('security_levels','privileges','profiles','profile_privileges','aggregations','records','roles')
  AND (c.relname IN ('security_levels','privileges','profiles','profile_privileges')
       OR t.tgname LIKE '%security_level%' OR t.tgname LIKE '%profile%'
       OR t.tgname LIKE '%ownership%')
UNION ALL
SELECT 'function|' || p.proname || '|' || regexp_replace(pg_get_functiondef(p.oid), E'\\s+', ' ', 'g')
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='public'
  AND p.proname IN (
      'default_role_profile','touch_authorization_catalogue',
      'event_reference_identity','event_state_reference_snapshots',
      'enforce_aggregation_ownership','propagate_aggregation_ownership',
      'enforce_record_ownership'
  )
ORDER BY 1;
SQL

psql "${DATABASE_URL}" -At --set ON_ERROR_STOP=on --command "${SIGNATURE_SQL}" \
    >"${TEMPORARY_DIRECTORY}/upgraded.txt"
psql "${CLEAN_URL}" -At --set ON_ERROR_STOP=on --command "${SIGNATURE_SQL}" \
    >"${TEMPORARY_DIRECTORY}/clean.txt"
diff -u "${TEMPORARY_DIRECTORY}/upgraded.txt" "${TEMPORARY_DIRECTORY}/clean.txt"
echo "Security schema parity check passed."
