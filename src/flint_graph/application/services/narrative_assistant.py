"""Project assistant threads, durable turns and reviewed proposals (ADR 0038).

API requests only record intent: a turn is queued with an ID-only outbox message
and a model runs later in a fenced job. Proposals become canon solely through
``accept_proposal``, which creates a normal revision through ``create_revision``
(rebased when the touched records are unchanged, otherwise a conflict revision).
Audit metadata and outbox payloads carry identifiers, never story or chat text.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.narrative_assistant_workflow import CANCELLED_TOPIC, QUEUED_TOPIC
from flint_graph.application.services.audit import AuditActor, record_audit_event
from flint_graph.application.services.narrative_assistant_events import (
    add_status_event,
    add_turn_event,
    events_after,
)
from flint_graph.application.services.narrative_projects import (
    create_revision,
    get_project,
    get_revision,
)
from flint_graph.application.services.outbox import append_outbox_message, capture_trace_context
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
from flint_graph.narrative.assistant.context import HistoryTurn
from flint_graph.narrative.assistant.operations import Proposal, check_proposal
from flint_graph.narrative.assistant.turn import TurnResult
from flint_graph.narrative.values import canonical_json

HISTORY_TURNS = 4
_ACTIVE = ("queued", "running")


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
    history: tuple[HistoryTurn, ...]
    # Story format 2: approved library files under story-ready IDs, and each
    # character's described looks (editor metadata the model may reuse).
    library: tuple[LibraryEntry, ...] = ()
    profiles: dict[str, str] = field(default_factory=dict)


async def create_thread(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    author_user_id: UUID,
    title: str,
    idempotency_key: UUID,
    actor: AuditActor,
) -> NarrativeAssistantThread:
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    request_hash = _fingerprint({"title": title})
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
    thread = NarrativeAssistantThread(
        tenant_id=tenant_id,
        project_id=project_id,
        author_user_id=author_user_id,
        title=title,
        creation_key=idempotency_key,
        request_hash=request_hash,
        next_sequence=1,
    )
    session.add(thread)
    await session.flush()
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
    statement = select(NarrativeAssistantThread).where(*scope)
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
    request_hash = _fingerprint(
        {"request": request, "base_revision_id": str(base_revision_id), "focus_node": focus_node}
    )
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
    await get_revision(
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
        status="queued",
        cancel_requested=False,
    )
    thread.next_sequence += 1
    thread.updated_at = _now()
    session.add(turn)
    await session.flush()
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
        turn.status, turn.finished_at = "cancelled", _now()
        await add_status_event(session, turn)
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
    earlier = await session.scalars(
        select(NarrativeAssistantTurn)
        .where(
            NarrativeAssistantTurn.thread_id == turn.thread_id,
            NarrativeAssistantTurn.sequence < turn.sequence,
            NarrativeAssistantTurn.status == "completed",
        )
        .order_by(NarrativeAssistantTurn.sequence.desc())
        .limit(HISTORY_TURNS)
    )
    history: list[HistoryTurn] = []
    for previous in reversed(list(earlier)):
        history.append(HistoryTurn("user", previous.request))
        if previous.reply:
            history.append(HistoryTurn("assistant", previous.reply))
    story = json.loads(base.story_json)
    library: tuple[LibraryEntry, ...] = ()
    profiles: dict[str, str] = {}
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
        library = library_entries(
            story,
            (LibraryRow(row.name, row.kind, row.media_type, row.sha256) for row in rows),
        )
    looks = await session.scalars(
        select(NarrativeCharacterProfile).where(
            NarrativeCharacterProfile.tenant_id == turn.tenant_id,
            NarrativeCharacterProfile.project_id == turn.project_id,
        )
    )
    profiles = {row.character_id: row.appearance for row in looks if row.appearance}
    await session.flush()
    return TurnWork(
        tenant_id=turn.tenant_id,
        project_id=turn.project_id,
        turn_id=turn.id,
        story=story,
        request=turn.request,
        focus=turn.focus_node,
        history=tuple(history),
        library=library,
        profiles=profiles,
    )


def _owned(turn: NarrativeAssistantTurn | None, token: UUID) -> bool:
    return turn is not None and turn.status == "running" and turn.execution_token == token


async def _finish(session: AsyncSession, turn: NarrativeAssistantTurn, status: str) -> None:
    turn.status, turn.execution_token, turn.finished_at = status, None, _now()
    await add_status_event(session, turn)


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
        session.add(
            NarrativeAssistantProposal(
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
                warnings=[
                    {"code": item.code, "location": item.location} for item in result.warnings
                ],
                touched=list(result.touched),
            )
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
