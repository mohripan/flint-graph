"""Character profile, portrait job and image contracts (ADR 0039)."""

from datetime import datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

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
    # Cut the figure out into a transparent stage sprite (full-body framing only).
    transparent: StrictBool = False
    # Upscale and lightly repaint each render so sprites stay sharp when drawn large.
    hires: StrictBool = False

    @model_validator(mode="after")
    def _sprites_are_full_body(self) -> Self:
        if self.transparent and self.framing != "full_body":
            raise ValueError("Transparent sprites need full-body framing")
        return self


class ExpressionJobCreate(BaseModel):
    """Repaint the face of a base image once per expression (ADR 0041)."""

    model_config = ConfigDict(extra="forbid")

    base_asset_id: UUID
    face_box: list[Annotated[int, Field(ge=0, le=4096)]] = Field(min_length=4, max_length=4)
    expressions: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(
        min_length=1, max_length=4
    )
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


class CutoutResponse(BaseModel):
    model: str
    sha256: str


class HiresResponse(BaseModel):
    scale: float
    strength: float


class ImageJobResponse(BaseModel):
    id: UUID
    purpose: str
    character_id: str | None
    transparent: bool
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
    # The base render; a high-resolution job upscales it to the output size.
    width: int
    height: int
    hires: HiresResponse | None
    output_width: int
    output_height: int
    steps: int
    guidance: float
    seeds: list[int]
    model: str | None
    # The segmenter that cut out a completed sprite job, with the ONNX file's SHA-256.
    cutout: CutoutResponse | None
    prompt_tokens: int | None
    truncated: bool | None
    # Expression jobs (ADR 0041): the base image, its face box and one entry per image.
    base_asset_id: UUID | None = None
    face_box: list[int] | None = None
    strength: float | None = None
    expressions: list[str] | None = None
    prompts: list[str] | None = None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    assets: list[AssetResponse]


class ImageJobListResponse(BaseModel):
    jobs: list[ImageJobResponse]
