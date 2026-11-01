"""Reviewed immutable looks, optimistic selection and private job provenance."""

from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.audit import AuditActor, record_audit_event
from flint_graph.application.services.narrative_characters import get_asset
from flint_graph.application.services.narrative_projects import get_project
from flint_graph.application.services.prompt_bundles import pin_bundle
from flint_graph.domain.enums import AuditAction
from flint_graph.domain.errors import ConflictError, DomainError, NotFoundError
from flint_graph.infrastructure.db.models import (
    NarrativeAsset,
    NarrativeCharacterProfile,
    NarrativeImageJob,
    Tenant,
)
from flint_graph.infrastructure.db.narrative_look_models import (
    NarrativeCharacterLook,
    NarrativeLookJob,
    NarrativeLookObservation,
    NarrativeLookSelection,
)
from flint_graph.narrative.imagegen import ContentPolicy, clean_appearance
from flint_graph.narrative.values import canonical_json


def invalid(detail: str) -> DomainError:
    return DomainError(422, "Invalid look", detail, "invalid-character-look")


def tags(values: list[str]) -> list[str]:
    cleaned = list(
        dict.fromkeys(clean_appearance(value.replace("_", " ")).lower() for value in values)
    )
    if len(cleaned) > 24 or any(not value or len(value) > 60 for value in cleaned):
        raise invalid("Use up to 24 short, nonempty tags per field.")
    if any(
        value
        in {"general", "sensitive", "questionable", "explicit", "safe", "nsfw", "1girl", "1boy"}
        or "(" in value
        or ")" in value
        for value in cleaned
    ):
        raise invalid(
            "Use visible appearance and clothing tags, without ratings or character-name tags."
        )
    return cleaned


async def selection(
    session: AsyncSession, project_id: UUID, character_id: str
) -> NarrativeLookSelection | None:
    return await session.get(
        NarrativeLookSelection, (project_id, character_id), populate_existing=True
    )


async def get_look(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, character_id: str, look_id: UUID
) -> NarrativeCharacterLook:
    row = await session.scalar(
        select(NarrativeCharacterLook).where(
            NarrativeCharacterLook.id == look_id,
            NarrativeCharacterLook.tenant_id == tenant_id,
            NarrativeCharacterLook.project_id == project_id,
            NarrativeCharacterLook.character_id == character_id,
        )
    )
    if row is None:
        raise NotFoundError("Reviewed look was not found.")
    return row


def look_snapshot(look: NarrativeCharacterLook) -> dict[str, Any]:
    return {
        "id": str(look.id),
        "sha256": look.sha256,
        "name": look.name,
        "character_id": look.character_id,
        "asset_id": str(look.asset_id),
        "source_sha256": look.source_sha256,
        "identity_tags": look.identity_tags,
        "clothing_tags": look.clothing_tags,
        "character_type": look.character_type,
        "prompt_bundle_sha256": look.prompt_bundle_sha256,
        "policy_sha256": look.policy_sha256,
    }


async def replay_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    idempotency_key: UUID,
    request_hash: str,
) -> NarrativeImageJob | None:
    # Match the existing admission lock order. This closes the gap between the
    # look-aware retry check and the original job ledger's idempotency check.
    tenant = await session.scalar(
        select(Tenant).where(Tenant.id == tenant_id).with_for_update(key_share=True)
    )
    if tenant is None:
        raise NotFoundError("Workspace was not found.")
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    job = await session.scalar(
        select(NarrativeImageJob).where(
            NarrativeImageJob.project_id == project_id,
            NarrativeImageJob.tenant_id == tenant_id,
            NarrativeImageJob.idempotency_key == idempotency_key,
        )
    )
    if job:
        bound = list(
            await session.scalars(select(NarrativeLookJob).where(NarrativeLookJob.job_id == job.id))
        )
        if (
            job.request_hash != request_hash
            or not bound
            or any(row.request_hash != request_hash for row in bound)
        ):
            raise ConflictError("This request key belongs to a different image request or look.")
    return job


async def bind_job(
    session: AsyncSession,
    job: NarrativeImageJob,
    looks: list[NarrativeCharacterLook],
    request_hash: str,
) -> None:
    # Admission in the existing generator serializes by workspace/project. Check
    # again after admission so concurrent identical captions cannot rebind a job.
    bound = list(
        await session.scalars(select(NarrativeLookJob).where(NarrativeLookJob.job_id == job.id))
    )
    if bound:
        if any(row.request_hash != request_hash for row in bound):
            raise ConflictError("This request key belongs to a different reviewed look.")
        return
    job.request_hash = request_hash
    for look in looks:
        asset = await reference(
            session,
            tenant_id=look.tenant_id,
            project_id=look.project_id,
            character_id=look.character_id,
            asset_id=look.asset_id,
        )
        if asset.sha256 != look.source_sha256:
            raise ConflictError("The reviewed reference image changed.")
        session.add(
            NarrativeLookJob(
                job_id=job.id,
                character_id=look.character_id,
                tenant_id=job.tenant_id,
                project_id=job.project_id,
                look_id=look.id,
                request_hash=request_hash,
                snapshot=look_snapshot(look),
            )
        )
    await session.flush()


async def queue_look_portrait(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    look_id: UUID,
    author_user_id: UUID,
    idempotency_key: UUID,
    actor: AuditActor,
    available: bool,
    max_active_jobs: int,
    policy: ContentPolicy,
    **options: Any,
) -> NarrativeImageJob:
    from flint_graph.application.services.narrative_images import create_portrait_job

    request_hash = sha256(
        canonical_json(
            {
                "purpose": "portrait",
                "character_id": character_id,
                "look_id": str(look_id),
                **options,
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
    job = await create_portrait_job(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        author_user_id=author_user_id,
        appearance=", ".join([*look.identity_tags, *look.clothing_tags]),
        character_type=look.character_type,
        idempotency_key=idempotency_key,
        actor=actor,
        available=available,
        max_active_jobs=max_active_jobs,
        policy=policy,
        **options,
    )
    await bind_job(session, job, [look], request_hash)
    return job


async def reference(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, character_id: str, asset_id: UUID
) -> NarrativeAsset:
    asset = await get_asset(session, tenant_id=tenant_id, project_id=project_id, asset_id=asset_id)
    if (
        asset.status != "approved"
        or asset.kind not in ("sprite", "character_portrait", "image")
        or asset.media_type != "image/png"
    ):
        raise invalid("Choose an approved portrait, sprite or single-character image.")
    if asset.character_id not in (None, character_id) or asset.provenance.get("ip_adapter"):
        raise invalid("Choose an image of this character alone, without a CG scene.")
    return asset


async def select_look(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    look_id: UUID | None,
    base_version: int,
    actor: AuditActor,
) -> NarrativeLookSelection:
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    if project.archived_at is not None:
        raise ConflictError("Restore this project before editing looks.")
    current = await selection(session, project_id, character_id)
    if (current.version if current else 0) != base_version:
        raise DomainError(
            409,
            "Look conflict",
            "Someone else changed the selected look. Reload before choosing again.",
            "stale-character-look",
        )
    if look_id:
        await get_look(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            look_id=look_id,
        )
    if current is None:
        current = NarrativeLookSelection(
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            version=1,
            look_id=look_id,
        )
        session.add(current)
    else:
        current.version += 1
        current.look_id = look_id
    await session.flush()
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action=AuditAction.NARRATIVE_CHARACTER_LOOK_SELECTED,
        resource_type="narrative_character_look",
        resource_id=look_id,
        metadata={
            "project_id": str(project_id),
            "character_id": character_id,
            "selection_version": current.version,
        },
    )
    return current


async def create_look(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    character_id: str,
    name: str,
    asset_id: UUID,
    identity_tags: list[str],
    clothing_tags: list[str],
    parent_look_id: UUID | None,
    base_version: int,
    idempotency_key: UUID,
    author_user_id: UUID,
    actor: AuditActor,
    policy: ContentPolicy,
    observation_id: UUID | None = None,
) -> NarrativeCharacterLook:
    try:
        name = clean_appearance(name)
        identity_tags, clothing_tags = tags(identity_tags), tags(clothing_tags)
        caption = clean_appearance(", ".join([*identity_tags, *clothing_tags]))
    except ValueError as error:
        raise invalid(str(error)) from None
    if not 1 <= len(name) <= 80 or not caption:
        raise invalid("Name the look and describe its visible hair, eyes or clothes.")
    await get_project(session, tenant_id=tenant_id, project_id=project_id, for_update=True)
    request = {
        "observation_id": str(observation_id) if observation_id else None,
        "character_id": character_id,
        "name": name,
        "asset_id": str(asset_id),
        "identity_tags": identity_tags,
        "clothing_tags": clothing_tags,
        "parent_look_id": str(parent_look_id) if parent_look_id else None,
        "base_version": base_version,
    }
    request_hash = sha256(canonical_json(request)).hexdigest()
    existing = await session.scalar(
        select(NarrativeCharacterLook).where(
            NarrativeCharacterLook.project_id == project_id,
            NarrativeCharacterLook.creation_key == idempotency_key,
        )
    )
    if existing:
        if existing.request_hash != request_hash:
            raise ConflictError("This request key was already used for a different look.")
        return existing
    try:
        policy.check(caption)
    except ValueError as error:
        raise invalid(str(error)) from None
    if (
        await session.scalar(
            select(func.count())
            .select_from(NarrativeCharacterLook)
            .where(
                NarrativeCharacterLook.project_id == project_id,
                NarrativeCharacterLook.character_id == character_id,
            )
        )
        or 0
    ) >= 200:
        raise invalid("This character already has 200 looks.")
    asset = await reference(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        asset_id=asset_id,
    )
    if parent_look_id:
        await get_look(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            look_id=parent_look_id,
        )
    profile = await session.get(NarrativeCharacterProfile, (project_id, character_id))
    observation = None
    if observation_id:
        recorded = await session.get(NarrativeLookObservation, observation_id)
        if (
            not recorded
            or recorded.tenant_id != tenant_id
            or recorded.project_id != project_id
            or recorded.asset_id != asset.id
            or recorded.source_sha256 != asset.sha256
        ):
            raise invalid("These suggestions belong to a different reference image.")
        observation = recorded.observation
    identity = request | {
        "schema": 1,
        "source_sha256": asset.sha256,
        "character_type": profile.character_type if profile else "other",
        "reviewed_by_user_id": str(author_user_id),
        "prompt_bundle_sha256": await pin_bundle(session),
        "policy_sha256": sha256(
            canonical_json({"negative": policy.negative, "blocked": list(policy.blocked)})
        ).hexdigest(),
    }
    row = NarrativeCharacterLook(
        prompt_bundle_sha256=identity["prompt_bundle_sha256"],
        policy_sha256=identity["policy_sha256"],
        tagger_observation=observation,
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        name=name,
        asset_id=asset_id,
        source_sha256=asset.sha256,
        identity_tags=identity_tags,
        clothing_tags=clothing_tags,
        parent_look_id=parent_look_id,
        character_type=identity["character_type"],
        reviewed_by_user_id=author_user_id,
        creation_key=idempotency_key,
        request_hash=request_hash,
        sha256=sha256(canonical_json(identity)).hexdigest(),
    )
    session.add(row)
    await session.flush()
    await select_look(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        look_id=row.id,
        base_version=base_version,
        actor=actor,
    )
    await session.refresh(row)
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action=AuditAction.NARRATIVE_CHARACTER_LOOK_REVIEWED,
        resource_type="narrative_character_look",
        resource_id=row.id,
        metadata={
            "project_id": str(project_id),
            "character_id": character_id,
            "look_sha256": row.sha256,
            "asset_id": str(asset_id),
        },
    )
    return row
