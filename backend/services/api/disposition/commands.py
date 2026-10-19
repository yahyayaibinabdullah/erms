"""Transaction/retry kernel for the approved disposition commands.

This is server-internal infrastructure, never a generic CRUD/HTTP endpoint or
an administrator-defined workflow runtime. A later action service supplies its
operation-specific authorization, blockers, routing and evidence gates before
calling this kernel on the same connection. The database independently guards
state, membership, identity, actor and whole-unit consistency.
"""
from collections.abc import Callable
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb


class StaleVersion(ValueError):
    pass


def execute_command(
    connection: Connection, *, command_id: UUID, operation: str,
    payload: dict[str, Any], acting_role_id: int, reason: str,
    apply: Callable[[Connection], dict[str, Any]],
) -> dict[str, Any]:
    """Apply once atomically, or return the exact committed result on retry.

    The caller owns the outer transaction/commit. Exceptions roll back this
    command's savepoint, including resource changes, events and the receipt.
    Identity, acting role and exact payload/reason are bound to the retry key;
    authorization is rechecked even when returning an earlier result.
    """
    with connection.transaction():
        row = connection.execute(
            "SELECT disposition_private.begin_command(%s,%s,%s,%s,%s) AS result",
            (command_id, operation, Jsonb(payload), acting_role_id, reason),
        ).fetchone()
        if row["result"] is not None:
            return row["result"]
        result = apply(connection)
        if not isinstance(result, dict):
            raise TypeError("Disposition command result must be an object")
        from .notifications import publish_command_tasks
        publish_command_tasks(connection)
        connection.execute("SELECT disposition_private.finish_command(%s)", (Jsonb(result),))
        # Check this command before acknowledging it to another service in the
        # same outer transaction. Preserve deferred mode for subsequent work.
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        connection.execute("SET CONSTRAINTS ALL DEFERRED")
        return result


def lock_job(connection: Connection, job_id: int, expected_version: int) -> dict[str, Any]:
    connection.execute("SELECT disposition_private.require_command()")
    row = connection.execute(
        "SELECT * FROM disposition_jobs WHERE id=%s FOR UPDATE", (job_id,),
    ).fetchone()
    if row is None or row["version"] != expected_version:
        raise StaleVersion("disposition_stale_version")
    return row


def transition_unit(connection: Connection, root_id: int, expected_version: int, status: int) -> None:
    """Private whole-unit primitive; the command determines permitted causes.

    Pending membership must be written in this transaction. Terminal outcomes
    remain closed until final-action implementation passes its release gate.
    """
    connection.execute(
        "SELECT disposition_private.transition_unit(%s,%s,%s)",
        (root_id, expected_version, status),
    )


def claim_task(connection: Connection, task_id: int, expected_version: int) -> int:
    """Claim one current task atomically within a task_claim command."""
    return connection.execute(
        "SELECT disposition_private.claim_task(%s,%s) AS version",
        (task_id, expected_version),
    ).fetchone()["version"]
