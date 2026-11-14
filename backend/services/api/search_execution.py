"""Execution settings scoped to interactive search SQL, never server defaults."""
from contextlib import contextmanager
from functools import wraps

from psycopg.pq import TransactionStatus


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
