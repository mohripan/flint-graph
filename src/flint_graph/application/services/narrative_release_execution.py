"""Internal worker transitions under release -> job locks; no engine side effects.

Caller commits before launching a child and generates a fresh token for every
execution. Tokens are never exposed through public metadata or event payloads.
Completion is deliberately absent: only verified atomic publication may complete.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.narrative_release_state import (
    ReleaseAttempt,
    ReleaseJobStatus,
    claim_execution,
    finish_execution,
)
from flint_graph.application.services.narrative_projects import get_revision
from flint_graph.application.services.narrative_releases import BuildIdentity, latest_job
from flint_graph.domain.errors import NotFoundError
from flint_graph.infrastructure.db.models import (
    NarrativeRelease,
    NarrativeReleaseEvent,
    NarrativeReleaseJob,
)
from flint_graph.narrative.package import load_text_package
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


async def _locked(
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


def _state(job: NarrativeReleaseJob) -> ReleaseAttempt:
    return ReleaseAttempt(
        job.id, ReleaseJobStatus(job.status), job.cancel_requested, job.execution_token
    )


def _event(session: AsyncSession, job: NarrativeReleaseJob, code: str) -> None:
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
) -> ExecutionClaim:
    _, job, active_id = await _locked(session, tenant_id, release_id, job_id)
    before = _state(job)
    after = claim_execution(before, token=token, active_job_id=active_id)
    if before == after:
        return ExecutionClaim(before, acquired=False)
    # Acquire before validating the engine/input, so an unavailable pinned builder
    # can fail an owned attempt instead of stranding accepted work in queued state.
    # This lease alone never authorizes engine launch or publication.
    job.status, job.execution_token = after.status.value, after.execution_token
    if job.started_at is None:
        job.started_at = datetime.now(UTC)
    _event(
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
    _, job, active_id = await _locked(session, tenant_id, release_id, job_id)
    before = _state(job)
    after = finish_execution(
        before, token=token, active_job_id=active_id, outcome="cancelled" if cancelled else "failed"
    )
    if before == after:
        return False
    job.status, job.execution_token = after.status.value, None
    job.cancel_requested = after.cancel_requested
    job.error_code = None if after.status == ReleaseJobStatus.CANCELLED else error_code
    job.finished_at = datetime.now(UTC)
    _event(session, job, "release." + after.status.value)
    await session.flush()
    return True


async def load_release_input(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    release_id: UUID,
    job_id: UUID,
    token: UUID,
    build: BuildIdentity | None,
) -> StoryPackage:
    """Activity-local source, never a Temporal input/result/heartbeat or public DTO.

    Caller commits/releases locks before engine work. A later execution replacement
    or cancellation still fences publication; the runner must check at boundaries.
    """
    release, job, active_id = await _locked(session, tenant_id, release_id, job_id)
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
            revision.story_json.encode("utf-8"), revision.notices.encode("utf-8")
        )
    except (PackageError, UnicodeError):
        raise ReleaseInputError("input_integrity") from None
    if (
        package.content_hash != release.package_hash
        or revision.content_hash != release.package_hash
    ):
        raise ReleaseInputError("package_integrity")
    return package
