"""Execution settings scoped to interactive search SQL, never server defaults."""
from contextlib import contextmanager, nullcontext
from functools import wraps

from psycopg.pq import TransactionStatus

GLOBAL_RANKING_IO_CONCURRENCY = 0


@contextmanager
def global_ranking_io(connection, concurrency=GLOBAL_RANKING_IO_CONCURRENCY):
    """Use synchronous reads for the Global Search ranking SELECT.

    The worker-based read path produced repeatable latency spikes on
    PostgreSQL 18.4. See docs/search-performance.md#global-search-ranking-io.
    The disposable benchmark can supply another value for paired comparisons.
    """
    needs_transaction = connection.autocommit and connection.info.transaction_status == TransactionStatus.IDLE
    with connection.transaction() if needs_transaction else nullcontext():
        previous = connection.execute("SHOW effective_io_concurrency").fetchone()['effective_io_concurrency']
        if previous == str(concurrency):
            yield
            return
        connection.execute("SELECT set_config('effective_io_concurrency', %s, true)", (str(concurrency),))
        try:
            yield
        finally:
            # A failed SQL transaction can only roll back. SET LOCAL then
            # restores the prior value without masking the ranking error.
            if connection.info.transaction_status == TransactionStatus.INTRANS:
                connection.execute("SELECT set_config('effective_io_concurrency', %s, true)", (previous,))


@contextmanager
def search_sql_execution(connection):
    """Avoid LLVM compilation dominating bounded interactive search requests.

    Linux PostgreSQL's JIT-enabled build compiled 649 record-plan functions
    for 5.51 seconds and 449 aggregation-plan functions for another 4.50
    seconds. Recursive ACL estimates triggered expensive JIT even on branches
    that returned few/no rows. The same SQL on a build without LLVM concealed
    this deployment difference. Repeated, parameter-specific search plans do
    not amortize that compilation across requests.

    This changes neither planner join choices nor permissions/ranking. Disable
    JIT only while executing these search operations, then restore the caller's
    setting so pooled connections and unrelated API work are unaffected. SET
    LOCAL also guarantees rollback/transaction completion removes the override.
    If SQL aborts the transaction, do not issue another statement that would
    hide its original error; the connection owner's rollback restores settings.
    """
    previous = connection.execute("SELECT current_setting('jit') AS value").fetchone()['value']
    if previous == 'on':
        connection.execute('SET LOCAL jit=off')
    try:
        yield
    finally:
        if previous == 'on' and connection.info.transaction_status == TransactionStatus.INTRANS:
            connection.execute('SET LOCAL jit=on')


def interactive_search(operation):
    @wraps(operation)
    def execute(connection, *args, **kwargs):
        with search_sql_execution(connection):
            return operation(connection, *args, **kwargs)
    return execute
