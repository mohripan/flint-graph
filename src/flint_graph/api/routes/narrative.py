from collections.abc import Awaitable
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.api.dependencies import (
    AuditActorDep,
    CurrentUserDep,
    SessionDep,
    SettingsDep,
    TenantAdminDep,
    TenantIdDep,
    TenantMemberDep,
)
from flint_graph.api.narrative_schemas import (
    NarrativeArchiveRequest,
    NarrativeProjectCreate,
    NarrativeProjectResponse,
    NarrativeRevisionCreate,
    NarrativeRevisionResponse,
    NarrativeRevisionSummary,
    NarrativeUpgradeRequest,
)
from flint_graph.application.services.narrative_projects import (
    archive_project,
    create_project,
    create_revision,
    get_project,
    get_revision,
    list_projects,
    list_revisions,
    upgrade_to_v2,
)
from flint_graph.domain.errors import DomainError

router = APIRouter(prefix="/v1/narrative/projects", tags=["narrative"])


async def _persist[T](session: AsyncSession, operation: Awaitable[T]) -> T:
    # Driver errors can contain the entire inserted story, even with hidden SQL
    # parameters. Commit inside this boundary rather than the dependency teardown.
    try:
        result = await operation
        await session.commit()
        return result
    except SQLAlchemyError:
        try:
            await session.rollback()
        except SQLAlchemyError:
            pass
        raise DomainError(
            503,
            "Service unavailable",
            "Narrative storage is unavailable. Retry with the same idempotency key.",
            "storage-unavailable",
        ) from None


@router.post("", response_model=NarrativeProjectResponse, status_code=201)
async def create_project_endpoint(
    payload: NarrativeProjectCreate,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    actor: AuditActorDep,
    settings: SettingsDep,
) -> NarrativeProjectResponse:
    project = await _persist(
        session,
        create_project(
            session,
            tenant_id=tenant_id,
            author_user_id=current_user.user.id,
            name=payload.name,
            idempotency_key=payload.idempotency_key,
            actor=actor,
            schema_version="2" if settings.narrative_package_v2_enabled else "1",
        ),
    )
    return NarrativeProjectResponse.model_validate(project)


@router.get("/{project_id}/revisions/{revision_id}", response_model=NarrativeRevisionResponse)
async def get_revision_endpoint(
    project_id: UUID,
    revision_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    include_archived: bool = False,
) -> NarrativeRevisionResponse:
    revision = await get_revision(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        revision_id=revision_id,
        include_archived=include_archived,
    )
    return NarrativeRevisionResponse.model_validate(revision)


@router.get("/{project_id}", response_model=NarrativeProjectResponse)
async def get_project_endpoint(
    project_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    include_archived: bool = False,
) -> NarrativeProjectResponse:
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, include_archived=include_archived
    )
    return NarrativeProjectResponse.model_validate(project)


@router.post("/{project_id}/revisions", response_model=NarrativeRevisionResponse, status_code=201)
async def create_revision_endpoint(
    project_id: UUID,
    payload: NarrativeRevisionCreate,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    actor: AuditActorDep,
    settings: SettingsDep,
) -> NarrativeRevisionResponse | JSONResponse:
    revision = await _persist(
        session,
        create_revision(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            author_user_id=current_user.user.id,
            actor=actor,
            allow_v2=settings.narrative_package_v2_enabled,
            asset_budget_bytes=settings.narrative_package_v2_asset_budget_bytes,
            **payload.model_dump(),
        ),
    )
    if revision.conflicted:
        # The conflict snapshot has committed. Raising a DomainError before commit
        # would silently discard the very work this response promises to preserve.
        return JSONResponse(
            status_code=409,
            media_type="application/problem+json",
            content={
                "type": "urn:flint-graph:error:stale-revision",
                "title": "Revision conflict",
                "status": 409,
                "detail": "Your edit was saved as a conflict revision. "
                "The current story is unchanged.",
                "errors": [
                    {
                        "code": "stale_revision",
                        "conflict_revision_id": str(revision.id),
                        "observed_head_revision_id": str(revision.observed_head_revision_id),
                    }
                ],
            },
        )
    return NarrativeRevisionResponse.model_validate(revision)


@router.post("/{project_id}/archive", response_model=NarrativeProjectResponse)
async def archive_project_endpoint(
    project_id: UUID,
    payload: NarrativeArchiveRequest,
    tenant_id: TenantAdminDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> NarrativeProjectResponse:
    project = await _persist(
        session,
        archive_project(
            session, tenant_id=tenant_id, project_id=project_id, actor=actor, **payload.model_dump()
        ),
    )
    return NarrativeProjectResponse.model_validate(project)


@router.get("", response_model=list[NarrativeProjectResponse])
async def list_projects_endpoint(
    tenant_id: TenantIdDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=100),
    before_id: UUID | None = None,
    include_archived: bool = False,
) -> list[NarrativeProjectResponse]:
    projects = await list_projects(
        session,
        tenant_id=tenant_id,
        limit=limit,
        before_id=before_id,
        include_archived=include_archived,
    )
    return [NarrativeProjectResponse.model_validate(project) for project in projects]


@router.get("/{project_id}/revisions", response_model=list[NarrativeRevisionSummary])
async def list_revisions_endpoint(
    project_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=100),
    before_id: UUID | None = None,
    include_archived: bool = False,
) -> list[NarrativeRevisionSummary]:
    revisions = await list_revisions(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        limit=limit,
        before_id=before_id,
        include_archived=include_archived,
    )
    return [NarrativeRevisionSummary.model_validate(revision) for revision in revisions]


@router.post("/{project_id}/upgrade", response_model=NarrativeRevisionResponse, status_code=201)
async def upgrade_project_endpoint(
    project_id: UUID,
    payload: NarrativeUpgradeRequest,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    actor: AuditActorDep,
    settings: SettingsDep,
) -> NarrativeRevisionResponse:
    """Explicitly move a project to story format v2 (stage and theme, ADR 0040)."""
    revision = await _persist(
        session,
        upgrade_to_v2(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            author_user_id=current_user.user.id,
            base_revision_id=payload.base_revision_id,
            idempotency_key=payload.idempotency_key,
            actor=actor,
            enabled=settings.narrative_package_v2_enabled,
            asset_budget_bytes=settings.narrative_package_v2_asset_budget_bytes,
        ),
    )
    return NarrativeRevisionResponse.model_validate(revision)
