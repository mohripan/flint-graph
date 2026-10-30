from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NarrativeReleaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: UUID
    idempotency_key: UUID


class NarrativeReleaseRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID


class NarrativeReleaseBuildIdentity(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    compiler_version: str
    runtime_version: str
    godot_version: str
    toolchain_sha256: str
    builder_image_digest: str


class NarrativeReleaseJobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    attempt_number: int
    status: str
    cancel_requested: bool
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class NarrativeReleaseArtifactSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: str
    sha256: str
    size_bytes: int
    filename: str
    media_type: str


class NarrativeReleaseResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    project_id: UUID
    revision_id: UUID
    package_hash: str
    created_at: datetime
    build_identity: NarrativeReleaseBuildIdentity
    job: NarrativeReleaseJobSummary
    artifacts: list[NarrativeReleaseArtifactSummary] = Field(default_factory=list)


class NarrativeReleaseEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    release_id: UUID
    job_id: UUID
    sequence: int
    code: str
    payload: dict[str, str]
    created_at: datetime
