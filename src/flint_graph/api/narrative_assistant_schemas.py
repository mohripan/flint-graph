from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AssistantThreadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    idempotency_key: UUID


class AssistantTurnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: str = Field(min_length=1, max_length=8000)
    base_revision_id: UUID
    focus_node: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    idempotency_key: UUID


class AssistantDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID


class AssistantThreadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    project_id: UUID
    title: str
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AssistantDiagnostic(BaseModel):
    code: str
    location: str


class AssistantProposalSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    summary: str
    touched: list[str]
    accepted_revision_id: UUID | None


class AssistantProposalResponse(AssistantProposalSummary):
    turn_id: UUID
    thread_id: UUID
    base_revision_id: UUID
    operations: list[dict[str, Any]]
    diagnostics: list[AssistantDiagnostic]
    warnings: list[AssistantDiagnostic]
    decided_at: datetime | None
    created_at: datetime


class AssistantTurnResponse(BaseModel):
    id: UUID
    thread_id: UUID
    sequence: int
    request: str
    base_revision_id: UUID
    focus_node: str | None
    status: str
    cancel_requested: bool
    reply: str | None
    error_code: str | None
    model: str | None
    attempts: int | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    proposal: AssistantProposalSummary | None


class AssistantTurnEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    turn_id: UUID
    sequence: int
    attempt: int
    kind: str
    payload: dict[str, Any]
    created_at: datetime
