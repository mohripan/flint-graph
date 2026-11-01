"""Pose admission: shared quotas/fences, an immutable look and a pinned model."""

from hashlib import sha256
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.audit import AuditActor
from flint_graph.application.services.narrative_images import _queue_job
from flint_graph.application.services.narrative_look_images import caption, source_size
from flint_graph.application.services.narrative_looks import (
    bind_job,
    get_look,
    reference,
    replay_job,
)
from flint_graph.domain.errors import DomainError
from flint_graph.infrastructure.db.models import NarrativeImageJob
from flint_graph.infrastructure.db.narrative_pose_models import NarrativePoseJob
from flint_graph.narrative.imagegen import ContentPolicy, clean_appearance
from flint_graph.narrative.poses import pose_request
from flint_graph.narrative.values import canonical_json
from flint_graph.prompts.source import snapshot_async


@snapshot_async
async def queue_pose_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    look_id: UUID,
    pose: str,
    count: int,
    transparent: bool,
    idempotency_key: UUID,
    author_user_id: UUID,
    actor: AuditActor,
    available: bool,
    max_active_jobs: int,
    policy: ContentPolicy,
    model_manifest_sha256: str | None,
    cutout_manifest_sha256: str | None,
) -> NarrativeImageJob:
    try:
        pose = clean_appearance(pose)
        if not pose or len(pose) > 300:
            raise ValueError("Describe the pose in 1-300 characters.")
    except ValueError as error:
        raise DomainError(422, "Invalid pose", str(error), "invalid-pose") from None
    request_hash = sha256(
        canonical_json(
            {
                "operation": "pose",
                "character_id": character_id,
                "look_id": str(look_id),
                "pose": pose,
                "count": count,
                "transparent": transparent,
            }
        )
    ).hexdigest()
    prior = await replay_job(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if prior:
        return prior
    if not available or not model_manifest_sha256 or (transparent and not cutout_manifest_sha256):
        raise DomainError(
            503,
            "Pose model unavailable",
            "Pose generation is not configured on this server.",
            "pose-generation-unavailable",
        )
    look = await get_look(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        look_id=look_id,
    )
    source = await reference(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        asset_id=look.asset_id,
    )
    source_size(source)
    job = await _queue_job(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        author_user_id=author_user_id,
        purpose="character_portrait",
        appearance=caption(look),
        character_type=look.character_type,
        framing="full_body",
        transparent=transparent,
        hires=False,
        build=lambda: pose_request(caption(look), pose, policy=policy),
        count=count,
        idempotency_key=idempotency_key,
        actor=actor,
        available=available,
        max_active_jobs=max_active_jobs,
        policy=policy,
    )
    await bind_job(session, job, [look], request_hash)
    session.add(
        NarrativePoseJob(
            job_id=job.id,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            look_id=look.id,
            pose=pose,
            model_manifest_sha256=model_manifest_sha256,
            cutout_manifest_sha256=cutout_manifest_sha256 if transparent else None,
        )
    )
    await session.flush()
    return job
