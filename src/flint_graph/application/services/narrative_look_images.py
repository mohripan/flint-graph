"""Admission adapters: pin a reviewed look without changing owned image workers."""

from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.audit import AuditActor
from flint_graph.application.services.narrative_images import (
    MAX_BASE,
    MIN_BASE,
    MIN_FACE,
    _queue_job,
)
from flint_graph.application.services.narrative_looks import (
    bind_job,
    get_look,
    invalid,
    reference,
    replay_job,
)
from flint_graph.infrastructure.db.models import NarrativeAsset, NarrativeImageJob
from flint_graph.infrastructure.db.narrative_look_models import NarrativeCharacterLook
from flint_graph.narrative.imagegen import ContentPolicy, expression_request, scene_art_request
from flint_graph.narrative.values import canonical_json
from flint_graph.prompts.source import snapshot_async


def caption(look: NarrativeCharacterLook) -> str:
    return ", ".join([*look.identity_tags, *look.clothing_tags])


def source_size(asset: NarrativeAsset) -> tuple[int, int]:
    width, height = asset.width or 0, asset.height or 0
    if not (MIN_BASE <= width <= MAX_BASE and MIN_BASE <= height <= MAX_BASE):
        raise invalid(f"Use a reference between {MIN_BASE} and {MAX_BASE} pixels per edge.")
    return width, height


@snapshot_async
async def queue_look_expression(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    look_id: UUID,
    face_box: list[int],
    expressions: list[str],
    idempotency_key: UUID,
    author_user_id: UUID,
    actor: AuditActor,
    available: bool,
    max_active_jobs: int,
    policy: ContentPolicy,
) -> NarrativeImageJob:
    request_hash = sha256(
        canonical_json(
            {
                "purpose": "expression",
                "character_id": character_id,
                "look_id": str(look_id),
                "face_box": face_box,
                "expressions": expressions,
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
    width, height = source_size(source)
    left, top, right, bottom = face_box
    box_width, box_height = right - left, bottom - top
    if not (
        0 <= left < right <= width
        and 0 <= top < bottom <= height
        and min(box_width, box_height) >= MIN_FACE
        and 0.5 <= box_width / box_height <= 2
    ):
        raise invalid("Place the face box over the face, inside the reference image.")
    # Share the ledger's admission/outbox/fences without rereading mutable profile
    # wording. The central builder maps policy/description failures to HTTP 422.
    job = await _queue_job(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        author_user_id=author_user_id,
        purpose="character_expression",
        appearance=caption(look),
        character_type=look.character_type,
        framing="face",
        transparent=False,
        hires=False,
        build=lambda: expression_request(
            caption(look), look.character_type, expressions, policy=policy
        ),
        count=len(expressions),
        base=(source, (left, top, right, bottom)),
        expressions=expressions,
        idempotency_key=idempotency_key,
        actor=actor,
        available=available,
        max_active_jobs=max_active_jobs,
        policy=policy,
    )
    await bind_job(session, job, [look], request_hash)
    job.prompt_identity = {
        **(job.prompt_identity or {}),
        "look_sha256": look.sha256,
    }
    await session.flush()
    return job


@snapshot_async
async def queue_look_scene(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    characters: list[dict[str, Any]],
    scene: str,
    count: int,
    idempotency_key: UUID,
    author_user_id: UUID,
    actor: AuditActor,
    available: bool,
    max_active_jobs: int,
    policy: ContentPolicy,
) -> NarrativeImageJob:
    request_hash = sha256(
        canonical_json(
            {
                "purpose": "scene",
                "characters": [
                    {"character_id": item["character_id"], "look_id": str(item["look_id"])}
                    for item in characters
                ],
                "scene": scene,
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
    if len({pick["character_id"] for pick in characters}) != len(characters):
        raise invalid("Choose different characters for this CG.")
    looks, references, wording = [], [], []
    for pick in characters:
        look_id = pick.get("look_id")
        if look_id is None:
            raise invalid("Choose a reviewed look for each character in this CG.")
        look = await get_look(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=pick["character_id"],
            look_id=look_id,
        )
        looks.append(look)
        source = await reference(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=look.character_id,
            asset_id=look.asset_id,
        )
        source_size(source)
        references.append((look.character_id, source))
        wording.append((caption(look), look.character_type))
    job = await _queue_job(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        purpose="scene_art",
        character_id=looks[0].character_id,
        appearance=scene,
        character_type=looks[0].character_type,
        framing="scene",
        transparent=False,
        hires=False,
        build=lambda: scene_art_request(scene, wording, policy=policy),
        references=references,
        count=count,
        idempotency_key=idempotency_key,
        author_user_id=author_user_id,
        actor=actor,
        available=available,
        max_active_jobs=max_active_jobs,
        policy=policy,
    )
    await bind_job(session, job, looks, request_hash)
    job.prompt_identity = {
        **(job.prompt_identity or {}),
        "look_sha256": [look.sha256 for look in looks],
    }
    await session.flush()
    return job
