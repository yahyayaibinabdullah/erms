"""Current schema has no temporary switch; normal workflow guards stay active."""
from backend.services.api.tests.test_disposition_membership import db


def test_migrated_database_has_no_gate_functions_or_remaining_callers(client):
    with db() as connection:
        row = connection.execute("""SELECT
            to_regprocedure('disposition_private.physical_execution_released()') physical,
            to_regprocedure('disposition_private.digital_execution_released()') digital""").fetchone()
        assert row == {'physical': None, 'digital': None}
        assert not connection.execute("""SELECT p.proname FROM pg_proc p
            JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='disposition_private'
            AND p.prosrc ~ '(physical|digital)_execution_released'""").fetchall()
        assert connection.execute("SELECT 1 FROM schema_migrations WHERE version='071_remove_destruction_release_gates'").fetchone()
