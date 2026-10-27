"""Authorized callers organize bounded immutable authored source revisions."""

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from flint_graph.application.services.audit import AuditActor, record_audit_event
from flint_graph.domain.enums import AuditAction
from flint_graph.domain.errors import BadRequestError, ConflictError, NotFoundError
from flint_graph.infrastructure.db.models import NarrativeProject, NarrativeRevision, Tenant
from flint_graph.narrative.package import load_text_package
from flint_graph.narrative.values import PackageError, StoryPackage, canonical_json


async def get_project(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    for_update: bool = False,
    include_archived: bool = True,
) -> NarrativeProject:
    statement = select(NarrativeProject).where(
        NarrativeProject.id == project_id, NarrativeProject.tenant_id == tenant_id
    )
    if not include_archived:
        statement = statement.where(NarrativeProject.archived_at.is_(None))
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    project = await session.scalar(statement)
    if project is None:
        raise NotFoundError("Narrative project was not found.")
    return project


async def get_revision(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    revision_id: UUID,
    include_archived: bool = True,
) -> NarrativeRevision:
    await get_project(
        session, tenant_id=tenant_id, project_id=project_id, include_archived=include_archived
    )
    revision = await session.scalar(
        select(NarrativeRevision).where(
            NarrativeRevision.tenant_id == tenant_id,
            NarrativeRevision.project_id == project_id,
            NarrativeRevision.id == revision_id,
        )
    )
    if revision is None:
        raise NotFoundError("Narrative revision was not found.")
    return revision


async def list_projects(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    limit: int,
    before_id: UUID | None,
    include_archived: bool,
) -> list[NarrativeProject]:
    statement = select(NarrativeProject).where(NarrativeProject.tenant_id == tenant_id)
    if not include_archived:
        statement = statement.where(NarrativeProject.archived_at.is_(None))
    if before_id is not None:
        cursor = await get_project(
            session, tenant_id=tenant_id, project_id=before_id, include_archived=include_archived
        )
        cursor_time = (
            select(NarrativeProject.created_at)
            .where(NarrativeProject.id == cursor.id, NarrativeProject.tenant_id == tenant_id)
            .correlate(None)
            .scalar_subquery()
        )
        statement = statement.where(
            or_(
                NarrativeProject.created_at < cursor_time,
                and_(NarrativeProject.created_at == cursor_time, NarrativeProject.id < cursor.id),
            )
        )
    return list(
        await session.scalars(
            statement.order_by(
                NarrativeProject.created_at.desc(), NarrativeProject.id.desc()
            ).limit(limit)
        )
    )


async def list_revisions(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    limit: int,
    before_id: UUID | None,
    include_archived: bool,
) -> list[NarrativeRevision]:
    await get_project(
        session, tenant_id=tenant_id, project_id=project_id, include_archived=include_archived
    )
    statement = (
        select(NarrativeRevision)
        .where(NarrativeRevision.tenant_id == tenant_id, NarrativeRevision.project_id == project_id)
        .options(
            defer(NarrativeRevision.story_json, raiseload=True),
            defer(NarrativeRevision.notices, raiseload=True),
        )
    )
    if before_id is not None:
        cursor_number = await session.scalar(
            select(NarrativeRevision.revision_number).where(
                NarrativeRevision.tenant_id == tenant_id,
                NarrativeRevision.project_id == project_id,
                NarrativeRevision.id == before_id,
            )
        )
        if cursor_number is None:
            raise NotFoundError("Narrative revision was not found.")
        statement = statement.where(NarrativeRevision.revision_number < cursor_number)
    return list(
        await session.scalars(
            statement.order_by(NarrativeRevision.revision_number.desc()).limit(limit)
        )
    )


async def archive_project(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    base_revision_id: UUID,
    archived: bool,
    actor: AuditActor,
) -> NarrativeProject:
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    if project.head_revision_id != base_revision_id:
        raise ConflictError("Project head changed. Reload before changing archive state.")
    if (project.archived_at is not None) == archived:
        return project
    project.archived_at = datetime.now(UTC) if archived else None
    await session.flush()
    await session.refresh(project)
    await record_audit_event(
        session,
        action=(
            AuditAction.NARRATIVE_PROJECT_ARCHIVED
            if archived
            else AuditAction.NARRATIVE_PROJECT_RESTORED
        ),
        actor=actor,
        tenant_id=tenant_id,
        resource_type="narrative_project",
        resource_id=project_id,
        metadata={"head_revision_id": str(project.head_revision_id)},
    )
    return project


async def create_project(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    author_user_id: UUID,
    name: str,
    idempotency_key: UUID,
    actor: AuditActor,
) -> NarrativeProject:
    name = name.strip()
    try:
        name.encode("utf-8")
    except UnicodeError:
        raise BadRequestError("Invalid project name.") from None
    if not name or len(name) > 200 or "\x00" in name:
        raise BadRequestError("Project name must contain 1..200 characters.")
    fingerprint = sha256(canonical_json({"name": name})).hexdigest()
    await session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    existing = await session.scalar(
        select(NarrativeProject).where(
            NarrativeProject.tenant_id == tenant_id,
            NarrativeProject.creation_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.creation_hash != fingerprint:
            raise ConflictError("Idempotency key was used for a different project request.")
        return existing
    project = NarrativeProject(
        tenant_id=tenant_id,
        name=name,
        creation_key=idempotency_key,
        creation_hash=fingerprint,
        next_revision_number=2,
    )
    session.add(project)
    await session.flush()
    story = {
        "schema_version": "1",
        "id": "story_" + uuid4().hex,
        "title": name,
        "language": "en",
        "entry": "opening",
        "characters": {},
        "variables": {},
        "assets": {},
        "nodes": {
            "opening": {
                "type": "line",
                "text_id": "opening_text",
                "text": "A new story begins.",
                "next": "ending",
            },
            "ending": {
                "type": "end",
                "text_id": "ending_text",
                "text": "To be continued.",
                "ending": "complete",
            },
        },
    }
    package = StoryPackage(canonical_json(story), b"")
    revision = NarrativeRevision(
        tenant_id=tenant_id,
        project_id=project.id,
        revision_number=1,
        idempotency_key=idempotency_key,
        request_hash=fingerprint,
        story_json=package.canonical_story.decode(),
        notices="",
        content_hash=package.content_hash,
        author_user_id=author_user_id,
    )
    session.add(revision)
    await session.flush()
    project.head_revision_id = revision.id
    await session.flush()
    await session.refresh(project)
    await record_audit_event(
        session,
        action=AuditAction.NARRATIVE_PROJECT_CREATED,
        actor=actor,
        tenant_id=tenant_id,
        resource_type="narrative_project",
        resource_id=project.id,
        metadata={"revision_id": str(revision.id), "content_hash": revision.content_hash},
    )
    return project


async def create_revision(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    author_user_id: UUID,
    base_revision_id: UUID,
    idempotency_key: UUID,
    story_json: str,
    notices: str,
    actor: AuditActor,
) -> NarrativeRevision:
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    await get_revision(
        session, tenant_id=tenant_id, project_id=project_id, revision_id=base_revision_id
    )
    try:
        package = load_text_package(story_json.encode("utf-8"), notices.encode("utf-8"))
    except UnicodeError:
        raise BadRequestError("Invalid source text.") from None
    except PackageError as exc:
        failure = BadRequestError("Invalid narrative source.")
        failure.errors = [{"code": exc.code, "location": exc.location}]
        raise failure from None
    fingerprint = sha256(
        canonical_json(
            {"base_revision_id": str(base_revision_id), "package_hash": package.content_hash}
        )
    ).hexdigest()
    existing = await session.scalar(
        select(NarrativeRevision).where(
            NarrativeRevision.tenant_id == tenant_id,
            NarrativeRevision.project_id == project_id,
            NarrativeRevision.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != fingerprint:
            raise ConflictError("Idempotency key was used for a different revision request.")
        return existing
    if project.archived_at is not None:
        raise ConflictError("Archived narrative projects cannot be edited.")
    revision = NarrativeRevision(
        tenant_id=tenant_id,
        project_id=project_id,
        revision_number=project.next_revision_number,
        parent_revision_id=base_revision_id,
        observed_head_revision_id=project.head_revision_id,
        conflicted=base_revision_id != project.head_revision_id,
        idempotency_key=idempotency_key,
        request_hash=fingerprint,
        story_json=package.canonical_story.decode("utf-8"),
        notices=notices,
        content_hash=package.content_hash,
        author_user_id=author_user_id,
    )
    session.add(revision)
    await session.flush()
    project.next_revision_number += 1
    if not revision.conflicted:
        project.head_revision_id = revision.id
    await session.flush()
    await record_audit_event(
        session,
        action=(
            AuditAction.NARRATIVE_REVISION_CONFLICTED
            if revision.conflicted
            else AuditAction.NARRATIVE_REVISION_CREATED
        ),
        actor=actor,
        tenant_id=tenant_id,
        resource_type="narrative_revision",
        resource_id=revision.id,
        metadata={
            "project_id": str(project_id),
            "revision_number": revision.revision_number,
            "content_hash": revision.content_hash,
        },
    )
    return revision
