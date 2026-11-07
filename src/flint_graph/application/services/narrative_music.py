"""Generated music jobs (ADR 0067): admission, the execution fence and their finished track.

Results land in the library as candidates for the creator to approve, like generated images.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.narrative_image_workflow import (
    MUSIC_CANCELLED_TOPIC,
    MUSIC_QUEUED_TOPIC,
)
from flint_graph.application.services.access import charge_usage
from flint_graph.application.services.audit import AuditActor, record_audit_event
from flint_graph.application.services.narrative_projects import get_project
from flint_graph.application.services.outbox import append_outbox_message, capture_trace_context
from flint_graph.domain.enums import AuditAction
from flint_graph.domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    TooManyRequestsError,
)
from flint_graph.infrastructure.db.models import NarrativeAsset, NarrativeMusicJob, Tenant
from flint_graph.infrastructure.narrative_imagegen import ModelIdentity
from flint_graph.infrastructure.narrative_musicgen import (
    DESCRIPTION_LIMIT,
    MAX_SECONDS,
    MIN_SECONDS,
    MusicRequest,
    MusicResult,
)
from flint_graph.narrative.values import canonical_json

_ACTIVE = ("queued", "running")
# The notice every generated track carries into a game's NOTICES.
MODEL_LICENSE = "Apache-2.0"
MODEL_NOTICE = "Generated with ACE-Step v1 3.5B (Apache-2.0)."
MUSIC_PRICE_ITEM = "music.track"


def _now() -> datetime:
    return datetime.now(UTC)


def _invalid(detail: str) -> DomainError:
    return DomainError(422, "Invalid music request", detail, "invalid-music-request")


@dataclass(frozen=True)
class MusicWork:
    tenant_id: UUID
    project_id: UUID
    job_id: UUID
    request: MusicRequest


class MusicRegistrationPending(Exception):
    """The run has not been bound to this job yet; the activity retries."""


async def create_music_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    author_user_id: UUID,
    description: str,
    seconds: int,
    idempotency_key: UUID,
    actor: AuditActor,
    available: bool,
    max_active_jobs: int,
) -> NarrativeMusicJob:
    # NO KEY UPDATE serializes workspace admission without blocking audit FK checks.
    tenant = await session.scalar(
        select(Tenant).where(Tenant.id == tenant_id).with_for_update(key_share=True)
    )
    if tenant is None:
        raise NotFoundError("Project was not found.")
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    if project.archived_at is not None:
        raise ConflictError("Restore this project before generating music.")
    cleaned = " ".join(description.split())
    if not 0 < len(cleaned) <= DESCRIPTION_LIMIT:
        raise _invalid(f"Describe the music in 1 to {DESCRIPTION_LIMIT} characters.")
    if not MIN_SECONDS <= seconds <= MAX_SECONDS:
        raise _invalid(f"A track can be {MIN_SECONDS} to {MAX_SECONDS} seconds long.")
    request_hash = sha256(canonical_json({"description": cleaned, "seconds": seconds})).hexdigest()
    existing = await session.scalar(
        select(NarrativeMusicJob).where(
            NarrativeMusicJob.project_id == project_id,
            NarrativeMusicJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ConflictError("This request key was already used for different music.")
        return existing
    if not available:
        raise DomainError(
            409,
            "Music generation unavailable",
            "Music generation is not turned on for this Studio.",
            "music-generation-unavailable",
        )
    active = (
        await session.scalar(
            select(func.count(NarrativeMusicJob.id)).where(
                NarrativeMusicJob.tenant_id == tenant_id,
                NarrativeMusicJob.status.in_(_ACTIVE),
            )
        )
        or 0
    )
    if active >= max_active_jobs:
        raise TooManyRequestsError("Wait for the current music to finish.")
    job = NarrativeMusicJob(
        tenant_id=tenant_id,
        project_id=project_id,
        requested_by_user_id=author_user_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        description=cleaned,
        seconds=seconds,
        seed=secrets.randbelow(2**32),
        status="queued",
        progress=0,
        cancel_requested=False,
    )
    session.add(job)
    await session.flush()
    await charge_usage(
        session,
        user_id=author_user_id,
        item=MUSIC_PRICE_ITEM,
        units=1,
        subject=f"music_job:{job.id}",
    )
    payload = {"schema_version": "1", "tenant_id": str(tenant_id), "job_id": str(job.id)}
    await append_outbox_message(
        session,
        tenant_id=tenant_id,
        topic=MUSIC_QUEUED_TOPIC,
        aggregate_type="narrative_music_job",
        aggregate_id=job.id,
        payload=payload,
        headers=capture_trace_context(),
    )
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_MUSIC_JOB_REQUESTED,
        actor=actor,
        resource_type="narrative_music_job",
        resource_id=job.id,
        metadata={"project_id": str(project_id), "seconds": seconds},
    )
    await session.refresh(job)
    return job


async def _track(session: AsyncSession, job_ids: list[UUID]) -> dict[UUID, list[NarrativeAsset]]:
    found: dict[UUID, list[NarrativeAsset]] = {job_id: [] for job_id in job_ids}
    if job_ids:
        for asset in await session.scalars(
            select(NarrativeAsset).where(
                NarrativeAsset.music_job_id.in_(job_ids), NarrativeAsset.status != "discarded"
            )
        ):
            assert asset.music_job_id is not None
            found[asset.music_job_id].append(asset)
    return found


async def list_music_jobs(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, limit: int
) -> list[tuple[NarrativeMusicJob, list[NarrativeAsset]]]:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    jobs = list(
        await session.scalars(
            select(NarrativeMusicJob)
            .where(
                NarrativeMusicJob.tenant_id == tenant_id,
                NarrativeMusicJob.project_id == project_id,
            )
            .order_by(NarrativeMusicJob.created_at.desc(), NarrativeMusicJob.id.desc())
            .limit(limit)
        )
    )
    tracks = await _track(session, [job.id for job in jobs])
    return [(job, tracks[job.id]) for job in jobs]


async def _job(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, job_id: UUID, lock: bool = False
) -> NarrativeMusicJob:
    statement = select(NarrativeMusicJob).where(
        NarrativeMusicJob.tenant_id == tenant_id,
        NarrativeMusicJob.project_id == project_id,
        NarrativeMusicJob.id == job_id,
    )
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    job = await session.scalar(statement)
    if job is None:
        raise NotFoundError("Music job was not found.")
    return job


async def get_music_job(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, job_id: UUID
) -> tuple[NarrativeMusicJob, list[NarrativeAsset]]:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    job = await _job(session, tenant_id=tenant_id, project_id=project_id, job_id=job_id)
    return job, (await _track(session, [job.id]))[job.id]


async def cancel_music_job(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, job_id: UUID, actor: AuditActor
) -> NarrativeMusicJob:
    await get_project(session, tenant_id=tenant_id, project_id=project_id, for_update=True)
    job = await _job(session, tenant_id=tenant_id, project_id=project_id, job_id=job_id, lock=True)
    if job.status not in _ACTIVE or job.cancel_requested:
        return job
    if job.status == "queued":
        job.status, job.finished_at = "cancelled", _now()
    else:
        job.cancel_requested = True
        await append_outbox_message(
            session,
            tenant_id=tenant_id,
            topic=MUSIC_CANCELLED_TOPIC,
            aggregate_type="narrative_music_job",
            aggregate_id=job.id,
            payload={"schema_version": "1", "tenant_id": str(tenant_id), "job_id": str(job.id)},
            headers=capture_trace_context(),
        )
    await session.flush()
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_MUSIC_JOB_CANCELLED,
        actor=actor,
        resource_type="narrative_music_job",
        resource_id=job.id,
        metadata={"project_id": str(project_id), "status": job.status},
    )
    await session.refresh(job)
    return job


async def _locked(session: AsyncSession, job_id: UUID) -> NarrativeMusicJob | None:
    job: NarrativeMusicJob | None = await session.scalar(
        select(NarrativeMusicJob)
        .where(NarrativeMusicJob.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return job


async def register_music_workflow(
    session: AsyncSession, *, tenant_id: UUID, job_id: UUID, workflow_run_id: UUID
) -> None:
    """Bind a queued job to the run Temporal accepted, before any claim (ADR 0037)."""
    job = await _locked(session, job_id)
    if job is None or job.tenant_id != tenant_id:
        raise ValueError("Invalid music dispatch identity")
    if job.workflow_run_id is None:
        if job.status == "queued":
            job.workflow_run_id, job.activity_attempt = workflow_run_id, 0
            await session.flush()
    elif job.workflow_run_id != workflow_run_id:
        raise ValueError("Unowned music execution")


def _finish(job: NarrativeMusicJob, status: str) -> None:
    job.status, job.execution_token, job.finished_at = status, None, _now()


def _owned(job: NarrativeMusicJob | None, token: UUID) -> bool:
    return job is not None and job.status == "running" and job.execution_token == token


async def abandon_music_job(
    session: AsyncSession, *, job_id: UUID, workflow_run_id: UUID, error_code: str
) -> NarrativeMusicJob | None:
    """Close an active job of this run only; returns ``None`` when it is not ours."""
    job = await _locked(session, job_id)
    if job is None or job.workflow_run_id != workflow_run_id or job.status not in _ACTIVE:
        return None
    job.error_code = error_code[:80]
    _finish(job, "cancelled" if job.cancel_requested else "failed")
    await session.flush()
    return job


async def claim_music_job(
    session: AsyncSession,
    *,
    job_id: UUID,
    execution_token: UUID,
    workflow_run_id: UUID,
    activity_attempt: int,
) -> MusicWork | None:
    """Fence one execution of the registered run; its later attempts replace it."""
    job = await _locked(session, job_id)
    if job is None or job.status not in _ACTIVE:
        return None
    if job.workflow_run_id is None:
        raise MusicRegistrationPending
    if job.workflow_run_id != workflow_run_id:
        return None
    if job.cancel_requested:
        _finish(job, "cancelled")
        await session.flush()
        return None
    job.status = "running"
    job.execution_token = execution_token
    job.activity_attempt = activity_attempt
    job.progress = 0
    job.started_at = job.started_at or _now()
    await session.flush()
    return MusicWork(
        tenant_id=job.tenant_id,
        project_id=job.project_id,
        job_id=job.id,
        request=MusicRequest(description=job.description, seconds=job.seconds, seed=job.seed),
    )


async def record_music_progress(
    session: AsyncSession, *, job_id: UUID, execution_token: UUID, progress: int
) -> bool:
    """Whether this execution may carry on."""
    job = await _locked(session, job_id)
    if not _owned(job, execution_token):
        return False
    assert job is not None
    if job.cancel_requested:
        return False
    job.progress = max(job.progress, min(progress, 1))
    await session.flush()
    return True


def track_name(description: str) -> str:
    return description if len(description) <= 80 else description[:79].rstrip() + "…"


async def complete_music_job(
    session: AsyncSession,
    *,
    job_id: UUID,
    execution_token: UUID,
    result: MusicResult,
    asset_id: UUID,
    model: ModelIdentity,
) -> NarrativeMusicJob:
    job = await _locked(session, job_id)
    if job is None:
        raise NotFoundError("Music job was not found.")
    if not _owned(job, execution_token):
        return job
    if job.cancel_requested:
        _finish(job, "cancelled")
        await session.flush()
        return job
    track = result.track
    # Identical bytes are one asset per project; a repeated track adds nothing new.
    known = await session.scalar(
        select(NarrativeAsset.id).where(
            NarrativeAsset.tenant_id == job.tenant_id,
            NarrativeAsset.project_id == job.project_id,
            NarrativeAsset.sha256 == track.sha256,
            NarrativeAsset.status != "discarded",
        )
    )
    if known is None:
        session.add(
            NarrativeAsset(
                id=asset_id,
                tenant_id=job.tenant_id,
                project_id=job.project_id,
                kind="music",
                source="generated",
                name=track_name(job.description),
                music_job_id=job.id,
                job_index=0,
                media_type="audio/ogg",
                sha256=track.sha256,
                size_bytes=len(track.data),
                duration_ms=max(1, track.duration_ms),
                seed=job.seed,
                provenance={
                    "generator": "local-ace-step",
                    "model_repo": model.repo,
                    "model_revision": model.revision,
                    "license": MODEL_LICENSE,
                    "description": job.description,
                    "seconds": job.seconds,
                    "seed": job.seed,
                    "channels": track.channels,
                    "rate": track.rate,
                    "runtime": result.runtime,
                },
                license=MODEL_LICENSE,
                notice=MODEL_NOTICE,
                status="candidate",
                created_by_user_id=job.requested_by_user_id,
            )
        )
    job.model = f"{model.repo}@{model.revision}"[:200]
    job.runtime = result.runtime
    job.progress = 1
    _finish(job, "completed")
    await session.flush()
    return job


async def fail_music_job(
    session: AsyncSession, *, job_id: UUID, execution_token: UUID, error_code: str
) -> NarrativeMusicJob | None:
    job = await _locked(session, job_id)
    if not _owned(job, execution_token):
        return job
    assert job is not None
    if error_code == "cancelled" or job.cancel_requested:
        _finish(job, "cancelled")
    else:
        job.error_code = error_code[:80]
        _finish(job, "failed")
    await session.flush()
    return job
