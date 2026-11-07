"""Generated music jobs for one project (ADR 0067)."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from flint_graph.api.dependencies import (
    AuditActorDep,
    CurrentUserDep,
    SessionDep,
    SettingsDep,
    TenantIdDep,
    TenantMemberDep,
)
from flint_graph.api.narrative_character_schemas import AssetResponse
from flint_graph.api.routes.narrative import _persist
from flint_graph.application.services.narrative_music import (
    cancel_music_job,
    create_music_job,
    get_music_job,
    list_music_jobs,
)
from flint_graph.infrastructure.db.models import NarrativeAsset, NarrativeMusicJob
from flint_graph.infrastructure.narrative_musicgen import (
    DESCRIPTION_LIMIT,
    MAX_SECONDS,
    MIN_SECONDS,
)

router = APIRouter(prefix="/v1/narrative/projects/{project_id}", tags=["narrative"])


class MusicJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1, max_length=DESCRIPTION_LIMIT)
    seconds: int = Field(default=60, ge=MIN_SECONDS, le=MAX_SECONDS)
    idempotency_key: UUID


class MusicJobResponse(BaseModel):
    id: UUID
    description: str
    seconds: int
    status: str
    progress: int
    count: int = 1
    cancel_requested: bool
    error_code: str | None
    model: str | None
    runtime: dict[str, str] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    assets: list[AssetResponse]


class MusicJobListResponse(BaseModel):
    available: bool
    min_seconds: int = MIN_SECONDS
    max_seconds: int = MAX_SECONDS
    jobs: list[MusicJobResponse]


def music_job_response(job: NarrativeMusicJob, assets: list[NarrativeAsset]) -> MusicJobResponse:
    return MusicJobResponse(
        id=job.id,
        description=job.description,
        seconds=job.seconds,
        status=job.status,
        progress=job.progress,
        cancel_requested=job.cancel_requested,
        error_code=job.error_code,
        model=job.model,
        runtime=job.runtime,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        assets=[AssetResponse.model_validate(asset) for asset in assets],
    )


@router.post("/music-jobs", response_model=MusicJobResponse, status_code=201)
async def create_music_job_endpoint(
    project_id: UUID,
    payload: MusicJobCreate,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    actor: AuditActorDep,
) -> MusicJobResponse:
    job = await _persist(
        session,
        create_music_job(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            author_user_id=current_user.user.id,
            description=payload.description,
            seconds=payload.seconds,
            idempotency_key=payload.idempotency_key,
            actor=actor,
            available=settings.narrative_music_generation_enabled,
            max_active_jobs=settings.narrative_music_max_active_jobs_per_workspace,
        ),
    )
    return music_job_response(job, [])


@router.get("/music-jobs", response_model=MusicJobListResponse)
async def list_music_jobs_endpoint(
    project_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> MusicJobListResponse:
    rows = await list_music_jobs(session, tenant_id=tenant_id, project_id=project_id, limit=limit)
    return MusicJobListResponse(
        available=settings.narrative_music_generation_enabled,
        jobs=[music_job_response(job, assets) for job, assets in rows],
    )


@router.get("/music-jobs/{job_id}", response_model=MusicJobResponse)
async def get_music_job_endpoint(
    project_id: UUID, job_id: UUID, tenant_id: TenantIdDep, session: SessionDep
) -> MusicJobResponse:
    job, assets = await get_music_job(
        session, tenant_id=tenant_id, project_id=project_id, job_id=job_id
    )
    return music_job_response(job, assets)


@router.post("/music-jobs/{job_id}/cancel", response_model=MusicJobResponse)
async def cancel_music_job_endpoint(
    project_id: UUID,
    job_id: UUID,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> MusicJobResponse:
    job = await _persist(
        session,
        cancel_music_job(
            session, tenant_id=tenant_id, project_id=project_id, job_id=job_id, actor=actor
        ),
    )
    _, assets = await get_music_job(
        session, tenant_id=tenant_id, project_id=project_id, job_id=job_id
    )
    return music_job_response(job, assets)
