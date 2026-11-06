"""A thread's conversation is a fold over its append-only event log (ADR 0060).

``fold_thread`` is the only way to build a ``ThreadState``: the model's history and
the Studio's timeline both read the same fold of the same events, so they cannot
disagree about what happened. Deciding here is pure: no clock, no database.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from flint_graph.narrative.assistant.context import HistoryTurn

THREAD_CREATED = "thread.created"
TURN_REQUESTED = "turn.requested"
TURN_COMPLETED = "turn.completed"
TURN_FAILED = "turn.failed"
TURN_CANCELLED = "turn.cancelled"
PROPOSAL_CREATED = "proposal.created"
PROPOSAL_ACCEPTED = "proposal.accepted"
PROPOSAL_REJECTED = "proposal.rejected"
ACTION_STARTED = "action.started"
ACTION_BLOCKED = "action.blocked"
JOB_FINISHED = "job.finished"
ASSET_APPROVED = "asset.approved"

ALL_KINDS = frozenset(
    {
        THREAD_CREATED,
        TURN_REQUESTED,
        TURN_COMPLETED,
        TURN_FAILED,
        TURN_CANCELLED,
        PROPOSAL_CREATED,
        PROPOSAL_ACCEPTED,
        PROPOSAL_REJECTED,
        ACTION_STARTED,
        ACTION_BLOCKED,
        JOB_FINISHED,
        ASSET_APPROVED,
    }
)

RECENT_TURNS = 4
_EARLIER_CHARS = 2000
_EARLIER_LINE_CHARS = 160


class LogOrderError(Exception):
    """Events were not in strictly increasing order; a reader bug, never guessed around."""


@dataclass(frozen=True)
class RecordedEvent:
    sequence: int
    kind: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class ActionRecord:
    """A generation action as far as the conversation knows."""

    index: int
    label: str
    status: str  # started, blocked, completed, failed or cancelled
    detail: str | None = None
    candidates: int = 0
    approved: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProposalRecord:
    proposal_id: str
    summary: str
    status: str
    revision_id: str | None = None
    conflicted: bool = False
    actions: tuple[ActionRecord, ...] = ()


@dataclass(frozen=True)
class TurnRecord:
    turn_id: str
    turn_sequence: int
    request: str
    status: str = "queued"
    reply: str | None = None
    error_code: str | None = None
    proposal: ProposalRecord | None = None
    attached: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThreadState:
    title: str | None = None
    cursor: int = 0
    turns: tuple[TurnRecord, ...] = field(default=())


@dataclass(frozen=True)
class Conversation:
    """What the model is told: recent turns verbatim, older ones as one line each."""

    recent: tuple[HistoryTurn, ...]
    earlier: tuple[str, ...]


def fold_thread(events: Iterable[RecordedEvent]) -> ThreadState:
    """Replay a thread's events. Unknown kinds are skipped, so an older worker reading
    a newer log during a rolling deploy still sees everything it understands."""
    title: str | None = None
    cursor = 0
    turns: dict[str, TurnRecord] = {}
    proposals: dict[str, str] = {}

    def update_proposal(proposal_id: str, **changes: Any) -> None:
        turn_id = proposals.get(proposal_id)
        turn = turns.get(turn_id) if turn_id is not None else None
        if turn is not None and turn.proposal is not None:
            turns[turn.turn_id] = replace(turn, proposal=replace(turn.proposal, **changes))

    def update_action(data: Mapping[str, Any], **changes: Any) -> None:
        proposal_id, index = str(data.get("proposal_id")), data.get("index")
        turn = turns.get(proposals.get(proposal_id, ""))
        if turn is None or turn.proposal is None or not isinstance(index, int):
            return
        known = {item.index: item for item in turn.proposal.actions}
        current = known.get(index) or ActionRecord(index, str(data.get("label", "")), "")
        known[index] = replace(current, **changes)
        ordered = tuple(known[key] for key in sorted(known))
        update_proposal(proposal_id, actions=ordered)

    for event in events:
        if event.sequence <= cursor:
            raise LogOrderError(f"event {event.sequence} after {cursor}")
        cursor = event.sequence
        data = event.payload
        turn = turns.get(str(data.get("turn_id")))
        if event.kind == THREAD_CREATED:
            title = str(data.get("title"))
        elif event.kind == TURN_REQUESTED:
            key = str(data["turn_id"])
            turns[key] = TurnRecord(
                key,
                int(data["turn_sequence"]),
                str(data["request"]),
                attached=tuple(str(name) for name in data.get("attached") or ()),
            )
        elif event.kind == TURN_COMPLETED and turn is not None:
            reply = data.get("reply")
            turns[turn.turn_id] = replace(
                turn, status="completed", reply=None if reply is None else str(reply)
            )
        elif event.kind in (TURN_FAILED, TURN_CANCELLED) and turn is not None:
            code = data.get("error_code")
            turns[turn.turn_id] = replace(
                turn,
                status="failed" if event.kind == TURN_FAILED else "cancelled",
                error_code=None if code is None else str(code),
            )
        elif event.kind == PROPOSAL_CREATED and turn is not None:
            proposal_id = str(data["proposal_id"])
            proposals[proposal_id] = turn.turn_id
            turns[turn.turn_id] = replace(
                turn,
                proposal=ProposalRecord(
                    proposal_id, str(data.get("summary", "")), str(data.get("status", "ready"))
                ),
            )
        elif event.kind == PROPOSAL_ACCEPTED:
            revision = data.get("revision_id")
            update_proposal(
                str(data["proposal_id"]),
                status="accepted",
                revision_id=None if revision is None else str(revision),
                conflicted=bool(data.get("conflicted")),
            )
        elif event.kind == PROPOSAL_REJECTED:
            update_proposal(str(data["proposal_id"]), status="rejected")
        elif event.kind == ACTION_STARTED:
            update_action(data, status="started", label=str(data.get("label", "")))
        elif event.kind == ACTION_BLOCKED:
            update_action(
                data,
                status="blocked",
                label=str(data.get("label", "")),
                detail=str(data.get("detail", "")),
            )
        elif event.kind == JOB_FINISHED:
            code = data.get("error_code")
            update_action(
                data,
                status=str(data.get("status")),
                candidates=int(data.get("candidates") or 0),
                detail=None if code is None else str(code),
            )
        elif event.kind == ASSET_APPROVED:
            turn = turns.get(proposals.get(str(data.get("proposal_id")), ""))
            action = next(
                (
                    item
                    for item in (turn.proposal.actions if turn and turn.proposal else ())
                    if item.index == data.get("index")
                ),
                None,
            )
            if action is not None:
                update_action(data, approved=(*action.approved, str(data.get("name", ""))))
    ordered = tuple(sorted(turns.values(), key=lambda item: item.turn_sequence))
    return ThreadState(title=title, cursor=cursor, turns=ordered)


def _proposal_outcome(proposal: ProposalRecord) -> str:
    quoted = f'"{proposal.summary}"'
    if proposal.status == "accepted":
        if proposal.conflicted:
            return (
                f"The creator accepted {quoted}, but the story had changed, "
                "so it was kept as a conflict copy and not applied."
            )
        return f"The creator accepted {quoted}; it is in the saved story."
    if proposal.status == "rejected":
        return f"The creator rejected {quoted}; it is not in the story."
    if proposal.status == "invalid":
        return f"{quoted} broke the story rules and could not be used."
    return f"The creator has not decided on {quoted} yet; it is not in the story."


def _action_outcome(action: ActionRecord) -> str:
    if action.status == "started":
        return f"{action.label}: generating now"
    if action.status == "blocked":
        return f"{action.label}: could not start ({action.detail})"
    if action.status == "completed":
        chosen = (
            f"approved in the library: {', '.join(action.approved)}"
            if action.approved
            else "none approved yet"
        )
        return f"{action.label}: {action.candidates} candidates ready, {chosen}"
    if action.status == "cancelled":
        return f"{action.label}: stopped"
    return f"{action.label}: failed ({action.detail or 'unknown error'})"


def _assistant_text(turn: TurnRecord) -> str:
    """The assistant's side of a turn, plus what happened next."""
    if turn.status == "failed":
        reason = turn.error_code or "unknown error"
        return f"[This reply could not finish ({reason}); nothing changed.]"
    if turn.status == "cancelled":
        return "[The creator stopped this reply; nothing changed.]"
    if turn.proposal is None:
        return turn.reply or ""
    notes = [_proposal_outcome(turn.proposal)]
    if turn.proposal.actions:
        notes.append(
            "Generation: " + "; ".join(_action_outcome(item) for item in turn.proposal.actions)
        )
    return f"{turn.reply or ''}\n[{' '.join(notes)}]".strip()


def _one_line(text: str, limit: int) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


def _earlier_line(turn: TurnRecord) -> str:
    asked = _one_line(turn.request, 70)
    if turn.status in ("failed", "cancelled"):
        return _one_line(f'- Asked "{asked}": {turn.status}', _EARLIER_LINE_CHARS)
    if turn.proposal is None:
        return _one_line(f'- Asked "{asked}": answered', _EARLIER_LINE_CHARS)
    return _one_line(
        f'- Asked "{asked}": {turn.proposal.status} "{turn.proposal.summary}"',
        _EARLIER_LINE_CHARS,
    )


def conversation_from_log(
    state: ThreadState, *, before_turn: int, recent_turns: int = RECENT_TURNS
) -> Conversation:
    """The conversation as of ``before_turn``, in a bounded size.

    A turn still queued or running has no answer yet and is left out. Failed and
    stopped turns stay in, so "try again" has something to refer to.
    """
    finished = [
        turn
        for turn in state.turns
        if turn.turn_sequence < before_turn and turn.status in ("completed", "failed", "cancelled")
    ]
    older = finished[:-recent_turns] if recent_turns else finished
    recent = finished[-recent_turns:] if recent_turns else []
    messages: list[HistoryTurn] = []
    for turn in recent:
        asked = turn.request
        if turn.attached:
            asked += f"\n[Attached: {', '.join(turn.attached)}]"
        messages.append(HistoryTurn("user", asked))
        answer = _assistant_text(turn)
        if answer:
            messages.append(HistoryTurn("assistant", answer))
    lines: list[str] = []
    used = 0
    for turn in reversed(older):  # The newest older turns matter most.
        line = _earlier_line(turn)
        if used + len(line) + 1 > _EARLIER_CHARS - 60:
            break
        lines.append(line)
        used += len(line) + 1
    lines.reverse()
    if len(lines) < len(older):
        lines.insert(0, f"({len(older) - len(lines)} older requests omitted)")
    return Conversation(tuple(messages), tuple(lines))
