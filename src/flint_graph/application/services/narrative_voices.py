"""Character voices and local voice jobs (ADR 0043, ADR 0045).

A character's profile names a catalog voice model (Kokoro-82M by default) and either
one of its stock voices or a private voice reference to clone (#176). API requests
only record intent: a job is queued with an ID-only outbox message and the model runs
later (on the GPU, or the CPU when the shared card is busy) in a fenced activity of
the registered workflow run (ADR 0037). A job snapshots the model, the reference hash
and its consent record, the language and each line's delivery (#177); a model whose
license puts duties on its audio runs only for a creator who accepted that license in
the workspace (#178). Every spoken text becomes a candidate voice clip whose
provenance names the model and license, so obligations follow the clip; only approval
lets a story bind it. Audit metadata and outbox payloads carry identifiers, never the
spoken text or a speaker's name.
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
from flint_graph.application.services.narrative_package_v2 import bind_story_assets
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
    NarrativeAsset,
    NarrativeCharacterProfile,
    NarrativeVoiceJob,
    NarrativeVoiceLicenseAcceptance,
    NarrativeVoiceReference,
    Tenant,
)
from flint_graph.infrastructure.narrative_imagegen import ModelIdentity
from flint_graph.infrastructure.narrative_voicegen import (
    GeneratedClip,
    VoiceItem,
    VoiceRequest,
    VoiceResult,
)
from flint_graph.narrative.json_format import parse_json
from flint_graph.narrative.values import canonical_json
from flint_graph.narrative.voice_models import (
    DEFAULT_MODEL,
    LICENSES,
    MODELS,
    Delivery,
    VoiceModelSpec,
    clean_delivery,
    license_by_sha256,
)
from flint_graph.narrative.voices import MAX_ITEMS, VOICE_IDS, clean_voice_text

_ACTIVE = ("queued", "running")
_NODE_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ReferenceWork:
    """Which reference audio the activity reads from storage for the child."""

    id: UUID
    sha256: str
    size_bytes: int
    transcript: str | None


@dataclass(frozen=True)
class VoiceWork:
    tenant_id: UUID
    project_id: UUID
    job_id: UUID
    request: VoiceRequest
    reference: ReferenceWork | None = None


def _invalid_choice(detail: str) -> DomainError:
    return DomainError(422, "Invalid voice", detail, "invalid-voice")


def installed_spec(model_id: str, installed: frozenset[str]) -> VoiceModelSpec:
    """A catalog model this server can run, or 422."""
    spec = MODELS.get(model_id)
    if spec is None or model_id not in installed:
        raise _invalid_choice("Choose one of the voice models installed on this server.")
    return spec


def stock_voice_ids(spec: VoiceModelSpec) -> frozenset[str]:
    if spec.engine == "kokoro":
        return VOICE_IDS
    return frozenset(voice.id for voice in spec.stock_voices)


async def active_reference(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, reference_id: UUID
) -> NarrativeVoiceReference:
    reference = await session.scalar(
        select(NarrativeVoiceReference).where(
            NarrativeVoiceReference.tenant_id == tenant_id,
            NarrativeVoiceReference.project_id == project_id,
            NarrativeVoiceReference.id == reference_id,
        )
    )
    if reference is None:
        raise NotFoundError("Voice reference was not found.")
    if reference.status != "active":
        raise DomainError(
            409,
            "Reference deleted",
            "This voice reference was deleted. Choose another reference.",
            "voice-reference-deleted",
        )
    return reference


async def has_accepted(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID, spec: VoiceModelSpec
) -> bool:
    if spec.license.obligations == "none":
        return True
    found = await session.scalar(
        select(NarrativeVoiceLicenseAcceptance.id).where(
            NarrativeVoiceLicenseAcceptance.tenant_id == tenant_id,
            NarrativeVoiceLicenseAcceptance.user_id == user_id,
            NarrativeVoiceLicenseAcceptance.model_id == spec.id,
            NarrativeVoiceLicenseAcceptance.license_sha256 == spec.license.sha256,
        )
    )
    return found is not None


async def accepted_models(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID
) -> frozenset[str]:
    """Models whose current license text this creator accepted in this workspace."""
    rows = await session.execute(
        select(
            NarrativeVoiceLicenseAcceptance.model_id,
            NarrativeVoiceLicenseAcceptance.license_sha256,
        ).where(
            NarrativeVoiceLicenseAcceptance.tenant_id == tenant_id,
            NarrativeVoiceLicenseAcceptance.user_id == user_id,
        )
    )
    return frozenset(
        model_id
        for model_id, digest in rows
        if model_id in MODELS and MODELS[model_id].license.sha256 == digest
    )


async def accept_license(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    model_id: str,
    license_sha256: str,
    installed: frozenset[str],
    actor: AuditActor,
) -> NarrativeVoiceLicenseAcceptance:
    spec = MODELS.get(model_id)
    if spec is None or model_id not in installed:
        raise NotFoundError("Voice model was not found.")
    if license_sha256 != spec.license.sha256:
        raise DomainError(
            409,
            "License changed",
            "This license text changed since you opened it. Read it again before accepting.",
            "voice-license-changed",
        )
    scope = (
        NarrativeVoiceLicenseAcceptance.tenant_id == tenant_id,
        NarrativeVoiceLicenseAcceptance.user_id == user_id,
        NarrativeVoiceLicenseAcceptance.model_id == model_id,
        NarrativeVoiceLicenseAcceptance.license_sha256 == license_sha256,
    )
    existing = await session.scalar(select(NarrativeVoiceLicenseAcceptance).where(*scope))
    if existing is not None:
        return existing
    acceptance = NarrativeVoiceLicenseAcceptance(
        tenant_id=tenant_id,
        user_id=user_id,
        model_id=model_id,
        license_id=spec.license_id,
        license_sha256=license_sha256,
    )
    session.add(acceptance)
    await session.flush()
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_VOICE_LICENSE_ACCEPTED,
        actor=actor,
        resource_type="narrative_voice_model",
        resource_id=model_id,
        metadata={"license_id": spec.license_id, "license_sha256": license_sha256},
    )
    await session.refresh(acceptance)
    return acceptance


async def set_character_voice(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    base_version: int,
    voice: str | None,
    author_user_id: UUID,
    model: str | None = None,
    reference_id: UUID | None = None,
    installed: frozenset[str] = frozenset({DEFAULT_MODEL}),
) -> Profile:
    """A stock voice or a reference to clone; switching never touches made clips."""
    if voice is not None and reference_id is not None:
        raise _invalid_choice("Choose a stock voice or a voice reference, not both.")
    spec = None
    if voice is not None or reference_id is not None:
        spec = installed_spec(model or DEFAULT_MODEL, installed | {DEFAULT_MODEL})
        if voice is not None and voice not in stock_voice_ids(spec):
            raise _invalid_choice("Choose one of the listed voices.")
        if reference_id is not None:
            if not spec.cloning:
                raise _invalid_choice(f"{spec.name} cannot clone a voice from a reference.")
            await active_reference(
                session, tenant_id=tenant_id, project_id=project_id, reference_id=reference_id
            )
    profile = await _editable(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        base_version=base_version,
        author_user_id=author_user_id,
    )
    profile.voice = voice
    profile.voice_model = spec.id if spec is not None else None
    profile.voice_reference_id = reference_id
    await session.flush()
    portrait = (
        await session.get(NarrativeAsset, profile.portrait_asset_id)
        if profile.portrait_asset_id
        else None
    )
    return profile, portrait


def _invalid(detail: str) -> DomainError:
    return DomainError(422, "Invalid voice request", detail, "invalid-voice-request")


def clean_items(
    items: list[dict[str, Any]], spec: VoiceModelSpec | None = None
) -> list[dict[str, Any]]:
    if not 1 <= len(items) <= MAX_ITEMS:
        raise _invalid(f"Ask for 1 to {MAX_ITEMS} clips at a time.")
    model = spec or MODELS[DEFAULT_MODEL]
    cleaned = []
    for item in items:
        node_id = item.get("node_id")
        if node_id is not None and (type(node_id) is not str or not _NODE_ID.fullmatch(node_id)):
            raise _invalid("Check the line each clip is for.")
        try:
            text = clean_voice_text(str(item.get("text", "")), str(item.get("mode", "")))
            delivery = clean_delivery(item.get("delivery"), model)
        except ValueError as error:
            raise _invalid(str(error)) from None
        cleaned.append(
            {"mode": item["mode"], "text": text, "node_id": node_id, "delivery": delivery.as_dict()}
        )
    return cleaned


def _consent(reference: NarrativeVoiceReference) -> dict[str, Any]:
    return {
        "reference_id": str(reference.id),
        "consent": reference.consent,
        "speaker_name": reference.speaker_name,
        "declared_by_user_id": str(reference.consent_declared_by_user_id),
        "declared_at": reference.consent_declared_at.isoformat(),
    }


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
    installed: frozenset[str] = frozenset({DEFAULT_MODEL}),
    language: str = "en",
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
    profile = await session.scalar(
        select(NarrativeCharacterProfile).where(
            NarrativeCharacterProfile.tenant_id == tenant_id,
            NarrativeCharacterProfile.project_id == project_id,
            NarrativeCharacterProfile.character_id == character_id,
        )
    )
    voice = profile.voice if profile is not None else None
    reference_id = profile.voice_reference_id if profile is not None else None
    model_id = (profile.voice_model if profile is not None else None) or DEFAULT_MODEL
    spec = MODELS.get(model_id)
    cleaned = clean_items(items, spec)
    identity = {
        "character_id": character_id,
        "model": model_id,
        "voice": voice,
        "reference_id": str(reference_id) if reference_id else None,
        "language": language,
        "items": cleaned,
    }
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
    if voice is None and reference_id is None:
        raise DomainError(
            409,
            "No voice chosen",
            "Choose a voice for this character first.",
            "voice-not-chosen",
        )
    if spec is None or model_id not in installed | {DEFAULT_MODEL}:
        raise DomainError(
            409,
            "Voice model unavailable",
            "This character's voice model is not installed on this server. Choose another.",
            "voice-model-unavailable",
        )
    if language not in spec.languages:
        raise _invalid(f"{spec.name} does not speak this story's language.")
    if not await has_accepted(session, tenant_id=tenant_id, user_id=author_user_id, spec=spec):
        raise DomainError(
            409,
            "License not accepted",
            f"Read and accept the {spec.license.name} before generating with {spec.name}.",
            "voice-license-not-accepted",
        )
    reference = (
        await active_reference(
            session, tenant_id=tenant_id, project_id=project_id, reference_id=reference_id
        )
        if reference_id is not None
        else None
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
        voice_model=model_id,
        voice=voice,
        reference_id=reference.id if reference else None,
        reference_sha256=reference.sha256 if reference else None,
        consent=_consent(reference) if reference else None,
        language=language,
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
        metadata={"project_id": str(project_id), "count": job.count, "model": model_id},
    )
    await session.refresh(job)
    return job


@dataclass(frozen=True)
class CarriedLicense:
    license_id: str
    name: str
    obligations: str
    summary: str
    # (line node ID, story asset key) pairs whose clips cause this license.
    lines: tuple[tuple[str, str], ...]


async def revision_voice_licenses(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, revision_id: UUID
) -> list[CarriedLicense]:
    """The voice model licenses a release of this revision carries, and why (#178)."""
    revision = await get_revision(
        session, tenant_id=tenant_id, project_id=project_id, revision_id=revision_id
    )
    story = parse_json(revision.story_json.encode("utf-8"), limit=5 * 1024 * 1024)
    audio = {key: item for key, item in story["assets"].items() if item["kind"] == "audio"}
    if not audio:
        return []
    bound = await bind_story_assets(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        assets=audio,
        budget=2**40,
        lock=False,
    )
    by_key: dict[str, list[str]] = {}
    for node_id, node in sorted(story["nodes"].items()):
        clip = node.get("voice", {}).get("audio") if node["type"] == "line" else None
        if clip is not None:
            by_key.setdefault(clip, []).append(node_id)
    found: dict[str, list[tuple[str, str]]] = {}
    for item in bound:
        named = item.asset.provenance.get("license") if item.asset.source == "generated" else None
        license = license_by_sha256(str(named.get("sha256"))) if isinstance(named, dict) else None
        if license is not None:
            lines = found.setdefault(license.id, [])
            lines.extend((node_id, item.key) for node_id in by_key.get(item.key, []))
    carried = []
    for license_id in sorted(found):
        license = LICENSES[license_id]
        carried.append(
            CarriedLicense(
                license_id=license.id,
                name=license.name,
                obligations=license.obligations,
                summary=license.summary,
                lines=tuple(sorted(found[license_id])),
            )
        )
    return carried


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
    reference = (
        await session.get(NarrativeVoiceReference, job.reference_id)
        if job.reference_id is not None
        else None
    )
    if job.reference_id is not None and (
        reference is None
        or reference.status != "active"
        or reference.sha256 != job.reference_sha256
    ):
        # Deleting a reference blocks every job that has not spoken yet.
        job.error_code = "reference_deleted"
        _finish(job, "failed")
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
            items=tuple(
                VoiceItem(
                    text=item["text"],
                    mode=item["mode"],
                    delivery=Delivery(**item["delivery"]) if item.get("delivery") else None,
                )
                for item in job.items
            ),
            model=job.voice_model,
            language=job.language,
        ),
        reference=(
            ReferenceWork(
                id=reference.id,
                sha256=reference.sha256,
                size_bytes=reference.size_bytes,
                transcript=reference.transcript,
            )
            if reference is not None
            else None
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


def _provenance(
    job: NarrativeVoiceJob,
    model: ModelIdentity,
    item: dict[str, Any],
    clip: GeneratedClip,
    result: VoiceResult,
) -> dict[str, Any]:
    """What made this clip; the license travels with it, not with the character."""
    spec = MODELS[job.voice_model]
    made: dict[str, Any] = {
        "generator": f"local-{spec.engine}",
        "model_id": spec.id,
        "model_repo": model.repo,
        "model_revision": model.revision,
        "license": {
            "id": spec.license.id,
            "name": spec.license.name,
            "sha256": spec.license.sha256,
            "obligations": spec.license.obligations,
        },
        "voice": job.voice,
        "speed": job.speed,
        "mode": item["mode"],
        "text": item["text"],
        "node_id": item.get("node_id"),
        "delivery": item.get("delivery") or Delivery().as_dict(),
        "language": job.language,
        "seed": job.seed + clip.index,
        "device": clip.device,
        "watermark": spec.watermark,
        "runtime": result.runtime,
    }
    if job.consent is not None:
        consent = job.consent
        made["reference"] = {
            "id": consent["reference_id"],
            "sha256": job.reference_sha256,
            "consent": consent["consent"],
            "speaker_name": consent["speaker_name"],
            "declared_by_user_id": consent["declared_by_user_id"],
            "declared_at": consent["declared_at"],
        }
    return made


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
    spec = MODELS[job.voice_model]
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
                provenance=_provenance(job, model, item, clip, result),
                license=spec.license.name[:120],
                notice=spec.license.notice or None,
                status="candidate",
                created_by_user_id=job.requested_by_user_id,
            )
        )
    job.model = f"{model.repo}@{model.revision}"[:200]
    # The device each clip was spoken on: the GPU, or the CPU when the card was busy.
    job.runtime = {**result.runtime, "clip_devices": ",".join(c.device for _, c in stored)}
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
