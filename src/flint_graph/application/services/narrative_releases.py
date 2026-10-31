"""Authorized immutable release intent; no engine execution on API requests."""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.narrative_release_state import (
    ReleaseAttempt,
    ReleaseJobStatus,
    request_cancellation,
)
from flint_graph.application.services.audit import AuditActor, record_audit_event
from flint_graph.application.services.narrative_projects import get_project, get_revision
from flint_graph.application.services.outbox import append_outbox_message, capture_trace_context
from flint_graph.domain.enums import AuditAction
from flint_graph.domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    TooManyRequestsError,
)
from flint_graph.infrastructure.db.models import (
    NarrativeRelease,
    NarrativeReleaseArtifact,
    NarrativeReleaseEvent,
    NarrativeReleaseJob,
    Tenant,
)
from flint_graph.narrative.values import canonical_json


@dataclass(frozen=True)
class BuildIdentity:
    builder_image_digest: str
    toolchain_sha256: str
    compiler_version: str = "0.1.0"
    runtime_version: str = "0.6.1"
    godot_version: str = "4.7.2.stable"


async def latest_job(
    session: AsyncSession, release: NarrativeRelease, *, attempt_number: int | None = None
) -> NarrativeReleaseJob:
    statement = select(NarrativeReleaseJob).where(
        NarrativeReleaseJob.release_id == release.id,
        NarrativeReleaseJob.project_id == release.project_id,
        NarrativeReleaseJob.tenant_id == release.tenant_id,
    )
    if attempt_number is not None:
        statement = statement.where(NarrativeReleaseJob.attempt_number == attempt_number)
    job = await session.scalar(
        statement.order_by(NarrativeReleaseJob.attempt_number.desc()).limit(1)
    )
    if job is None:
        raise DomainError(
            503, "Service unavailable", "Release state is unavailable.", "release-state-unavailable"
        )
    return job


async def create_release(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    revision_id: UUID,
    author_user_id: UUID,
    idempotency_key: UUID,
    build: BuildIdentity | None,
    actor: AuditActor,
    max_active_jobs: int = 10,
) -> tuple[NarrativeRelease, NarrativeReleaseJob]:
    # NO KEY UPDATE serializes admissions while allowing a project writer's audit
    # FK KEY SHARE. FOR UPDATE here would deadlock Tenant -> Project vs Project -> Tenant.
    tenant = await session.scalar(
        select(Tenant).where(Tenant.id == tenant_id).with_for_update(key_share=True)
    )
    if tenant is None:
        raise NotFoundError("Workspace was not found.")
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    intent_hash = sha256(canonical_json({"revision_id": str(revision_id)})).hexdigest()
    existing = await session.scalar(
        select(NarrativeRelease).where(
            NarrativeRelease.tenant_id == tenant_id,
            NarrativeRelease.project_id == project_id,
            NarrativeRelease.creation_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != intent_hash:
            raise ConflictError("This release key was already used for a different revision.")
        return existing, await latest_job(session, existing, attempt_number=1)
    revision = await get_revision(
        session, tenant_id=tenant_id, project_id=project_id, revision_id=revision_id
    )
    if project.archived_at is not None:
        raise ConflictError("Restore this project before requesting a new release.")
    if build is None:
        raise DomainError(
            503,
            "Service unavailable",
            "Narrative release building is not configured.",
            "release-unavailable",
        )
    active = (
        await session.scalar(
            select(func.count(NarrativeReleaseJob.id)).where(
                NarrativeReleaseJob.tenant_id == tenant_id,
                NarrativeReleaseJob.status.in_(["queued", "running"]),
            )
        )
        or 0
    )
    if active >= max_active_jobs:
        raise TooManyRequestsError("This workspace has reached its active release job limit.")
    release = NarrativeRelease(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        revision_id=revision_id,
        creator_user_id=author_user_id,
        creation_key=idempotency_key,
        request_hash=intent_hash,
        package_hash=revision.content_hash,
        compiler_version=build.compiler_version,
        runtime_version=build.runtime_version,
        godot_version=build.godot_version,
        builder_image_digest=build.builder_image_digest,
        toolchain_sha256=build.toolchain_sha256,
    )
    session.add(release)
    await session.flush()
    job = NarrativeReleaseJob(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        release_id=release.id,
        attempt_number=1,
        status="queued",
        cancel_requested=False,
        next_event_sequence=2,
    )
    session.add(job)
    await session.flush()
    session.add(
        NarrativeReleaseEvent(
            tenant_id=tenant_id,
            project_id=project_id,
            release_id=release.id,
            job_id=job.id,
            sequence=1,
            code="release.queued",
            payload={"release_id": str(release.id), "job_id": str(job.id)},
        )
    )
    await append_outbox_message(
        session,
        tenant_id=tenant_id,
        topic="narrative.release_queued",
        aggregate_type="narrative_release_job",
        aggregate_id=job.id,
        payload={
            "schema_version": "1",
            "tenant_id": str(tenant_id),
            "release_id": str(release.id),
            "job_id": str(job.id),
        },
        headers=capture_trace_context(),
    )
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_RELEASE_REQUESTED,
        actor=actor,
        resource_type="narrative_release",
        resource_id=release.id,
        metadata={
            "revision_id": str(revision_id),
            "job_id": str(job.id),
            "package_hash": release.package_hash,
        },
    )
    return release, job


async def list_releases(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    limit: int,
    before_id: UUID | None,
    include_archived: bool,
) -> list[tuple[NarrativeRelease, NarrativeReleaseJob]]:
    await get_project(
        session, tenant_id=tenant_id, project_id=project_id, include_archived=include_archived
    )
    statement = select(NarrativeRelease).where(
        NarrativeRelease.tenant_id == tenant_id, NarrativeRelease.project_id == project_id
    )
    if before_id is not None:
        cursor = await session.scalar(statement.where(NarrativeRelease.id == before_id))
        if cursor is None:
            raise NotFoundError("Release cursor was not found.")
        cursor_time = (
            select(NarrativeRelease.created_at)
            .where(
                NarrativeRelease.id == cursor.id,
                NarrativeRelease.tenant_id == tenant_id,
                NarrativeRelease.project_id == project_id,
            )
            .correlate(None)
            .scalar_subquery()
        )
        statement = statement.where(
            or_(
                NarrativeRelease.created_at < cursor_time,
                and_(
                    NarrativeRelease.created_at == cursor_time,
                    NarrativeRelease.id < cursor.id,
                ),
            )
        )
    releases = list(
        await session.scalars(
            statement.order_by(
                NarrativeRelease.created_at.desc(), NarrativeRelease.id.desc()
            ).limit(limit)
        )
    )
    # Each latest-attempt read is bounded to one compact metadata record.
    return [(release, await latest_job(session, release)) for release in releases]


async def get_release(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    release_id: UUID,
    include_archived: bool = False,
    for_update: bool = False,
) -> NarrativeRelease:
    await get_project(
        session, tenant_id=tenant_id, project_id=project_id, include_archived=include_archived
    )
    statement = select(NarrativeRelease).where(
        NarrativeRelease.id == release_id,
        NarrativeRelease.project_id == project_id,
        NarrativeRelease.tenant_id == tenant_id,
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    release = await session.scalar(statement)
    if release is None:
        raise NotFoundError("Narrative release was not found.")
    return release


async def get_release_job(
    session: AsyncSession,
    release: NarrativeRelease,
    job_id: UUID,
    *,
    for_update: bool = False,
) -> NarrativeReleaseJob:
    statement = select(NarrativeReleaseJob).where(
        NarrativeReleaseJob.id == job_id,
        NarrativeReleaseJob.release_id == release.id,
        NarrativeReleaseJob.project_id == release.project_id,
        NarrativeReleaseJob.tenant_id == release.tenant_id,
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    job = await session.scalar(statement)
    if job is None:
        raise NotFoundError("Narrative release job was not found.")
    return job


async def cancel_release_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    release_id: UUID,
    job_id: UUID,
    actor: AuditActor,
) -> NarrativeReleaseJob:
    release = await get_release(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        release_id=release_id,
        include_archived=True,
        for_update=True,
    )
    job = await get_release_job(session, release, job_id, for_update=True)
    before = ReleaseAttempt(
        id=job.id,
        status=ReleaseJobStatus(job.status),
        cancel_requested=job.cancel_requested,
        execution_token=job.execution_token,
    )
    after = request_cancellation(before)
    if before == after:
        return job
    job.status = after.status.value
    job.cancel_requested = after.cancel_requested
    job.execution_token = after.execution_token
    if after.status == ReleaseJobStatus.CANCELLED:
        job.finished_at = datetime.now(UTC)
    sequence = job.next_event_sequence
    job.next_event_sequence += 1
    session.add(
        NarrativeReleaseEvent(
            tenant_id=tenant_id,
            project_id=project_id,
            release_id=release_id,
            job_id=job.id,
            sequence=sequence,
            code="release.cancelled"
            if after.status == ReleaseJobStatus.CANCELLED
            else "release.cancel_requested",
            payload={"release_id": str(release_id), "job_id": str(job.id)},
        )
    )
    await append_outbox_message(
        session,
        tenant_id=tenant_id,
        topic="narrative.release_cancelled",
        aggregate_type="narrative_release_job",
        aggregate_id=job.id,
        payload={
            "schema_version": "1",
            "tenant_id": str(tenant_id),
            "release_id": str(release_id),
            "job_id": str(job.id),
        },
        headers=capture_trace_context(),
    )
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_RELEASE_CANCELLED,
        actor=actor,
        resource_type="narrative_release_job",
        resource_id=job.id,
        metadata={"release_id": str(release_id), "status": job.status},
    )
    await session.flush()
    await session.refresh(job)
    return job


async def retry_release(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    release_id: UUID,
    idempotency_key: UUID,
    build: BuildIdentity | None,
    actor: AuditActor,
    max_active_jobs: int = 10,
) -> tuple[NarrativeRelease, NarrativeReleaseJob]:
    await session.scalar(
        select(Tenant).where(Tenant.id == tenant_id).with_for_update(key_share=True)
    )
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    release = await get_release(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        release_id=release_id,
        include_archived=True,
        for_update=True,
    )
    replay = await session.scalar(
        select(NarrativeReleaseJob).where(
            NarrativeReleaseJob.tenant_id == tenant_id,
            NarrativeReleaseJob.project_id == project_id,
            NarrativeReleaseJob.release_id == release_id,
            NarrativeReleaseJob.retry_key == idempotency_key,
        )
    )
    if replay is not None:
        return release, replay
    previous = await latest_job(session, release)
    previous = await get_release_job(session, release, previous.id, for_update=True)
    if previous.status not in ("failed", "cancelled"):
        raise ConflictError("Only a failed or cancelled release attempt can be retried.")
    if await session.scalar(
        select(NarrativeReleaseArtifact.id)
        .where(
            NarrativeReleaseArtifact.release_id == release_id,
            NarrativeReleaseArtifact.tenant_id == tenant_id,
        )
        .limit(1)
    ):
        raise ConflictError("A published release cannot be retried in place.")
    if project.archived_at is not None:
        raise ConflictError("Restore this project before retrying a release.")
    fields = (
        "compiler_version",
        "runtime_version",
        "godot_version",
        "toolchain_sha256",
        "builder_image_digest",
    )
    if build is None or any(getattr(build, field) != getattr(release, field) for field in fields):
        raise DomainError(
            503,
            "Service unavailable",
            "The release's pinned builder is unavailable.",
            "release-runtime-unavailable",
        )
    active = (
        await session.scalar(
            select(func.count(NarrativeReleaseJob.id)).where(
                NarrativeReleaseJob.tenant_id == tenant_id,
                NarrativeReleaseJob.status.in_(["queued", "running"]),
            )
        )
        or 0
    )
    if active >= max_active_jobs:
        raise TooManyRequestsError("This workspace has reached its active release job limit.")
    job = NarrativeReleaseJob(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        release_id=release_id,
        attempt_number=previous.attempt_number + 1,
        retry_key=idempotency_key,
        status="queued",
        cancel_requested=False,
        next_event_sequence=2,
    )
    session.add(job)
    await session.flush()
    session.add(
        NarrativeReleaseEvent(
            tenant_id=tenant_id,
            project_id=project_id,
            release_id=release_id,
            job_id=job.id,
            sequence=1,
            code="release.queued",
            payload={"release_id": str(release_id), "job_id": str(job.id)},
        )
    )
    await append_outbox_message(
        session,
        tenant_id=tenant_id,
        topic="narrative.release_queued",
        aggregate_type="narrative_release_job",
        aggregate_id=job.id,
        payload={
            "schema_version": "1",
            "tenant_id": str(tenant_id),
            "release_id": str(release_id),
            "job_id": str(job.id),
        },
        headers=capture_trace_context(),
    )
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_RELEASE_RETRIED,
        actor=actor,
        resource_type="narrative_release_job",
        resource_id=job.id,
        metadata={
            "release_id": str(release_id),
            "previous_job_id": str(previous.id),
            "attempt_number": job.attempt_number,
        },
    )
    return release, job


async def list_release_jobs(
    session: AsyncSession,
    release: NarrativeRelease,
    *,
    limit: int,
    before_id: UUID | None,
) -> list[NarrativeReleaseJob]:
    statement = select(NarrativeReleaseJob).where(
        NarrativeReleaseJob.release_id == release.id,
        NarrativeReleaseJob.project_id == release.project_id,
        NarrativeReleaseJob.tenant_id == release.tenant_id,
    )
    if before_id is not None:
        cursor = await get_release_job(session, release, before_id)
        statement = statement.where(NarrativeReleaseJob.attempt_number < cursor.attempt_number)
    return list(
        await session.scalars(
            statement.order_by(NarrativeReleaseJob.attempt_number.desc()).limit(limit)
        )
    )


async def list_release_events(
    session: AsyncSession,
    release: NarrativeRelease,
    *,
    job_id: UUID,
    after_sequence: int,
    limit: int,
) -> list[NarrativeReleaseEvent]:
    await get_release_job(session, release, job_id)
    return list(
        await session.scalars(
            select(NarrativeReleaseEvent)
            .where(
                NarrativeReleaseEvent.tenant_id == release.tenant_id,
                NarrativeReleaseEvent.project_id == release.project_id,
                NarrativeReleaseEvent.release_id == release.id,
                NarrativeReleaseEvent.job_id == job_id,
                NarrativeReleaseEvent.sequence > after_sequence,
            )
            .order_by(NarrativeReleaseEvent.sequence)
            .limit(limit)
        )
    )
