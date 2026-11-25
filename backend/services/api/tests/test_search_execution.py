"""Interactive search must not leak execution settings to pooled connections."""
import os

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
import pytest

from backend.services.api.search_execution import global_ranking_io, search_sql_execution


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


def _ranking_io(connection):
    return connection.execute('SHOW effective_io_concurrency').fetchone()['effective_io_concurrency']


@pytest.mark.parametrize('previous', ['0', '16', '37'])
def test_ranking_restores_callers_transaction_local_value(previous):
    with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as connection, \
            psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as other:
        connection.execute('SET effective_io_concurrency=9')
        connection.commit()
        connection.execute("SELECT set_config('effective_io_concurrency', %s, true)", (previous,))
        other.execute('SET LOCAL effective_io_concurrency=31')
        with global_ranking_io(connection):
            assert _ranking_io(connection) == '0'
            with global_ranking_io(connection):
                assert _ranking_io(connection) == '0'
            assert _ranking_io(connection) == '0'
            assert _ranking_io(other) == '31'
        assert _ranking_io(connection) == previous
        with pytest.raises(ValueError, match='ranking failed'):
            with global_ranking_io(connection):
                raise ValueError('ranking failed')
        assert _ranking_io(connection) == previous
        connection.commit()
        assert _ranking_io(connection) == '9'


def test_failed_ranking_rolls_back_before_pool_reuse():
    with ConnectionPool(os.environ['DATABASE_URL'], min_size=1, max_size=1,
                        kwargs={'row_factory': dict_row}) as pool:
        with pool.connection() as c:
            c.execute('SET effective_io_concurrency=37')
            pid = c.info.backend_pid
        with pytest.raises(psycopg.errors.DivisionByZero):
            with pool.connection() as c, global_ranking_io(c):
                assert _ranking_io(c) == '0'
                c.execute('SELECT 1/0')
        with pool.connection() as c:
            assert c.info.backend_pid == pid
            assert _ranking_io(c) == '37'


def test_ranking_on_autocommit_connection_owns_its_transaction():
    with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row, autocommit=True) as c:
        c.execute('SET effective_io_concurrency=7')
        with global_ranking_io(c):
            assert _ranking_io(c) == '0'
        assert c.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
        assert _ranking_io(c) == '7'
