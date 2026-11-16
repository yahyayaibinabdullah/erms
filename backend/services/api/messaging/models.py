from datetime import date
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .config import LIMITS
from .content import REQUEST_BODY_BYTES


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Selector(Input):
    recipient_type: Literal["to", "cc"] = "to"
    selector_kind: Literal["user", "role", "org_unit", "everyone"]
    target_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_target(self):
        if (self.selector_kind == "everyone") != (self.target_id is None):
            raise ValueError("Everyone has no target ID; ordinary selectors require one")
        return self


class ResourceLink(Input):
    link_token: UUID
    resource_kind: Literal["aggregation", "record"]
    target_id: int = Field(gt=0)


class RecipientValidation(Input):
    security_level_id: int | None = Field(default=None, gt=0)
    selectors: list[Selector] = Field(
        min_length=1, max_length=LIMITS["MAX_SELECTORS_PER_SEND"]
    )


class Send(RecipientValidation):
    relationship_kind: Literal["reply", "forward", "follow_up"] | None = None
    related_delivery_id: UUID | None = None
    related_envelope_id: UUID | None = None
    complete_action: bool = False
    request_id: UUID
    subject: str = Field(max_length=1024)
    body_rich_text: str = Field(max_length=REQUEST_BODY_BYTES)
    priority: Literal["normal", "high", "very_high"] = "normal"
    action_required: bool = False
    action_due_date: date | None = None
    read_receipt_requested: bool = False
    resource_links: list[ResourceLink] = Field(
        default_factory=list, max_length=LIMITS["MAX_RESOURCE_LINKS"]
    )


class Amendment(Input):
    request_id: UUID
    amendment_kind: Literal[
        "due_date_added", "due_date_changed", "due_date_removed", "action_withdrawn"
    ]
    due_date: date | None = None
    reason: str = Field(min_length=1, max_length=8000)


class Draft(Input):
    subject: str = Field(default="", max_length=1024)
    body_rich_text: str = Field(default="", max_length=REQUEST_BODY_BYTES)
    priority: Literal["normal", "high", "very_high"] = "normal"
    security_level_id: int | None = Field(default=None, gt=0)
    action_required: bool = False
    action_due_date: date | None = None
    read_receipt_requested: bool = False
    selectors: list[Selector] = Field(
        default_factory=list, max_length=LIMITS["MAX_SELECTORS_PER_SEND"]
    )
    resource_links: list[ResourceLink] = Field(
        default_factory=list, max_length=LIMITS["MAX_RESOURCE_LINKS"]
    )
    relationship_kind: Literal["reply", "forward", "follow_up"] | None = None
    related_delivery_id: UUID | None = None
    related_envelope_id: UUID | None = None
    complete_action: bool = False


class DraftSend(Input):
    request_id: UUID
    version: int = Field(gt=0)
    complete_action: bool = False
