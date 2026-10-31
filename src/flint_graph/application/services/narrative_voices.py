"""Character voices and local voice jobs (ADR 0043).

A character's profile stores a Kokoro voice ID. API requests only record intent: a
job is queued with an ID-only outbox message and Kokoro runs later on the CPU in a
fenced activity of the registered workflow run (ADR 0037). Every spoken text becomes
a candidate voice clip; only approval lets a story bind it. Audit metadata and
outbox payloads carry identifiers, never the spoken text.
"""

import re
import secrets
import textwrap
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.narrative_image_workflow import (
    VOICE_CANCELLED_TOPIC,
    VOICE_QUEUED_TOPIC,
)
from flint_graph.application.services.audit import AuditActor, record_audit_event
from flint_graph.application.services.narrative_characters import Profile, _editable
from flint_graph.application.services.narrative_projects import get_project
from flint_graph.application.services.outbox import append_outbox_message, capture_trace_context
from flint_graph.domain.enums import AuditAction
from flint_graph.domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    TooManyRequestsError,
)
from flint_graph.infrastructure.db.models import (
    NarrativeAsset,
    NarrativeCharacterProfile,
    NarrativeVoiceJob,
    Tenant,
)
from flint_graph.infrastructure.narrative_imagegen import ModelIdentity
from flint_graph.infrastructure.narrative_voicegen import (
    GeneratedClip,
    VoiceItem,
    VoiceRequest,
    VoiceResult,
)
from flint_graph.narrative.values import canonical_json
from flint_graph.narrative.voices import MAX_ITEMS, VOICE_IDS, clean_voice_text

_ACTIVE = ("queued", "running")
_NODE_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class VoiceWork:
    tenant_id: UUID
    project_id: UUID
    job_id: UUID
    request: VoiceRequest


async def set_character_voice(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    base_version: int,
    voice: str | None,
    author_user_id: UUID,
) -> Profile:
    if voice is not None and voice not in VOICE_IDS:
        raise DomainError(422, "Invalid voice", "Choose one of the listed voices.", "invalid-voice")
    profile = await _editable(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        base_version=base_version,
        author_user_id=author_user_id,
    )
    profile.voice = voice
    await session.flush()
    portrait = (
        await session.get(NarrativeAsset, profile.portrait_asset_id)
        if profile.portrait_asset_id
        else None
    )
    return profile, portrait


def _invalid(detail: str) -> DomainError:
    return DomainError(422, "Invalid voice request", detail, "invalid-voice-request")


def clean_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not 1 <= len(items) <= MAX_ITEMS:
        raise _invalid(f"Ask for 1 to {MAX_ITEMS} clips at a time.")
    cleaned = []
    for item in items:
        node_id = item.get("node_id")
        if node_id is not None and (type(node_id) is not str or not _NODE_ID.fullmatch(node_id)):
            raise _invalid("Check the line each clip is for.")
        try:
            text = clean_voice_text(str(item.get("text", "")), str(item.get("mode", "")))
        except ValueError as error:
            raise _invalid(str(error)) from None
        cleaned.append({"mode": item["mode"], "text": text, "node_id": node_id})
    return cleaned


async def create_voice_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    author_user_id: UUID,
    items: list[dict[str, Any]],
    idempotency_key: UUID,
    actor: AuditActor,
    available: bool,
    max_active_jobs: int,
) -> NarrativeVoiceJob:
    # NO KEY UPDATE serializes workspace admission without blocking audit FK checks.
    tenant = await session.scalar(
        select(Tenant).where(Tenant.id == tenant_id).with_for_update(key_share=True)
    )
    if tenant is None:
        raise NotFoundError("Workspace was not found.")
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    cleaned = clean_items(items)
    profile = await session.scalar(
        select(NarrativeCharacterProfile).where(
            NarrativeCharacterProfile.tenant_id == tenant_id,
            NarrativeCharacterProfile.project_id == project_id,
            NarrativeCharacterProfile.character_id == character_id,
        )
    )
    voice = profile.voice if profile is not None else None
    identity = {"character_id": character_id, "voice": voice, "items": cleaned}
    request_hash = sha256(canonical_json(identity)).hexdigest()
    existing = await session.scalar(
        select(NarrativeVoiceJob).where(
            NarrativeVoiceJob.project_id == project_id,
            NarrativeVoiceJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ConflictError("This request key was already used for a different request.")
        return existing
    if project.archived_at is not None:
        raise ConflictError("Restore this project before generating voices.")
    if not available:
        raise DomainError(
            503,
            "Service unavailable",
            "Voice generation is not configured on this server. Lines can stay silent.",
            "voice-generation-unavailable",
        )
    if voice is None:
        raise DomainError(
            409,
            "No voice chosen",
            "Choose a voice for this character first.",
            "voice-not-chosen",
        )
    active = (
        await session.scalar(
            select(func.count(NarrativeVoiceJob.id)).where(
                NarrativeVoiceJob.tenant_id == tenant_id,
                NarrativeVoiceJob.status.in_(_ACTIVE),
            )
        )
        or 0
    )
    if active >= max_active_jobs:
        raise TooManyRequestsError("Wait for the current voices to finish.")
    job = NarrativeVoiceJob(
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        requested_by_user_id=author_user_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        voice=voice,
        speed=1.0,
        seed=secrets.randbelow(2**32),
        items=cleaned,
        count=len(cleaned),
        status="queued",
        progress=0,
        cancel_requested=False,
    )
    session.add(job)
    await session.flush()
    payload = {"schema_version": "1", "tenant_id": str(tenant_id), "job_id": str(job.id)}
    await append_outbox_message(
        session,
        tenant_id=tenant_id,
        topic=VOICE_QUEUED_TOPIC,
        aggregate_type="narrative_voice_job",
        aggregate_id=job.id,
        payload=payload,
        headers=capture_trace_context(),
    )
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_VOICE_JOB_REQUESTED,
        actor=actor,
        resource_type="narrative_voice_job",
        resource_id=job.id,
        metadata={"project_id": str(project_id), "count": job.count},
    )
    await session.refresh(job)
    return job


async def _assets(session: AsyncSession, job_ids: list[UUID]) -> dict[UUID, list[NarrativeAsset]]:
    grouped: dict[UUID, list[NarrativeAsset]] = {job_id: [] for job_id in job_ids}
    if not job_ids:
        return grouped
    rows = await session.scalars(
        select(NarrativeAsset)
        .where(NarrativeAsset.voice_job_id.in_(job_ids), NarrativeAsset.status != "discarded")
        .order_by(NarrativeAsset.job_index)
    )
    for asset in rows:
        if asset.voice_job_id is not None:
            grouped[asset.voice_job_id].append(asset)
    return grouped


async def list_voice_jobs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str | None,
    limit: int,
) -> list[tuple[NarrativeVoiceJob, list[NarrativeAsset]]]:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    scope = [NarrativeVoiceJob.tenant_id == tenant_id, NarrativeVoiceJob.project_id == project_id]
    if character_id is not None:
        scope.append(NarrativeVoiceJob.character_id == character_id)
    jobs = list(
        await session.scalars(
            select(NarrativeVoiceJob)
            .where(*scope)
            .order_by(NarrativeVoiceJob.created_at.desc(), NarrativeVoiceJob.id.desc())
            .limit(limit)
        )
    )
    assets = await _assets(session, [job.id for job in jobs])
    return [(job, assets[job.id]) for job in jobs]


async def _job(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, job_id: UUID, lock: bool = False
) -> NarrativeVoiceJob:
    statement = select(NarrativeVoiceJob).where(
        NarrativeVoiceJob.tenant_id == tenant_id,
        NarrativeVoiceJob.project_id == project_id,
        NarrativeVoiceJob.id == job_id,
    )
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    job = await session.scalar(statement)
    if job is None:
        raise NotFoundError("Voice job was not found.")
    return job


async def get_voice_job(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, job_id: UUID
) -> tuple[NarrativeVoiceJob, list[NarrativeAsset]]:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    job = await _job(session, tenant_id=tenant_id, project_id=project_id, job_id=job_id)
    return job, (await _assets(session, [job.id]))[job.id]


async def cancel_voice_job(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, job_id: UUID, actor: AuditActor
) -> NarrativeVoiceJob:
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
            topic=VOICE_CANCELLED_TOPIC,
            aggregate_type="narrative_voice_job",
            aggregate_id=job.id,
            payload={"schema_version": "1", "tenant_id": str(tenant_id), "job_id": str(job.id)},
            headers=capture_trace_context(),
        )
    await session.flush()
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_VOICE_JOB_CANCELLED,
        actor=actor,
        resource_type="narrative_voice_job",
        resource_id=job.id,
        metadata={"project_id": str(project_id), "status": job.status},
    )
    await session.refresh(job)
    return job


async def _locked(session: AsyncSession, job_id: UUID) -> NarrativeVoiceJob | None:
    job: NarrativeVoiceJob | None = await session.scalar(
        select(NarrativeVoiceJob)
        .where(NarrativeVoiceJob.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return job


class VoiceRegistrationPending(Exception):
    """The accepted workflow run is not committed on the job yet; retry shortly."""


async def register_voice_workflow(
    session: AsyncSession, *, tenant_id: UUID, job_id: UUID, workflow_run_id: UUID
) -> None:
    """Bind a queued job to the run Temporal accepted, before any claim (ADR 0037)."""
    job = await _locked(session, job_id)
    if job is None or job.tenant_id != tenant_id:
        raise ValueError("Invalid voice dispatch identity")
    if job.workflow_run_id is None:
        if job.status == "queued":
            job.workflow_run_id, job.activity_attempt = workflow_run_id, 0
            await session.flush()
    elif job.workflow_run_id != workflow_run_id:
        raise ValueError("Unowned voice execution")


def _finish(job: NarrativeVoiceJob, status: str) -> None:
    job.status, job.execution_token, job.finished_at = status, None, _now()


def _owned(job: NarrativeVoiceJob | None, token: UUID) -> bool:
    return job is not None and job.status == "running" and job.execution_token == token


async def abandon_voice_job(
    session: AsyncSession, *, job_id: UUID, workflow_run_id: UUID, error_code: str
) -> NarrativeVoiceJob | None:
    """Close an active job of this run only; returns ``None`` when it is not ours."""
    job = await _locked(session, job_id)
    if job is None or job.workflow_run_id != workflow_run_id or job.status not in _ACTIVE:
        return None
    job.error_code = error_code[:80]
    _finish(job, "cancelled" if job.cancel_requested else "failed")
    await session.flush()
    return job


async def claim_voice_job(
    session: AsyncSession,
    *,
    job_id: UUID,
    execution_token: UUID,
    workflow_run_id: UUID,
    activity_attempt: int,
) -> VoiceWork | None:
    """Fence one execution of the registered run; its later attempts replace it."""
    job = await _locked(session, job_id)
    if job is None or job.status not in _ACTIVE:
        return None
    if job.workflow_run_id is None:
        raise VoiceRegistrationPending
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
    return VoiceWork(
        tenant_id=job.tenant_id,
        project_id=job.project_id,
        job_id=job.id,
        request=VoiceRequest(
            voice=job.voice,
            speed=job.speed,
            seed=job.seed,
            items=tuple(VoiceItem(text=item["text"], mode=item["mode"]) for item in job.items),
        ),
    )


async def record_voice_progress(
    session: AsyncSession, *, job_id: UUID, execution_token: UUID, progress: int
) -> bool:
    """Store progress for the owning execution; ``False`` once cancellation is asked."""
    job = await _locked(session, job_id)
    if not _owned(job, execution_token):
        return False
    assert job is not None
    job.progress = max(job.progress, min(progress, job.count))
    await session.flush()
    return not job.cancel_requested


def clip_name(job: NarrativeVoiceJob, index: int) -> str:
    """A readable default the creator can rename: who says what."""
    item = job.items[index]
    if item["mode"] == "vocalization":
        return f"{job.character_id} ({item['text']})"[:120]
    return f"{job.character_id}: {textwrap.shorten(item['text'], width=80, placeholder='…')}"[:120]


async def complete_voice_job(
    session: AsyncSession,
    *,
    job_id: UUID,
    execution_token: UUID,
    result: VoiceResult,
    stored: list[tuple[UUID, GeneratedClip]],
    model: ModelIdentity,
) -> NarrativeVoiceJob:
    job = await _locked(session, job_id)
    if job is None:
        raise NotFoundError("Voice job was not found.")
    if not _owned(job, execution_token):
        return job
    if job.cancel_requested:
        _finish(job, "cancelled")
        await session.flush()
        return job
    if [clip.index for _, clip in stored] != list(range(job.count)):
        job.error_code = "invalid_output"
        _finish(job, "failed")
        await session.flush()
        return job
    finished = _now()
    # Identical bytes are one asset per project; a repeated clip adds nothing new.
    known = set(
        await session.scalars(
            select(NarrativeAsset.sha256).where(
                NarrativeAsset.tenant_id == job.tenant_id,
                NarrativeAsset.project_id == job.project_id,
                NarrativeAsset.sha256.in_([clip.sha256 for _, clip in stored]),
                NarrativeAsset.status != "discarded",
            )
        )
    )
    for asset_id, clip in stored:
        if clip.sha256 in known:
            continue
        known.add(clip.sha256)
        item = job.items[clip.index]
        session.add(
            NarrativeAsset(
                id=asset_id,
                tenant_id=job.tenant_id,
                project_id=job.project_id,
                kind="voice",
                source="generated",
                name=clip_name(job, clip.index),
                created_at=finished - timedelta(microseconds=clip.index),
                voice_job_id=job.id,
                job_index=clip.index,
                character_id=job.character_id,
                media_type="audio/wav",
                sha256=clip.sha256,
                size_bytes=len(clip.data),
                duration_ms=max(1, clip.duration_ms),
                seed=job.seed + clip.index,
                provenance={
                    "generator": "local-kokoro",
                    "model_repo": model.repo,
                    "model_revision": model.revision,
                    "voice": job.voice,
                    "speed": job.speed,
                    "mode": item["mode"],
                    "text": item["text"],
                    "node_id": item.get("node_id"),
                    "seed": job.seed + clip.index,
                    "runtime": result.runtime,
                },
                license=model.license[:120],
                status="candidate",
                created_by_user_id=job.requested_by_user_id,
            )
        )
    job.model = f"{model.repo}@{model.revision}"[:200]
    job.runtime = result.runtime
    job.progress = job.count
    _finish(job, "completed")
    await session.flush()
    return job


async def fail_voice_job(
    session: AsyncSession, *, job_id: UUID, execution_token: UUID, error_code: str
) -> NarrativeVoiceJob:
    job = await _locked(session, job_id)
    if job is None:
        raise NotFoundError("Voice job was not found.")
    if _owned(job, execution_token):
        job.error_code = error_code[:80]
        _finish(job, "cancelled" if job.cancel_requested else "failed")
        await session.flush()
    return job
