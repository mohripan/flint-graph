"""Authenticated private style training; weights have no public download route."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select

from flint_graph.api.dependencies import (
    CurrentUserDep,
    SessionDep,
    SettingsDep,
    TenantIdDep,
    TenantMemberDep,
)
from flint_graph.api.routes.narrative import _persist
from flint_graph.application.services.narrative_projects import get_project
from flint_graph.application.services.narrative_styles import (
    cancel_style,
    get_style,
    queue_style,
    response,
)
from flint_graph.infrastructure.db.narrative_style_models import NarrativeStyleJob
from flint_graph.narrative.imagegen import content_policy

router = APIRouter(prefix="/v1/narrative/projects/{project_id}/style-jobs", tags=["narrative"])


class TrainingImage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: UUID
    caption: str = Field(min_length=1, max_length=600)


class StyleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=80, pattern=r"\S")
    images: list[TrainingImage] = Field(min_length=4, max_length=12)
    rights_confirmed: StrictBool
    steps: int = Field(default=200, ge=20, le=400)
    seed: int = Field(default=42, ge=0, le=4294967295)
    idempotency_key: UUID = Field(strict=False)


@router.post("", status_code=202)
async def create(
    project_id: UUID,
    payload: StyleCreate,
    tenant_id: TenantMemberDep,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    row = await _persist(
        session,
        queue_style(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            author_user_id=user.user.id,
            available=settings.narrative_style_training_enabled,
            model_manifest_sha256=settings.narrative_pose_model_manifest_sha256,
            policy=content_policy(settings.narrative_image_content_policy),
            **payload.model_dump(),
        ),
    )
    return response(row)


@router.get("")
async def listing(
    project_id: UUID, tenant_id: TenantIdDep, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    jobs = await session.scalars(
        select(NarrativeStyleJob)
        .where(NarrativeStyleJob.tenant_id == tenant_id, NarrativeStyleJob.project_id == project_id)
        .order_by(NarrativeStyleJob.created_at.desc(), NarrativeStyleJob.id.desc())
        .limit(30)
    )
    return {
        "jobs": [response(row) for row in jobs],
        "available": bool(
            settings.narrative_style_training_enabled
            and settings.narrative_pose_model_manifest_sha256
        ),
    }


@router.get("/{job_id}")
async def detail(
    project_id: UUID, job_id: UUID, tenant_id: TenantIdDep, session: SessionDep
) -> dict[str, Any]:
    return response(
        await get_style(session, tenant_id=tenant_id, project_id=project_id, job_id=job_id)
    )


@router.post("/{job_id}/cancel")
async def cancel(
    project_id: UUID, job_id: UUID, tenant_id: TenantMemberDep, session: SessionDep
) -> dict[str, Any]:
    row = await _persist(
        session, cancel_style(session, tenant_id=tenant_id, project_id=project_id, job_id=job_id)
    )
    return response(row)
