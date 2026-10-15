"""Purpose-built disposition commands, document reads and evidence corrections."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Query, UploadFile, File, Form
import psycopg
from psycopg import Connection
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt

from ..audit_context import decode_change_reason
from ..concurrency import expected_version
from ..database import get_connection
from . import membership, queries, blockers, artifacts, documents
from .commands import StaleVersion


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
    except StaleVersion:
        raise HTTPException(409,detail={'code':'disposition_stale_version'}) from None
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


@router.get('/context')
def read_context(c: Connection=Depends(get_connection,scope='function')):
    return queries.context(c)


@router.get('/eligibility')
def read_eligibility(limit: int=Query(25,ge=1,le=100),offset: int=Query(0,ge=0),
                     sort: str='due',descending: bool=False,owner: int | None=None,
                     status: int | None=Query(None,ge=2,le=5),vital: bool | None=None,
                     security: bool | None=None,held: bool | None=None,due_from: AwareDatetime | None=None,
                     due_to: AwareDatetime | None=None,group_owner: bool=False,
                     c: Connection=Depends(get_connection,scope='function')):
    return queries.eligibility(c,limit=limit,offset=offset,sort=sort,descending=descending,owner=owner,status=status,
      vital=vital,security=security,held=held,due_from=due_from,due_to=due_to,group_owner=group_owner)


@router.get('/jobs')
def read_jobs(limit: int=Query(25,ge=1,le=100),offset: int=Query(0,ge=0),query: str=Query('',max_length=200),
              lifecycle: Literal['active','completed','terminated'] | None=None,sort: str='id',descending: bool=True,
              c: Connection=Depends(get_connection,scope='function')):
    return queries.jobs(c,limit=limit,offset=offset,query=query,lifecycle=lifecycle,sort=sort,descending=descending)


@router.get('/jobs/{job_id}')
def read_job(job_id: int,c: Connection=Depends(get_connection,scope='function')):
    return queries.job(c,job_id)


@router.get('/jobs/{job_id}/memberships')
def read_members(job_id: int,limit: int=Query(25,ge=1,le=100),offset: int=Query(0,ge=0),c: Connection=Depends(get_connection,scope='function')):
    return queries.members(c,job_id,limit=limit,offset=offset)


@router.get('/jobs/{job_id}/history')
def read_history(job_id: int,limit: int=Query(25,ge=1,le=100),offset: int=Query(0,ge=0),c: Connection=Depends(get_connection,scope='function')):
    return queries.history(c,job_id,limit=limit,offset=offset)


@router.get('/aggregations/{root_id}/blockers')
def read_blockers(root_id: int,limit: int=Query(25,ge=1,le=100),offset: int=Query(0,ge=0),c: Connection=Depends(get_connection,scope='function')):
    return {**blockers.summary(c,root_id),**blockers.protection_page(c,root_id,limit=limit,offset=offset)}


@router.get('/selectors/{kind}')
def read_selector(kind: Literal['owners','assignees'],query: str=Query('',max_length=200),selected: int | None=Query(None,ge=1),
                  job_type: Literal['destruction','permanent_transfer','selective_transfer','local_archives']='destruction',
                  c: Connection=Depends(get_connection,scope='function')):
    return queries.selector(c,kind,query=query,selected=selected,job_type=job_type)


@router.get('/aggregations/{root_id}/eligibility')
def read_root_eligibility(root_id: int,c: Connection=Depends(get_connection,scope='function')):
    blockers._require_root(c,root_id)
    return c.execute('''SELECT e.*,a.version FROM disposition_private.eligibility(%s) e
      JOIN aggregations a ON a.id=e.root_id''',(root_id,)).fetchone()


@router.get('/jobs/{job_id}/documents')
def document_page(job_id: int,limit: int=Query(25,ge=1,le=100),offset: int=Query(0,ge=0),sort: Literal['id','file_name','type_label','evidence_version','created_label']='id',descending: bool=True,c: Connection=Depends(get_connection,scope='function')):
    return artifacts.page(c,job_id,limit=limit,offset=offset,sort=sort,descending=descending)


@router.get('/jobs/{job_id}/artifact-destination')
def artifact_destination(job_id: int,document_type: str,c: Connection=Depends(get_connection,scope='function')):
    return artifacts.public_destination(c,job_id,document_type)


@router.post('/jobs/{job_id}/documents/{document_id}/corrections',status_code=201)
def correct_evidence(job_id: int,document_id: int,request: Request,
                     command_id: UUID=Form(...),acting_role_id: int=Form(...,ge=1),
                     destination_token: str=Form(...,min_length=64,max_length=64),
                     file: UploadFile=File(...),version: int=Depends(expected_version),
                     c: Connection=Depends(get_connection,scope='function')):
    from ..content_storage import stage_governed_upload
    from ..application_settings import cache
    reason=decode_change_reason(request.headers.get('X-Change-Reason','')).strip()
    if not reason:raise HTTPException(422,detail={'code':'disposition_reason_required'})
    old=artifacts.document(c,job_id,document_id)
    if old['origin']!='uploaded':raise HTTPException(409,detail={'code':'disposition_generated_correction_forbidden'})
    if not c.execute('SELECT disposition_private.can_correct_evidence(%s,%s) allowed',(job_id,acting_role_id)).fetchone()['allowed']:
        raise HTTPException(403,detail={'code':'disposition_evidence_correction_forbidden'})
    payload=Command(command_id=command_id,acting_role_id=acting_role_id)
    with stage_governed_upload(file,cache.for_connection(c)) as staged:
        return _command(c,request,payload,artifacts.correct,job_id=job_id,document_id=document_id,
                        expected_version=version,staged=staged,preview=destination_token)


@router.get('/jobs/{job_id}/documents/{document_id}/content')
def document_content(job_id: int,document_id: int,request: Request,c: Connection=Depends(get_connection,scope='function')):
    from ..main import download_digital_component_content
    row=artifacts.document(c,job_id,document_id)
    return download_digital_component_content(row['digital_component_id'],request,c)


@router.get('/jobs/{job_id}/documents/{document_id}/preview')
def document_preview(job_id: int,document_id: int,request: Request,c: Connection=Depends(get_connection,scope='function')):
    from ..main import view_digital_component_rendition
    row=artifacts.document(c,job_id,document_id)
    return view_digital_component_rendition(row['digital_component_id'],request,c)


@router.get('/jobs/{job_id}/templates')
def template_catalogue(job_id: int,c: Connection=Depends(get_connection,scope='function')):
    return documents.catalogue(c,job_id)


@router.get('/jobs/{job_id}/templates/{kind}/revisions')
def template_history(job_id: int,kind: str,limit: int=Query(25,ge=1,le=50),offset: int=Query(0,ge=0),
                     sort: Literal['revision_number','original_filename','uploaded_at']='revision_number',descending: bool=True,
                     c: Connection=Depends(get_connection,scope='function')):
    return documents.history(c,job_id,kind,limit=limit,offset=offset,sort=sort,descending=descending)


@router.get('/jobs/{job_id}/templates/{kind}/content')
def template_content(job_id: int,kind: str,reference: str | None=Query(None,max_length=150),c: Connection=Depends(get_connection,scope='function')):
    from fastapi.responses import Response
    from urllib.parse import quote
    row=documents.download(c,job_id,kind,reference)
    return Response(row['content'],media_type=documents.engine.MIME,
      headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(row['original_filename'],safe=''),
               'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


@router.post('/jobs/{job_id}/templates/{kind}/revisions',status_code=201)
def upload_template(job_id: int,kind: str,request: Request,command_id: UUID=Form(...),acting_role_id: int=Form(...,ge=1),
                    expected_reference: str=Form(...,min_length=1,max_length=150),file: UploadFile=File(...),
                    c: Connection=Depends(get_connection,scope='function')):
    from ..application_settings import cache
    documents.require_access(c,job_id,acting_role_id)
    settings=cache.for_connection(c)
    content=file.file.read(settings['MAX_RENDITION_SIZE_BYTES']+1)
    payload=Command(command_id=command_id,acting_role_id=acting_role_id)
    return _command(c,request,payload,documents.revise,job_id=job_id,kind=kind,expected_reference=expected_reference,
      content=content,filename=file.filename or '',settings=settings)
