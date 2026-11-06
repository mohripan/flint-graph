"""Append-only thread log: every lifecycle change writes its event in its own transaction
(ADR 0060). The turn rows stay the operational ledger for fencing and Temporal; the
conversation, as the model and the timeline see it, is a fold over these events.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.infrastructure.db.narrative_assistant_models import (
    NarrativeAssistantThread,
    NarrativeAssistantThreadEvent,
)
from flint_graph.narrative.assistant.log import ALL_KINDS, RecordedEvent

# A thread writes a handful of events per turn; this is a guard, not a working limit.
MAX_READ_EVENTS = 5000


async def append_thread_event(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    thread_id: UUID,
    kind: str,
    payload: dict[str, Any],
    actor_user_id: UUID | None = None,
) -> int:
    """Append one event and return its sequence.

    The sequence is taken under the thread row's lock, which is always the last lock
    a writer takes (no path holds a thread and then locks a turn), so appends cannot
    deadlock and two writers cannot take the same position.
    """
    if kind not in ALL_KINDS:
        raise ValueError(f"Unknown thread event kind: {kind}")
    upcoming = await session.scalar(
        update(NarrativeAssistantThread)
        .where(
            NarrativeAssistantThread.id == thread_id,
            NarrativeAssistantThread.tenant_id == tenant_id,
            NarrativeAssistantThread.project_id == project_id,
        )
        .values(next_event_sequence=NarrativeAssistantThread.next_event_sequence + 1)
        .returning(NarrativeAssistantThread.next_event_sequence)
        .execution_options(synchronize_session=False)
    )
    if upcoming is None:
        raise ValueError("Unknown assistant thread")
    sequence = int(upcoming) - 1
    session.add(
        NarrativeAssistantThreadEvent(
            tenant_id=tenant_id,
            project_id=project_id,
            thread_id=thread_id,
            sequence=sequence,
            kind=kind,
            payload=payload,
            actor_user_id=actor_user_id,
        )
    )
    await session.flush()
    return sequence


async def list_thread_events(
    session: AsyncSession, *, thread_id: UUID, after_sequence: int, limit: int
) -> list[NarrativeAssistantThreadEvent]:
    return list(
        await session.scalars(
            select(NarrativeAssistantThreadEvent)
            .where(
                NarrativeAssistantThreadEvent.thread_id == thread_id,
                NarrativeAssistantThreadEvent.sequence > after_sequence,
            )
            .order_by(NarrativeAssistantThreadEvent.sequence)
            .limit(limit)
        )
    )


async def read_thread_log(session: AsyncSession, *, thread_id: UUID) -> list[RecordedEvent]:
    """The newest events of a thread, oldest first, ready to fold."""
    rows = await session.execute(
        select(
            NarrativeAssistantThreadEvent.sequence,
            NarrativeAssistantThreadEvent.kind,
            NarrativeAssistantThreadEvent.payload,
        )
        .where(NarrativeAssistantThreadEvent.thread_id == thread_id)
        .order_by(NarrativeAssistantThreadEvent.sequence.desc())
        .limit(MAX_READ_EVENTS)
    )
    return [RecordedEvent(sequence, kind, payload) for sequence, kind, payload in rows][::-1]
