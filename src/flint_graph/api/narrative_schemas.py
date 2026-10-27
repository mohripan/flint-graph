from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NarrativeProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    idempotency_key: UUID


class NarrativeProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    name: str
    head_revision_id: UUID
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NarrativeRevisionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    project_id: UUID
    revision_number: int
    parent_revision_id: UUID | None
    observed_head_revision_id: UUID | None
    conflicted: bool
    content_hash: str
    author_user_id: UUID
    created_at: datetime


class NarrativeRevisionResponse(NarrativeRevisionSummary):
    story_json: str
    notices: str


class NarrativeRevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision_id: UUID
    idempotency_key: UUID
    story_json: str = Field(min_length=1, max_length=5 * 1024 * 1024)
    notices: str = Field(default="", max_length=1024 * 1024)


class NarrativeArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision_id: UUID
    archived: bool = Field(strict=True)
