"""Safe creation retries preserve the original key, operation and exact inputs."""

from copy import deepcopy

import httpx
import pytest

from frontend.webui.api_client import ApiError,ErmsApiClient
from frontend.webui.creation_submission import CreationAttempt


@pytest.mark.asyncio
async def test_lost_response_returns_one_saved_result_and_never_resubmits_changed_inputs():
    attempt=CreationAttempt()
    body={"title":"Original","field_values":{"7":"900719925474099312345.123456789"}}
    stored={}
    calls=[]

    async def send(key,payload):
        calls.append((key,deepcopy(payload)))
        stored.setdefault(key,{"id":len(stored)+1,"record_number":"R10"})
        if len(calls)==1:
            raise ApiError(503,"Response lost after commit")
        return stored[key]

    with pytest.raises(ApiError):
        await attempt.submit("records.create",body,send)
    assert attempt.uncertain
    with pytest.raises(ApiError) as rejected:
        await attempt.submit("records.create",{**body,"title":"Changed"},send)
    assert rejected.value.detail["code"]=="creation_submission_unknown_outcome"
    with pytest.raises(ApiError):
        await attempt.submit("aggregations.create",body,send)
    assert len(calls)==1
    row=await attempt.submit("records.create",body,send)
    assert row=={"id":1,"record_number":"R10"}
    assert len(stored)==1 and calls[0]==calls[1]
    assert not attempt.uncertain
    assert await attempt.submit("records.create",body,send)==row
    assert len(calls)==2


@pytest.mark.asyncio
async def test_confirmed_rollback_after_unknown_allows_a_corrected_new_submission():
    attempt=CreationAttempt()
    calls=[]

    async def send(key,body):
        calls.append((key,deepcopy(body)))
        if len(calls)==1:
            raise ApiError(503,"Unknown outcome")
        if len(calls)==2:
            raise ApiError(409,{"code":"code_generator_recommendation_conflict"})
        return {"id":1,"record_number":body["record_number"]}

    original={"record_number":"R10"}
    for _ in range(2):
        with pytest.raises(ApiError):
            await attempt.submit("records.create",original,send)
    assert not attempt.uncertain
    result=await attempt.submit("records.create",{"record_number":"R20"},send)
    assert result["record_number"]=="R20"
    assert calls[0][0]==calls[1][0] and calls[2][0]!=calls[0][0]


@pytest.mark.asyncio
async def test_permission_error_does_not_erase_unknown_outcome_and_completed_unavailable_is_terminal():
    attempt=CreationAttempt()
    errors=[ApiError(503,"Unknown"),ApiError(403,"Access changed"),
            ApiError(410,{"code":"creation_submission_unavailable"})]
    calls=[]

    async def send(key,body):
        calls.append(key)
        raise errors.pop(0)

    for _ in range(3):
        with pytest.raises(ApiError):
            await attempt.submit("records.create",{"title":"Original"},send)
    assert len(set(calls))==1 and attempt.completed_error is not None
    with pytest.raises(ApiError) as terminal:
        await attempt.submit("records.create",{"title":"New details"},send)
    assert terminal.value.status_code==410 and len(calls)==3


@pytest.mark.asyncio
async def test_resource_client_requires_and_transports_the_callers_key():
    requests=[]

    def handler(request):
        requests.append(request)
        return httpx.Response(201,json={"id":1})

    api=ErmsApiClient("http://api.test",transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApiError) as missing:
            await api.create("records",{"title":"Draft"})
        assert missing.value.status_code==428 and requests==[]
        key="00000000-0000-4000-8000-000000000001"
        await api.create("records",{"title":"Draft"},submission_key=key)
        await api.commit_record_draft(7,submission_key=key)
        assert [request.headers["Idempotency-Key"] for request in requests]==[key,key]
    finally:
        await api.close()


@pytest.mark.asyncio
async def test_confirmed_generic_validation_failure_resolves_unknown_and_permission_restoration_replays():
    attempt=CreationAttempt()
    calls=[]

    async def send(key,body):
        calls.append(key)
        if len(calls)==1:
            raise ApiError(503,"Unknown")
        if len(calls)==2:
            raise ApiError(422,[{"type":"missing"}],creation_outcome="not-created")
        return {"id":1}

    for _ in range(2):
        with pytest.raises(ApiError):
            await attempt.submit("records.create",{"title":"Original"},send)
    assert not attempt.uncertain
    assert await attempt.submit("records.create",{"title":"Corrected"},send)=={"id":1}
    assert calls[0]==calls[1] and calls[2]!=calls[1]

    attempt=CreationAttempt()
    calls=[]

    async def temporarily_unavailable(key,body):
        calls.append(key)
        if len(calls)==1:
            raise ApiError(410,{"code":"creation_submission_unavailable"})
        return {"id":7}

    with pytest.raises(ApiError):
        await attempt.submit("records.create",{"title":"Original"},temporarily_unavailable)
    assert await attempt.submit("records.create",{"title":"Original"},temporarily_unavailable)=={"id":7}
    assert calls[0]==calls[1] and attempt.completed_error is None
