"""079 upgrade and reconciliation, only in the runner's disposable database."""
import os
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
import pytest

from tools.canonical_schema import statements

ROOT = Path(__file__).resolve().parents[2]
VERSION = '079_disposition_admission_reason'
CLAIM_VERSION = '084_reasonless_task_claim'
FUNCTION = 'disposition_private.begin_command(uuid,text,jsonb,bigint,text)'


@pytest.fixture
def connection():
    dsn = os.environ['DATABASE_URL']
    assert conninfo_to_dict(dsn)['dbname'].startswith('erms_messaging_test_acl_'), 'Disposable runner required'
    with psycopg.connect(dsn, autocommit=True) as c, c.transaction(force_rollback=True):
        yield c


def apply(c, filename='079_disposition_admission_reason.sql'):
    body = statements((ROOT / 'database/migrations' / filename).read_text())
    assert body[0] == 'BEGIN' and body[-1] == 'COMMIT'
    # Execute the exact migration body in the fixture's rollback-only transaction.
    for statement in body[1:-1]:
        c.execute(statement, prepare=False)


def snapshot(c):
    function = c.execute('SELECT pg_get_functiondef(%s::regprocedure)', (FUNCTION,)).fetchone()[0]
    constraint = c.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='disposition_private.command_receipts'::regclass AND conname='command_receipts_reason_check'").fetchone()[0]
    return function, constraint


def allowed(c, operation, reason=''):
    expression = c.execute("SELECT pg_get_expr(conbin,conrelid) FROM pg_constraint WHERE conrelid='disposition_private.command_receipts'::regclass AND conname='command_receipts_reason_check'").fetchone()[0]
    return c.execute(sql.SQL('SELECT {} FROM (VALUES (%s::text,%s::text)) AS candidate(operation,reason)').format(sql.SQL(expression)), (operation, reason)).fetchone()[0]


def remove_marker(c, *versions):
    c.execute('DELETE FROM schema_migrations WHERE version=ANY(%s)', (list(versions),))


def old_contract(c):
    function = snapshot(c)[0]
    older = function.replace("('job_create','membership_add','task_claim')", "('not_a_real_operation')")
    assert older != function
    c.execute(older, prepare=False)
    c.execute('ALTER TABLE disposition_private.command_receipts DROP CONSTRAINT command_receipts_reason_check')
    c.execute("ALTER TABLE disposition_private.command_receipts ADD CONSTRAINT command_receipts_reason_check CHECK(btrim(reason)<>'')")


def test_fresh_baseline_already_records_079(connection):
    assert connection.execute('SELECT count(*) FROM schema_migrations WHERE version=%s', (VERSION,)).fetchone()[0] == 1


def test_upgrade_then_084_then_079_replay_preserves_reasonless_claim(connection):
    c = connection
    remove_marker(c, VERSION, CLAIM_VERSION)
    old_contract(c)
    assert not allowed(c, 'job_create')
    apply(c)
    assert allowed(c, 'job_create') and allowed(c, 'membership_add')
    assert not allowed(c, 'task_claim') and not allowed(c, 'review_submit')
    assert "p_operation NOT IN ('job_create','membership_add')" in snapshot(c)[0]
    apply(c, '084_reasonless_task_claim.sql')
    before = snapshot(c)
    marker = c.execute('SELECT id,applied_at FROM schema_migrations WHERE version=%s', (VERSION,)).fetchone()
    apply(c)
    assert snapshot(c) == before and allowed(c, 'task_claim')
    assert c.execute('SELECT id,applied_at FROM schema_migrations WHERE version=%s', (VERSION,)).fetchone() == marker


@pytest.mark.parametrize('later_marker', [True, False])
def test_reconciliation_preserves_newer_definitions_and_all_other_markers(connection, later_marker):
    c = connection
    remove_marker(c, VERSION)
    if not later_marker:
        remove_marker(c, CLAIM_VERSION)
    before = snapshot(c)
    history = c.execute('SELECT version,applied_at FROM schema_migrations ORDER BY version').fetchall()
    apply(c)
    assert snapshot(c) == before
    assert allowed(c, 'task_claim') and allowed(c, 'membership_add')
    assert not allowed(c, 'review_submit')
    assert c.execute('SELECT version,applied_at FROM schema_migrations WHERE version<>%s ORDER BY version', (VERSION,)).fetchall() == history
    apply(c)
    assert snapshot(c) == before
    assert c.execute('SELECT count(*) FROM schema_migrations WHERE version=%s', (VERSION,)).fetchone()[0] == 1


@pytest.mark.parametrize('drift', ['function', 'constraint', 'permissive_constraint'])
def test_reconciliation_refuses_drift_without_recording_success(connection, drift):
    c = connection
    remove_marker(c, VERSION)
    if drift == 'function':
        old_contract(c)
    else:
        c.execute('ALTER TABLE disposition_private.command_receipts DROP CONSTRAINT command_receipts_reason_check')
        expression = "operation IN ('job_create','membership_add') OR btrim(reason)<>''" if drift == 'constraint' else 'true'
        c.execute(sql.SQL('ALTER TABLE disposition_private.command_receipts ADD CONSTRAINT command_receipts_reason_check CHECK({})').format(sql.SQL(expression)))
    before = snapshot(c)
    with pytest.raises(psycopg.errors.RaiseException, match='079 reconciliation requires'), c.transaction():
        apply(c)
    assert snapshot(c) == before
    assert c.execute('SELECT count(*) FROM schema_migrations WHERE version=%s', (VERSION,)).fetchone()[0] == 0
