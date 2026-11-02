"""Authenticated private style training; weights have no public download route."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select

from flint_graph.api.dependencies import (
    CurrentUserDep,
    NarrativeArtifactStoreDep,
    SessionDep,
    SettingsDep,
    TenantIdDep,
    TenantMemberDep,
)
from flint_graph.api.routes.narrative import _persist
from flint_graph.api.routes.narrative_looks import get_look_tagger
from flint_graph.application.services.narrative_character_adapters import details, list_details
from flint_graph.application.services.narrative_characters import get_asset
from flint_graph.application.services.narrative_look_tags import record_observation
from flint_graph.application.services.narrative_projects import get_project
from flint_graph.application.services.narrative_styles import (
    cancel_style,
    get_style,
    queue_style,
    response,
)
from flint_graph.application.services.narrative_training_captions import caption_suggestion
from flint_graph.domain.errors import ConflictError, DomainError
from flint_graph.infrastructure.db.models import NarrativeAsset
from flint_graph.infrastructure.db.narrative_style_models import NarrativeStyleJob
from flint_graph.infrastructure.narrative_artifact_store import ArtifactStoreError, asset_object_key
from flint_graph.infrastructure.narrative_look_tagger import LookTagger, unavailable
from flint_graph.narrative.imagegen import content_policy

router = APIRouter(prefix="/v1/narrative/projects/{project_id}/style-jobs", tags=["narrative"])


class TrainingImage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: UUID
    caption: str = Field(min_length=1, max_length=600)


class CharacterTrainingTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    look_id: UUID
    same_look_confirmed: StrictBool
    anatomy_reviewed: StrictBool


class StyleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=80, pattern=r"\S")
    character_look: CharacterTrainingTarget | None = None
    images: list[TrainingImage] = Field(min_length=4, max_length=12)
    rights_confirmed: StrictBool
    steps: int = Field(default=200, ge=20, le=400)
    seed: int = Field(default=42, ge=0, le=4294967295)
    idempotency_key: UUID = Field(strict=False)


class CaptionSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: UUID


def caption_source(asset: NarrativeAsset) -> None:
    if (
        asset.status != "approved"
        or asset.media_type != "image/png"
        or not 64 <= (asset.width or 0) <= 2560
        or not 64 <= (asset.height or 0) <= 2560
        or asset.size_bytes > 8 * 1024 * 1024
    ):
        raise DomainError(
            422,
            "Invalid training image",
            "Choose an approved PNG training image.",
            "training-caption-image-invalid",
        )


@router.post("/caption-suggestions")
async def suggest_caption(
    project_id: UUID,
    payload: CaptionSuggestionRequest,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    store: NarrativeArtifactStoreDep,
    settings: SettingsDep,
    tagger: Annotated[LookTagger, Depends(get_look_tagger)],
) -> dict[str, Any]:
    project = await get_project(session, tenant_id=tenant_id, project_id=project_id)
    if project.archived_at is not None:
        raise ConflictError("Restore this project before suggesting training captions.")
    asset = await get_asset(
        session, tenant_id=tenant_id, project_id=project_id, asset_id=payload.asset_id
    )
    caption_source(asset)
    source_sha256 = asset.sha256
    try:
        data = await store.get_verified(
            asset_object_key(
                tenant_id=tenant_id, project_id=project_id, asset_id=asset.id, variant="image"
            ),
            expected_size=asset.size_bytes,
            expected_sha256=source_sha256,
            max_bytes=8 * 1024 * 1024,
        )
    except (ArtifactStoreError, ValueError):
        raise unavailable(
            "The approved training image is unavailable. Choose another image."
        ) from None
    # Do not hold the request's authentication/read transaction while CPU tagging
    # runs. Source and project state are checked again before observation writes.
    await session.commit()
    result = await tagger.tag(data)
    # Revalidate under the same project lock used by discard/archive and training.
    await get_project(session, tenant_id=tenant_id, project_id=project_id, for_update=True)
    await session.refresh(asset)
    caption_source(asset)
    row = await _persist(
        session,
        record_observation(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id="",
            asset_id=asset.id,
            source_sha256=source_sha256,
            result=result,
            approved_only=False,
        ),
    )
    return {
        **caption_suggestion(
            row.observation, content_policy(settings.narrative_image_content_policy)
        ),
        "asset_id": str(asset.id),
        "source_sha256": source_sha256,
        "observation_id": str(row.id),
        "model_manifest_sha256": result["model_manifest_sha256"],
        "tagger_sha256": result["tagger_sha256"],
    }


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
    return {**response(row), **await details(session, row)}


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
    rows = list(jobs)
    targets = await list_details(session, rows)
    return {
        "jobs": [{**response(row), **targets[row.id]} for row in rows],
        "available": bool(
            settings.narrative_style_training_enabled
            and settings.narrative_pose_model_manifest_sha256
        ),
        "caption_suggestions": bool(
            settings.narrative_look_tagger_python and settings.narrative_look_tagger_model_dir
        ),
    }


@router.get("/{job_id}")
async def detail(
    project_id: UUID, job_id: UUID, tenant_id: TenantIdDep, session: SessionDep
) -> dict[str, Any]:
    row = await get_style(session, tenant_id=tenant_id, project_id=project_id, job_id=job_id)
    return {**response(row), **await details(session, row)}


@router.post("/{job_id}/cancel")
async def cancel(
    project_id: UUID, job_id: UUID, tenant_id: TenantMemberDep, session: SessionDep
) -> dict[str, Any]:
    row = await _persist(
        session, cancel_style(session, tenant_id=tenant_id, project_id=project_id, job_id=job_id)
    )
    return {**response(row), **await details(session, row)}
