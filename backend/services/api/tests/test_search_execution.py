"""Interactive search must not leak execution settings to pooled connections."""
import os

import psycopg
from psycopg.rows import dict_row
import pytest

from backend.services.api.search_execution import search_sql_execution


@pytest.mark.parametrize('original', ['on', 'off'])
@pytest.mark.parametrize('memory', ['64kB', '4MB', '32MB'])
@pytest.mark.parametrize('raise_error', [False, True])
def test_search_settings_are_restored_after_success_or_python_error(original, memory, raise_error):
    with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as connection:
        connection.execute("SELECT set_config('jit',%s,false)", (original,))
        connection.execute("SELECT set_config('work_mem',%s,false)", (memory,))
        connection.commit()
        try:
            with search_sql_execution(connection):
                assert connection.execute('SHOW jit').fetchone()['jit'] == 'off'
                assert connection.execute('SHOW work_mem').fetchone()['work_mem'] == memory
                if raise_error:
                    raise ValueError('Search validation failed')
        except ValueError:
            assert raise_error
        assert connection.execute('SHOW jit').fetchone()['jit'] == original
        assert connection.execute('SHOW work_mem').fetchone()['work_mem'] == memory
        connection.commit()
        assert connection.execute('SHOW jit').fetchone()['jit'] == original
        assert connection.execute('SHOW work_mem').fetchone()['work_mem'] == memory


def test_sql_error_is_not_hidden_and_rollback_restores_settings():
    with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as connection:
        connection.execute('SET jit=on')
        connection.execute("SET work_mem='4MB'")
        connection.commit()
        with pytest.raises(psycopg.errors.DivisionByZero):
            with search_sql_execution(connection):
                connection.execute('SELECT 1/0')
        connection.rollback()
        assert connection.execute('SHOW jit').fetchone()['jit'] == 'on'
        assert connection.execute('SHOW work_mem').fetchone()['work_mem'] == '4MB'


def test_nested_search_settings_are_local_to_the_connection_and_transaction():
    with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as connection, \
            psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as other:
        for c in (connection, other):
            c.execute("SET jit=on; SET work_mem='4MB'")
            c.commit()
        with search_sql_execution(connection):
            with search_sql_execution(connection):
                assert connection.execute('SHOW work_mem').fetchone()['work_mem'] == '4MB'
            assert connection.execute('SHOW work_mem').fetchone()['work_mem'] == '4MB'
            assert other.execute('SHOW work_mem').fetchone()['work_mem'] == '4MB'
            assert other.execute('SHOW jit').fetchone()['jit'] == 'on'
        assert connection.execute('SHOW work_mem').fetchone()['work_mem'] == '4MB'
        assert connection.execute('SHOW jit').fetchone()['jit'] == 'on'
        with search_sql_execution(connection):
            connection.commit()  # SET LOCAL must also end at transaction completion.
        assert connection.execute('SHOW work_mem').fetchone()['work_mem'] == '4MB'
        assert connection.execute('SHOW jit').fetchone()['jit'] == 'on'
