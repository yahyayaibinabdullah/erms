#!/usr/bin/env bash
set -Eeuo pipefail

readonly DATABASE_URL="${1:?database URL is required}"
readonly CONTAINER_NAME="${2:?PostgreSQL container name is required}"
readonly ADMIN_URL="${DATABASE_URL%/*}/postgres"
readonly RESTORE_DB="erms_authorization_restore_test"
readonly RESTORE_URL="${DATABASE_URL%/*}/${RESTORE_DB}"
readonly DUMP_FILE="$(mktemp "${TMPDIR:-/tmp}/erms-auth-backup.dump.XXXXXX")"

cleanup() {
    rm -f "${DUMP_FILE}"
    psql "${ADMIN_URL}" --set ON_ERROR_STOP=on --command \
        "DROP DATABASE IF EXISTS ${RESTORE_DB} WITH (FORCE)" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker exec "${CONTAINER_NAME}" pg_dump \
    --username=erms_test --dbname=erms_test --format=plain --no-owner --no-privileges \
    >"${DUMP_FILE}"
# PostgreSQL 17 wraps plain dumps in client-side psql safety commands unknown to
# older clients. They do not affect the SQL payload or restored database state.
sed -i.bak '/^\\restrict /d; /^\\unrestrict /d' "${DUMP_FILE}"
rm -f "${DUMP_FILE}.bak"
psql "${ADMIN_URL}" --set ON_ERROR_STOP=on --command "DROP DATABASE IF EXISTS ${RESTORE_DB} WITH (FORCE)"
psql "${ADMIN_URL}" --set ON_ERROR_STOP=on --command "CREATE DATABASE ${RESTORE_DB}"
psql "${RESTORE_URL}" --set ON_ERROR_STOP=on --file="${DUMP_FILE}" >/dev/null

psql "${RESTORE_URL}" --set ON_ERROR_STOP=on <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname='current_user_can_view_record') THEN
        RAISE EXCEPTION 'authorization predicate missing after restore';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM privileges WHERE code='authorization.administer') THEN
        RAISE EXCEPTION 'privilege catalogue missing after restore';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM permissions WHERE code='record.view') THEN
        RAISE EXCEPTION 'permission catalogue missing after restore';
    END IF;
    IF EXISTS (
        SELECT 1 FROM event_history
        WHERE actor_type='user' AND (actor_name IS NULL OR actor_email IS NULL)
    ) THEN
        RAISE EXCEPTION 'audit actor snapshots incomplete after restore';
    END IF;
END;
$$;
SQL

# Automated seed events can have no email. Compare every actor snapshot
# with the source to detect a changed, lost or unexpectedly populated value.
audit_projection="SELECT md5(jsonb_agg(jsonb_build_array(id,actor_user_id,actor_type,actor_name,actor_email) ORDER BY id)::text) FROM event_history"
before_restore="$(psql "${DATABASE_URL}" --set ON_ERROR_STOP=on -Atc "${audit_projection}")"
after_restore="$(psql "${RESTORE_URL}" --set ON_ERROR_STOP=on -Atc "${audit_projection}")"
if [[ -z "${before_restore}" || "${before_restore}" != "${after_restore}" ]]; then
    echo "Audit actor snapshots differ from the source database" >&2
    exit 1
fi

echo "Authorization backup and restore exercise passed."
