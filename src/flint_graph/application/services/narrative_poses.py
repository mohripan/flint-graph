"""Pose admission: shared quotas/fences, an immutable look and a pinned model."""

from dataclasses import replace
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
    NarrativePoseGuide,
    NarrativePoseJob,
    NarrativePoseReference,
)
from flint_graph.narrative.imagegen import ContentPolicy, ImageRequest, clean_appearance
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
    style_adapter: dict[str, Any] | None = None,
    styles_enabled: bool = False,
    character_adapter: dict[str, Any] | None = None,
    max_adapters: int = 1,
    repair: dict[str, Any] | None = None,
    pose_guide: str | None = None,
    guides_enabled: bool = False,
    control_manifest_sha256: str | None = None,
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
                **({"pose_guide": pose_guide} if pose_guide else {}),
                **(
                    {
                        "style_adapter": {
                            "id": str(style_adapter["id"]),
                            "strength": style_adapter["strength"],
                        }
                    }
                    if style_adapter
                    else {}
                ),
                **(
                    {
                        "character_adapter": {
                            "id": str(character_adapter["id"]),
                            "strength": character_adapter["strength"],
                        }
                    }
                    if character_adapter
                    else {}
                ),
                "character_id": character_id,
                "look_id": str(look_id),
                "pose": pose,
                "count": count,
                "transparent": transparent,
                **({"additional_references": extra_identity} if extras else {}),
            }
        )
    ).hexdigest()
    if repair:
        request_hash = repair["request_hash"]
    prior = await replay_job(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if prior:
        return prior
    if pose_guide and (not guides_enabled or not control_manifest_sha256 or max_references < 2):
        raise DomainError(
            503,
            "Body guides unavailable",
            "Pose body guides are not enabled on this server.",
            "pose-guide-unavailable",
        )
    if pose_guide and (extras or repair):
        raise DomainError(
            422,
            "Invalid references",
            "Use a body guide or an additional character view, one at a time.",
            "invalid-pose-guide",
        )
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
    if character_adapter and max_adapters < 2:
        raise DomainError(
            503,
            "Character adapters unavailable",
            "Separate character and style adapters are not enabled on this server.",
            "pose-adapters-unavailable",
        )
    from flint_graph.application.services.narrative_pose_adapters import resolve_adapters
    from flint_graph.infrastructure.db.narrative_character_adapter_models import (
        NarrativePoseCharacterAdapter,
    )
    from flint_graph.infrastructure.db.narrative_style_models import NarrativePoseStyle

    character, style = await resolve_adapters(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        look_id=look_id,
        model_hash=model_manifest_sha256,
        enabled=styles_enabled,
        style_input=style_adapter,
        character_input=character_adapter,
    )

    def build() -> ImageRequest:
        request = pose_request(
            caption(look),
            repair["instruction"] if repair else pose,
            policy=policy,
            additional_view="detail" if repair else extras[0]["view"] if extras else None,
            body_guide=bool(pose_guide),
        )
        triggers = [item.trigger for item in (character, style) if item]
        return (
            replace(request, prompt=", ".join([*triggers, request.prompt])) if triggers else request
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
        build=build,
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
    if style and style_adapter:
        session.add(
            NarrativePoseStyle(
                job_id=job.id,
                tenant_id=tenant_id,
                project_id=project_id,
                style_id=style.id,
                strength=style_adapter["strength"],
                weights_sha256=style.weights_sha256,
            )
        )
    if character and character_adapter:
        session.add(
            NarrativePoseCharacterAdapter(
                job_id=job.id,
                tenant_id=tenant_id,
                project_id=project_id,
                adapter_id=character.id,
                strength=character_adapter["strength"],
                weights_sha256=character.weights_sha256,
            )
        )
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
    if pose_guide:
        from flint_graph.narrative.pose_guides import body_guide, guide_sha256

        guide = body_guide(pose_guide)
        assert control_manifest_sha256
        session.add(
            NarrativePoseGuide(
                job_id=job.id,
                tenant_id=tenant_id,
                project_id=project_id,
                guide=guide,
                guide_sha256=guide_sha256(guide),
                control_manifest_sha256=control_manifest_sha256,
            )
        )
    await session.flush()
    return job
