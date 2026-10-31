"""Image suggestions resolve to one durable job per accepted proposal operation."""

import json
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.audit import AuditActor
from flint_graph.application.services.narrative_assistant import get_proposal
from flint_graph.application.services.narrative_characters import save_profile
from flint_graph.application.services.narrative_images import (
    create_background_job,
    create_portrait_job,
)
from flint_graph.application.services.narrative_projects import get_project, get_revision
from flint_graph.config import Settings
from flint_graph.domain.errors import ConflictError, NotFoundError
from flint_graph.infrastructure.db.models import (
    NarrativeAssistantProposal,
    NarrativeAssistantTurn,
    NarrativeCharacterProfile,
    NarrativeImageJob,
    Tenant,
)
from flint_graph.narrative.assistant.operations import GenerateBackgrounds, GenerateCharacterImages
from flint_graph.narrative.assistant.prompts import PINNED_PROMPTS
from flint_graph.narrative.imagegen import content_policy

ImageAction = GenerateBackgrounds | GenerateCharacterImages


def action_key(proposal_id: UUID, index: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"flint-graph/assistant/{proposal_id}/image-actions/{index}")


def _actions(proposal: NarrativeAssistantProposal) -> list[tuple[int, ImageAction, dict[str, Any]]]:
    actions = []
    for index, raw in enumerate(proposal.operations):
        model: type[GenerateBackgrounds] | type[GenerateCharacterImages] | None = None
        if raw.get("op") == "generate_backgrounds":
            model = GenerateBackgrounds
        elif raw.get("op") == "generate_character_images":
            model = GenerateCharacterImages
        if model is not None:
            try:
                actions.append((index, model.model_validate(raw), raw))
            except ValidationError:
                continue  # Invalid/rejected proposals can still be inspected safely.
    return actions


async def _job(
    session: AsyncSession,
    proposal: NarrativeAssistantProposal,
    index: int,
    action: ImageAction,
    raw: dict[str, Any],
) -> NarrativeImageJob | None:
    scoped = select(NarrativeImageJob).where(
        NarrativeImageJob.tenant_id == proposal.tenant_id,
        NarrativeImageJob.project_id == proposal.project_id,
    )
    exact = await session.scalar(
        scoped.where(NarrativeImageJob.idempotency_key == action_key(proposal.id, index))
    )
    if exact is not None or proposal.status != "accepted" or proposal.decided_at is None:
        return exact
    prompt = await session.scalar(
        select(NarrativeAssistantTurn.prompt_sha256).where(
            NarrativeAssistantTurn.id == proposal.turn_id,
            NarrativeAssistantTurn.tenant_id == proposal.tenant_id,
        )
    )
    if prompt not in {
        PINNED_PROMPTS["narrative-assistant/v1"],
        PINNED_PROMPTS["narrative-assistant/v2"],
    }:
        return None
    # Pre-fix Studio jobs carried no proposal ID. Read-only recovery of matching
    # requests by this proposal's accepting creator; never rewrite their keys/data.
    legacy = scoped.where(
        NarrativeImageJob.created_at >= proposal.decided_at.replace(microsecond=0),
        NarrativeImageJob.requested_by_user_id == proposal.decided_by_user_id,
        NarrativeImageJob.count == 4,
    )
    if isinstance(action, GenerateBackgrounds):
        legacy = legacy.where(
            NarrativeImageJob.purpose == "background",
            NarrativeImageJob.appearance == action.description,
        )
    else:
        legacy = legacy.where(
            NarrativeImageJob.purpose == "character_portrait",
            NarrativeImageJob.character_id == action.character,
            NarrativeImageJob.appearance == action.appearance,
            NarrativeImageJob.character_type == action.character_type,
            NarrativeImageJob.framing == action.framing,
            NarrativeImageJob.transparent == action.transparent,
        )
        if "hires" in raw:
            legacy = legacy.where(
                NarrativeImageJob.hires_scale.is_not(None)
                if action.hires
                else NarrativeImageJob.hires_scale.is_(None)
            )
    candidates = await session.scalars(
        legacy.order_by(NarrativeImageJob.created_at.desc(), NarrativeImageJob.id.desc())
    )
    return next((job for job in candidates if job.idempotency_key.version == 4), None)


async def action_jobs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    proposal_id: UUID,
) -> list[tuple[int, NarrativeImageJob | None]]:
    proposal = await get_proposal(
        session, tenant_id=tenant_id, project_id=project_id, proposal_id=proposal_id
    )
    return [
        (index, await _job(session, proposal, index, action, raw))
        for index, action, raw in _actions(proposal)
    ]


async def start_action(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    proposal_id: UUID,
    index: int,
    author_user_id: UUID,
    actor: AuditActor,
    settings: Settings,
) -> NarrativeImageJob:
    # Same lock order as image admission; concurrent clicks cannot create two jobs
    # or repeatedly overwrite a character profile before the idempotency check.
    await session.scalar(
        select(Tenant).where(Tenant.id == tenant_id).with_for_update(key_share=True)
    )
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    proposal = await get_proposal(
        session, tenant_id=tenant_id, project_id=project_id, proposal_id=proposal_id
    )
    if proposal.status != "accepted":
        raise ConflictError("Accept the proposal before generating its images.")
    selected = next((item for item in _actions(proposal) if item[0] == index), None)
    if selected is None:
        raise NotFoundError("Image suggestion was not found.")
    _, action, raw = selected
    existing = await _job(session, proposal, index, action, raw)
    if existing is not None:
        return existing
    shared: dict[str, Any] = dict(
        tenant_id=tenant_id,
        project_id=project_id,
        author_user_id=author_user_id,
        count=4,
        idempotency_key=action_key(proposal.id, index),
        actor=actor,
        available=settings.narrative_image_generation_enabled,
        max_active_jobs=settings.narrative_image_max_active_jobs_per_workspace,
        policy=content_policy(settings.narrative_image_content_policy),
    )
    if isinstance(action, GenerateBackgrounds):
        return await create_background_job(session, description=action.description, **shared)
    if project.head_revision_id is None:
        raise ConflictError("The story has no saved revision.")
    revision = await get_revision(
        session, tenant_id=tenant_id, project_id=project_id, revision_id=project.head_revision_id
    )
    if action.character not in json.loads(revision.story_json)["characters"]:
        raise ConflictError("This character is no longer in the story.")
    profile = await session.scalar(
        select(NarrativeCharacterProfile).where(
            NarrativeCharacterProfile.project_id == project_id,
            NarrativeCharacterProfile.character_id == action.character,
        )
    )
    await save_profile(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=action.character,
        base_version=profile.version if profile else 0,
        appearance=action.appearance,
        character_type=action.character_type,
        framing=action.framing,
        author_user_id=author_user_id,
    )
    return await create_portrait_job(
        session,
        character_id=action.character,
        appearance=action.appearance,
        character_type=action.character_type,
        framing=action.framing,
        transparent=action.transparent,
        hires=action.hires,
        **shared,
    )
