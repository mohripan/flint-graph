"""Character profile, portrait job and image contracts (ADR 0039)."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from flint_graph.narrative.imagegen import MAX_APPEARANCE

CHARACTER_ID = r"^[a-z][a-z0-9_-]{0,63}$"
CharacterType = Literal["girl", "boy", "woman", "man", "other"]
Framing = Literal["portrait", "full_body"]


class ProfileWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version: int = Field(ge=0)
    appearance: str = Field(max_length=MAX_APPEARANCE)
    character_type: CharacterType
    framing: Framing


class PortraitChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version: int = Field(ge=0)
    asset_id: UUID | None


class PortraitJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    appearance: str = Field(min_length=1, max_length=MAX_APPEARANCE)
    character_type: CharacterType
    framing: Framing
    count: int = Field(default=4, ge=1, le=4)
    idempotency_key: UUID


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    character_id: str | None
    kind: str
    source: str
    name: str
    status: str
    media_type: str
    width: int | None
    height: int | None
    sha256: str
    size_bytes: int
    thumbnail_width: int | None
    thumbnail_height: int | None
    seed: int | None
    job_id: UUID | None
    license: str
    notice: str | None
    provenance: dict[str, Any]
    created_at: datetime
    approved_at: datetime | None
    rights_declared_at: datetime | None


class AssetListResponse(BaseModel):
    assets: list[AssetResponse]
    next_before: UUID | None


class AssetRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=120)


class BackgroundJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=MAX_APPEARANCE)
    count: int = Field(default=4, ge=1, le=4)
    idempotency_key: UUID


class ProfileResponse(BaseModel):
    character_id: str
    appearance: str
    character_type: str
    framing: str
    portrait: AssetResponse | None
    version: int


class ProfileListResponse(BaseModel):
    project_id: UUID
    profiles: list[ProfileResponse]


class ImageJobResponse(BaseModel):
    id: UUID
    purpose: str
    character_id: str | None
    status: str
    progress: int
    count: int
    cancel_requested: bool
    error_code: str | None
    appearance: str
    character_type: str
    framing: str
    prompt: str
    negative_prompt: str
    width: int
    height: int
    steps: int
    guidance: float
    seeds: list[int]
    model: str | None
    prompt_tokens: int | None
    truncated: bool | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    assets: list[AssetResponse]


class ImageJobListResponse(BaseModel):
    jobs: list[ImageJobResponse]
