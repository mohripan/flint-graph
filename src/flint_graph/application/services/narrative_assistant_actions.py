"""The assistant's generation actions become real jobs (ADR 0061).

Each action of a proposal resolves to one durable job through a key derived from the
proposal and the operation's position, so clicks, the dispatcher, retries and reloads
all converge on the same job. Starting an action only admits a normal job: the same
policy, credits, audit and outbox as a job started from Characters or Assets. Results
stay candidates until the creator approves them.

``dispatch_actions`` and ``reconcile_actions`` run in the assistant worker. Automatic
actions need no open page, a full queue waits rather than fails, and job endings reach
the thread log without the image and voice workers knowing about conversations.
"""

import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flint_graph.application.services.audit import AuditActor
from flint_graph.application.services.narrative_assistant import (
    create_thread,
    get_proposal,
    post_turn,
)
from flint_graph.application.services.narrative_assistant_action_state import (
    BLOCKED,
    FINISHED,
    OFFERED,
    PENDING,
    SKIPPED,
    STARTED,
    WAITING,
)
from flint_graph.application.services.narrative_assistant_log import append_thread_event
from flint_graph.application.services.narrative_characters import save_profile
from flint_graph.application.services.narrative_images import (
    BASE_KINDS,
    create_background_job,
    create_expression_job,
    create_portrait_job,
    create_scene_art_job,
)
from flint_graph.application.services.narrative_projects import get_project, get_revision
from flint_graph.application.services.narrative_voices import (
    create_voice_job,
    set_character_voice,
)
from flint_graph.config import Settings
from flint_graph.domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    TooManyRequestsError,
)
from flint_graph.infrastructure.db.models import (
    NarrativeAsset,
    NarrativeAssistantProposal,
    NarrativeAssistantTurn,
    NarrativeCharacterProfile,
    NarrativeImageJob,
    NarrativeProject,
    NarrativeVoiceJob,
    Tenant,
)
from flint_graph.infrastructure.db.narrative_assistant_models import (
    NarrativeAssistantAction,
    NarrativeAssistantThread,
)
from flint_graph.infrastructure.db.narrative_voice_models import NarrativeLineDelivery
from flint_graph.infrastructure.narrative_artifact_store import (
    ArtifactStoreError,
    asset_object_key,
)
from flint_graph.infrastructure.narrative_imagegen import IMAGE_LIMIT, THUMBNAIL_LIMIT
from flint_graph.narrative.assistant.log import ACTION_BLOCKED, ACTION_STARTED, JOB_FINISHED
from flint_graph.narrative.assistant.operations import (
    GenerateBackgrounds,
    GenerateCg,
    GenerateCharacterImages,
    GenerateExpressions,
    GenerateVoice,
    Proposal,
    StartChildSession,
    action_label,
    action_needs_accept,
)
from flint_graph.narrative.assistant.prompts import PINNED_PROMPTS
from flint_graph.narrative.face_box import Box, face_box_from_png
from flint_graph.narrative.imagegen import content_policy
from flint_graph.narrative.voice_models import DEFAULT_MODEL, MODELS, line_delivery
from flint_graph.narrative.voices import VOICE_IDS

logger = logging.getLogger(__name__)

ActionOp = (
    GenerateBackgrounds
    | GenerateCharacterImages
    | GenerateExpressions
    | GenerateCg
    | GenerateVoice
    | StartChildSession
)
_MODELS: dict[str, type[ActionOp]] = {
    "generate_backgrounds": GenerateBackgrounds,
    "generate_character_images": GenerateCharacterImages,
    "generate_expressions": GenerateExpressions,
    "generate_cg": GenerateCg,
    "generate_voice": GenerateVoice,
    "start_child_session": StartChildSession,
}
_CANDIDATES = 4
_FINISHED_JOB = ("completed", "failed", "cancelled")
# Expressions repaint a character's usual face first.
_NEUTRAL_FIRST = ("neutral", "default", "normal", "idle", "base")
_DEFAULT_VOICES = {
    "girl": "af_heart",
    "woman": "af_heart",
    "boy": "am_michael",
    "man": "am_michael",
}


class AssetBytes(Protocol):
    async def get_verified(
        self, key: str, *, expected_size: int, expected_sha256: str, max_bytes: int
    ) -> bytes: ...


def generation_capabilities(settings: Settings) -> tuple[str, ...]:
    """What the model may offer on this server, by the names its prompt expects."""
    found: list[str] = []
    if settings.narrative_image_generation_enabled:
        found += ["pictures", "expressions"]
        if settings.narrative_image_ip_adapter_model_dir:
            found.append("cgs")
    if settings.narrative_voice_generation_enabled:
        found.append("voices")
    return tuple(found)


def action_key(proposal_id: UUID, index: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"flint-graph/assistant/{proposal_id}/image-actions/{index}")


def parse_actions(
    proposal: NarrativeAssistantProposal,
) -> list[tuple[int, ActionOp, dict[str, Any]]]:
    found = []
    for index, raw in enumerate(proposal.operations):
        model = _MODELS.get(str(raw.get("op")))
        if model is not None:
            try:
                found.append((index, model.model_validate(raw), raw))
            except ValidationError:
                continue  # Invalid or rejected proposals can still be inspected safely.
    return found


async def _legacy_image_job(
    session: AsyncSession,
    proposal: NarrativeAssistantProposal,
    index: int,
    action: ActionOp,
    raw: dict[str, Any],
) -> NarrativeImageJob | None:
    """A job from before actions had rows; only pictures can have one."""
    if not isinstance(action, GenerateBackgrounds | GenerateCharacterImages):
        return None
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
        NarrativeImageJob.count == _CANDIDATES,
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


@dataclass(frozen=True)
class ActionView:
    index: int
    op: str
    label: str
    status: str
    needs_accept: bool
    error_code: str | None
    detail: str | None
    image_job: NarrativeImageJob | None
    voice_job: NarrativeVoiceJob | None
    child_thread: NarrativeAssistantThread | None = None


async def _head_story(
    session: AsyncSession, project: NarrativeProject, *, tenant_id: UUID
) -> dict[str, Any]:
    if project.head_revision_id is None:
        raise ConflictError("The story has no saved revision.")
    revision = await get_revision(
        session, tenant_id=tenant_id, project_id=project.id, revision_id=project.head_revision_id
    )
    story: dict[str, Any] = json.loads(revision.story_json)
    return story


def _operations(proposal: NarrativeAssistantProposal) -> Sequence[Any]:
    return Proposal.model_validate(
        {"summary": proposal.summary, "operations": proposal.operations}
    ).operations


async def _rows(session: AsyncSession, proposal_id: UUID) -> dict[int, NarrativeAssistantAction]:
    rows = await session.scalars(
        select(NarrativeAssistantAction).where(NarrativeAssistantAction.proposal_id == proposal_id)
    )
    return {row.op_index: row for row in rows}


async def list_actions(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, proposal_id: UUID
) -> list[ActionView]:
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, include_archived=True
    )
    proposal = await get_proposal(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        proposal_id=proposal_id,
        include_archived=True,
    )
    parsed = parse_actions(proposal)
    if not parsed:
        return []
    rows = await _rows(session, proposal.id)
    pending_review = proposal.status == "ready"
    story = await _head_story(session, project, tenant_id=tenant_id) if pending_review else None
    operations = _operations(proposal) if pending_review else ()
    views: list[ActionView] = []
    for index, action, raw in parsed:
        row = rows.get(index)
        image_job = voice_job = child_thread = None
        if row is not None and row.child_thread_id is not None:
            child_thread = await session.get(NarrativeAssistantThread, row.child_thread_id)
        elif row is not None and row.image_job_id is not None:
            image_job = await session.get(NarrativeImageJob, row.image_job_id)
        elif row is not None and row.voice_job_id is not None:
            voice_job = await session.get(NarrativeVoiceJob, row.voice_job_id)
        elif row is None or row.status == OFFERED:
            # Proposals from before actions had rows: Studio jobs may still belong to them.
            image_job = await _legacy_image_job(session, proposal, index, action, raw)
        status = (
            STARTED
            if image_job and (row is None or row.status == OFFERED)
            else (row.status if row is not None else OFFERED)
        )
        views.append(
            ActionView(
                index=index,
                op=action.op,
                label=action_label(action),
                status=status,
                needs_accept=bool(
                    story is not None and action_needs_accept(story, operations, action)
                ),
                error_code=row.error_code if row is not None else None,
                detail=row.detail if row is not None else None,
                image_job=image_job,
                voice_job=voice_job,
                child_thread=child_thread,
            )
        )
    return views


def _ordered_sprites(character: dict[str, Any]) -> list[str]:
    sprites = character.get("sprites") or {}
    neutral = [name for name in _NEUTRAL_FIRST if name in sprites]
    return [sprites[name] for name in neutral] + [
        key for name, key in sprites.items() if name not in neutral
    ]


async def _approved_picture(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    story: dict[str, Any],
    character_id: str,
) -> NarrativeAsset | None:
    """The picture that stands for a character: their stage sprite, portrait, or newest."""
    approved = select(NarrativeAsset).where(
        NarrativeAsset.tenant_id == tenant_id,
        NarrativeAsset.project_id == project_id,
        NarrativeAsset.status == "approved",
        NarrativeAsset.media_type == "image/png",
        NarrativeAsset.kind.in_(BASE_KINDS),
    )
    character = story["characters"].get(character_id) or {}
    assets = story.get("assets") or {}
    found: NarrativeAsset | None
    for key in _ordered_sprites(character):
        digest = (assets.get(key) or {}).get("sha256")
        found = await session.scalar(approved.where(NarrativeAsset.sha256 == digest).limit(1))
        if found is not None:
            return found
    portrait = await session.scalar(
        select(NarrativeCharacterProfile.portrait_asset_id).where(
            NarrativeCharacterProfile.tenant_id == tenant_id,
            NarrativeCharacterProfile.project_id == project_id,
            NarrativeCharacterProfile.character_id == character_id,
        )
    )
    if portrait is not None:
        found = await session.scalar(approved.where(NarrativeAsset.id == portrait))
        if found is not None:
            return found
    found = await session.scalar(
        approved.where(NarrativeAsset.character_id == character_id)
        .order_by(NarrativeAsset.approved_at.desc(), NarrativeAsset.id)
        .limit(1)
    )
    return found


def _needs_picture(story: dict[str, Any], character_id: str) -> DomainError:
    name = (story["characters"].get(character_id) or {}).get("name") or character_id
    return DomainError(
        409,
        "Needs an approved picture",
        f"Approve a picture of {name} first, then try this again.",
        "needs-approved-picture",
    )


async def _face_box(
    store: AssetBytes, asset: NarrativeAsset, *, tenant_id: UUID, project_id: UUID
) -> Box:
    thumbnail = asset.thumbnail_sha256 is not None and asset.thumbnail_size_bytes is not None
    size = asset.thumbnail_size_bytes if thumbnail else asset.size_bytes
    digest = asset.thumbnail_sha256 if thumbnail else asset.sha256
    assert size is not None and digest is not None
    try:
        data = await store.get_verified(
            asset_object_key(
                tenant_id=tenant_id,
                project_id=project_id,
                asset_id=asset.id,
                variant="thumbnail" if thumbnail else "image",
            ),
            expected_size=size,
            expected_sha256=digest,
            max_bytes=THUMBNAIL_LIMIT if thumbnail else IMAGE_LIMIT,
        )
        return await asyncio.to_thread(
            face_box_from_png, data, (asset.width or 0, asset.height or 0)
        )
    except (ArtifactStoreError, ValueError):
        raise DomainError(
            503, "Service unavailable", "This picture could not be read.", "asset-unavailable"
        ) from None


async def _voice_items(
    session: AsyncSession,
    *,
    project_id: UUID,
    story: dict[str, Any],
    action: GenerateVoice,
    model_id: str,
) -> list[dict[str, Any]]:
    saved = {
        row.node_id: {"emotion": row.emotion, "intensity": row.intensity, "tag": row.tag}
        for row in await session.scalars(
            select(NarrativeLineDelivery).where(
                NarrativeLineDelivery.project_id == project_id,
                NarrativeLineDelivery.node_id.in_(action.lines),
            )
        )
    }
    items = []
    for line in action.lines:
        node = story["nodes"].get(line)
        if (
            not isinstance(node, dict)
            or node.get("type") != "line"
            or node.get("speaker") != action.character
        ):
            raise ConflictError(f"Line {line} is no longer spoken by this character.")
        voice = node.get("voice") or {}
        mode = voice.get("mode", "full")
        text = voice.get("text", "") if mode == "vocalization" else " ".join(node["text"].split())
        spec = MODELS.get(model_id) or MODELS[DEFAULT_MODEL]
        delivery = line_delivery(saved.get(line), node.get("expression"), spec)
        items.append({"mode": mode, "text": text, "node_id": line, "delivery": delivery})
    return items


async def _ensure_voice(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    action: GenerateVoice,
    author_user_id: UUID,
    settings: Settings,
) -> str:
    """Give a silent character a voice; a voice the creator chose is never replaced."""
    profile = await session.scalar(
        select(NarrativeCharacterProfile).where(
            NarrativeCharacterProfile.tenant_id == tenant_id,
            NarrativeCharacterProfile.project_id == project_id,
            NarrativeCharacterProfile.character_id == action.character,
        )
    )
    if profile is not None and (profile.voice or profile.voice_reference_id):
        return profile.voice_model or DEFAULT_MODEL
    voice = action.voice if action.voice in VOICE_IDS else None
    if voice is None:
        kind = profile.character_type if profile is not None else "other"
        voice = _DEFAULT_VOICES.get(kind, "af_heart")
    await set_character_voice(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=action.character,
        base_version=profile.version if profile is not None else 0,
        voice=voice,
        author_user_id=author_user_id,
        model=DEFAULT_MODEL,
        installed=frozenset({DEFAULT_MODEL, *settings.narrative_voice_models}),
    )
    return DEFAULT_MODEL


async def _admit(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    proposal: NarrativeAssistantProposal,
    index: int,
    action: ActionOp,
    story: dict[str, Any],
    author_user_id: UUID,
    actor: AuditActor,
    settings: Settings,
    store: AssetBytes,
) -> NarrativeImageJob | NarrativeVoiceJob | NarrativeAssistantThread:
    key = action_key(proposal.id, index)
    if isinstance(action, StartChildSession):
        # Nothing is left behind if the slot is taken: the whole transaction rolls back.
        return await _start_child(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            proposal=proposal,
            action=action,
            key=key,
            author_user_id=author_user_id,
            actor=actor,
            settings=settings,
        )
    if isinstance(action, GenerateVoice):
        model_id = await _ensure_voice(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            action=action,
            author_user_id=author_user_id,
            settings=settings,
        )
        return await create_voice_job(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=action.character,
            author_user_id=author_user_id,
            items=await _voice_items(
                session,
                project_id=project_id,
                story=story,
                action=action,
                model_id=model_id,
            ),
            idempotency_key=key,
            actor=actor,
            available=settings.narrative_voice_generation_enabled,
            max_active_jobs=settings.narrative_voice_max_active_jobs_per_workspace,
            installed=frozenset({DEFAULT_MODEL, *settings.narrative_voice_models}),
            language=str(story.get("language", "en")),
        )
    shared: dict[str, Any] = {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "author_user_id": author_user_id,
        "idempotency_key": key,
        "actor": actor,
        "available": settings.narrative_image_generation_enabled,
        "max_active_jobs": settings.narrative_image_max_active_jobs_per_workspace,
        "policy": content_policy(settings.narrative_image_content_policy),
    }
    if isinstance(action, GenerateBackgrounds):
        return await create_background_job(
            session, description=action.description, count=_CANDIDATES, **shared
        )
    if isinstance(action, GenerateCg):
        references: list[tuple[str, UUID]] = []
        for character in action.characters:
            picture = await _approved_picture(
                session,
                tenant_id=tenant_id,
                project_id=project_id,
                story=story,
                character_id=character,
            )
            if picture is None:
                raise _needs_picture(story, character)
            references.append((character, picture.id))
        return await create_scene_art_job(
            session,
            scene=action.description,
            characters=references,
            # Two characters often lose a look (ADR 0041), so offer more to choose from.
            count=_CANDIDATES * len(references),
            **shared,
        )
    if isinstance(action, GenerateExpressions):
        base = await _approved_picture(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            story=story,
            character_id=action.character,
        )
        if base is None:
            raise _needs_picture(story, action.character)
        return await create_expression_job(
            session,
            character_id=action.character,
            base_asset_id=base.id,
            face_box=await _face_box(store, base, tenant_id=tenant_id, project_id=project_id),
            expressions=list(action.expressions),
            **shared,
        )
    if action.character not in story["characters"]:
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
        count=_CANDIDATES,
        **shared,
    )


async def _start_child(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    proposal: NarrativeAssistantProposal,
    action: StartChildSession,
    key: UUID,
    author_user_id: UUID,
    actor: AuditActor,
    settings: Settings,
) -> NarrativeAssistantThread:
    project = await get_project(session, tenant_id=tenant_id, project_id=project_id)
    if project.head_revision_id is None:
        raise ConflictError("The story has no saved revision.")
    asking = await session.get(NarrativeAssistantTurn, proposal.turn_id)
    child = await create_thread(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        author_user_id=author_user_id,
        title=action.title,
        idempotency_key=key,
        actor=actor,
        parent_thread_id=proposal.thread_id,
        task=action.task,
        origin="assistant",
    )
    await post_turn(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=child.id,
        author_user_id=author_user_id,
        request=action.task,
        base_revision_id=project.head_revision_id,
        focus_node=None,
        idempotency_key=key,
        actor=actor,
        available=settings.narrative_assistant_provider not in (None, "disabled"),
        max_active_turns=settings.narrative_assistant_max_active_turns_per_workspace,
        provider=settings.narrative_assistant_provider,
        auto_generate=bool(asking and asking.auto_generate),
    )
    return child


async def _action_row(
    session: AsyncSession,
    *,
    proposal: NarrativeAssistantProposal,
    index: int,
    action: ActionOp,
    author_user_id: UUID,
) -> NarrativeAssistantAction:
    row = await session.scalar(
        select(NarrativeAssistantAction)
        .where(
            NarrativeAssistantAction.proposal_id == proposal.id,
            NarrativeAssistantAction.op_index == index,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:  # A proposal from before actions had rows.
        row = NarrativeAssistantAction(
            tenant_id=proposal.tenant_id,
            project_id=proposal.project_id,
            thread_id=proposal.thread_id,
            proposal_id=proposal.id,
            op_index=index,
            op=action.op,
            author_user_id=author_user_id,
            status=OFFERED,
        )
        session.add(row)
        await session.flush()
    return row


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
    store: AssetBytes,
) -> None:
    """Start one action, or do nothing if it already has its job."""
    # The same lock order as job admission: concurrent starts cannot create two jobs.
    await session.scalar(
        select(Tenant).where(Tenant.id == tenant_id).with_for_update(key_share=True)
    )
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    proposal = await get_proposal(
        session, tenant_id=tenant_id, project_id=project_id, proposal_id=proposal_id
    )
    selected = next((item for item in parse_actions(proposal) if item[0] == index), None)
    if selected is None:
        raise NotFoundError("This action was not found.")
    if proposal.status not in ("ready", "accepted"):
        raise ConflictError("This proposal can no longer generate anything.")
    _, action, raw = selected
    row = await _action_row(
        session, proposal=proposal, index=index, action=action, author_user_id=author_user_id
    )
    if row.status in (STARTED, FINISHED):
        return
    if row.status == SKIPPED:
        raise ConflictError("This proposal can no longer generate anything.")
    legacy = await _legacy_image_job(session, proposal, index, action, raw)
    if legacy is not None:
        row.image_job_id, row.status = legacy.id, STARTED
        await session.flush()
        return
    story = await _head_story(session, project, tenant_id=tenant_id)
    if proposal.status == "ready" and action_needs_accept(story, _operations(proposal), action):
        raise ConflictError("Accept the proposal first: this needs what it adds to the story.")
    job = await _admit(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        proposal=proposal,
        index=index,
        action=action,
        story=story,
        author_user_id=author_user_id,
        actor=actor,
        settings=settings,
        store=store,
    )
    if isinstance(job, NarrativeAssistantThread):
        kind, count = "child", 1
        row.child_thread_id = job.id
    elif isinstance(job, NarrativeVoiceJob):
        kind, count = "voice", job.count
        row.voice_job_id = job.id
    else:
        kind, count = "image", job.count
        row.image_job_id = job.id
    row.status, row.error_code, row.detail = STARTED, None, None
    await session.flush()
    await append_thread_event(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=proposal.thread_id,
        kind=ACTION_STARTED,
        payload={
            "proposal_id": str(proposal.id),
            "index": index,
            "op": action.op,
            "label": action_label(action),
            "job_kind": kind,
            "job_id": str(job.id),
            "count": count,
        },
    )


async def queue_action(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, proposal_id: UUID, index: int
) -> None:
    """Hand an action to the dispatcher, for when a click finds the queue full."""
    row = await session.scalar(
        select(NarrativeAssistantAction)
        .where(
            NarrativeAssistantAction.tenant_id == tenant_id,
            NarrativeAssistantAction.project_id == project_id,
            NarrativeAssistantAction.proposal_id == proposal_id,
            NarrativeAssistantAction.op_index == index,
        )
        .with_for_update()
    )
    if row is not None and row.status in (OFFERED, BLOCKED, WAITING):
        row.status, row.error_code, row.detail = PENDING, None, None
        await session.flush()


async def _block(
    factory: async_sessionmaker[AsyncSession],
    *,
    proposal_id: UUID,
    index: int,
    code: str,
    detail: str,
) -> None:
    async with factory() as session:
        row = await session.scalar(
            select(NarrativeAssistantAction)
            .where(
                NarrativeAssistantAction.proposal_id == proposal_id,
                NarrativeAssistantAction.op_index == index,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or row.status != PENDING:
            return
        row.status, row.error_code, row.detail = BLOCKED, code[:80], detail[:300]
        proposal = await session.get(NarrativeAssistantProposal, proposal_id)
        parsed = parse_actions(proposal) if proposal is not None else []
        action = next((item[1] for item in parsed if item[0] == index), None)
        await append_thread_event(
            session,
            tenant_id=row.tenant_id,
            project_id=row.project_id,
            thread_id=row.thread_id,
            kind=ACTION_BLOCKED,
            payload={
                "proposal_id": str(proposal_id),
                "index": index,
                "op": row.op,
                "label": action_label(action) if action is not None else row.op,
                "code": row.error_code,
                "detail": row.detail,
            },
        )
        await session.commit()


async def dispatch_actions(
    factory: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    store: AssetBytes,
    limit: int = 10,
) -> int:
    """Start what is pending, oldest first, and return how many started.

    Each action has its own transaction, so one that cannot start holds up nothing. A
    full queue leaves it pending; anything else blocks it, with the reason for the creator.
    """
    async with factory() as session:
        rows = list(
            await session.execute(
                select(
                    NarrativeAssistantAction.tenant_id,
                    NarrativeAssistantAction.project_id,
                    NarrativeAssistantAction.proposal_id,
                    NarrativeAssistantAction.op_index,
                    NarrativeAssistantAction.author_user_id,
                )
                .where(NarrativeAssistantAction.status == PENDING)
                # One proposal's actions share a timestamp; they run in the order written.
                .order_by(
                    NarrativeAssistantAction.created_at,
                    NarrativeAssistantAction.proposal_id,
                    NarrativeAssistantAction.op_index,
                )
                .limit(limit)
            )
        )
    started = 0
    for tenant_id, project_id, proposal_id, index, author in rows:
        try:
            async with factory() as session:
                await start_action(
                    session,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    proposal_id=proposal_id,
                    index=index,
                    author_user_id=author,
                    actor=AuditActor(user_id=author),
                    settings=settings,
                    store=store,
                )
                await session.commit()
            started += 1
        except TooManyRequestsError:
            continue  # There is no room yet: try again on the next pass.
        except DomainError as error:
            await _block(
                factory,
                proposal_id=proposal_id,
                index=index,
                code=error.error_type,
                detail=error.detail,
            )
        except Exception:
            # Raw errors may hold story text; log the identifiers and show a plain reason.
            logger.warning("assistant action could not start: %s/%d", proposal_id, index)
            await _block(
                factory,
                proposal_id=proposal_id,
                index=index,
                code="action-failed",
                detail="This could not start. Try again.",
            )
    return started


async def reconcile_actions(factory: async_sessionmaker[AsyncSession], limit: int = 50) -> int:
    """Record finished jobs in their threads' logs, exactly once."""
    async with factory() as session:
        finished = list(
            await session.scalars(
                select(NarrativeAssistantAction.id)
                .outerjoin(
                    NarrativeImageJob,
                    NarrativeImageJob.id == NarrativeAssistantAction.image_job_id,
                )
                .outerjoin(
                    NarrativeVoiceJob,
                    NarrativeVoiceJob.id == NarrativeAssistantAction.voice_job_id,
                )
                .where(
                    NarrativeAssistantAction.status == STARTED,
                    or_(
                        NarrativeImageJob.status.in_(_FINISHED_JOB),
                        NarrativeVoiceJob.status.in_(_FINISHED_JOB),
                    ),
                )
                .limit(limit)
            )
        )
    recorded = 0
    for action_id in finished:
        async with factory() as session:
            row = await session.scalar(
                select(NarrativeAssistantAction)
                .where(NarrativeAssistantAction.id == action_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None or row.status != STARTED:
                continue
            job: NarrativeImageJob | NarrativeVoiceJob | None
            if row.image_job_id is not None:
                job = await session.get(NarrativeImageJob, row.image_job_id)
                owner = NarrativeAsset.job_id == row.image_job_id
            else:
                job = await session.get(NarrativeVoiceJob, row.voice_job_id)
                owner = NarrativeAsset.voice_job_id == row.voice_job_id
            if job is None:
                continue
            candidates = await session.scalar(
                select(func.count(NarrativeAsset.id)).where(
                    owner, NarrativeAsset.status != "discarded"
                )
            )
            row.status, row.error_code = FINISHED, job.error_code
            await append_thread_event(
                session,
                tenant_id=row.tenant_id,
                project_id=row.project_id,
                thread_id=row.thread_id,
                kind=JOB_FINISHED,
                payload={
                    "proposal_id": str(row.proposal_id),
                    "index": row.op_index,
                    "job_id": str(job.id),
                    "status": job.status,
                    "error_code": job.error_code,
                    "candidates": candidates or 0,
                },
            )
            await session.commit()
            recorded += 1
    return recorded + await _reconcile_children(factory, limit)


async def _reconcile_children(factory: async_sessionmaker[AsyncSession], limit: int) -> int:
    """A child session's action is done once its first reply ended; it reported that itself."""
    async with factory() as session:
        finished = list(
            await session.scalars(
                select(NarrativeAssistantAction.id)
                .join(
                    NarrativeAssistantTurn,
                    NarrativeAssistantTurn.thread_id == NarrativeAssistantAction.child_thread_id,
                )
                .where(
                    NarrativeAssistantAction.status == STARTED,
                    NarrativeAssistantTurn.sequence == 1,
                    NarrativeAssistantTurn.status.in_(_FINISHED_JOB),
                )
                .limit(limit)
            )
        )
    recorded = 0
    for action_id in finished:
        async with factory() as session:
            row = await session.scalar(
                select(NarrativeAssistantAction)
                .where(NarrativeAssistantAction.id == action_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is not None and row.status == STARTED:
                row.status = FINISHED
                await session.commit()
                recorded += 1
    return recorded
