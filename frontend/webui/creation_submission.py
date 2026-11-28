"""One form's creation identity and frozen request across uncertain outcomes."""

import asyncio
from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Any
from uuid import uuid4

from .api_client import ApiError


CONFIRMED_FAILURES={
    "duplicate_resource_number","code_generator_recommendation_conflict",
    "code_generator_required_value","code_generator_missing_context",
    "code_generator_length_exceeded","code_generator_invalid","code_generator_invalid_target",
}
COMPLETED_ERRORS={"creation_submission_unavailable","creation_submission_conflict"}


def unknown_outcome():
    return ApiError(409,{"code":"creation_submission_unknown_outcome",
        "message_key":"code_generation.error.unknown_outcome","parameters":{}})


@dataclass
class CreationAttempt:
    key: str | None=None
    payload: Any=None
    signature: str | None=None
    uncertain: bool=False
    result: Any=None
    completed_error: ApiError | None=None

    def prepare(self,operation,payload):
        signature=json.dumps([operation,payload],sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
        if self.completed_error is not None and signature!=self.signature:
            raise self.completed_error
        if self.uncertain and signature!=self.signature:
            raise unknown_outcome()
        if self.result is not None:
            return self.key
        if self.key is None or signature!=self.signature:
            self.key=str(uuid4())
            self.payload=deepcopy(payload)
            self.signature=signature
        return self.key

    async def submit(self,operation,payload,send):
        key=self.prepare(operation,payload)
        if self.result is not None:
            return deepcopy(self.result)
        try:
            result=await send(key,deepcopy(self.payload))
        except asyncio.CancelledError:
            self.uncertain=True
            raise
        except ApiError as error:
            code=error.detail.get("code") if isinstance(error.detail,dict) else None
            if code in COMPLETED_ERRORS:
                self.completed_error=error
                self.uncertain=False
            elif code in CONFIRMED_FAILURES or error.creation_outcome=="not-created":
                self.uncertain=False
            elif error.status_code>=500:
                self.uncertain=True
            # An authorization/schema error after a lost response does not
            # prove that the original request rolled back. Keep its identity.
            raise
        self.uncertain=False
        self.completed_error=None
        self.result=deepcopy(result)
        return result
