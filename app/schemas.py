from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str


class TeamMembershipResponse(BaseModel):
    team_id: UUID
    team_name: str
    role: str


class TeamMemberResponse(BaseModel):
    id: UUID
    display_name: str
    role: str


ItemType = Literal["incident", "customer_issue", "payment", "compliance", "task"]
Priority = Literal["low", "normal", "high", "urgent"]
Status = Literal["open", "in_progress", "awaiting_approval", "resolved", "closed"]


class WorkItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)
    item_type: ItemType
    priority: Priority = "normal"
    due_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Title cannot be blank")
        return value


class WorkItemUpdate(BaseModel):
    expected_version: int = Field(gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    item_type: ItemType | None = None
    priority: Priority | None = None
    due_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Title cannot be blank")
        return value

    @model_validator(mode="after")
    def require_update_fields(self) -> "WorkItemUpdate":
        provided = self.model_fields_set - {"expected_version"}
        if not provided:
            raise ValueError("Provide at least one field to update")
        for field_name in ("title", "description", "item_type", "priority"):
            if field_name in provided and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class WorkItemTransition(BaseModel):
    expected_version: int = Field(gt=0)
    target_status: Status


class WorkItemAssign(BaseModel):
    expected_version: int = Field(gt=0)
    assignee_id: UUID | None


class WorkItemCommentCreate(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)

    @field_validator("comment")
    @classmethod
    def trim_comment(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Comment cannot be blank")
        return value


class ActivityEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: UUID
    event_type: str
    old_value: dict | None = None
    new_value: dict | None = None
    created_at: datetime


class WorkItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    title: str
    description: str
    item_type: ItemType
    priority: Priority
    status: Status
    assignee_id: UUID | None
    created_by_id: UUID
    due_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class WorkItemDetailResponse(WorkItemResponse):
    activity: list[ActivityEventResponse]


class WorkItemPage(BaseModel):
    items: list[WorkItemResponse]
    next_cursor: str | None
    limit: int
