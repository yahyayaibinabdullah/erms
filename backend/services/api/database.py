from collections.abc import Generator

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .audit_context import (
    actor_email_context,
    actor_name_context,
    actor_type_context,
    actor_user_id_context,
    change_reason_context,
    correlation_id_context,
    event_metadata_context,
    event_source_context,
    request_id_context,
)
from .config import (
    float_environment,
    integer_environment,
    required_environment,
)


def database_url() -> str:
    return required_environment("DATABASE_URL")


POOL_TIMEOUT = float_environment("DB_POOL_TIMEOUT", 10, minimum=0.1)

pool = ConnectionPool(
    conninfo=database_url(),
    min_size=integer_environment("DB_POOL_MIN_SIZE", 1, minimum=0),
    max_size=integer_environment("DB_POOL_MAX_SIZE", 10, minimum=1),
    timeout=POOL_TIMEOUT,
    kwargs={"row_factory": dict_row, "options": "-c timezone=UTC"},
    name="erms-api",
    open=False,
)


def open_pool() -> None:
    pool.open(wait=True, timeout=POOL_TIMEOUT)


def close_pool() -> None:
    pool.close()


def _get_connection(consistent=False) -> Generator[Connection, None, None]:
    from .application_settings import cache
    with pool.connection() as connection:
        if consistent:
            connection.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        settings = cache.for_connection(connection)
        connection.execute(
            """
            SELECT
                set_config('app.user_id', %s, true),
                set_config('app.actor_name', %s, true),
                set_config('app.actor_email', %s, true),
                set_config('app.actor_type', %s, true),
                set_config('app.event_source', %s, true),
                set_config('app.request_id', %s, true),
                set_config('app.correlation_id', %s, true),
                set_config('app.change_reason', %s, true),
                set_config('app.event_metadata', %s, true),
                set_config('app.content_indexing_scheduling_enabled', %s, true)
            """,
            (
                actor_user_id_context.get(),
                actor_name_context.get(),
                actor_email_context.get(),
                actor_type_context.get(),
                event_source_context.get(),
                request_id_context.get(),
                correlation_id_context.get(),
                change_reason_context.get(),
                event_metadata_context.get(),
                str(
                    settings["CONTENT_INDEXING_SCHEDULING_ENABLED"]
                ).lower(),
            ),
        )
        yield connection


def get_connection() -> Generator[Connection, None, None]:
    yield from _get_connection()


def get_consistent_connection() -> Generator[Connection, None, None]:
    from fastapi import HTTPException
    from psycopg.errors import SerializationFailure, DeadlockDetected

    try:
        yield from _get_connection(consistent=True)
    except (SerializationFailure, DeadlockDetected):
        raise HTTPException(status_code=409, detail={"code": "stale_version"})
