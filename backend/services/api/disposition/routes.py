"""Purpose-built disposition commands, document reads and evidence corrections."""
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Query, UploadFile, File, Form
import psycopg
from psycopg import Connection
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt

from ..audit_context import decode_change_reason
from ..concurrency import expected_version
from ..database import get_connection, get_consistent_connection
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


def _command(c,request,payload,handler,*,audit_reason=None,**values):
    reason=(audit_reason if audit_reason is not None else decode_change_reason(request.headers.get('X-Change-Reason',''))).strip()
    if not reason:
        raise HTTPException(422,detail={'code':'disposition_reason_required'})
    try:
        # The SQL exception must leave its savepoint before HTTP conversion;
        # no success is returned before deferred unit/history checks finish.
        with c.transaction():
            return handler(c,acting_role_id=payload.acting_role_id,command_id=payload.command_id,reason=reason,**values)
    except StaleVersion:
        raise HTTPException(409,detail={'code':'disposition_stale_version'}) from None
    except psycopg.Error as error:
        code=error.diag.message_primary or ''
        safe=code if code.startswith('disposition_') and code.replace('_','').isalnum() else 'disposition_command_failed'
        status=422 if safe=='disposition_submission_reason_required' else 403 if error.sqlstate=='42501' else 409
        detail={'code':safe}
        if safe=='disposition_proposal_requires_correction':
            import json
            try:
                ids=json.loads(error.diag.message_detail or '{}').get('proposal_ids',[])
                if isinstance(ids,list) and all(type(i) is int and i>0 for i in ids):detail['proposal_ids']=ids
            except (ValueError,TypeError):pass
        raise HTTPException(status,detail=detail) from None


@router.post('/jobs',status_code=201)
def create_job(payload: CreateJob,request: Request,c: Connection=Depends(get_consistent_connection,scope='function')):
    return _command(c,request,payload,membership.create_job,**payload.model_dump(exclude={'acting_role_id','command_id'}))


@router.post('/jobs/{job_id}/assignment')
def assign_job(job_id: int,payload: AssignJob,request: Request,version: int=Depends(expected_version),c: Connection=Depends(get_consistent_connection,scope='function')):
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
def read_members(job_id: int,limit: int=Query(25,ge=1,le=100),offset: int=Query(0,ge=0),query: str=Query('',max_length=200),sort: str='id',descending: bool=True,state: Literal['active','removed','completed_history','terminated_history'] | None=None,c: Connection=Depends(get_connection,scope='function')):
    return queries.members(c,job_id,limit=limit,offset=offset,query=query,sort=sort,descending=descending,state=state)


@router.get('/jobs/{job_id}/history')
def read_history(job_id: int,limit: int=Query(25,ge=1,le=100),offset: int=Query(0,ge=0),c: Connection=Depends(get_connection,scope='function')):
    return queries.history(c,job_id,limit=limit,offset=offset)


@router.get('/aggregations/{root_id}/blockers')
def read_blockers(root_id: int,limit: int=Query(25,ge=1,le=100),offset: int=Query(0,ge=0),c: Connection=Depends(get_connection,scope='function')):
    return {**blockers.summary(c,root_id),**blockers.protection_page(c,root_id,limit=limit,offset=offset)}


@router.get('/selectors/{kind}')
def read_selector(kind: Literal['owners','assignees'],query: str=Query('',max_length=200),selected: int | None=Query(None,ge=1),
                  job_type: Literal['destruction','permanent_transfer','selective_transfer','local_archives']='destruction',job_id: int | None=Query(None,ge=1),
                  c: Connection=Depends(get_connection,scope='function')):
    return queries.selector(c,kind,query=query,selected=selected,job_type=job_type,job_id=job_id)


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


class ReassignTask(Command):
    destination_role_id: StrictInt | None = Field(default=None, ge=1)
    assigned_user_id: StrictInt | None = Field(default=None, ge=1)


@router.get('/tasks')
def read_tasks(limit: int=Query(25,ge=1,le=100),offset: int=Query(0,ge=0),
               sort: str='received',descending: bool=False,
               state: Literal['open','claimed'] | None=None,job_id: int | None=Query(None,ge=1),query: str=Query('',max_length=200),stage: str | None=Query(None,max_length=100),task_type: str | None=Query(None,max_length=100),indicator: Literal['blocked','removal_required','failed_reports'] | None=None,min_priority: int | None=None,min_roots: int | None=Query(None,ge=0),has_claimant: bool | None=None,
               c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import workflow
    return workflow.tasks(c,limit=limit,offset=offset,sort=sort,descending=descending,state=state,job_id=job_id,query=query,stage=stage,task_type=task_type,indicator=indicator,min_priority=min_priority,min_roots=min_roots,has_claimant=has_claimant)


@router.post('/tasks/{task_id}/claim')
def claim_task(task_id: int,payload: Command,request: Request,version: int=Depends(expected_version),c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import workflow
    return _command(c,request,payload,workflow.task_command,task_id=task_id,expected_version=version,action='claim')


@router.post('/tasks/{task_id}/release')
def release_task(task_id: int,payload: Command,request: Request,version: int=Depends(expected_version),c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import workflow
    return _command(c,request,payload,workflow.task_command,task_id=task_id,expected_version=version,action='release')


@router.post('/tasks/{task_id}/reassignment')
def reassign_task(task_id: int,payload: ReassignTask,request: Request,version: int=Depends(expected_version),c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import workflow
    return _command(c,request,payload,workflow.task_command,task_id=task_id,expected_version=version,action='reassign',assigned_user_id=payload.assigned_user_id,destination_role_id=payload.destination_role_id)


# Proposal payloads remain type-validated independently in PostgreSQL. Identity
# and actor fields are server-owned; an update cannot submit them through CRUD.


class ReviewCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action: Literal['create']
    governing_root_id: StrictInt=Field(ge=1)
    target_aggregation_id: StrictInt=Field(ge=1)
    target_record_id: StrictInt | None=Field(default=None,ge=1)
    target_version: StrictInt=Field(ge=1)
    proposal_type: Literal['remove_from_job','make_vital','blocking_security','add_to_holds','create_aggregation_relationship','remove_aggregation_relationship','remove_record_relationship','local_retention_override']
    proposed_values: dict[str,Any]
    reason: str | None=None


class ReviewRevise(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action: Literal['revise']
    proposal_id: StrictInt=Field(ge=1)
    expected_version: StrictInt=Field(ge=1)
    target_version: StrictInt=Field(ge=1)
    proposed_values: dict[str,Any]
    reason: str | None=None


class ReviewWithdraw(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action: Literal['withdraw']
    proposal_id: StrictInt=Field(ge=1)
    expected_version: StrictInt=Field(ge=1)
    reason: str | None=None


class SaveReview(Command):
    task_version: StrictInt=Field(ge=1)
    changes: list[Annotated[ReviewCreate | ReviewRevise | ReviewWithdraw,Field(discriminator='action')]]=Field(default_factory=list,max_length=100)
    review_notes: str | None=None
    note_version: StrictInt | None=Field(default=None,ge=0)
    overall_reason: str | None=None


class SubmitReview(Command):
    task_version: StrictInt=Field(ge=1)
    overall_reason: str


class DecideReview(Command):
    task_version: StrictInt=Field(ge=1)
    decision: Literal['approved','rejected']
    decision_reason: str=''


@router.post('/tasks/{task_id}/review-work')
def save_review(task_id: int,payload: SaveReview,request: Request,version: int=Depends(expected_version),c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import proposals
    return _command(c,request,payload,proposals.save,audit_reason='Save destruction review work',task_id=task_id,expected_version=version,
      task_version=payload.task_version,changes=[v.model_dump() for v in payload.changes],review_notes=payload.review_notes,
      note_version=payload.note_version,overall_reason=payload.overall_reason)


@router.post('/tasks/{task_id}/submit-review')
def submit_review(task_id: int,payload: SubmitReview,request: Request,version: int=Depends(expected_version),c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import proposals
    return _command(c,request,payload,proposals.submit,audit_reason=payload.overall_reason or 'Submit destruction review',task_id=task_id,expected_version=version,
      task_version=payload.task_version,overall_reason=payload.overall_reason)


@router.post('/tasks/{task_id}/review-decision')
def decide_review(task_id: int,payload: DecideReview,request: Request,version: int=Depends(expected_version),c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import proposals
    return _command(c,request,payload,proposals.decide,audit_reason=payload.decision_reason.strip() or 'Complete authorized review',task_id=task_id,expected_version=version,
      task_version=payload.task_version,decision=payload.decision,decision_reason=payload.decision_reason)


@router.get('/tasks/{task_id}/review-work')
def read_review_work(task_id: int,c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import proposals
    return proposals.work(c,task_id)


@router.get('/jobs/{job_id}/proposals')
def read_proposals(job_id: int,limit: int=Query(25,ge=1,le=100),offset: int=Query(0,ge=0),review_round: int | None=Query(None,ge=1),
                   state: Literal['active','withdrawn','executed','failed'] | None=None,root_id: int | None=Query(None,ge=1),c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import proposals
    return proposals.page(c,job_id,limit=limit,offset=offset,review_round=review_round,state=state,root_id=root_id)


@router.get('/jobs/{job_id}/review-notes')
def read_review_notes(job_id: int,limit: int=Query(25,ge=1,le=100),offset: int=Query(0,ge=0),c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import proposals
    return proposals.notes(c,job_id,limit=limit,offset=offset)


@router.get('/tasks/{task_id}/review-candidates/{kind}')
def read_review_candidates(task_id: int,kind: Literal['holds','aggregations','records','relationship_types','security_levels'],acting_role_id: int=Query(ge=1),
                           query: str=Query('',max_length=200),selected: int | None=Query(None,ge=1),c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import proposals
    return proposals.candidates(c,task_id,acting_role_id=acting_role_id,kind=kind,query=query,selected=selected)


@router.get('/jobs/{job_id}/review-rounds')
def read_review_rounds(job_id: int,limit: int=Query(25,ge=1,le=100),offset: int=Query(0,ge=0),summary: bool=False,c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import proposals
    return proposals.rounds(c,job_id,limit=limit,offset=offset,summary=summary)


@router.get('/jobs/{job_id}/review-decisions')
def read_review_decisions(job_id: int,limit: int=Query(25,ge=1,le=100),offset: int=Query(0,ge=0),summary: bool=False,c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import proposals
    return proposals.rounds(c,job_id,limit=limit,offset=offset,decisions=True,summary=summary)


class ApproveProposals(Command):
    task_version: StrictInt=Field(ge=1)
    membership_token: str=Field(pattern=r'^[0-9a-f]{64}$')
    proposals_token: str=Field(pattern=r'^[0-9a-f]{64}$')
    overall_reason: str | None=None


class RetryExecutionReport(Command):
    destination_token: str | None=Field(default=None,pattern=r'^[0-9a-f]{64}$')


def _execution_report_after_commit(job_id,round_id,acting_role_id,preview=None):
    from contextlib import contextmanager
    from . import approval
    from ..application_settings import cache
    # A report failure cannot roll back the already-committed approval or cause
    # any proposal to execute again. Current permissions/destination are checked.
    try:
        with contextmanager(get_connection)() as report_c:
            result=approval.generate_report(report_c,job_id=job_id,round_id=round_id,acting_role_id=acting_role_id,
                preview=preview,settings=cache.for_connection(report_c))
        return {'report_status':'available','report_document_id':result['id']}
    except HTTPException as error:
        detail=error.detail if isinstance(error.detail,dict) else {}
        pending={'report_status':'pending','report_error':detail.get('code','disposition_execution_report_pending')}
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Proposal execution report remains pending')
        # No renderer/storage/SQL error text or credentials cross the API.
        pending={'report_status':'pending','report_error':'disposition_execution_report_pending'}
    try:
        from psycopg.types.json import Jsonb
        with contextmanager(get_connection)() as audit_c:
            approval.execution(audit_c,job_id,round_id,acting_role_id)
            audit_c.execute("SELECT append_domain_event('disposition_job',%s,'REVIEW_EXECUTION_REPORT_PENDING',%s)",(job_id,Jsonb(dict(round_id=round_id,acting_role_id=acting_role_id,code=pending['report_error']))))
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Execution-report failure audit could not be saved')
        raise HTTPException(503,detail={'code':'disposition_report_failure_audit_unavailable','approval_committed':True,'round_id':round_id,**pending}) from None
    return pending


@router.get('/tasks/{task_id}/approval-preview')
def preview_proposal_approval(task_id: int,acting_role_id: int=Query(ge=1),c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import approval
    try:
        with c.transaction():return approval.preview(c,task_id,acting_role_id)
    except psycopg.Error:
        raise HTTPException(403,detail={'code':'disposition_approval_unavailable'}) from None


@router.post('/tasks/{task_id}/approve-proposals')
def approve_proposal_set(task_id: int,payload: ApproveProposals,request: Request,version: int=Depends(expected_version),c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import approval
    result=_command(c,request,payload,approval.approve,audit_reason=(payload.overall_reason or '').strip() or 'Approve the complete reviewed proposal set',
        task_id=task_id,expected_version=version,task_version=payload.task_version,membership_token=payload.membership_token,
        proposals_token=payload.proposals_token,overall_reason=payload.overall_reason)
    c.commit()
    return {**result,**_execution_report_after_commit(result['job_id'],result['round_id'],payload.acting_role_id)}


@router.post('/jobs/{job_id}/review-rounds/{round_id}/execution-report')
def retry_execution_report(job_id: int,round_id: int,payload: RetryExecutionReport,request: Request,c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import approval
    approval.execution(c,job_id,round_id,payload.acting_role_id)
    c.commit()
    return _execution_report_after_commit(job_id,round_id,payload.acting_role_id,preview=payload.destination_token)


@router.get('/jobs/{job_id}/proposal-effects')
def read_proposal_effects(job_id: int,limit: int=Query(25,ge=1,le=100),offset: int=Query(0,ge=0),c: Connection=Depends(get_connection,scope='function')):
    from . import approval
    return approval.effects(c,job_id,limit=limit,offset=offset)


@router.get('/jobs/{job_id}/workspace')
def read_workspace(job_id: int,task_id: int | None=Query(None,ge=1),c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import workspace
    return workspace.read(c,job_id,task_id)


@router.get('/tasks/{task_id}/proposal-targets/{kind}')
def read_proposal_targets(task_id: int,kind: Literal['aggregations','records'],root_id: int=Query(ge=1),acting_role_id: int=Query(ge=1),
                          query: str=Query('',max_length=200),selected: int | None=Query(None,ge=1),c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import workspace
    return workspace.targets(c,task_id,acting_role_id=acting_role_id,root_id=root_id,kind=kind,query=query,selected=selected)


@router.get('/tasks/{task_id}/assignment-candidates/{kind}')
def read_task_assignment_candidates(task_id: int,kind: Literal['users','roles'],acting_role_id: int=Query(ge=1),query: str=Query('',max_length=200),selected: int | None=Query(None,ge=1),c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import workspace
    return workspace.assignment_candidates(c,task_id,acting_role_id=acting_role_id,kind=kind,query=query,selected=selected)


@router.get('/jobs/{job_id}/review-history/{kind}/{identity}')
def read_review_history(job_id: int,kind: Literal['proposal','note'],identity: int,limit: int=Query(25,ge=1,le=100),offset: int=Query(0,ge=0),c: Connection=Depends(get_consistent_connection,scope='function')):
    from . import workspace
    return workspace.review_history(c,job_id,kind=kind,identity=identity,limit=limit,offset=offset)
