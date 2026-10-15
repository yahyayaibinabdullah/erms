"""Purpose-built common job commands; every caller uses the same SQL gates.

The caller owns the transaction. Multi-add has a savepoint per selected root;
its immutable command receipt preserves the exact mixed result for retries.
No command grants content access or implements irreversible execution.
"""
from uuid import UUID

from psycopg.types.json import Jsonb

from .commands import execute_command


def _run(connection, operation, payload, acting_role_id, reason, command_id, statement, parameters):
    return execute_command(
        connection, command_id=command_id, operation=operation, payload=payload,
        acting_role_id=acting_role_id, reason=reason,
        apply=lambda c: c.execute(statement, parameters).fetchone()['result'],
    )


def create_job(connection, *, job_number, job_type, owning_org_unit_id=None,
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
