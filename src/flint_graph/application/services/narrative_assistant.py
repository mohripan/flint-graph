"""Project assistant threads, durable turns and reviewed proposals (ADR 0038).

API requests only record intent: a turn is queued with an ID-only outbox message
and a model runs later in a fenced job. Proposals become canon solely through
``accept_proposal``, which creates a normal revision through ``create_revision``
(rebased when the touched records are unchanged, otherwise a conflict revision).
Audit metadata and outbox payloads carry identifiers, never story or chat text.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.credit_prices import assistant_item
from flint_graph.application.narrative_assistant_workflow import CANCELLED_TOPIC, QUEUED_TOPIC
from flint_graph.application.services.access import charge_usage
from flint_graph.application.services.audit import AuditActor, record_audit_event
from flint_graph.application.services.narrative_assistant_action_state import (
    create_actions,
    release_waiting_actions,
    skip_open_actions,
)
from flint_graph.application.services.narrative_assistant_events import (
    add_status_event,
    add_turn_event,
    events_after,
)
from flint_graph.application.services.narrative_assistant_log import (
    append_thread_event,
    read_thread_log,
)
from flint_graph.application.services.narrative_projects import (
    create_revision,
    get_project,
    get_revision,
)
from flint_graph.application.services.outbox import append_outbox_message, capture_trace_context
from flint_graph.application.services.prompt_bundles import execution_bundle, pin_bundle
from flint_graph.domain.enums import AuditAction
from flint_graph.domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    TooManyRequestsError,
)
from flint_graph.infrastructure.db.models import (
    NarrativeAssistantProposal,
    NarrativeAssistantThread,
    NarrativeAssistantTurn,
    NarrativeRevision,
    Tenant,
)
from flint_graph.infrastructure.db.narrative_assistant_models import NarrativeAssistantTurnEvent
from flint_graph.infrastructure.db.narrative_character_models import (
    NarrativeAsset,
    NarrativeCharacterProfile,
)
from flint_graph.narrative.assistant.assets import (
    LIBRARY_LIMIT,
    LibraryEntry,
    LibraryRow,
    library_entries,
)
from flint_graph.narrative.assistant.context import HistoryTurn, attached_lines
from flint_graph.narrative.assistant.log import (
    CHILD_STARTED,
    CHILD_UPDATED,
    PROPOSAL_ACCEPTED,
    PROPOSAL_CREATED,
    PROPOSAL_REJECTED,
    THREAD_CREATED,
    TURN_CANCELLED,
    TURN_COMPLETED,
    TURN_FAILED,
    TURN_REQUESTED,
    child_context,
    conversation_from_log,
    fold_thread,
)
from flint_graph.narrative.assistant.operations import Proposal, check_proposal
from flint_graph.narrative.assistant.turn import TurnResult
from flint_graph.narrative.values import canonical_json
from flint_graph.prompts.source import PromptBundle

_ACTIVE = ("queued", "running")
MAX_CHILDREN = 32
_CHILD_REPLY_CHARS = 200
_TURN_ENDED = {"completed": TURN_COMPLETED, "failed": TURN_FAILED, "cancelled": TURN_CANCELLED}


def _fingerprint(value: dict[str, Any]) -> str:
    return sha256(canonical_json(value)).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class TurnWork:
    """Everything an execution needs, loaded inside the claim transaction."""

    tenant_id: UUID
    project_id: UUID
    turn_id: UUID
    story: dict[str, Any]
    request: str
    focus: str | None
    # Folded from the thread log (ADR 0060): recent turns verbatim, older ones as one line.
    history: tuple[HistoryTurn, ...]
    earlier: tuple[str, ...] = ()
    # What the creator attached from the library, described for the model (ADR 0062).
    attached: tuple[str, ...] = ()
    child_session: bool = False
    # Story format 2: approved library files under story-ready IDs, and each
    # character's described looks (editor metadata the model may reuse).
    library: tuple[LibraryEntry, ...] = ()
    profiles: dict[str, str] = field(default_factory=dict)
    voices: dict[str, str] = field(default_factory=dict)
    prompt_bundle: PromptBundle | None = None


async def create_thread(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    author_user_id: UUID,
    title: str,
    idempotency_key: UUID,
    actor: AuditActor,
    parent_thread_id: UUID | None = None,
    task: str | None = None,
    origin: str = "creator",
) -> NarrativeAssistantThread:
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    identity: dict[str, Any] = {"title": title}
    if parent_thread_id is not None:  # Only when set, so earlier creations keep their hashes.
        identity |= {"parent_thread_id": str(parent_thread_id), "task": task}
    request_hash = _fingerprint(identity)
    existing = await session.scalar(
        select(NarrativeAssistantThread).where(
            NarrativeAssistantThread.tenant_id == tenant_id,
            NarrativeAssistantThread.project_id == project_id,
            NarrativeAssistantThread.creation_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ConflictError("This thread key was already used for a different title.")
        return existing
    if project.archived_at is not None:
        raise ConflictError("Restore this project before starting a new conversation.")
    if parent_thread_id is not None:
        parent = await get_thread(
            session, tenant_id=tenant_id, project_id=project_id, thread_id=parent_thread_id
        )
        if parent.parent_thread_id is not None:
            raise ConflictError("A child session cannot have child sessions of its own.")
        siblings = await session.scalar(
            select(func.count(NarrativeAssistantThread.id)).where(
                NarrativeAssistantThread.parent_thread_id == parent.id
            )
        )
        if (siblings or 0) >= MAX_CHILDREN:
            raise ConflictError("This conversation has as many child sessions as it can.")
    thread = NarrativeAssistantThread(
        tenant_id=tenant_id,
        project_id=project_id,
        author_user_id=author_user_id,
        title=title,
        creation_key=idempotency_key,
        request_hash=request_hash,
        next_sequence=1,
        parent_thread_id=parent_thread_id,
        task=task,
        origin=origin,
    )
    session.add(thread)
    await session.flush()
    await append_thread_event(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=thread.id,
        kind=THREAD_CREATED,
        payload={
            "title": title,
            **(
                {"parent_thread_id": str(parent_thread_id), "task": task}
                if parent_thread_id
                else {}
            ),
        },
        actor_user_id=author_user_id,
    )
    if parent_thread_id is not None:
        await append_thread_event(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            thread_id=parent_thread_id,
            kind=CHILD_STARTED,
            payload={"child_thread_id": str(thread.id), "title": title, "origin": origin},
            actor_user_id=author_user_id,
        )
    await session.refresh(thread)
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_ASSISTANT_THREAD_CREATED,
        actor=actor,
        resource_type="narrative_assistant_thread",
        resource_id=thread.id,
        metadata={"project_id": str(project_id)},
    )
    return thread


async def get_thread(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    thread_id: UUID,
    include_archived: bool = False,
    for_update: bool = False,
) -> NarrativeAssistantThread:
    await get_project(
        session, tenant_id=tenant_id, project_id=project_id, include_archived=include_archived
    )
    statement = select(NarrativeAssistantThread).where(
        NarrativeAssistantThread.tenant_id == tenant_id,
        NarrativeAssistantThread.project_id == project_id,
        NarrativeAssistantThread.id == thread_id,
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    thread = await session.scalar(statement)
    if thread is None:
        raise NotFoundError("Assistant conversation was not found.")
    return thread


async def list_threads(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    limit: int,
    before_id: UUID | None,
    include_archived: bool,
) -> list[NarrativeAssistantThread]:
    await get_project(
        session, tenant_id=tenant_id, project_id=project_id, include_archived=include_archived
    )
    scope = (
        NarrativeAssistantThread.tenant_id == tenant_id,
        NarrativeAssistantThread.project_id == project_id,
    )
    statement = select(NarrativeAssistantThread).where(
        *scope, NarrativeAssistantThread.parent_thread_id.is_(None)
    )
    if before_id is not None:
        cursor = await session.scalar(
            select(NarrativeAssistantThread).where(*scope, NarrativeAssistantThread.id == before_id)
        )
        if cursor is None:
            raise NotFoundError("Assistant conversation cursor was not found.")
        statement = statement.where(
            (NarrativeAssistantThread.created_at < cursor.created_at)
            | (
                (NarrativeAssistantThread.created_at == cursor.created_at)
                & (NarrativeAssistantThread.id < cursor.id)
            )
        )
    statement = statement.order_by(
        NarrativeAssistantThread.created_at.desc(), NarrativeAssistantThread.id.desc()
    ).limit(limit)
    return list(await session.scalars(statement))


@dataclass(frozen=True)
class ThreadNode:
    """A conversation with its child sessions, and whether a reply is in progress."""

    thread: NarrativeAssistantThread
    children: tuple["ThreadNode", ...] = ()
    active: bool = False


async def thread_nodes(
    session: AsyncSession, *, tenant_id: UUID, threads: Sequence[NarrativeAssistantThread]
) -> list[ThreadNode]:
    children = (
        list(
            await session.scalars(
                select(NarrativeAssistantThread)
                .where(
                    NarrativeAssistantThread.tenant_id == tenant_id,
                    NarrativeAssistantThread.parent_thread_id.in_([row.id for row in threads]),
                )
                .order_by(NarrativeAssistantThread.created_at, NarrativeAssistantThread.id)
            )
        )
        if threads
        else []
    )
    ids = [row.id for row in (*threads, *children)]
    busy = (
        set(
            await session.scalars(
                select(NarrativeAssistantTurn.thread_id)
                .where(
                    NarrativeAssistantTurn.tenant_id == tenant_id,
                    NarrativeAssistantTurn.thread_id.in_(ids),
                    NarrativeAssistantTurn.status.in_(_ACTIVE),
                )
                .distinct()
            )
        )
        if ids
        else set()
    )
    return [
        ThreadNode(
            thread,
            tuple(
                ThreadNode(child, active=child.id in busy)
                for child in children
                if child.parent_thread_id == thread.id
            ),
            thread.id in busy,
        )
        for thread in threads
    ]


async def _tell_parent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    thread_id: UUID,
    what: str,
    summary: str | None,
) -> None:
    """A child session reports to the conversation above it, if it has one."""
    row = (
        await session.execute(
            select(NarrativeAssistantThread.parent_thread_id, NarrativeAssistantThread.title).where(
                NarrativeAssistantThread.id == thread_id
            )
        )
    ).first()
    if row is None or row[0] is None:
        return
    await append_thread_event(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=row[0],
        kind=CHILD_UPDATED,
        payload={
            "child_thread_id": str(thread_id),
            "title": row[1],
            "what": what,
            "summary": summary,
        },
    )


async def post_turn(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    thread_id: UUID,
    author_user_id: UUID,
    request: str,
    base_revision_id: UUID,
    focus_node: str | None,
    idempotency_key: UUID,
    actor: AuditActor,
    available: bool,
    max_active_turns: int,
    provider: str | None = None,
    auto_generate: bool = False,
    attachments: Sequence[dict[str, str]] = (),
) -> NarrativeAssistantTurn:
    # NO KEY UPDATE serializes workspace admission without blocking audit FK checks.
    tenant = await session.scalar(
        select(Tenant).where(Tenant.id == tenant_id).with_for_update(key_share=True)
    )
    if tenant is None:
        raise NotFoundError("Workspace was not found.")
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    thread = await get_thread(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=thread_id,
        include_archived=True,
        for_update=True,
    )
    identity: dict[str, Any] = {
        "request": request,
        "base_revision_id": str(base_revision_id),
        "focus_node": focus_node,
    }
    # Only when set, so earlier messages keep their hashes.
    if auto_generate:
        identity["auto_generate"] = True
    chosen = list({(item["kind"], item["id"]): item for item in attachments}.values())
    if chosen:
        identity["attachments"] = chosen
    request_hash = _fingerprint(identity)
    existing = await session.scalar(
        select(NarrativeAssistantTurn).where(
            NarrativeAssistantTurn.thread_id == thread.id,
            NarrativeAssistantTurn.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ConflictError("This message key was already used for a different message.")
        return existing
    base = await get_revision(
        session, tenant_id=tenant_id, project_id=project_id, revision_id=base_revision_id
    )
    if project.archived_at is not None or thread.archived_at is not None:
        raise ConflictError("Restore this project before asking the assistant for changes.")
    if not available:
        raise DomainError(
            503,
            "Service unavailable",
            "The story assistant is not configured. Manual writing still works.",
            "assistant-unavailable",
        )
    resolved = await _resolve_attachments(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        story_json=base.story_json,
        items=chosen,
    )
    active = (
        await session.scalar(
            select(func.count(NarrativeAssistantTurn.id)).where(
                NarrativeAssistantTurn.tenant_id == tenant_id,
                NarrativeAssistantTurn.status.in_(_ACTIVE),
            )
        )
        or 0
    )
    if active >= max_active_turns:
        raise TooManyRequestsError("Wait for the assistant to finish its current reply.")
    turn = NarrativeAssistantTurn(
        prompt_bundle_sha256=await pin_bundle(session),
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=thread.id,
        sequence=thread.next_sequence,
        author_user_id=author_user_id,
        request=request,
        base_revision_id=base_revision_id,
        focus_node=focus_node,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        auto_generate=auto_generate,
        attachments=resolved,
        status="queued",
        cancel_requested=False,
    )
    thread.next_sequence += 1
    thread.updated_at = _now()
    session.add(turn)
    await session.flush()
    # Priced by the server's provider: each runs one configured model (ADR 0059).
    await charge_usage(
        session,
        user_id=author_user_id,
        item=assistant_item(provider or "ollama"),
        units=1,
        subject=f"assistant_turn:{turn.id}",
    )
    await append_thread_event(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=thread.id,
        kind=TURN_REQUESTED,
        payload={
            "turn_id": str(turn.id),
            "turn_sequence": turn.sequence,
            "request": request,
            "base_revision_id": str(base_revision_id),
            "focus_node": focus_node,
            "attached": [item["name"] for item in resolved],
        },
        actor_user_id=author_user_id,
    )
    await append_outbox_message(
        session,
        tenant_id=tenant_id,
        topic=QUEUED_TOPIC,
        aggregate_type="narrative_assistant_turn",
        aggregate_id=turn.id,
        payload={"schema_version": "1", "tenant_id": str(tenant_id), "turn_id": str(turn.id)},
        headers=capture_trace_context(),
    )
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_ASSISTANT_TURN_REQUESTED,
        actor=actor,
        resource_type="narrative_assistant_turn",
        resource_id=turn.id,
        metadata={
            "project_id": str(project_id),
            "thread_id": str(thread.id),
            "base_revision_id": str(base_revision_id),
        },
    )
    await session.refresh(turn)
    return turn


def _invalid_attachment(detail: str) -> DomainError:
    return DomainError(422, "Invalid attachment", detail, "invalid-attachment")


async def _resolve_attachments(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    story_json: str,
    items: Sequence[dict[str, str]],
) -> list[dict[str, Any]]:
    """Check what was attached belongs to this project, and freeze its name."""
    if not items:
        return []
    characters = json.loads(story_json).get("characters") or {}
    resolved: list[dict[str, Any]] = []
    for item in items:
        if item["kind"] == "character":
            character = characters.get(item["id"])
            if character is None:
                raise _invalid_attachment(f"There is no character {item['id']} in this story.")
            name = character.get("name") or item["id"]
            resolved.append(
                {"kind": "character", "id": item["id"], "name": name, "asset_kind": None}
            )
            continue
        try:
            asset_id = UUID(item["id"])
        except ValueError:
            raise _invalid_attachment("Attach a file from this project's library.") from None
        asset = await session.scalar(
            select(NarrativeAsset).where(
                NarrativeAsset.tenant_id == tenant_id,
                NarrativeAsset.project_id == project_id,
                NarrativeAsset.id == asset_id,
            )
        )
        if asset is None:
            raise _invalid_attachment("Attach a file from this project's library.")
        if asset.status != "approved":
            raise _invalid_attachment(f"Approve {asset.name} before attaching it.")
        resolved.append(
            {"kind": "asset", "id": str(asset.id), "name": asset.name, "asset_kind": asset.kind}
        )
    return resolved


async def list_turns(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    thread_id: UUID,
    after_sequence: int,
    limit: int,
    include_archived: bool,
) -> list[tuple[NarrativeAssistantTurn, NarrativeAssistantProposal | None]]:
    thread = await get_thread(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=thread_id,
        include_archived=include_archived,
    )
    rows = await session.execute(
        select(NarrativeAssistantTurn, NarrativeAssistantProposal)
        .outerjoin(
            NarrativeAssistantProposal,
            NarrativeAssistantProposal.turn_id == NarrativeAssistantTurn.id,
        )
        .where(
            NarrativeAssistantTurn.tenant_id == tenant_id,
            NarrativeAssistantTurn.thread_id == thread.id,
            NarrativeAssistantTurn.sequence > after_sequence,
        )
        .order_by(NarrativeAssistantTurn.sequence)
        .limit(limit)
    )
    return [(turn, proposal) for turn, proposal in rows.tuples()]


async def turn_status(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    thread_id: UUID,
    turn_id: UUID,
    include_archived: bool,
) -> str:
    """Authorize a turn read in its project and thread; foreign turns are not found."""
    thread = await get_thread(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=thread_id,
        include_archived=include_archived,
    )
    status = await session.scalar(
        select(NarrativeAssistantTurn.status).where(
            NarrativeAssistantTurn.tenant_id == tenant_id,
            NarrativeAssistantTurn.thread_id == thread.id,
            NarrativeAssistantTurn.id == turn_id,
        )
    )
    if status is None:
        raise NotFoundError("Assistant message was not found.")
    return status


async def list_turn_events(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    thread_id: UUID,
    turn_id: UUID,
    after_sequence: int,
    limit: int,
    include_archived: bool,
) -> list[NarrativeAssistantTurnEvent]:
    await turn_status(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=thread_id,
        turn_id=turn_id,
        include_archived=include_archived,
    )
    return await events_after(
        session, tenant_id=tenant_id, turn_id=turn_id, after_sequence=after_sequence, limit=limit
    )


async def _turn(
    session: AsyncSession, *, tenant_id: UUID, thread: NarrativeAssistantThread, turn_id: UUID
) -> NarrativeAssistantTurn:
    turn = await session.scalar(
        select(NarrativeAssistantTurn)
        .where(
            NarrativeAssistantTurn.tenant_id == tenant_id,
            NarrativeAssistantTurn.thread_id == thread.id,
            NarrativeAssistantTurn.id == turn_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if turn is None:
        raise NotFoundError("Assistant message was not found.")
    return turn


async def cancel_turn(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    thread_id: UUID,
    turn_id: UUID,
    actor: AuditActor,
) -> NarrativeAssistantTurn:
    await get_project(session, tenant_id=tenant_id, project_id=project_id, for_update=True)
    thread = await get_thread(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=thread_id,
        include_archived=True,
    )
    turn = await _turn(session, tenant_id=tenant_id, thread=thread, turn_id=turn_id)
    if turn.status not in _ACTIVE or turn.cancel_requested:
        return turn
    if turn.status == "queued":
        await _finish(session, turn, "cancelled")
    else:
        turn.cancel_requested = True
        await append_outbox_message(
            session,
            tenant_id=tenant_id,
            topic=CANCELLED_TOPIC,
            aggregate_type="narrative_assistant_turn",
            aggregate_id=turn.id,
            payload={"schema_version": "1", "tenant_id": str(tenant_id), "turn_id": str(turn.id)},
            headers=capture_trace_context(),
        )
    await session.flush()
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_ASSISTANT_TURN_CANCELLED,
        actor=actor,
        resource_type="narrative_assistant_turn",
        resource_id=turn.id,
        metadata={"project_id": str(project_id), "status": turn.status},
    )
    await session.refresh(turn)
    return turn


async def get_proposal(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    proposal_id: UUID,
    include_archived: bool = False,
    for_update: bool = False,
) -> NarrativeAssistantProposal:
    await get_project(
        session, tenant_id=tenant_id, project_id=project_id, include_archived=include_archived
    )
    statement = select(NarrativeAssistantProposal).where(
        NarrativeAssistantProposal.tenant_id == tenant_id,
        NarrativeAssistantProposal.project_id == project_id,
        NarrativeAssistantProposal.id == proposal_id,
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    proposal = await session.scalar(statement)
    if proposal is None:
        raise NotFoundError("Assistant proposal was not found.")
    return proposal


def _record(story: dict[str, Any], target: str) -> Any:
    collection, _, key = target.partition(".")
    return story.get(collection) if not key else story.get(collection, {}).get(key)


async def accept_proposal(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    proposal_id: UUID,
    author_user_id: UUID,
    idempotency_key: UUID,
    actor: AuditActor,
) -> NarrativeRevision:
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    proposal = await get_proposal(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        proposal_id=proposal_id,
        for_update=True,
    )
    if proposal.status == "accepted":
        if proposal.decision_key != idempotency_key or proposal.accepted_revision_id is None:
            raise ConflictError("This proposal was already accepted.")
        return await get_revision(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            revision_id=proposal.accepted_revision_id,
        )
    if proposal.status != "ready":
        raise ConflictError("Only a ready proposal can be accepted.")
    operations = Proposal.model_validate(
        {"summary": proposal.summary, "operations": proposal.operations}
    ).operations
    base = await get_revision(
        session, tenant_id=tenant_id, project_id=project_id, revision_id=proposal.base_revision_id
    )
    base_story = json.loads(base.story_json)
    target, story = base, check_proposal(base_story, operations).story
    head_id = project.head_revision_id
    if head_id is not None and head_id != base.id:
        head = await get_revision(
            session, tenant_id=tenant_id, project_id=project_id, revision_id=head_id
        )
        head_story = json.loads(head.story_json)
        untouched = all(
            _record(base_story, key) == _record(head_story, key) for key in proposal.touched
        )
        rebased = check_proposal(head_story, operations).story if untouched else None
        if rebased is not None:
            target, story = head, rebased
    if story is None:
        raise ConflictError("This proposal no longer applies to its saved revision.")
    revision = await create_revision(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        author_user_id=author_user_id,
        base_revision_id=target.id,
        idempotency_key=idempotency_key,
        story_json=json.dumps(story, ensure_ascii=False),
        notices=target.notices,
        actor=actor,
    )
    proposal.status = "accepted"
    proposal.accepted_revision_id = revision.id
    proposal.decision_key = idempotency_key
    proposal.decided_by_user_id = author_user_id
    proposal.decided_at = _now()
    await session.flush()
    await append_thread_event(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=proposal.thread_id,
        kind=PROPOSAL_ACCEPTED,
        payload={
            "proposal_id": str(proposal.id),
            "revision_id": str(revision.id),
            "summary": proposal.summary,
            "conflicted": revision.conflicted,
        },
        actor_user_id=author_user_id,
    )
    await _tell_parent(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=proposal.thread_id,
        what="kept as a conflict copy" if revision.conflicted else "accepted",
        summary=proposal.summary,
    )
    if not revision.conflicted:
        await release_waiting_actions(session, proposal.id)
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_ASSISTANT_PROPOSAL_ACCEPTED,
        actor=actor,
        resource_type="narrative_assistant_proposal",
        resource_id=proposal.id,
        metadata={
            "project_id": str(project_id),
            "revision_id": str(revision.id),
            "base_revision_id": str(target.id),
            "conflicted": revision.conflicted,
        },
    )
    return revision


async def reject_proposal(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    proposal_id: UUID,
    author_user_id: UUID,
    actor: AuditActor,
) -> NarrativeAssistantProposal:
    await get_project(session, tenant_id=tenant_id, project_id=project_id, for_update=True)
    proposal = await get_proposal(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        proposal_id=proposal_id,
        for_update=True,
    )
    if proposal.status == "rejected":
        return proposal
    if proposal.status == "accepted":
        raise ConflictError("An accepted proposal cannot be rejected.")
    proposal.status = "rejected"
    proposal.decided_by_user_id = author_user_id
    proposal.decided_at = _now()
    await session.flush()
    await append_thread_event(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=proposal.thread_id,
        kind=PROPOSAL_REJECTED,
        payload={"proposal_id": str(proposal.id), "summary": proposal.summary},
        actor_user_id=author_user_id,
    )
    await _tell_parent(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=proposal.thread_id,
        what="rejected",
        summary=proposal.summary,
    )
    await skip_open_actions(session, proposal.id)
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_ASSISTANT_PROPOSAL_REJECTED,
        actor=actor,
        resource_type="narrative_assistant_proposal",
        resource_id=proposal.id,
        metadata={"project_id": str(project_id)},
    )
    await session.refresh(proposal)
    return proposal


async def _locked_turn(session: AsyncSession, turn_id: UUID) -> NarrativeAssistantTurn | None:
    turn: NarrativeAssistantTurn | None = await session.scalar(
        select(NarrativeAssistantTurn)
        .where(NarrativeAssistantTurn.id == turn_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return turn


class TurnRegistrationPending(Exception):
    """The accepted workflow run is not committed on the turn yet; retry shortly."""


async def register_turn_workflow(
    session: AsyncSession, *, tenant_id: UUID, turn_id: UUID, workflow_run_id: UUID
) -> None:
    """Bind a queued turn to the run Temporal accepted, before any claim (ADR 0037)."""
    turn = await session.scalar(
        select(NarrativeAssistantTurn)
        .where(NarrativeAssistantTurn.id == turn_id, NarrativeAssistantTurn.tenant_id == tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if turn is None:
        raise ValueError("Invalid assistant dispatch identity")
    if turn.workflow_run_id is None:
        if turn.status == "queued":
            turn.workflow_run_id, turn.activity_attempt = workflow_run_id, 0
            await session.flush()
    elif turn.workflow_run_id != workflow_run_id:
        raise ValueError("Unowned assistant execution")


async def abandon_turn(
    session: AsyncSession, *, turn_id: UUID, workflow_run_id: UUID, error_code: str
) -> NarrativeAssistantTurn | None:
    """Close an active turn of this run only; returns ``None`` when it is not ours."""
    turn = await _locked_turn(session, turn_id)
    if turn is None or turn.workflow_run_id != workflow_run_id or turn.status not in _ACTIVE:
        return None
    turn.error_code = error_code[:80]
    await _finish(session, turn, "cancelled" if turn.cancel_requested else "failed")
    await session.flush()
    return turn


async def claim_turn(
    session: AsyncSession,
    *,
    turn_id: UUID,
    execution_token: UUID,
    workflow_run_id: UUID,
    activity_attempt: int,
) -> TurnWork | None:
    """Fence one execution of the registered run; its later attempts replace it.

    Raises ``TurnRegistrationPending`` while the relay has started the workflow but
    not yet committed its run, so the activity retries instead of going stale.
    """
    turn = await _locked_turn(session, turn_id)
    if turn is None or turn.status not in _ACTIVE:
        return None
    if turn.workflow_run_id is None:
        raise TurnRegistrationPending
    if turn.workflow_run_id != workflow_run_id:
        return None
    if turn.cancel_requested:
        await _finish(session, turn, "cancelled")
        await session.flush()
        return None
    turn.status = "running"
    turn.execution_token = execution_token
    turn.activity_attempt = activity_attempt
    turn.started_at = turn.started_at or _now()
    # Readers discard streamed text of an earlier attempt when a new one starts.
    await add_turn_event(session, turn, "step", {"name": "start", "state": "done"})
    base = await session.scalar(
        select(NarrativeRevision).where(
            NarrativeRevision.id == turn.base_revision_id,
            NarrativeRevision.project_id == turn.project_id,
            NarrativeRevision.tenant_id == turn.tenant_id,
        )
    )
    if base is None:
        raise DomainError(503, "Service unavailable", "Turn state is unavailable.", "turn-state")
    conversation = conversation_from_log(
        fold_thread(await read_thread_log(session, thread_id=turn.thread_id)),
        before_turn=turn.sequence,
    )
    earlier = conversation.earlier
    thread = await session.get(NarrativeAssistantThread, turn.thread_id)
    if thread is not None and thread.parent_thread_id is not None:
        parent = await session.get(NarrativeAssistantThread, thread.parent_thread_id)
        if parent is not None:
            earlier = (
                *child_context(
                    fold_thread(await read_thread_log(session, thread_id=parent.id)),
                    title=parent.title,
                    task=thread.task,
                ),
                *earlier,
            )
    story = json.loads(base.story_json)
    library: tuple[LibraryEntry, ...] = ()
    profiles: dict[str, str] = {}
    files: dict[str, LibraryRow] = {}
    attached_ids = [UUID(item["id"]) for item in turn.attachments or [] if item["kind"] == "asset"]
    if attached_ids:
        # Still approved, or it is no longer the creator's to use.
        for row in await session.scalars(
            select(NarrativeAsset).where(
                NarrativeAsset.tenant_id == turn.tenant_id,
                NarrativeAsset.project_id == turn.project_id,
                NarrativeAsset.id.in_(attached_ids),
                NarrativeAsset.status == "approved",
            )
        ):
            files[str(row.id)] = LibraryRow(
                row.name, row.kind, row.media_type, row.sha256, row.character_id
            )
    if story.get("schema_version") == "2":
        rows = await session.scalars(
            select(NarrativeAsset)
            .where(
                NarrativeAsset.tenant_id == turn.tenant_id,
                NarrativeAsset.project_id == turn.project_id,
                NarrativeAsset.status == "approved",
            )
            .order_by(NarrativeAsset.created_at.desc(), NarrativeAsset.id)
            .limit(4 * LIBRARY_LIMIT)
        )
        listed = [
            LibraryRow(row.name, row.kind, row.media_type, row.sha256, row.character_id)
            for row in rows
        ]
        library = library_entries(
            story,
            [*files.values(), *(row for row in listed if row not in files.values())],
            attached={row.sha256 for row in files.values()},
        )
    looks = list(
        await session.scalars(
            select(NarrativeCharacterProfile).where(
                NarrativeCharacterProfile.tenant_id == turn.tenant_id,
                NarrativeCharacterProfile.project_id == turn.project_id,
            )
        )
    )
    profiles = {row.character_id: row.appearance for row in looks if row.appearance}
    voices = {
        row.character_id: row.voice or "a cloned voice"
        for row in looks
        if row.voice or row.voice_reference_id
    }
    attached = attached_lines(
        story,
        turn.attachments or [],
        files=files,
        library=library,
        profiles=profiles,
        voices=voices,
    )
    await session.flush()
    return TurnWork(
        tenant_id=turn.tenant_id,
        project_id=turn.project_id,
        turn_id=turn.id,
        story=story,
        request=turn.request,
        focus=turn.focus_node,
        history=conversation.recent,
        earlier=earlier,
        attached=attached,
        child_session=bool(thread and thread.parent_thread_id),
        library=library,
        profiles=profiles,
        voices=voices,
        prompt_bundle=await execution_bundle(session, turn),
    )


def _owned(turn: NarrativeAssistantTurn | None, token: UUID) -> bool:
    return turn is not None and turn.status == "running" and turn.execution_token == token


async def _finish(session: AsyncSession, turn: NarrativeAssistantTurn, status: str) -> None:
    turn.status, turn.execution_token, turn.finished_at = status, None, _now()
    await add_status_event(session, turn)
    payload: dict[str, Any] = {"turn_id": str(turn.id), "turn_sequence": turn.sequence}
    if status == "completed":
        payload |= {
            "reply": turn.reply,
            "model": turn.model,
            "attempts": turn.attempts,
            "input_tokens": turn.input_tokens,
            "output_tokens": turn.output_tokens,
        }
    else:
        payload["error_code"] = turn.error_code
    await append_thread_event(
        session,
        tenant_id=turn.tenant_id,
        project_id=turn.project_id,
        thread_id=turn.thread_id,
        kind=_TURN_ENDED[status],
        payload=payload,
    )
    await _tell_parent(
        session,
        tenant_id=turn.tenant_id,
        project_id=turn.project_id,
        thread_id=turn.thread_id,
        what={"completed": "replied", "failed": "failed", "cancelled": "stopped"}[status],
        summary=(turn.reply or "")[:_CHILD_REPLY_CHARS] if status == "completed" else None,
    )


async def complete_turn(
    session: AsyncSession,
    *,
    turn_id: UUID,
    execution_token: UUID,
    result: TurnResult,
    provider: str,
) -> NarrativeAssistantTurn:
    turn = await _locked_turn(session, turn_id)
    if turn is None:
        raise NotFoundError("Assistant message was not found.")
    if not _owned(turn, execution_token):
        return turn
    if turn.cancel_requested:
        await _finish(session, turn, "cancelled")
        await session.flush()
        return turn
    turn.reply = result.reply
    turn.provider = provider
    turn.model = result.model[:200]
    turn.prompt_sha256 = result.prompt_sha256
    turn.attempts = result.attempts
    turn.input_tokens = result.input_tokens
    turn.output_tokens = result.output_tokens
    await _finish(session, turn, "completed")
    if result.proposal is not None or result.diagnostics:
        proposal = NarrativeAssistantProposal(
            tenant_id=turn.tenant_id,
            project_id=turn.project_id,
            thread_id=turn.thread_id,
            turn_id=turn.id,
            base_revision_id=turn.base_revision_id,
            status="invalid" if result.diagnostics else "ready",
            summary=(
                result.proposal.summary
                if result.proposal is not None
                else "The assistant's answer could not be used."
            ),
            operations=(
                [item.model_dump() for item in result.proposal.operations]
                if result.proposal is not None
                else []
            ),
            diagnostics=[
                {"code": item.code, "location": item.location} for item in result.diagnostics
            ],
            warnings=[{"code": item.code, "location": item.location} for item in result.warnings],
            touched=list(result.touched),
        )
        session.add(proposal)
        await session.flush()
        await append_thread_event(
            session,
            tenant_id=turn.tenant_id,
            project_id=turn.project_id,
            thread_id=turn.thread_id,
            kind=PROPOSAL_CREATED,
            payload={
                "proposal_id": str(proposal.id),
                "turn_id": str(turn.id),
                "summary": proposal.summary,
                "status": proposal.status,
                "operations": len(proposal.operations),
            },
        )
        if proposal.status == "ready" and result.proposal is not None:
            base = await session.scalar(
                select(NarrativeRevision).where(
                    NarrativeRevision.id == turn.base_revision_id,
                    NarrativeRevision.project_id == turn.project_id,
                    NarrativeRevision.tenant_id == turn.tenant_id,
                )
            )
            if base is not None:
                await create_actions(
                    session,
                    turn=turn,
                    proposal=proposal,
                    story=json.loads(base.story_json),
                    operations=result.proposal.operations,
                )
    await session.flush()
    return turn


async def fail_turn(
    session: AsyncSession, *, turn_id: UUID, execution_token: UUID, error_code: str
) -> NarrativeAssistantTurn:
    turn = await _locked_turn(session, turn_id)
    if turn is None:
        raise NotFoundError("Assistant message was not found.")
    if _owned(turn, execution_token):
        turn.error_code = error_code[:80]
        await _finish(session, turn, "cancelled" if turn.cancel_requested else "failed")
        await session.flush()
    return turn
