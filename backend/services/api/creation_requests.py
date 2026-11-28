"""Authenticated replay of one completed creation, without re-creating it."""

from uuid import UUID
from typing import Annotated
from decimal import Decimal
import json

from fastapi import Depends, Header, Request
from psycopg import Connection

from .code_generation import CodeGenerationError
from .code_generation_store import CreationSubmission, submission_fingerprint
from .dashboard_visibility import visibility_ctes
from .resource_authorization import require_clearance_for_level,require_global
from .continuity_lock import acquire_continuity_shared_lock
from .database import get_connection
from .metadata_json import JsonSource


def creation_key(value: Annotated[str | None,Header(alias="Idempotency-Key",
    description="Stable key for this logical creation. Reuse it with the same inputs after a lost response.")]=None) -> UUID:
    if not value:
        raise CodeGenerationError("creation_submission_key_required")
    try:
        key=UUID(value)
    except (ValueError,TypeError):
        raise CodeGenerationError("creation_submission_key_invalid") from None
    return key


CreationKey=Annotated[UUID,Depends(creation_key)]


def begin(c, key: UUID, operation, raw, *, route=None, files=None):
    if isinstance(key,CreationSubmission):
        if key.operation!=operation:
            raise CodeGenerationError("creation_submission_conflict")
        return key
    fingerprint=submission_fingerprint(c,operation,raw,route=route or {},files=files)
    return CreationSubmission.lock(c,operation,key,fingerprint)


def replay(c, submission):
    result=submission.completed_result
    if result is None:
        return None
    kind=result.get("kind")
    identities=result.get("resource_ids",[])
    if kind not in {"record","aggregation"} or not identities or result.get("unavailable"):
        raise CodeGenerationError("creation_submission_unavailable")
    table=kind+"s"
    rights=visibility_ctes(candidate_resource=table,ordinary_access=True)
    allowed=c.execute(f"""WITH RECURSIVE candidate_ids AS (SELECT unnest(%s::bigint[]) AS id),{rights}
        SELECT count(*) AS n FROM authorized_{table}""",(identities,)).fetchone()["n"]
    if allowed!=len(identities):
        raise CodeGenerationError("creation_submission_unavailable")
    response=result["response"]
    # Current resource access does not by itself authorize an older type's
    # values or higher historical clearance in the original response snapshot.
    if isinstance(response,dict) and "security_level_id" in response:
        require_clearance_for_level(c,response["security_level_id"])
        if response.get("type_id") is not None and not c.execute(
            "SELECT user_passes_type_gate(current_user_id(),%s,%s,%s,false) AS allowed",
            (kind,response["type_id"],response["security_level_id"])).fetchone()["allowed"]:
            raise CodeGenerationError("creation_submission_unavailable")
    return response


def complete(c, submission, kind, rows, response):
    submission.complete(c,{"kind":kind,"resource_ids":[row["id"] for row in rows],"response":response})


def track(request,submission):
    request.state.creation_no_completed_result=submission.completed_result is None
    request.state.creation_finished=False


def finished(request):
    # Set only after all business work, audit and staging cleanup succeeds.
    # A subsequent commit/response failure remains an uncertain outcome.
    request.state.creation_finished=True


class CompletedCreation(Exception):
    def __init__(self,kind,response):
        self.kind=kind
        self.response=response
        super().__init__("completed creation replay")


def direct_submission(request:Request,raw:JsonSource,key:CreationKey,
                      c:Annotated[Connection,Depends(get_connection,scope="function")]):
    """Find completed requests before creation-only model validators run.

    A review date can have passed since a successful creation. New requests
    still receive the ordinary Pydantic validation; an authorized completed
    response is returned through its read model without creating anything.
    """
    kind="aggregation" if request.url.path.rstrip("/").endswith("/aggregations") else "record"
    body=json.loads(raw,parse_float=Decimal)
    parent=body.get("parent_aggregation_id") if isinstance(body,dict) else None
    privilege="record.create" if kind=="record" else "aggregation.create_child" if parent is not None else "aggregation.create_root"
    acquire_continuity_shared_lock(c)
    require_global(c,privilege)
    submission=begin(c,key,kind+".create",raw)
    track(request,submission)
    if submission.completed_result is not None:
        raise CompletedCreation(kind,replay(c,submission))
    return submission


DirectSubmission=Annotated[CreationSubmission,Depends(direct_submission)]
