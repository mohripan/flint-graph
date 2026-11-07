from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from flint_graph.api.narrative_character_schemas import ImageJobResponse
from flint_graph.api.routes.narrative_music import MusicJobResponse
from flint_graph.api.routes.narrative_voices import VoiceJobResponse


class ActionFactResponse(BaseModel):
    icon: str
    text: str


class ActionPartResponse(BaseModel):
    item: str
    quantity: int


class ActionQuoteResponse(BaseModel):
    """What a generation card promises before anything runs (ADR 0068)."""

    kind: str
    title: str
    facts: list[ActionFactResponse]
    parts: list[ActionPartResponse]
    button: str
    opens: str | None


class AssistantActionResponse(BaseModel):
    """One generation action of a proposal and the job it became, if any (ADR 0061)."""

    index: int
    op: str
    label: str
    status: str
    needs_accept: bool
    error_code: str | None
    detail: str | None
    image_job: ImageJobResponse | None
    voice_job: VoiceJobResponse | None
    music_job: MusicJobResponse | None = None
    child_thread: "AssistantThreadResponse | None" = None
    quote: ActionQuoteResponse | None = None


class AssistantAttachment(BaseModel):
    """A library item the creator attached: a character's ID or an approved file's ID."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["character", "asset"]
    id: str = Field(min_length=1, max_length=64)


class AssistantAttachmentResponse(BaseModel):
    kind: str
    id: str
    name: str
    asset_kind: str | None


class AssistantThreadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    idempotency_key: UUID
    parent_thread_id: UUID | None = None
    task: str | None = Field(default=None, max_length=2000)


class AssistantTurnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: str = Field(min_length=1, max_length=8000)
    base_revision_id: UUID
    focus_node: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    idempotency_key: UUID
    # Ignored, and only accepted so a tab opened before ADR 0068 can still send a message.
    auto_generate: bool = False
    attachments: list[AssistantAttachment] = Field(default_factory=list, max_length=12)


class AssistantDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID


class AssistantThreadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    project_id: UUID
    title: str
    parent_thread_id: UUID | None = None
    task: str | None = None
    origin: str = "creator"
    active: bool = False
    children: list["AssistantThreadResponse"] = Field(default_factory=list)
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
    auto_generate: bool
    attachments: list[AssistantAttachmentResponse]
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


class AssistantThreadEventResponse(BaseModel):
    """One entry of a thread's append-only log (ADR 0060)."""

    model_config = ConfigDict(from_attributes=True)
    thread_id: UUID
    sequence: int
    kind: str
    payload: dict[str, Any]
    actor_user_id: UUID | None
    created_at: datetime


AssistantActionResponse.model_rebuild()
