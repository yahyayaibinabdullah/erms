"""Purpose-built common job commands; every caller uses the same SQL gates.

The caller owns the transaction. Multi-add has a savepoint per selected root;
its immutable command receipt preserves the exact mixed result for retries.
No command grants content access or implements irreversible execution.
"""
from uuid import UUID

from psycopg.types.json import Jsonb

from .commands import execute_command, lock_job
from fastapi import HTTPException


def _run(connection, operation, payload, acting_role_id, reason, command_id, statement, parameters):
    return execute_command(
        connection, command_id=command_id, operation=operation, payload=payload,
        acting_role_id=acting_role_id, reason=reason,
        apply=lambda c: c.execute(statement, parameters).fetchone()['result'],
    )


def create_job(connection, *, job_number=None, job_type, owning_org_unit_id=None,
               assigned_user_id=None, acting_role_id, reason, command_id: UUID):
    payload=dict(job_number=job_number,job_type=job_type,owning_org_unit_id=owning_org_unit_id,assigned_user_id=assigned_user_id)
    return _run(connection,'job_create',payload,acting_role_id,reason,command_id,
                'SELECT disposition_private.create_job(%s,%s,%s,%s) result',
                (job_number,job_type,owning_org_unit_id,assigned_user_id))


def assign_job(connection, *, job_id, expected_version, assigned_user_id, acting_role_id, reason, command_id: UUID):
    payload=dict(job_id=job_id,expected_version=expected_version,assigned_user_id=assigned_user_id)
    return _run(connection,'job_assign',payload,acting_role_id,reason,command_id,
                'SELECT disposition_private.assign_job(%s,%s,%s) result',(job_id,expected_version,assigned_user_id))


def add_many(connection, *, job_id, expected_version, items, acting_role_id, reason, command_id: UUID):
    payload=dict(job_id=job_id,expected_version=expected_version,items=items)
    return _run(connection,'membership_add',payload,acting_role_id,reason,command_id,
                'SELECT disposition_private.add_items(%s,%s,%s) result',(job_id,expected_version,Jsonb(items)))


def remove_member(connection, *, membership_id, expected_version, root_version, acting_role_id, reason, command_id: UUID):
    payload=dict(membership_id=membership_id,expected_version=expected_version,root_version=root_version)
    return _run(connection,'membership_remove',payload,acting_role_id,reason,command_id,
                'SELECT disposition_private.remove_member(%s,%s,%s) result',(membership_id,expected_version,root_version))


def remove_many(connection, *, job_id, expected_version, items, acting_role_id, reason, command_id: UUID):
    """One receipt/savepoint for one job; reuse every individual SQL removal gate.

    No per-item savepoints or partial success: a late access/version/stage failure
    rolls back preceding removals, status transitions, events and the receipt.
    """
    ids = [item['membership_id'] for item in items]
    if not 1 <= len(ids) <= 100 or len(set(ids)) != len(ids):
        raise HTTPException(422, detail={'code': 'disposition_selection_bounds_invalid'})
    if not str(reason or '').strip():
        raise HTTPException(422, detail={'code': 'disposition_reason_required'})
    payload = dict(job_id=job_id, expected_version=expected_version, items=items)

    def apply(c):
        lock_job(c, job_id, expected_version)
        c.execute('SELECT disposition_private.require_membership_stage(%s)', (job_id,))
        rows = c.execute('''SELECT m.id,m.version,m.membership_state,a.version root_version,
                 current_user_can_view_aggregation(a.id) visible
             FROM disposition_job_memberships m JOIN aggregations a ON a.id=m.root_aggregation_id
             WHERE m.job_id=%s AND m.id=ANY(%s) ORDER BY m.id FOR UPDATE OF m,a''',
             (job_id, ids)).fetchall()
        current = {row['id']: row for row in rows}
        invalid = [item['membership_id'] for item in items if
                   (row := current.get(item['membership_id'])) is None or
                   row['membership_state'] != 'active' or not row['visible'] or
                   row['version'] != item['expected_version'] or row['root_version'] != item['root_version']]
        if invalid:
            # Only echo client-supplied IDs, never inaccessible names or facts.
            raise HTTPException(409, detail={'code': 'disposition_bulk_selection_changed', 'item_ids': invalid})
        results = [c.execute('SELECT disposition_private.remove_member(%s,%s,%s) result',
                   (item['membership_id'], item['expected_version'], item['root_version'])).fetchone()['result']
                   for item in sorted(items, key=lambda item: item['membership_id'])]
        return dict(job_id=job_id, items=results,
                    job_version=c.execute('SELECT version FROM disposition_jobs WHERE id=%s', (job_id,)).fetchone()['version'])

    return execute_command(connection, command_id=command_id, operation='membership_remove',
                           payload=payload, acting_role_id=acting_role_id, reason=reason, apply=apply)


def accelerate(connection, *, root_id, expected_version, acting_role_id, reason, command_id: UUID):
    payload=dict(root_id=root_id,expected_version=expected_version)
    return _run(connection,'eligibility_accelerate',payload,acting_role_id,reason,command_id,
                'SELECT disposition_private.accelerate(%s,%s) result',(root_id,expected_version))


def terminate_job(connection, *, job_id, expected_version, confirmed, acting_role_id, reason, command_id: UUID):
    payload=dict(job_id=job_id,expected_version=expected_version,confirmed=confirmed)
    return _run(connection,'job_terminate',payload,acting_role_id,reason,command_id,
                'SELECT disposition_private.terminate_job(%s,%s,%s) result',(job_id,expected_version,confirmed))


def change_job_owner(connection, *, job_id, expected_version, owning_org_unit_id, acting_role_id, reason, command_id: UUID):
    payload=dict(job_id=job_id,expected_version=expected_version,owning_org_unit_id=owning_org_unit_id)
    return _run(connection,'job_owner_change',payload,acting_role_id,reason,command_id,
                'SELECT disposition_private.change_job_owner(%s,%s,%s) result',(job_id,expected_version,owning_org_unit_id))
