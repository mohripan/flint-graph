"""Explicit pose jobs from an approved reviewed look."""

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.api.dependencies import (
    AuditActorDep,
    CurrentUserDep,
    SessionDep,
    SettingsDep,
    TenantIdDep,
    TenantMemberDep,
)
from flint_graph.api.routes.narrative import _persist
from flint_graph.api.routes.narrative_characters import job_response
from flint_graph.api.routes.narrative_looks import CharacterId
from flint_graph.application.services.narrative_poses import queue_pose_job
from flint_graph.application.services.narrative_projects import get_project
from flint_graph.infrastructure.db.models import NarrativeAsset, NarrativeImageJob
from flint_graph.infrastructure.db.narrative_look_models import NarrativeLookJob
from flint_graph.infrastructure.db.narrative_pose_models import (
    NarrativePoseJob,
    NarrativePoseReference,
)
from flint_graph.narrative.imagegen import content_policy
from flint_graph.narrative.poses import MODEL_ID

router = APIRouter(
    prefix="/v1/narrative/projects/{project_id}/characters/{character_id}/looks", tags=["narrative"]
)


class PoseReferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: UUID
    view: Literal["front", "side", "back", "detail"]


class PoseStyleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    strength: float = Field(default=0.5, ge=0.1, le=1, strict=True)


class PoseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    look_id: UUID
    style_adapter: PoseStyleInput | None = None
    character_adapter: PoseStyleInput | None = None
    additional_references: list[PoseReferenceInput] = Field(default_factory=list, max_length=1)
    pose: str = Field(min_length=1, max_length=300)
    count: int = Field(default=1, ge=1, le=4)
    transparent: StrictBool = True
    idempotency_key: UUID


async def pose_response(session: AsyncSession, job: NarrativeImageJob) -> dict[str, Any]:
    plan = await session.get(NarrativePoseJob, job.id)
    assert plan is not None
    snapshot = await session.get(NarrativeLookJob, (job.id, plan.character_id))
    assert snapshot is not None
    assets = list(
        await session.scalars(
            select(NarrativeAsset)
            .where(NarrativeAsset.job_id == job.id, NarrativeAsset.status != "discarded")
            .order_by(NarrativeAsset.job_index)
        )
    )
    references = list(
        await session.scalars(
            select(NarrativePoseReference)
            .where(NarrativePoseReference.job_id == job.id)
            .order_by(NarrativePoseReference.position)
        )
    )
    frozen = [
        {
            "asset_id": str(row.asset_id),
            "sha256": row.sha256,
            "view": row.view,
            "name": row.name,
            "size_bytes": row.size_bytes,
        }
        for row in references
    ]
    if not frozen:
        # Jobs admitted before migration 0036 keep their original single source.
        frozen = [
            {
                "asset_id": snapshot.snapshot["asset_id"],
                "sha256": snapshot.snapshot["source_sha256"],
                "view": "primary",
                "name": snapshot.snapshot["name"],
            }
        ]
    from flint_graph.infrastructure.db.narrative_style_models import (
        NarrativePoseStyle,
        NarrativeStyleJob,
    )

    binding = await session.get(NarrativePoseStyle, job.id)
    style = await session.get(NarrativeStyleJob, binding.style_id) if binding else None
    from flint_graph.application.services.narrative_character_adapters import details

    target = await details(session, style) if style else {}
    from flint_graph.infrastructure.db.narrative_character_adapter_models import (
        NarrativePoseCharacterAdapter,
    )

    character_binding = await session.get(NarrativePoseCharacterAdapter, job.id)
    character = (
        await session.get(NarrativeStyleJob, character_binding.adapter_id)
        if character_binding
        else None
    )
    return {
        "character_adapter": {
            **(await details(session, character)),
            "id": str(character.id),
            "name": character.name,
            "strength": character_binding.strength,
            "weights_sha256": character_binding.weights_sha256,
        }
        if character and character_binding
        else None,
        "style_adapter": {
            **target,
            "id": str(style.id),
            "name": style.name,
            "strength": binding.strength,
            "weights_sha256": binding.weights_sha256,
        }
        if style and binding
        else None,
        "references": frozen,
        "operation": "pose",
        "model_id": MODEL_ID,
        "model_manifest_sha256": plan.model_manifest_sha256,
        "pose": plan.pose,
        "look": snapshot.snapshot,
        "job": job_response(job, assets),
    }


@router.post("/pose-jobs", status_code=202)
async def create_pose_endpoint(
    project_id: UUID,
    character_id: CharacterId,
    payload: PoseCreate,
    tenant_id: TenantMemberDep,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    actor: AuditActorDep,
) -> dict[str, Any]:
    job = await _persist(
        session,
        queue_pose_job(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            author_user_id=user.user.id,
            actor=actor,
            available=settings.narrative_pose_generation_enabled,
            styles_enabled=settings.narrative_style_training_enabled,
            max_references=settings.narrative_pose_max_references,
            max_adapters=settings.narrative_pose_max_adapters,
            max_active_jobs=settings.narrative_image_max_active_jobs_per_workspace,
            policy=content_policy(settings.narrative_image_content_policy),
            model_manifest_sha256=settings.narrative_pose_model_manifest_sha256,
            cutout_manifest_sha256=settings.narrative_image_cutout_manifest_sha256,
            **payload.model_dump(),
        ),
    )
    return await pose_response(session, job)


@router.get("/pose-jobs")
async def list_pose_endpoint(
    project_id: UUID,
    character_id: CharacterId,
    tenant_id: TenantIdDep,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    jobs = await session.scalars(
        select(NarrativeImageJob)
        .join(NarrativePoseJob, NarrativePoseJob.job_id == NarrativeImageJob.id)
        .where(
            NarrativePoseJob.tenant_id == tenant_id,
            NarrativePoseJob.project_id == project_id,
            NarrativePoseJob.character_id == character_id,
        )
        .order_by(NarrativeImageJob.created_at.desc(), NarrativeImageJob.id.desc())
        .limit(30)
    )
    return {
        "jobs": [await pose_response(session, job) for job in jobs],
        "capabilities": {
            "available": bool(
                settings.narrative_pose_generation_enabled
                and settings.narrative_pose_model_manifest_sha256
            ),
            "transparent": bool(settings.narrative_image_cutout_manifest_sha256),
            "model_id": MODEL_ID,
            "max_references": settings.narrative_pose_max_references,
            "max_adapters": settings.narrative_pose_max_adapters,
            "styles": settings.narrative_style_training_enabled,
            "character_training": settings.narrative_style_training_enabled,
        },
    }
