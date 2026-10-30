from uuid import UUID

from fastapi import APIRouter, Query

from flint_graph.api.dependencies import (
    AuditActorDep,
    CurrentUserDep,
    SessionDep,
    SettingsDep,
    TenantIdDep,
    TenantMemberDep,
)
from flint_graph.api.narrative_release_schemas import (
    NarrativeReleaseBuildIdentity,
    NarrativeReleaseCreate,
    NarrativeReleaseJobSummary,
    NarrativeReleaseResponse,
)
from flint_graph.api.routes.narrative import _persist
from flint_graph.application.services.narrative_releases import (
    BuildIdentity,
    create_release,
    list_releases,
)
from flint_graph.infrastructure.db.models import NarrativeRelease, NarrativeReleaseJob

router = APIRouter(prefix="/v1/narrative/projects/{project_id}/releases", tags=["narrative"])


def response(release: NarrativeRelease, job: NarrativeReleaseJob) -> NarrativeReleaseResponse:
    return NarrativeReleaseResponse(
        id=release.id,
        tenant_id=release.tenant_id,
        project_id=release.project_id,
        revision_id=release.revision_id,
        package_hash=release.package_hash,
        created_at=release.created_at,
        build_identity=NarrativeReleaseBuildIdentity.model_validate(release),
        job=NarrativeReleaseJobSummary.model_validate(job),
    )


@router.post("", response_model=NarrativeReleaseResponse, status_code=202)
async def create_release_endpoint(
    project_id: UUID,
    payload: NarrativeReleaseCreate,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    actor: AuditActorDep,
) -> NarrativeReleaseResponse:
    build = None
    if (
        settings.narrative_releases_enabled
        and settings.narrative_release_builder_image_digest
        and settings.narrative_release_toolchain_sha256
    ):
        build = BuildIdentity(
            builder_image_digest=settings.narrative_release_builder_image_digest,
            toolchain_sha256=settings.narrative_release_toolchain_sha256,
        )
    release, job = await _persist(
        session,
        create_release(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            revision_id=payload.revision_id,
            author_user_id=current_user.user.id,
            idempotency_key=payload.idempotency_key,
            build=build,
            actor=actor,
            max_active_jobs=settings.narrative_release_max_active_jobs_per_workspace,
        ),
    )
    return response(release, job)


@router.get("", response_model=list[NarrativeReleaseResponse])
async def list_releases_endpoint(
    project_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    limit: int = Query(default=25, ge=1, le=100),
    before_id: UUID | None = None,
    include_archived: bool = False,
) -> list[NarrativeReleaseResponse]:
    rows = await list_releases(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        limit=limit,
        before_id=before_id,
        include_archived=include_archived,
    )
    return [response(release, job) for release, job in rows]
