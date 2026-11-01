"""Pose admission: shared quotas/fences, an immutable look and a pinned model."""

from hashlib import sha256
from typing import Any
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
from flint_graph.infrastructure.db.narrative_pose_models import (
    NarrativePoseJob,
    NarrativePoseReference,
)
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
    additional_references: list[dict[str, Any]] | None = None,
    max_references: int = 1,
) -> NarrativeImageJob:
    try:
        pose = clean_appearance(pose)
        if not pose or len(pose) > 300:
            raise ValueError("Describe the pose in 1-300 characters.")
    except ValueError as error:
        raise DomainError(422, "Invalid pose", str(error), "invalid-pose") from None
    extras = additional_references or []
    if len(extras) > 1:
        raise DomainError(
            422,
            "Invalid references",
            "Choose at most one additional view.",
            "invalid-pose-reference",
        )
    extra_identity = [{"asset_id": str(item["asset_id"]), "view": item["view"]} for item in extras]
    request_hash = sha256(
        canonical_json(
            {
                "operation": "pose",
                "character_id": character_id,
                "look_id": str(look_id),
                "pose": pose,
                "count": count,
                "transparent": transparent,
                **({"additional_references": extra_identity} if extras else {}),
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
    if extras and max_references < 2:
        raise DomainError(
            503,
            "Additional references unavailable",
            "Additional pose views are not enabled on this server.",
            "pose-reference-unavailable",
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
    sources = [(source, "primary")]
    for item in extras:
        if item["view"] not in {"front", "side", "back", "detail"}:
            raise DomainError(
                422, "Invalid view", "Choose front, side, back or detail.", "invalid-pose-reference"
            )
        extra = await reference(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            asset_id=UUID(str(item["asset_id"])),
        )
        source_size(extra)
        if extra.sha256 == source.sha256:
            raise DomainError(
                422,
                "Duplicate reference",
                "Choose a different approved image.",
                "invalid-pose-reference",
            )
        sources.append((extra, item["view"]))
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
        build=lambda: pose_request(
            caption(look),
            pose,
            policy=policy,
            additional_view=extras[0]["view"] if extras else None,
        ),
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
    for position, (asset, view) in enumerate(sources):
        session.add(
            NarrativePoseReference(
                job_id=job.id,
                position=position,
                tenant_id=tenant_id,
                project_id=project_id,
                asset_id=asset.id,
                view=view,
                name=asset.name,
                sha256=asset.sha256,
                size_bytes=asset.size_bytes,
            )
        )
    await session.flush()
    return job
