"""Project asset library: list, upload, rename, approve and generate backgrounds (ADR 0040).

Viewers read; members change. Upload bytes are validated for their kind and stored
create-only and hash-verified before the row is written; the uploader's rights
declaration is recorded, not verified.
"""

from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Query, Response, UploadFile

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
    AssetListResponse,
    AssetRename,
    AssetResponse,
    BackgroundJobCreate,
    ImageJobListResponse,
    ImageJobResponse,
)
from flint_graph.api.routes.narrative import _persist
from flint_graph.api.routes.narrative_characters import job_response
from flint_graph.application.services.narrative_asset_library import (
    approve_asset,
    check_uploadable,
    find_duplicate,
    inspect_upload_bounded,
    list_assets,
    record_upload,
    rename_asset,
    upload_limit,
)
from flint_graph.application.services.narrative_images import (
    create_background_job,
    list_image_jobs,
)
from flint_graph.domain.errors import DomainError, PayloadTooLargeError
from flint_graph.infrastructure.narrative_artifact_store import (
    ArtifactStoreError,
    asset_object_key,
)
from flint_graph.narrative.imagegen import content_policy

router = APIRouter(prefix="/v1/narrative/projects/{project_id}/assets", tags=["narrative"])
Kind = Literal["character_portrait", "background", "sprite", "image", "font"]


def _text(value: str, field: str, *, limit: int, required: bool) -> str:
    text = value.strip()
    if (required and not text) or len(text) > limit:
        raise DomainError(422, "Invalid asset", f"Check the {field}.", "invalid-asset")
    return text


@router.get("", response_model=AssetListResponse)
async def list_assets_endpoint(
    project_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    kind: Kind | None = None,
    status: Literal["candidate", "approved", "discarded"] | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: UUID | None = None,
) -> AssetListResponse:
    rows = await list_assets(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        kind=kind,
        status=status,
        limit=limit,
        before=before,
    )
    return AssetListResponse(
        assets=[AssetResponse.model_validate(row) for row in rows],
        next_before=rows[-1].id if len(rows) == limit else None,
    )


@router.post("", response_model=AssetResponse, status_code=201)
async def upload_asset_endpoint(
    project_id: UUID,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    store: NarrativeArtifactStoreDep,
    response: Response,
    file: Annotated[UploadFile, File()],
    kind: Annotated[str, Form()],
    name: Annotated[str, Form(max_length=400)],
    license: Annotated[str, Form(max_length=400)],
    rights_declared: Annotated[bool, Form()],
    notice: Annotated[str, Form(max_length=8000)] = "",
) -> AssetResponse:
    if not rights_declared:
        raise DomainError(
            422,
            "Rights not declared",
            "Confirm you made this file or have the right to use it in your game.",
            "invalid-asset",
        )
    clean_name = _text(name, "name", limit=120, required=True)
    clean_license = _text(license, "license", limit=120, required=True)
    clean_notice = _text(notice, "notice", limit=4000, required=False)
    if kind not in ("background", "sprite", "image", "font"):
        raise DomainError(
            422, "Invalid asset", "Choose background, sprite, image or font.", "invalid-asset"
        )
    limit = upload_limit(kind)
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise PayloadTooLargeError("This file is larger than the asset limit.")
    upload = await inspect_upload_bounded(kind, data)
    await check_uploadable(session, tenant_id=tenant_id, project_id=project_id)
    existing = await find_duplicate(
        session, tenant_id=tenant_id, project_id=project_id, upload=upload
    )
    if existing is not None:
        # The same bytes are already in the library; bind to that one asset.
        response.status_code = 200
        return AssetResponse.model_validate(existing)
    asset_id = uuid4()
    try:
        await store.put_once(
            asset_object_key(
                tenant_id=tenant_id,
                project_id=project_id,
                asset_id=asset_id,
                variant="font" if kind == "font" else "image",
            ),
            upload.data,
            expected_sha256=upload.sha256,
            content_type=upload.media_type,
            max_bytes=limit,
        )
    except (ArtifactStoreError, ValueError):
        raise DomainError(
            503, "Service unavailable", "The file could not be stored.", "asset-unavailable"
        ) from None
    asset = await _persist(
        session,
        record_upload(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            asset_id=asset_id,
            upload=upload,
            name=clean_name,
            license=clean_license,
            notice=clean_notice,
            author_user_id=current_user.user.id,
        ),
    )
    return AssetResponse.model_validate(asset)


@router.patch("/{asset_id}", response_model=AssetResponse)
async def rename_asset_endpoint(
    project_id: UUID,
    asset_id: UUID,
    payload: AssetRename,
    tenant_id: TenantMemberDep,
    session: SessionDep,
) -> AssetResponse:
    name = _text(payload.name, "name", limit=120, required=True)
    asset = await _persist(
        session,
        rename_asset(
            session, tenant_id=tenant_id, project_id=project_id, asset_id=asset_id, name=name
        ),
    )
    return AssetResponse.model_validate(asset)


@router.post("/{asset_id}/approve", response_model=AssetResponse)
async def approve_asset_endpoint(
    project_id: UUID,
    asset_id: UUID,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> AssetResponse:
    asset = await _persist(
        session,
        approve_asset(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            asset_id=asset_id,
            author_user_id=current_user.user.id,
        ),
    )
    return AssetResponse.model_validate(asset)


@router.post("/background-jobs", response_model=ImageJobResponse, status_code=202)
async def create_background_job_endpoint(
    project_id: UUID,
    payload: BackgroundJobCreate,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    actor: AuditActorDep,
) -> ImageJobResponse:
    job = await _persist(
        session,
        create_background_job(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            author_user_id=current_user.user.id,
            description=payload.description,
            count=payload.count,
            idempotency_key=payload.idempotency_key,
            actor=actor,
            available=settings.narrative_image_generation_enabled,
            max_active_jobs=settings.narrative_image_max_active_jobs_per_workspace,
            policy=content_policy(settings.narrative_image_content_policy),
        ),
    )
    return job_response(job, [])


@router.get("/background-jobs", response_model=ImageJobListResponse)
async def list_background_jobs_endpoint(
    project_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> ImageJobListResponse:
    rows = await list_image_jobs(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        purpose="background",
        character_id=None,
        limit=limit,
    )
    return ImageJobListResponse(jobs=[job_response(job, assets) for job, assets in rows])
