"""Durable, bounded live progress for assistant turns (#171).

The worker appends steps, thinking and reply-text deltas while it owns a turn;
every terminal transition appends one ``status`` event in the same transaction,
so readers can resume by sequence and know when a turn's stream ends. Events stay
in PostgreSQL: Temporal history, outbox payloads and audit metadata are unchanged.
"""

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flint_graph.infrastructure.db.narrative_assistant_models import (
    NarrativeAssistantTurn,
    NarrativeAssistantTurnEvent,
)
from flint_graph.narrative.assistant.turn import AssistantModelError

DELTA_CHARS = 4000
MAX_EVENTS = 1500
STEP_RESERVE = 100  # Rows under MAX_EVENTS that only steps may use.
TEXT_LIMITS = {"thinking": 64000, "text": 16000}
FLUSH_SECONDS = 0.35
SLOW_FLUSH_SECONDS = 1.0
FAST_FLUSHES = 40
FLUSH_CHARS = 2000


class TurnEventsClosed(Exception):
    """This execution may no longer write: ``stale_execution`` or ``cancelled``."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass
class TurnEventItem:
    kind: str
    payload: dict[str, Any]


async def _next_sequence(session: AsyncSession, turn_id: UUID) -> int:
    current = await session.scalar(
        select(func.max(NarrativeAssistantTurnEvent.sequence)).where(
            NarrativeAssistantTurnEvent.turn_id == turn_id
        )
    )
    return (current or 0) + 1


def _add(
    session: AsyncSession,
    turn: NarrativeAssistantTurn,
    sequence: int,
    kind: str,
    payload: dict[str, Any],
) -> None:
    session.add(
        NarrativeAssistantTurnEvent(
            tenant_id=turn.tenant_id,
            project_id=turn.project_id,
            thread_id=turn.thread_id,
            turn_id=turn.id,
            sequence=sequence,
            attempt=turn.activity_attempt or 0,
            kind=kind,
            payload=payload,
        )
    )


async def add_turn_event(
    session: AsyncSession, turn: NarrativeAssistantTurn, kind: str, payload: dict[str, Any]
) -> None:
    """Append one event for a turn whose row this transaction already locked."""
    _add(session, turn, await _next_sequence(session, turn.id), kind, payload)
    await session.flush()  # The next sequence must see it even without autoflush.


async def add_status_event(session: AsyncSession, turn: NarrativeAssistantTurn) -> None:
    # Always written, even past MAX_EVENTS: readers stop on it.
    await add_turn_event(
        session, turn, "status", {"status": turn.status, "error_code": turn.error_code}
    )


async def append_turn_events(
    session: AsyncSession,
    *,
    turn_id: UUID,
    execution_token: UUID,
    items: Sequence[TurnEventItem],
    limit: int = MAX_EVENTS,
    reserve: int = STEP_RESERVE,
) -> int:
    """Append items as the owning execution; returns how many fit.

    Steps fit up to ``limit`` rows per turn, deltas only up to ``limit - reserve``.
    """
    turn = await session.scalar(
        select(NarrativeAssistantTurn)
        .where(NarrativeAssistantTurn.id == turn_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if turn is None or turn.status != "running" or turn.execution_token != execution_token:
        raise TurnEventsClosed("stale_execution")
    if turn.cancel_requested:
        raise TurnEventsClosed("cancelled")
    sequence = await _next_sequence(session, turn_id)
    written = 0
    for item in items:
        if sequence > limit - (reserve if item.kind in TEXT_LIMITS else 0):
            continue
        _add(session, turn, sequence, item.kind, item.payload)
        sequence, written = sequence + 1, written + 1
    await session.flush()
    return written


async def events_after(
    session: AsyncSession, *, tenant_id: UUID, turn_id: UUID, after_sequence: int, limit: int
) -> list[NarrativeAssistantTurnEvent]:
    return list(
        await session.scalars(
            select(NarrativeAssistantTurnEvent)
            .where(
                NarrativeAssistantTurnEvent.tenant_id == tenant_id,
                NarrativeAssistantTurnEvent.turn_id == turn_id,
                NarrativeAssistantTurnEvent.sequence > after_sequence,
            )
            .order_by(NarrativeAssistantTurnEvent.sequence)
            .limit(limit)
        )
    )


class TurnEventWriter:
    """A ``TurnObserver`` that batches one execution's progress into fenced rows.

    Deltas are coalesced per kind and call, flushed every ``interval`` seconds
    (``slow_interval`` after ``fast_flushes`` flushes, so long thinking stays well
    under the row cap) or at ``flush_chars`` pending characters. Steps flush at once
    so order is kept, and progress steps replace an unflushed one. A lost fence or
    a requested stop raises ``AssistantModelError`` so the model call ends promptly.
    """

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        *,
        turn_id: UUID,
        execution_token: UUID,
        interval: float = FLUSH_SECONDS,
        slow_interval: float = SLOW_FLUSH_SECONDS,
        fast_flushes: int = FAST_FLUSHES,
        flush_chars: int = FLUSH_CHARS,
        limits: Mapping[str, int] = TEXT_LIMITS,
        max_events: int = MAX_EVENTS,
        step_reserve: int = STEP_RESERVE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._factory, self._turn_id, self._token = factory, turn_id, execution_token
        self._intervals, self._fast_flushes = (interval, slow_interval), fast_flushes
        self._flush_chars, self._limits = flush_chars, limits
        self._max_events, self._reserve, self._clock = max_events, step_reserve, clock
        self._flushes = 0
        self._pending: list[TurnEventItem] = []
        self._pending_chars = 0
        self._chars = dict.fromkeys(limits, 0)
        self._truncated: set[str] = set()
        self._closed: str | None = None
        self._full = self._deltas_full = False
        self._flushed_at = clock()

    async def step(self, name: str, state: str, detail: Mapping[str, Any]) -> None:
        item = TurnEventItem("step", {"name": name, "state": state, **detail})
        if state == "progress":
            last = self._pending[-1] if self._pending else None
            if last is not None and last.kind == "step" and _same_progress(last, item):
                self._pending[-1] = item
            else:
                self._pending.append(item)
            await self._maybe_flush()
            return
        self._pending.append(item)
        await self.flush()

    async def thinking(self, call: int, text: str) -> None:
        await self._delta("thinking", call, text)

    async def text(self, call: int, text: str) -> None:
        await self._delta("text", call, text)

    def _truncate(self, kind: str, call: int) -> None:
        if kind not in self._truncated:
            self._truncated.add(kind)
            self._pending.append(
                TurnEventItem(
                    "step", {"name": "truncated", "state": "done", "kind": kind, "call": call}
                )
            )

    async def _delta(self, kind: str, call: int, text: str) -> None:
        if self._deltas_full:
            return
        room = self._limits[kind] - self._chars[kind]
        if room <= 0:
            self._truncate(kind, call)
            await self._maybe_flush()
            return
        text = text[:room]
        self._chars[kind] += len(text)
        self._pending_chars += len(text)
        last = self._pending[-1] if self._pending else None
        if last is not None and last.kind == kind and last.payload["call"] == call:
            space = DELTA_CHARS - len(last.payload["text"])
            last.payload["text"] += text[:space]
            text = text[space:]
        for start in range(0, len(text), DELTA_CHARS):
            self._pending.append(
                TurnEventItem(kind, {"call": call, "text": text[start : start + DELTA_CHARS]})
            )
        await self._maybe_flush()

    async def _maybe_flush(self) -> None:
        interval = self._intervals[self._flushes >= self._fast_flushes]
        due = self._clock() - self._flushed_at >= interval
        if due or self._pending_chars >= self._flush_chars:
            await self.flush()

    async def flush(self) -> None:
        if self._closed is not None:
            raise AssistantModelError(self._closed)
        items, self._pending, self._pending_chars = self._pending, [], 0
        self._flushed_at = self._clock()
        if not items or self._full:
            return
        try:
            async with self._factory() as session:
                written = await append_turn_events(
                    session,
                    turn_id=self._turn_id,
                    execution_token=self._token,
                    items=items,
                    limit=self._max_events,
                    reserve=self._reserve,
                )
                await session.commit()
        except TurnEventsClosed as closed:
            self._closed = closed.code
            raise AssistantModelError(closed.code) from None
        self._flushes += 1
        if written < len(items):
            dropped = [item for item in items if item.kind in self._limits]
            if dropped and not self._deltas_full:
                # Keep the steps that follow; say once per kind that text was cut.
                self._deltas_full = True
                for item in dropped:
                    self._truncate(item.kind, item.payload["call"])
            elif not dropped:
                self._full = True


def _same_progress(left: TurnEventItem, right: TurnEventItem) -> bool:
    keys = ("name", "state", "call")
    return all(left.payload.get(key) == right.payload.get(key) for key in keys)
