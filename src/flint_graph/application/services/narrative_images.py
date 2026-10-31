"""Local portrait generation jobs (ADR 0039).

API requests only record intent: a job is queued with an ID-only outbox message and
the GPU work runs later in a fenced activity of the registered workflow run (ADR
0037). Results are candidate images; only creator approval makes one a portrait.
Audit metadata and outbox payloads carry identifiers, never prompts.
"""

import secrets
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.narrative_image_workflow import CANCELLED_TOPIC, QUEUED_TOPIC
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
from flint_graph.infrastructure.db.models import (
    NarrativeAsset,
    NarrativeCharacterProfile,
    NarrativeImageJob,
    Tenant,
)
from flint_graph.infrastructure.narrative_imagegen import (
    GeneratedImage,
    GenerationRequest,
    GenerationResult,
    ModelIdentity,
)
from flint_graph.narrative.imagegen import (
    DEFAULT_POLICY,
    ContentPolicy,
    ExpressionRequest,
    ImageRequest,
    background_request,
    clean_appearance,
    expression_names,
    expression_request,
    portrait_request,
)
from flint_graph.narrative.values import canonical_json

_ACTIVE = ("queued", "running")


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class InpaintPlan:
    """The base image to repaint; its bytes are fetched, hash-verified, after the claim."""

    asset_id: UUID
    sha256: str
    size_bytes: int
    box: tuple[int, int, int, int]
    strength: float
    prompts: tuple[str, ...]


@dataclass(frozen=True)
class ImageWork:
    """Everything an execution needs, loaded inside the claim transaction."""

    tenant_id: UUID
    project_id: UUID
    job_id: UUID
    request: GenerationRequest
    inpaint: InpaintPlan | None = None


# Expression bases: what the child accepts, and images a character can be drawn from.
BASE_KINDS = ("sprite", "image", "character_portrait")
MIN_BASE, MAX_BASE, MIN_FACE = 64, 2560, 16  # up to 2x high-resolution sprites


def _invalid(detail: str) -> DomainError:
    return DomainError(422, "Invalid expression request", detail, "invalid-expression-request")


async def create_expression_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    author_user_id: UUID,
    base_asset_id: UUID,
    face_box: tuple[int, int, int, int],
    expressions: list[str],
    idempotency_key: UUID,
    actor: AuditActor,
    available: bool,
    max_active_jobs: int,
    policy: ContentPolicy = DEFAULT_POLICY,
) -> NarrativeImageJob:
    """Queue face repaints of one base image, one per expression (ADR 0041)."""
    base = await session.scalar(
        select(NarrativeAsset).where(
            NarrativeAsset.tenant_id == tenant_id,
            NarrativeAsset.project_id == project_id,
            NarrativeAsset.id == base_asset_id,
            NarrativeAsset.status != "discarded",
        )
    )
    if base is None or base.media_type != "image/png" or base.kind not in BASE_KINDS:
        raise NotFoundError("Choose a sprite, image or portrait of this project.")
    width, height = base.width or 0, base.height or 0
    if not (MIN_BASE <= width <= MAX_BASE and MIN_BASE <= height <= MAX_BASE):
        raise _invalid(f"Expressions need an image between {MIN_BASE} and {MAX_BASE} pixels.")
    left, top, right, bottom = face_box
    box_width, box_height = right - left, bottom - top
    if not (
        0 <= left < right <= width
        and 0 <= top < bottom <= height
        and min(box_width, box_height) >= MIN_FACE
        and 0.5 <= box_width / box_height <= 2
    ):
        raise _invalid("Place the face box over the face, inside the image.")
    try:
        expression_names(expressions)
    except ValueError as error:
        raise _invalid(str(error)) from None
    profile = await session.scalar(
        select(NarrativeCharacterProfile).where(
            NarrativeCharacterProfile.tenant_id == tenant_id,
            NarrativeCharacterProfile.project_id == project_id,
            NarrativeCharacterProfile.character_id == character_id,
        )
    )
    appearance = profile.appearance if profile else ""
    character_type = profile.character_type if profile else "other"
    return await _queue_job(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        author_user_id=author_user_id,
        purpose="character_expression",
        character_id=character_id,
        appearance=appearance,
        character_type=character_type,
        framing="face",
        transparent=False,
        build=lambda: expression_request(appearance, character_type, expressions, policy=policy),
        count=len(expressions),
        idempotency_key=idempotency_key,
        actor=actor,
        available=available,
        max_active_jobs=max_active_jobs,
        base=(base, (left, top, right, bottom)),
        expressions=expressions,
    )


async def create_portrait_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    author_user_id: UUID,
    appearance: str,
    character_type: str,
    framing: str,
    count: int,
    idempotency_key: UUID,
    actor: AuditActor,
    available: bool,
    max_active_jobs: int,
    transparent: bool = False,
    policy: ContentPolicy = DEFAULT_POLICY,
) -> NarrativeImageJob:
    """Queue candidate portraits, or cut-out stage sprites when ``transparent``."""
    return await _queue_job(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        author_user_id=author_user_id,
        purpose="character_portrait",
        character_id=character_id,
        appearance=appearance,
        character_type=character_type,
        framing=framing,
        transparent=transparent,
        build=lambda: portrait_request(
            appearance, character_type, framing, transparent=transparent, policy=policy
        ),
        count=count,
        idempotency_key=idempotency_key,
        actor=actor,
        available=available,
        max_active_jobs=max_active_jobs,
    )


async def create_background_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    author_user_id: UUID,
    description: str,
    count: int,
    idempotency_key: UUID,
    actor: AuditActor,
    available: bool,
    max_active_jobs: int,
    policy: ContentPolicy = DEFAULT_POLICY,
) -> NarrativeImageJob:
    return await _queue_job(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        author_user_id=author_user_id,
        purpose="background",
        character_id=None,
        appearance=description,
        character_type="other",
        framing="scenery",
        transparent=False,
        build=lambda: background_request(description, policy=policy),
        count=count,
        idempotency_key=idempotency_key,
        actor=actor,
        available=available,
        max_active_jobs=max_active_jobs,
    )


async def _queue_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    author_user_id: UUID,
    purpose: str,
    character_id: str | None,
    appearance: str,
    character_type: str,
    framing: str,
    transparent: bool,
    build: Callable[[], ImageRequest | ExpressionRequest],
    count: int,
    idempotency_key: UUID,
    actor: AuditActor,
    available: bool,
    max_active_jobs: int,
    base: tuple[NarrativeAsset, tuple[int, int, int, int]] | None = None,
    expressions: list[str] | None = None,
) -> NarrativeImageJob:
    # NO KEY UPDATE serializes workspace admission without blocking audit FK checks.
    tenant = await session.scalar(
        select(Tenant).where(Tenant.id == tenant_id).with_for_update(key_share=True)
    )
    if tenant is None:
        raise NotFoundError("Workspace was not found.")
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    identity: dict[str, Any] = {
        "purpose": purpose,
        "character_id": character_id,
        "appearance": appearance,
        "character_type": character_type,
        "framing": framing,
        "count": count,
    }
    # Only sprite requests carry the flag, so earlier requests keep their hashes.
    if transparent:
        identity["transparent"] = True
    if base is not None:
        identity |= {"base_asset_id": str(base[0].id), "face_box": list(base[1]),
                     "expressions": expressions}
    request_hash = sha256(canonical_json(identity)).hexdigest()
    existing = await session.scalar(
        select(NarrativeImageJob).where(
            NarrativeImageJob.project_id == project_id,
            NarrativeImageJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ConflictError("This request key was already used for a different request.")
        return existing
    if project.archived_at is not None:
        raise ConflictError("Restore this project before generating images.")
    if not available:
        raise DomainError(
            503,
            "Service unavailable",
            "Image generation is not configured on this server. Characters still work.",
            "image-generation-unavailable",
        )
    try:
        built = build()
    except ValueError as error:
        raise DomainError(422, "Invalid description", str(error), "invalid-appearance") from None
    if isinstance(built, ExpressionRequest):
        assert base is not None
        size = (base[0].width or 0, base[0].height or 0)
        built_fields: dict[str, Any] = {
            "prompt": built.prompts[0],
            "width": size[0],
            "height": size[1],
            "base_asset_id": base[0].id,
            "face_box": list(base[1]),
            "strength": built.strength,
            "expressions": list(built.ids),
            "prompts": list(built.prompts),
        }
    else:
        built_fields = {"prompt": built.prompt, "width": built.width, "height": built.height}
    active = (
        await session.scalar(
            select(func.count(NarrativeImageJob.id)).where(
                NarrativeImageJob.tenant_id == tenant_id,
                NarrativeImageJob.status.in_(_ACTIVE),
            )
        )
        or 0
    )
    if active >= max_active_jobs:
        raise TooManyRequestsError("Wait for the current images to finish.")
    job = NarrativeImageJob(
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        purpose=purpose,
        requested_by_user_id=author_user_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        appearance=appearance,
        character_type=character_type,
        framing=framing,
        negative_prompt=built.negative_prompt,
        steps=built.steps,
        guidance=built.guidance,
        seeds=[secrets.randbelow(2**32) for _ in range(count)],
        count=count,
        transparent=transparent,
        status="queued",
        progress=0,
        cancel_requested=False,
        **built_fields,
    )
    session.add(job)
    await session.flush()
    await append_outbox_message(
        session,
        tenant_id=tenant_id,
        topic=QUEUED_TOPIC,
        aggregate_type="narrative_image_job",
        aggregate_id=job.id,
        payload={"schema_version": "1", "tenant_id": str(tenant_id), "job_id": str(job.id)},
        headers=capture_trace_context(),
    )
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_IMAGE_JOB_REQUESTED,
        actor=actor,
        resource_type="narrative_image_job",
        resource_id=job.id,
        metadata={"project_id": str(project_id), "purpose": purpose, "count": count},
    )
    await session.refresh(job)
    return job


async def _assets(session: AsyncSession, job_ids: list[UUID]) -> dict[UUID, list[NarrativeAsset]]:
    grouped: dict[UUID, list[NarrativeAsset]] = {job_id: [] for job_id in job_ids}
    if not job_ids:
        return grouped
    rows = await session.scalars(
        select(NarrativeAsset)
        .where(NarrativeAsset.job_id.in_(job_ids), NarrativeAsset.status != "discarded")
        .order_by(NarrativeAsset.job_index)
    )
    for asset in rows:
        if asset.job_id is not None:
            grouped[asset.job_id].append(asset)
    return grouped


async def list_image_jobs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    purpose: str,
    character_id: str | None,
    limit: int,
) -> list[tuple[NarrativeImageJob, list[NarrativeAsset]]]:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    jobs = list(
        await session.scalars(
            select(NarrativeImageJob)
            .where(
                NarrativeImageJob.tenant_id == tenant_id,
                NarrativeImageJob.project_id == project_id,
                NarrativeImageJob.purpose == purpose,
                NarrativeImageJob.character_id.is_(None)
                if character_id is None
                else NarrativeImageJob.character_id == character_id,
            )
            .order_by(NarrativeImageJob.created_at.desc(), NarrativeImageJob.id.desc())
            .limit(limit)
        )
    )
    assets = await _assets(session, [job.id for job in jobs])
    return [(job, assets[job.id]) for job in jobs]


async def _job(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, job_id: UUID, lock: bool = False
) -> NarrativeImageJob:
    statement = select(NarrativeImageJob).where(
        NarrativeImageJob.tenant_id == tenant_id,
        NarrativeImageJob.project_id == project_id,
        NarrativeImageJob.id == job_id,
    )
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    job = await session.scalar(statement)
    if job is None:
        raise NotFoundError("Image job was not found.")
    return job


async def get_image_job(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, job_id: UUID
) -> tuple[NarrativeImageJob, list[NarrativeAsset]]:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    job = await _job(session, tenant_id=tenant_id, project_id=project_id, job_id=job_id)
    return job, (await _assets(session, [job.id]))[job.id]


async def cancel_image_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    job_id: UUID,
    actor: AuditActor,
) -> NarrativeImageJob:
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
            topic=CANCELLED_TOPIC,
            aggregate_type="narrative_image_job",
            aggregate_id=job.id,
            payload={"schema_version": "1", "tenant_id": str(tenant_id), "job_id": str(job.id)},
            headers=capture_trace_context(),
        )
    await session.flush()
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_IMAGE_JOB_CANCELLED,
        actor=actor,
        resource_type="narrative_image_job",
        resource_id=job.id,
        metadata={"project_id": str(project_id), "status": job.status},
    )
    await session.refresh(job)
    return job


async def _locked(session: AsyncSession, job_id: UUID) -> NarrativeImageJob | None:
    job: NarrativeImageJob | None = await session.scalar(
        select(NarrativeImageJob)
        .where(NarrativeImageJob.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return job


class ImageRegistrationPending(Exception):
    """The accepted workflow run is not committed on the job yet; retry shortly."""


async def register_image_workflow(
    session: AsyncSession, *, tenant_id: UUID, job_id: UUID, workflow_run_id: UUID
) -> None:
    """Bind a queued job to the run Temporal accepted, before any claim (ADR 0037)."""
    job = await session.scalar(
        select(NarrativeImageJob)
        .where(NarrativeImageJob.id == job_id, NarrativeImageJob.tenant_id == tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        raise ValueError("Invalid image dispatch identity")
    if job.workflow_run_id is None:
        if job.status == "queued":
            job.workflow_run_id, job.activity_attempt = workflow_run_id, 0
            await session.flush()
    elif job.workflow_run_id != workflow_run_id:
        raise ValueError("Unowned image execution")


def _finish(job: NarrativeImageJob, status: str) -> None:
    job.status, job.execution_token, job.finished_at = status, None, _now()


def _owned(job: NarrativeImageJob | None, token: UUID) -> bool:
    return job is not None and job.status == "running" and job.execution_token == token


async def abandon_image_job(
    session: AsyncSession, *, job_id: UUID, workflow_run_id: UUID, error_code: str
) -> NarrativeImageJob | None:
    """Close an active job of this run only; returns ``None`` when it is not ours."""
    job = await _locked(session, job_id)
    if job is None or job.workflow_run_id != workflow_run_id or job.status not in _ACTIVE:
        return None
    job.error_code = error_code[:80]
    _finish(job, "cancelled" if job.cancel_requested else "failed")
    await session.flush()
    return job


async def claim_image_job(
    session: AsyncSession,
    *,
    job_id: UUID,
    execution_token: UUID,
    workflow_run_id: UUID,
    activity_attempt: int,
) -> ImageWork | None:
    """Fence one execution of the registered run; its later attempts replace it."""
    job = await _locked(session, job_id)
    if job is None or job.status not in _ACTIVE:
        return None
    if job.workflow_run_id is None:
        raise ImageRegistrationPending
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
    plan = None
    if job.purpose == "character_expression":
        # The composite foreign key keeps the base in this project; RESTRICT keeps it.
        base = await session.get(NarrativeAsset, job.base_asset_id)
        assert base is not None and job.face_box and job.prompts and job.strength
        left, top, right, bottom = job.face_box
        plan = InpaintPlan(
            asset_id=base.id,
            sha256=base.sha256,
            size_bytes=base.size_bytes,
            box=(left, top, right, bottom),
            strength=job.strength,
            prompts=tuple(job.prompts),
        )
    return ImageWork(
        inpaint=plan,
        tenant_id=job.tenant_id,
        project_id=job.project_id,
        job_id=job.id,
        request=GenerationRequest(
            prompt=job.prompt,
            negative_prompt=job.negative_prompt,
            width=job.width,
            height=job.height,
            steps=job.steps,
            guidance=job.guidance,
            seeds=tuple(job.seeds),
            cutout=job.transparent,
        ),
    )


async def record_progress(
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


async def complete_image_job(
    session: AsyncSession,
    *,
    job_id: UUID,
    execution_token: UUID,
    result: GenerationResult,
    stored: list[tuple[UUID, GeneratedImage]],
    model: ModelIdentity,
) -> NarrativeImageJob:
    job = await _locked(session, job_id)
    if job is None:
        raise NotFoundError("Image job was not found.")
    if not _owned(job, execution_token):
        return job
    if job.cancel_requested:
        _finish(job, "cancelled")
        await session.flush()
        return job
    cutout = result.cutout
    if (cutout is not None) != job.transparent or any(
        (image.box is not None) != job.transparent for _, image in stored
    ):
        # A sprite with its scenery still around it, or an opaque portrait that was cropped.
        job.error_code = "invalid_output"
        _finish(job, "failed")
        await session.flush()
        return job
    # Lists are newest first; earlier candidates of one job get slightly later times so
    # they read 1, 2, 3, 4 even where the clock does not advance between rows.
    finished = _now()
    kind = _asset_kind(job)
    if job.purpose == "character_expression":
        # A repainted face is the same kind of image as its base.
        base = await session.get(NarrativeAsset, job.base_asset_id)
        kind = base.kind if base is not None else "sprite"
    # Identical bytes are one asset per project; a repeated image adds nothing new.
    known = set(
        await session.scalars(
            select(NarrativeAsset.sha256).where(
                NarrativeAsset.tenant_id == job.tenant_id,
                NarrativeAsset.project_id == job.project_id,
                NarrativeAsset.sha256.in_([image.sha256 for _, image in stored]),
                NarrativeAsset.status != "discarded",
            )
        )
    )
    for asset_id, image in stored:
        if image.sha256 in known:
            continue
        known.add(image.sha256)
        provenance: dict[str, Any] = {
            "generator": "local-diffusers",
            "model_repo": model.repo,
            "model_revision": model.revision,
            "prompt": job.prompt,
            "negative_prompt": job.negative_prompt,
            "width": job.width,
            "height": job.height,
            "steps": job.steps,
            "guidance": job.guidance,
            "seed": image.seed,
            "runtime": result.runtime,
        }
        if cutout is not None and image.box is not None:
            provenance["cutout"] = {
                "model_repo": cutout.identity.repo,
                "model_revision": cutout.identity.revision,
                "sha256": cutout.sha256,
                "license": cutout.identity.license,
                "box": list(image.box),
            }
        if job.purpose == "character_expression" and job.expressions and job.prompts:
            provenance |= {
                "prompt": job.prompts[image.index],
                "expression": job.expressions[image.index],
                "base_asset_id": str(job.base_asset_id),
                "face_box": job.face_box,
                "strength": job.strength,
            }
        session.add(
            NarrativeAsset(
                id=asset_id,
                tenant_id=job.tenant_id,
                project_id=job.project_id,
                kind=kind,
                source="generated",
                name=_asset_name(job, image.index),
                created_at=finished - timedelta(microseconds=image.index),
                job_id=job.id,
                job_index=image.index,
                character_id=job.character_id,
                media_type="image/png",
                sha256=image.sha256,
                size_bytes=len(image.data),
                width=image.width,
                height=image.height,
                thumbnail_sha256=image.thumbnail_sha256,
                thumbnail_size_bytes=len(image.thumbnail),
                thumbnail_width=image.thumbnail_width,
                thumbnail_height=image.thumbnail_height,
                seed=image.seed,
                provenance=provenance,
                license=model.license[:120],
                status="candidate",
                created_by_user_id=job.requested_by_user_id,
            )
        )
    job.model = f"{model.repo}@{model.revision}"[:200]
    if cutout is not None:
        job.cutout_model = f"{cutout.identity.repo}@{cutout.identity.revision}"[:200]
        job.cutout_sha256 = cutout.sha256
    job.runtime = result.runtime
    job.prompt_tokens = result.prompt_tokens
    job.truncated = result.truncated
    job.progress = job.count
    _finish(job, "completed")
    await session.flush()
    return job


def _asset_kind(job: NarrativeImageJob) -> str:
    """Cut-out sprites wait in the library for a character's expression slots."""
    if job.purpose == "background":
        return "background"
    return "sprite" if job.transparent else "character_portrait"


def _asset_name(job: NarrativeImageJob, index: int) -> str:
    """A readable default the creator can rename: what was asked for, numbered."""
    if job.purpose == "background":
        base = textwrap.shorten(clean_appearance(job.appearance), width=60, placeholder="…")
    elif job.purpose == "character_expression" and job.expressions:
        return f"{job.character_id} {job.expressions[index]}"
    else:
        base = f"{job.character_id} {'sprite' if job.transparent else 'portrait'}"
    return f"{base} {index + 1}"


async def fail_image_job(
    session: AsyncSession, *, job_id: UUID, execution_token: UUID, error_code: str
) -> NarrativeImageJob:
    job = await _locked(session, job_id)
    if job is None:
        raise NotFoundError("Image job was not found.")
    if _owned(job, execution_token):
        job.error_code = error_code[:80]
        _finish(job, "cancelled" if job.cancel_requested else "failed")
        await session.flush()
    return job
