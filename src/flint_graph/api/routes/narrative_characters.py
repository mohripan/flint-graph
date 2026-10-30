"""Characters: appearance, local portrait jobs and approved images (ADR 0039).

Viewers read; members edit, generate, choose and discard. Generation is queued as
a durable job and never runs inside a request. Image bytes are served only after
their stored SHA-256 and size verify.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Path, Query
from fastapi.responses import Response

from flint_graph.api.dependencies import (
    AuditActorDep,
    CurrentUserDep,
    NarrativeArtifactStoreDep,
    SessionDep,
    SettingsDep,
    TenantIdDep,
    TenantMemberDep,
)
from flint_graph.api.narrative_character_schemas import (
    CHARACTER_ID,
    AssetResponse,
    ImageJobListResponse,
    ImageJobResponse,
    PortraitChoice,
    PortraitJobCreate,
    ProfileListResponse,
    ProfileResponse,
    ProfileWrite,
)
from flint_graph.api.routes.narrative import _persist
from flint_graph.application.services.narrative_characters import (
    choose_portrait,
    discard_asset,
    get_asset,
    list_profiles,
    save_profile,
)
from flint_graph.application.services.narrative_images import (
    cancel_image_job,
    create_portrait_job,
    get_image_job,
    list_portrait_jobs,
)
from flint_graph.application.services.narrative_projects import get_project
from flint_graph.domain.errors import DomainError
from flint_graph.infrastructure.db.models import (
    NarrativeAsset,
    NarrativeCharacterProfile,
    NarrativeImageJob,
)
from flint_graph.infrastructure.narrative_artifact_store import (
    ArtifactStoreError,
    asset_object_key,
)
from flint_graph.infrastructure.narrative_imagegen import IMAGE_LIMIT, THUMBNAIL_LIMIT

router = APIRouter(prefix="/v1/narrative/projects/{project_id}", tags=["narrative"])
CharacterId = Annotated[str, Path(pattern=CHARACTER_ID)]


def _profile(row: NarrativeCharacterProfile, portrait: NarrativeAsset | None) -> ProfileResponse:
    return ProfileResponse(
        character_id=row.character_id,
        appearance=row.appearance,
        character_type=row.character_type,
        framing=row.framing,
        portrait=AssetResponse.model_validate(portrait) if portrait is not None else None,
        version=row.version,
    )


def _job(job: NarrativeImageJob, assets: list[NarrativeAsset]) -> ImageJobResponse:
    return ImageJobResponse(
        id=job.id,
        character_id=job.character_id,
        status=job.status,
        progress=job.progress,
        count=job.count,
        cancel_requested=job.cancel_requested,
        error_code=job.error_code,
        appearance=job.appearance,
        character_type=job.character_type,
        framing=job.framing,
        prompt=job.prompt,
        negative_prompt=job.negative_prompt,
        width=job.width,
        height=job.height,
        steps=job.steps,
        guidance=job.guidance,
        seeds=list(job.seeds),
        model=job.model,
        prompt_tokens=job.prompt_tokens,
        truncated=job.truncated,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        assets=[AssetResponse.model_validate(asset) for asset in assets],
    )


@router.get("/characters", response_model=ProfileListResponse)
async def list_character_profiles(
    project_id: UUID, tenant_id: TenantIdDep, session: SessionDep
) -> ProfileListResponse:
    rows = await list_profiles(session, tenant_id=tenant_id, project_id=project_id)
    return ProfileListResponse(
        project_id=project_id, profiles=[_profile(row, portrait) for row, portrait in rows]
    )


@router.put("/characters/{character_id}", response_model=ProfileResponse)
async def save_character_profile(
    project_id: UUID,
    character_id: CharacterId,
    payload: ProfileWrite,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> ProfileResponse:
    row, portrait = await _persist(
        session,
        save_profile(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            base_version=payload.base_version,
            appearance=payload.appearance,
            character_type=payload.character_type,
            framing=payload.framing,
            author_user_id=current_user.user.id,
        ),
    )
    return _profile(row, portrait)


@router.put("/characters/{character_id}/portrait", response_model=ProfileResponse)
async def choose_character_portrait(
    project_id: UUID,
    character_id: CharacterId,
    payload: PortraitChoice,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> ProfileResponse:
    row, portrait = await _persist(
        session,
        choose_portrait(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            base_version=payload.base_version,
            asset_id=payload.asset_id,
            author_user_id=current_user.user.id,
            actor=actor,
        ),
    )
    return _profile(row, portrait)


@router.post(
    "/characters/{character_id}/portrait-jobs", response_model=ImageJobResponse, status_code=202
)
async def create_character_portrait_job(
    project_id: UUID,
    character_id: CharacterId,
    payload: PortraitJobCreate,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    actor: AuditActorDep,
) -> ImageJobResponse:
    job = await _persist(
        session,
        create_portrait_job(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            author_user_id=current_user.user.id,
            appearance=payload.appearance,
            character_type=payload.character_type,
            framing=payload.framing,
            count=payload.count,
            idempotency_key=payload.idempotency_key,
            actor=actor,
            available=settings.narrative_image_generation_enabled,
            max_active_jobs=settings.narrative_image_max_active_jobs_per_workspace,
        ),
    )
    return _job(job, [])


@router.get("/characters/{character_id}/portrait-jobs", response_model=ImageJobListResponse)
async def list_character_portrait_jobs(
    project_id: UUID,
    character_id: CharacterId,
    tenant_id: TenantIdDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> ImageJobListResponse:
    rows = await list_portrait_jobs(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        limit=limit,
    )
    return ImageJobListResponse(jobs=[_job(job, assets) for job, assets in rows])


@router.get("/image-jobs/{job_id}", response_model=ImageJobResponse)
async def get_image_job_endpoint(
    project_id: UUID, job_id: UUID, tenant_id: TenantIdDep, session: SessionDep
) -> ImageJobResponse:
    job, assets = await get_image_job(
        session, tenant_id=tenant_id, project_id=project_id, job_id=job_id
    )
    return _job(job, assets)


@router.post("/image-jobs/{job_id}/cancel", response_model=ImageJobResponse)
async def cancel_image_job_endpoint(
    project_id: UUID,
    job_id: UUID,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> ImageJobResponse:
    job = await _persist(
        session,
        cancel_image_job(
            session, tenant_id=tenant_id, project_id=project_id, job_id=job_id, actor=actor
        ),
    )
    _, assets = await get_image_job(
        session, tenant_id=tenant_id, project_id=project_id, job_id=job.id
    )
    return _job(job, assets)


@router.post("/assets/{asset_id}/discard", response_model=AssetResponse)
async def discard_asset_endpoint(
    project_id: UUID,
    asset_id: UUID,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> AssetResponse:
    asset = await _persist(
        session,
        discard_asset(
            session, tenant_id=tenant_id, project_id=project_id, asset_id=asset_id, actor=actor
        ),
    )
    return AssetResponse.model_validate(asset)


@router.get("/assets/{asset_id}/content")
async def asset_content(
    project_id: UUID,
    asset_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    store: NarrativeArtifactStoreDep,
    variant: Literal["image", "thumbnail"] = "image",
) -> Response:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    asset = await get_asset(session, tenant_id=tenant_id, project_id=project_id, asset_id=asset_id)
    thumbnail = variant == "thumbnail"
    try:
        data = await store.get_verified(
            asset_object_key(
                tenant_id=tenant_id, project_id=project_id, asset_id=asset.id, variant=variant
            ),
            expected_size=asset.thumbnail_size_bytes if thumbnail else asset.size_bytes,
            expected_sha256=asset.thumbnail_sha256 if thumbnail else asset.sha256,
            max_bytes=THUMBNAIL_LIMIT if thumbnail else IMAGE_LIMIT,
        )
    except (ArtifactStoreError, ValueError):
        raise DomainError(
            503, "Service unavailable", "This image is unavailable.", "asset-unavailable"
        ) from None
    return Response(
        content=data,
        media_type="image/png",
        headers={
            # Bytes never change for an asset ID; viewers revalidate access per request.
            "Cache-Control": "private, max-age=31536000, immutable",
            "ETag": f'"{asset.thumbnail_sha256 if thumbnail else asset.sha256}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="{asset.id}-{variant}.png"',
        },
    )
