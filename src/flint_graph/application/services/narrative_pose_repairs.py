"""Admission for a creator-selected local repair of an existing pose image."""

from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.audit import AuditActor
from flint_graph.application.services.narrative_characters import get_asset
from flint_graph.application.services.narrative_looks import replay_job
from flint_graph.application.services.narrative_poses import queue_pose_job
from flint_graph.config import Settings
from flint_graph.domain.errors import DomainError, NotFoundError
from flint_graph.infrastructure.db.models import NarrativeImageJob
from flint_graph.infrastructure.db.narrative_character_adapter_models import (
    NarrativePoseCharacterAdapter,
)
from flint_graph.infrastructure.db.narrative_pose_models import (
    NarrativePoseJob,
    NarrativePoseRepair,
)
from flint_graph.infrastructure.db.narrative_style_models import (
    NarrativePoseStyle,
    NarrativeStyleJob,
)
from flint_graph.narrative.imagegen import clean_appearance, content_policy
from flint_graph.narrative.pose_repairs import validate_region
from flint_graph.narrative.values import canonical_json
from flint_graph.prompts.source import snapshot_async


def invalid(detail: str) -> DomainError:
    return DomainError(422, "Invalid pose repair", detail, "invalid-pose-repair")


@snapshot_async
async def queue_pose_repair(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    settings: Settings,
    author_user_id: UUID,
    actor: AuditActor,
    asset_id: UUID,
    box: list[int],
    instruction: str,
    count: int,
    idempotency_key: UUID,
) -> NarrativeImageJob:
    try:
        instruction = clean_appearance(instruction)
        if not instruction or len(instruction) > 300:
            raise ValueError("Describe the correction in 1-300 characters.")
    except ValueError as error:
        raise invalid(str(error)) from None
    request_hash = sha256(
        canonical_json(
            {
                "operation": "pose_repair",
                "character_id": character_id,
                "asset_id": str(asset_id),
                "box": box,
                "instruction": instruction,
                "count": count,
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
    if not settings.narrative_pose_repairs_enabled or settings.narrative_pose_max_references < 2:
        raise DomainError(
            503,
            "Repairs unavailable",
            "Local pose repairs are not enabled on this server.",
            "pose-repairs-unavailable",
        )
    source = await get_asset(session, tenant_id=tenant_id, project_id=project_id, asset_id=asset_id)
    plan = await session.get(NarrativePoseJob, source.job_id) if source.job_id else None
    original = await session.get(NarrativeImageJob, source.job_id) if plan else None
    if (
        not plan
        or not original
        or plan.project_id != project_id
        or plan.tenant_id != tenant_id
        or plan.character_id != character_id
    ):
        raise NotFoundError("Pose source was not found.")
    if (
        source.status == "discarded"
        or original.status != "completed"
        or source.media_type != "image/png"
    ):
        raise invalid("Choose an available completed pose image. It need not be approved.")
    if plan.model_manifest_sha256 != settings.narrative_pose_model_manifest_sha256:
        raise invalid("The source uses another pose model. Restore its installed model first.")
    width, height = source.width or 0, source.height or 0
    if not 32 <= width <= 768 or not 32 <= height <= 1152:
        raise invalid("Choose an image made by the current pose renderer.")
    try:
        validate_region(box, width, height)
    except ValueError:
        raise DomainError(
            422,
            "Invalid repair area",
            "Select an area inside the image, at least 16 pixels per side "
            "and at most a quarter of it.",
            "invalid-repair-region",
        ) from None
    source_box = source.provenance.get("cutout", {}).get("box") if original.transparent else None
    if original.transparent:
        if (
            not isinstance(source_box, list)
            or len(source_box) != 4
            or any(type(v) is not int for v in source_box)
            or not 0 <= source_box[0] < source_box[2] <= 768
            or not 0 <= source_box[1] < source_box[3] <= 1152
            or [source_box[2] - source_box[0], source_box[3] - source_box[1]] != [width, height]
        ):
            raise invalid("The source crop is unavailable.")
    elif (width, height) != (768, 1152):
        raise invalid("The source canvas is unavailable.")
    chosen: dict[str, Any] = {}
    for role, binding in (
        ("style_adapter", await session.get(NarrativePoseStyle, plan.job_id)),
        ("character_adapter", await session.get(NarrativePoseCharacterAdapter, plan.job_id)),
    ):
        if binding is None:
            continue
        adapter_id = (
            binding.style_id if isinstance(binding, NarrativePoseStyle) else binding.adapter_id
        )
        adapter = await session.get(NarrativeStyleJob, adapter_id)
        if (
            not adapter
            or adapter.project_id != project_id
            or adapter.tenant_id != tenant_id
            or adapter.weights_sha256 != binding.weights_sha256
        ):
            raise invalid("A source training version is unavailable or changed.")
        chosen[role] = {"id": adapter_id, "strength": binding.strength}
    repair = {"request_hash": request_hash, "instruction": instruction}
    job = await queue_pose_job(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        look_id=plan.look_id,
        pose=plan.pose,
        count=count,
        transparent=original.transparent,
        idempotency_key=idempotency_key,
        author_user_id=author_user_id,
        actor=actor,
        available=settings.narrative_pose_generation_enabled,
        max_active_jobs=settings.narrative_image_max_active_jobs_per_workspace,
        policy=content_policy(settings.narrative_image_content_policy),
        model_manifest_sha256=settings.narrative_pose_model_manifest_sha256,
        cutout_manifest_sha256=settings.narrative_image_cutout_manifest_sha256,
        max_references=settings.narrative_pose_max_references,
        max_adapters=settings.narrative_pose_max_adapters,
        styles_enabled=settings.narrative_style_training_enabled,
        repair=repair,
        **chosen,
    )
    session.add(
        NarrativePoseRepair(
            job_id=job.id,
            tenant_id=tenant_id,
            project_id=project_id,
            source_asset_id=source.id,
            source_job_id=plan.job_id,
            source_sha256=source.sha256,
            size_bytes=source.size_bytes,
            width=width,
            height=height,
            source_box=source_box,
            box=box,
            instruction=instruction,
        )
    )
    await session.flush()
    return job
