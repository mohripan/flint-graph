"""Character voices and local voice jobs (ADR 0043).

Viewers read; members choose voices and start, list or cancel jobs. Jobs are queued
here and run later in the opt-in voice worker; clips arrive as candidates.
"""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from flint_graph.api.dependencies import (
    AuditActorDep,
    CurrentUserDep,
    SessionDep,
    SettingsDep,
    TenantIdDep,
    TenantMemberDep,
)
from flint_graph.api.narrative_character_schemas import (
    CHARACTER_ID,
    AssetResponse,
    ProfileResponse,
)
from flint_graph.api.routes.narrative import _persist
from flint_graph.api.routes.narrative_characters import _profile
from flint_graph.application.services.narrative_voices import (
    cancel_voice_job,
    create_voice_job,
    get_voice_job,
    list_voice_jobs,
    set_character_voice,
)
from flint_graph.infrastructure.db.models import NarrativeAsset, NarrativeVoiceJob
from flint_graph.narrative.voices import MAX_ITEMS, TEXT_LIMIT, VOICES

router = APIRouter(prefix="/v1/narrative/projects/{project_id}", tags=["narrative"])
CharacterId = Annotated[str, Path(pattern=CHARACTER_ID)]


class VoiceOption(BaseModel):
    id: str
    name: str
    accent: str
    gender: str


class VoiceCatalog(BaseModel):
    available: bool
    voices: list[VoiceOption]


class VoiceChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version: int = Field(ge=0)
    voice: str | None = Field(max_length=32)


class VoiceItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["full", "vocalization"]
    text: str = Field(min_length=1, max_length=TEXT_LIMIT)
    node_id: str | None = Field(default=None, pattern=CHARACTER_ID)


class VoiceJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[VoiceItemCreate] = Field(min_length=1, max_length=MAX_ITEMS)
    idempotency_key: UUID


class VoiceJobResponse(BaseModel):
    id: UUID
    character_id: str
    voice: str
    speed: float
    status: str
    progress: int
    count: int
    cancel_requested: bool
    error_code: str | None
    items: list[dict[str, Any]]
    model: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    assets: list[AssetResponse]


class VoiceJobListResponse(BaseModel):
    jobs: list[VoiceJobResponse]


def voice_job_response(job: NarrativeVoiceJob, assets: list[NarrativeAsset]) -> VoiceJobResponse:
    return VoiceJobResponse(
        id=job.id,
        character_id=job.character_id,
        voice=job.voice,
        speed=job.speed,
        status=job.status,
        progress=job.progress,
        count=job.count,
        cancel_requested=job.cancel_requested,
        error_code=job.error_code,
        items=list(job.items),
        model=job.model,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        assets=[AssetResponse.model_validate(asset) for asset in assets],
    )


@router.get("/voices", response_model=VoiceCatalog)
async def voice_catalog(
    project_id: UUID, tenant_id: TenantIdDep, settings: SettingsDep
) -> VoiceCatalog:
    return VoiceCatalog(
        available=settings.narrative_voice_generation_enabled,
        voices=[VoiceOption(**voice.__dict__) for voice in VOICES],
    )


@router.put("/characters/{character_id}/voice", response_model=ProfileResponse)
async def choose_character_voice(
    project_id: UUID,
    character_id: CharacterId,
    payload: VoiceChoice,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> ProfileResponse:
    row, portrait = await _persist(
        session,
        set_character_voice(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            base_version=payload.base_version,
            voice=payload.voice,
            author_user_id=current_user.user.id,
        ),
    )
    return _profile(row, portrait)


@router.post(
    "/characters/{character_id}/voice-jobs", response_model=VoiceJobResponse, status_code=202
)
async def create_character_voice_job(
    project_id: UUID,
    character_id: CharacterId,
    payload: VoiceJobCreate,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    actor: AuditActorDep,
) -> VoiceJobResponse:
    job = await _persist(
        session,
        create_voice_job(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            author_user_id=current_user.user.id,
            items=[item.model_dump() for item in payload.items],
            idempotency_key=payload.idempotency_key,
            actor=actor,
            available=settings.narrative_voice_generation_enabled,
            max_active_jobs=settings.narrative_voice_max_active_jobs_per_workspace,
        ),
    )
    return voice_job_response(job, [])


@router.get("/voice-jobs", response_model=VoiceJobListResponse)
async def list_voice_jobs_endpoint(
    project_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    character_id: Annotated[str | None, Query(pattern=CHARACTER_ID)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> VoiceJobListResponse:
    rows = await list_voice_jobs(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        limit=limit,
    )
    return VoiceJobListResponse(jobs=[voice_job_response(job, assets) for job, assets in rows])


@router.get("/voice-jobs/{job_id}", response_model=VoiceJobResponse)
async def get_voice_job_endpoint(
    project_id: UUID, job_id: UUID, tenant_id: TenantIdDep, session: SessionDep
) -> VoiceJobResponse:
    job, assets = await get_voice_job(
        session, tenant_id=tenant_id, project_id=project_id, job_id=job_id
    )
    return voice_job_response(job, assets)


@router.post("/voice-jobs/{job_id}/cancel", response_model=VoiceJobResponse)
async def cancel_voice_job_endpoint(
    project_id: UUID,
    job_id: UUID,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> VoiceJobResponse:
    job = await _persist(
        session,
        cancel_voice_job(
            session, tenant_id=tenant_id, project_id=project_id, job_id=job_id, actor=actor
        ),
    )
    _, assets = await get_voice_job(
        session, tenant_id=tenant_id, project_id=project_id, job_id=job.id
    )
    return voice_job_response(job, assets)
