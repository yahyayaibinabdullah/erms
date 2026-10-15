"""Explicit Phase 9 command endpoints, never general workflow-table CRUD."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
import psycopg
from psycopg import Connection
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from ..audit_context import decode_change_reason
from ..concurrency import expected_version
from ..database import get_connection
from . import membership


class Command(BaseModel):
    model_config=ConfigDict(extra='forbid')
    command_id: UUID
    acting_role_id: StrictInt=Field(ge=1)


class CreateJob(Command):
    job_number: str=Field(min_length=1)
    job_type: Literal['destruction','permanent_transfer','selective_transfer','local_archives']
    owning_org_unit_id: StrictInt | None=Field(default=None,ge=1)
    assigned_user_id: StrictInt | None=Field(default=None,ge=1)


class AssignJob(Command):
    assigned_user_id: StrictInt | None=Field(default=None,ge=1)


class ChangeOwner(Command):
    owning_org_unit_id: StrictInt=Field(ge=1)


class SelectedRoot(BaseModel):
    model_config=ConfigDict(extra='forbid')
    root_id: StrictInt=Field(ge=1)
    expected_version: StrictInt=Field(ge=1)


class AddItems(Command):
    items: list[SelectedRoot]=Field(min_length=1,max_length=100)


class RemoveMember(Command):
    root_version: StrictInt=Field(ge=1)


class TerminateJob(Command):
    confirmed: StrictBool


router=APIRouter(prefix='/api/v1/disposition',tags=['disposition'])


def _command(c,request,payload,action,**values):
    reason=decode_change_reason(request.headers.get('X-Change-Reason','')).strip()
    if not reason:
        raise HTTPException(422,detail={'code':'disposition_reason_required'})
    try:
        # The SQL exception must leave its savepoint before HTTP conversion;
        # no success is returned before deferred unit/history checks finish.
        with c.transaction():
            return action(c,acting_role_id=payload.acting_role_id,command_id=payload.command_id,reason=reason,**values)
    except psycopg.Error as error:
        code=error.diag.message_primary or ''
        safe=code if code.startswith('disposition_') and code.replace('_','').isalnum() else 'disposition_command_failed'
        status=403 if error.sqlstate=='42501' else 409
        raise HTTPException(status,detail={'code':safe}) from None


@router.post('/jobs',status_code=201)
def create_job(payload: CreateJob,request: Request,c: Connection=Depends(get_connection,scope='function')):
    return _command(c,request,payload,membership.create_job,**payload.model_dump(exclude={'acting_role_id','command_id'}))


@router.post('/jobs/{job_id}/assignment')
def assign_job(job_id: int,payload: AssignJob,request: Request,version: int=Depends(expected_version),c: Connection=Depends(get_connection,scope='function')):
    return _command(c,request,payload,membership.assign_job,job_id=job_id,expected_version=version,assigned_user_id=payload.assigned_user_id)


@router.post('/jobs/{job_id}/memberships')
def add_items(job_id: int,payload: AddItems,request: Request,version: int=Depends(expected_version),c: Connection=Depends(get_connection,scope='function')):
    return _command(c,request,payload,membership.add_many,job_id=job_id,expected_version=version,items=[item.model_dump() for item in payload.items])


@router.post('/memberships/{membership_id}/remove')
def remove_member(membership_id: int,payload: RemoveMember,request: Request,version: int=Depends(expected_version),c: Connection=Depends(get_connection,scope='function')):
    return _command(c,request,payload,membership.remove_member,membership_id=membership_id,expected_version=version,root_version=payload.root_version)


@router.post('/aggregations/{root_id}/accelerate')
def accelerate(root_id: int,payload: Command,request: Request,version: int=Depends(expected_version),c: Connection=Depends(get_connection,scope='function')):
    return _command(c,request,payload,membership.accelerate,root_id=root_id,expected_version=version)


@router.post('/jobs/{job_id}/terminate')
def terminate_job(job_id: int,payload: TerminateJob,request: Request,version: int=Depends(expected_version),c: Connection=Depends(get_connection,scope='function')):
    return _command(c,request,payload,membership.terminate_job,job_id=job_id,expected_version=version,confirmed=payload.confirmed)


@router.post('/jobs/{job_id}/owning-unit')
def change_job_owner(job_id: int,payload: ChangeOwner,request: Request,version: int=Depends(expected_version),c: Connection=Depends(get_connection,scope='function')):
    return _command(c,request,payload,membership.change_job_owner,job_id=job_id,expected_version=version,owning_org_unit_id=payload.owning_org_unit_id)
