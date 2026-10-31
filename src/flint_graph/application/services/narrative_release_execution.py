"""Internal worker transitions under release -> job locks; no engine side effects.

Caller commits before launching a child and generates a fresh token for every
execution. Tokens are never exposed through public metadata or event payloads.
Completion is deliberately absent: only verified atomic publication may complete.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.narrative_release_state import (
    ReleaseAttempt,
    ReleaseJobStatus,
    claim_execution,
    finish_execution,
)
from flint_graph.application.services.narrative_package_v2 import (
    bind_story_assets,
    bound_object_key,
    compose_notices,
)
from flint_graph.application.services.narrative_projects import get_revision
from flint_graph.application.services.narrative_releases import BuildIdentity, latest_job
from flint_graph.domain.errors import DomainError, NotFoundError
from flint_graph.infrastructure.db.models import (
    NarrativeRelease,
    NarrativeReleaseEvent,
    NarrativeReleaseJob,
)
from flint_graph.narrative.font import FONT_LIMIT
from flint_graph.narrative.package import ASSET_LIMIT, PACKAGE_LIMIT, load_text_package
from flint_graph.narrative.values import PackageError, StoryPackage

FAILURE_CODES = frozenset(
    {
        "runtime_unavailable",
        "input_integrity",
        "package_integrity",
        "engine_failed",
        "engine_timeout",
        "output_inventory",
        "output_size_limit",
        "build_io",
        "artifact_invalid",
        "artifact_storage",
        "build_timeout",
        "worker_interrupted",
    }
)


@dataclass(frozen=True)
class ExecutionClaim:
    state: ReleaseAttempt
    acquired: bool


class ReleaseInputError(ValueError):
    """Safe internal stop/failure code; never contains private source or driver text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


async def lock_release_execution(
    session: AsyncSession,
    tenant_id: UUID,
    release_id: UUID,
    job_id: UUID,
) -> tuple[NarrativeRelease, NarrativeReleaseJob, UUID]:
    release = await session.scalar(
        select(NarrativeRelease)
        .where(
            NarrativeRelease.id == release_id,
            NarrativeRelease.tenant_id == tenant_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if release is None:
        raise NotFoundError("Narrative release was not found.")
    job = await session.scalar(
        select(NarrativeReleaseJob)
        .where(
            NarrativeReleaseJob.id == job_id,
            NarrativeReleaseJob.release_id == release_id,
            NarrativeReleaseJob.tenant_id == tenant_id,
            NarrativeReleaseJob.project_id == release.project_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        raise NotFoundError("Narrative release job was not found.")
    return release, job, (await latest_job(session, release)).id


def release_attempt(job: NarrativeReleaseJob) -> ReleaseAttempt:
    return ReleaseAttempt(
        job.id, ReleaseJobStatus(job.status), job.cancel_requested, job.execution_token
    )


def append_execution_event(session: AsyncSession, job: NarrativeReleaseJob, code: str) -> None:
    sequence = job.next_event_sequence
    job.next_event_sequence += 1
    session.add(
        NarrativeReleaseEvent(
            tenant_id=job.tenant_id,
            project_id=job.project_id,
            release_id=job.release_id,
            job_id=job.id,
            sequence=sequence,
            code=code,
            payload={"release_id": str(job.release_id), "job_id": str(job.id)},
        )
    )


async def claim_release_execution(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    release_id: UUID,
    job_id: UUID,
    token: UUID,
    workflow_run_id: UUID | None = None,
    activity_attempt: int | None = None,
) -> ExecutionClaim:
    if (workflow_run_id is None) != (activity_attempt is None) or (
        activity_attempt is not None and (type(activity_attempt) is not int or activity_attempt < 1)
    ):
        raise ValueError("Invalid release activity ownership")
    _, job, active_id = await lock_release_execution(session, tenant_id, release_id, job_id)
    before = release_attempt(job)
    if before.id != active_id or before.status not in (
        ReleaseJobStatus.QUEUED,
        ReleaseJobStatus.RUNNING,
    ):
        return ExecutionClaim(before, acquired=False)
    if workflow_run_id is not None:
        if job.workflow_run_id is None:
            if before.status == ReleaseJobStatus.QUEUED:
                raise ReleaseInputError("execution_registration_pending")
            return ExecutionClaim(before, acquired=False)
        if (
            job.workflow_run_id != workflow_run_id
            or activity_attempt is None
            or job.activity_attempt is None
            or activity_attempt < job.activity_attempt
        ):
            return ExecutionClaim(before, acquired=False)
    elif job.workflow_run_id is not None:
        return ExecutionClaim(before, acquired=False)
    after = claim_execution(before, token=token, active_job_id=active_id)
    if before == after:
        return ExecutionClaim(before, acquired=False)
    # Acquire before validating the engine/input, so an unavailable pinned builder
    # can fail an owned attempt instead of stranding accepted work in queued state.
    # This lease alone never authorizes engine launch or publication.
    job.status, job.execution_token = after.status.value, after.execution_token
    if workflow_run_id is not None:
        job.activity_attempt = activity_attempt
    if job.started_at is None:
        job.started_at = datetime.now(UTC)
    append_execution_event(
        session,
        job,
        "release.running"
        if before.status == ReleaseJobStatus.QUEUED
        else "release.execution_replaced",
    )
    await session.flush()
    return ExecutionClaim(after, acquired=True)


async def finish_release_failure(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    release_id: UUID,
    job_id: UUID,
    token: UUID,
    error_code: str | None = None,
    cancelled: bool = False,
) -> bool:
    if error_code not in FAILURE_CODES and not (cancelled and error_code is None):
        raise ValueError("Invalid release failure code")
    _, job, active_id = await lock_release_execution(session, tenant_id, release_id, job_id)
    before = release_attempt(job)
    after = finish_execution(
        before, token=token, active_job_id=active_id, outcome="cancelled" if cancelled else "failed"
    )
    if before == after:
        return False
    job.status, job.execution_token = after.status.value, None
    job.cancel_requested = after.cancel_requested
    job.error_code = None if after.status == ReleaseJobStatus.CANCELLED else error_code
    job.finished_at = datetime.now(UTC)
    append_execution_event(session, job, "release." + after.status.value)
    await session.flush()
    return True


@dataclass(frozen=True)
class AssetSource:
    """Where a story asset's verified bytes live; fetched after the locks are released."""

    id: str
    object_key: str
    size: int
    sha256: str
    max_bytes: int


@dataclass(frozen=True)
class ReleaseInput:
    package: StoryPackage  # v2 packages carry asset references without bytes.
    assets: tuple[AssetSource, ...] = ()


async def load_release_input(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    release_id: UUID,
    job_id: UUID,
    token: UUID,
    build: BuildIdentity | None,
) -> ReleaseInput:
    """Activity-local source, never a Temporal input/result/heartbeat or public DTO.

    Caller commits/releases locks before engine work. A later execution replacement
    or cancellation still fences publication; the runner must check at boundaries.
    """
    release, job, active_id = await lock_release_execution(session, tenant_id, release_id, job_id)
    if job.id != active_id or job.status != "running" or job.execution_token != token:
        raise ReleaseInputError("execution_stale")
    if job.cancel_requested:
        raise ReleaseInputError("execution_cancelled")
    if build is None or any(
        getattr(build, name) != getattr(release, name)
        for name in (
            "compiler_version",
            "runtime_version",
            "godot_version",
            "toolchain_sha256",
            "builder_image_digest",
        )
    ):
        raise ReleaseInputError("runtime_unavailable")
    revision = await get_revision(
        session, tenant_id=tenant_id, project_id=release.project_id, revision_id=release.revision_id
    )
    try:
        package = load_text_package(
            revision.story_json.encode("utf-8"),
            revision.notices.encode("utf-8"),
            allow_asset_refs=True,
        )
    except (PackageError, UnicodeError):
        raise ReleaseInputError("input_integrity") from None
    if (
        package.content_hash != release.package_hash
        or revision.content_hash != release.package_hash
    ):
        raise ReleaseInputError("package_integrity")
    if not package.assets:
        return ReleaseInput(package)
    # The saved binding and its server-built notices must still hold (ADR 0040).
    try:
        bound = await bind_story_assets(
            session,
            tenant_id=tenant_id,
            project_id=release.project_id,
            assets=package.story["assets"],
            budget=PACKAGE_LIMIT,
            lock=False,
        )
    except DomainError:
        raise ReleaseInputError("input_integrity") from None
    if compose_notices(revision.notices, bound) != revision.notices:
        raise ReleaseInputError("input_integrity")
    sources = tuple(
        AssetSource(
            item.key,
            bound_object_key(tenant_id, release.project_id, item),
            item.asset.size_bytes,
            item.sha256,
            FONT_LIMIT if item.kind == "font" else ASSET_LIMIT,
        )
        for item in bound
    )
    return ReleaseInput(package, sources)


async def register_release_workflow(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    release_id: UUID,
    job_id: UUID,
    workflow_run_id: UUID,
) -> bool:
    """Relay records the exact accepted run before its outbox publication commits."""
    _, job, active_id = await lock_release_execution(session, tenant_id, release_id, job_id)
    if job.workflow_run_id is not None:
        if job.workflow_run_id != workflow_run_id:
            raise ReleaseInputError("execution_registration_conflict")
        return False
    if job.status in ("completed", "failed", "cancelled") or active_id != job.id:
        return False
    if job.status != "queued" or job.execution_token is not None:
        raise ReleaseInputError("execution_registration_conflict")
    job.workflow_run_id, job.activity_attempt = workflow_run_id, 0
    append_execution_event(session, job, "release.dispatched")
    await session.flush()
    return True


@dataclass(frozen=True)
class WorkflowCleanupPlan:
    execution_token: UUID | None
    activity_attempt: int


async def workflow_cleanup_plan(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    release_id: UUID,
    job_id: UUID,
    workflow_run_id: UUID,
) -> WorkflowCleanupPlan | None:
    """Only a matching run's terminal supervisor may use this internal plan.

    SDK context or an exact closed-run observation must authorize the caller.
    Physical cleanup happens after commit, before token-checked finalization.
    """
    _, job, active_id = await lock_release_execution(session, tenant_id, release_id, job_id)
    if (
        active_id != job.id
        or job.workflow_run_id != workflow_run_id
        or job.activity_attempt is None
        or job.status not in ("queued", "running")
    ):
        return None
    if job.status == "queued" and (job.activity_attempt != 0 or job.execution_token is not None):
        return None
    return WorkflowCleanupPlan(job.execution_token, job.activity_attempt)


async def finalize_release_workflow(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    release_id: UUID,
    job_id: UUID,
    workflow_run_id: UUID,
    expected_token: UUID | None,
    expected_attempt: int,
    cancelled: bool = False,
    error_code: str = "worker_interrupted",
) -> bool:
    """Run-authorized supervisor; never ordinary old build-attempt cleanup."""
    if error_code not in FAILURE_CODES:
        raise ValueError("Invalid release failure code")
    _, job, active_id = await lock_release_execution(session, tenant_id, release_id, job_id)
    if (
        job.workflow_run_id != workflow_run_id
        or job.activity_attempt != expected_attempt
        or job.execution_token != expected_token
        or active_id != job.id
        or job.status not in ("queued", "running")
    ):
        return False
    before = release_attempt(job)
    if before.status == ReleaseJobStatus.QUEUED:
        if expected_attempt != 0 or expected_token is not None:
            return False
        token = uuid4()
        before = claim_execution(before, token=token, active_job_id=active_id)
    else:
        if expected_token is None:
            return False
        token = expected_token
    after = finish_execution(
        before, token=token, active_job_id=active_id, outcome="cancelled" if cancelled else "failed"
    )
    job.status, job.execution_token, job.cancel_requested = (
        after.status.value,
        None,
        after.cancel_requested,
    )
    job.error_code = None if after.status == ReleaseJobStatus.CANCELLED else error_code
    job.finished_at = datetime.now(UTC)
    append_execution_event(session, job, "release." + after.status.value)
    await session.flush()
    return True
