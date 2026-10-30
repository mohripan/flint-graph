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
    NarrativeReleaseEventResponse,
    NarrativeReleaseJobSummary,
    NarrativeReleaseResponse,
    NarrativeReleaseRetry,
)
from flint_graph.api.routes.narrative import _persist
from flint_graph.application.services.narrative_releases import (
    BuildIdentity,
    cancel_release_job,
    create_release,
    get_release,
    get_release_job,
    latest_job,
    list_release_events,
    list_release_jobs,
    list_releases,
    retry_release,
)
from flint_graph.config import Settings
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


def build_identity(settings: Settings) -> BuildIdentity | None:
    if (
        settings.narrative_releases_enabled
        and settings.narrative_release_builder_image_digest
        and settings.narrative_release_toolchain_sha256
    ):
        return BuildIdentity(
            builder_image_digest=settings.narrative_release_builder_image_digest,
            toolchain_sha256=settings.narrative_release_toolchain_sha256,
        )
    return None


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
    build = build_identity(settings)
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


@router.get("/{release_id}", response_model=NarrativeReleaseResponse)
async def get_release_endpoint(
    project_id: UUID,
    release_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    include_archived: bool = False,
) -> NarrativeReleaseResponse:
    release = await get_release(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        release_id=release_id,
        include_archived=include_archived,
    )
    return response(release, await latest_job(session, release))


@router.post("/{release_id}/retry", response_model=NarrativeReleaseResponse, status_code=202)
async def retry_release_endpoint(
    project_id: UUID,
    release_id: UUID,
    payload: NarrativeReleaseRetry,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    settings: SettingsDep,
    actor: AuditActorDep,
) -> NarrativeReleaseResponse:
    release, job = await _persist(
        session,
        retry_release(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            release_id=release_id,
            idempotency_key=payload.idempotency_key,
            build=build_identity(settings),
            actor=actor,
            max_active_jobs=settings.narrative_release_max_active_jobs_per_workspace,
        ),
    )
    return response(release, job)


@router.post("/{release_id}/jobs/{job_id}/cancel", response_model=NarrativeReleaseJobSummary)
async def cancel_release_job_endpoint(
    project_id: UUID,
    release_id: UUID,
    job_id: UUID,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> NarrativeReleaseJobSummary:
    job = await _persist(
        session,
        cancel_release_job(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            release_id=release_id,
            job_id=job_id,
            actor=actor,
        ),
    )
    return NarrativeReleaseJobSummary.model_validate(job)


@router.get("/{release_id}/jobs", response_model=list[NarrativeReleaseJobSummary])
async def list_release_jobs_endpoint(
    project_id: UUID,
    release_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    limit: int = Query(default=25, ge=1, le=100),
    before_id: UUID | None = None,
    include_archived: bool = False,
) -> list[NarrativeReleaseJobSummary]:
    release = await get_release(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        release_id=release_id,
        include_archived=include_archived,
    )
    return [
        NarrativeReleaseJobSummary.model_validate(job)
        for job in await list_release_jobs(session, release, limit=limit, before_id=before_id)
    ]


@router.get("/{release_id}/jobs/{job_id}", response_model=NarrativeReleaseJobSummary)
async def get_release_job_endpoint(
    project_id: UUID,
    release_id: UUID,
    job_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    include_archived: bool = False,
) -> NarrativeReleaseJobSummary:
    release = await get_release(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        release_id=release_id,
        include_archived=include_archived,
    )
    return NarrativeReleaseJobSummary.model_validate(
        await get_release_job(session, release, job_id)
    )


@router.get(
    "/{release_id}/jobs/{job_id}/events", response_model=list[NarrativeReleaseEventResponse]
)
async def list_release_events_endpoint(
    project_id: UUID,
    release_id: UUID,
    job_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    after_sequence: int = Query(default=0, ge=0, le=2**31 - 1),
    limit: int = Query(default=100, ge=1, le=100),
    include_archived: bool = False,
) -> list[NarrativeReleaseEventResponse]:
    release = await get_release(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        release_id=release_id,
        include_archived=include_archived,
    )
    events = await list_release_events(
        session, release, job_id=job_id, after_sequence=after_sequence, limit=limit
    )
    return [NarrativeReleaseEventResponse.model_validate(event) for event in events]
