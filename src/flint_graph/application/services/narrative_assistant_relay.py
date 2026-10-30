"""Opt-in assistant dispatch and recovery; never consumes ingestion or release topics."""

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flint_graph.application.narrative_assistant_workflow import (
    CANCELLED_TOPIC,
    QUEUED_TOPIC,
    TurnPayload,
    validate_turn_payload,
)
from flint_graph.application.services.narrative_assistant import (
    abandon_turn,
    register_turn_workflow,
)
from flint_graph.domain.enums import OutboxMessageStatus
from flint_graph.infrastructure.db.models import NarrativeAssistantTurn, OutboxMessage


class AssistantDispatcher(Protocol):
    async def start(self, payload: TurnPayload) -> UUID: ...

    async def cancel(self, payload: TurnPayload, *, run_id: UUID) -> None: ...

    async def closed(self, payload: TurnPayload, *, run_id: UUID) -> bool: ...


async def relay_assistant_message(
    session: AsyncSession,
    *,
    dispatcher: AssistantDispatcher,
    retry_delay_seconds: int = 30,
) -> bool | None:
    """Caller commits the acknowledgement and run registration together.

    A lost commit replays the same Temporal run (USE_EXISTING). A per-message
    savepoint keeps one bad record from starving independent turns, and raw
    exceptions never reach persisted errors.
    """
    if not 1 <= retry_delay_seconds <= 3600:
        raise ValueError("Invalid assistant relay limits")
    message = await session.scalar(
        select(OutboxMessage)
        .where(
            OutboxMessage.status == OutboxMessageStatus.PENDING,
            OutboxMessage.topic.in_([QUEUED_TOPIC, CANCELLED_TOPIC]),
            OutboxMessage.available_at <= datetime.now(UTC),
        )
        .order_by(
            case((OutboxMessage.topic == QUEUED_TOPIC, 0), else_=1),
            OutboxMessage.available_at,
            OutboxMessage.created_at,
            OutboxMessage.id,
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if message is None:
        return None
    message_id = message.id
    try:
        async with session.begin_nested():
            payload = validate_turn_payload(message.payload)
            turn_id, tenant_id = UUID(payload["turn_id"]), UUID(payload["tenant_id"])
            if (
                message.aggregate_type != "narrative_assistant_turn"
                or message.aggregate_id != turn_id
                or message.tenant_id != tenant_id
            ):
                raise ValueError("Invalid assistant dispatch identity")
            turn = await session.scalar(
                select(NarrativeAssistantTurn)
                .where(
                    NarrativeAssistantTurn.id == turn_id,
                    NarrativeAssistantTurn.tenant_id == tenant_id,
                )
                .execution_options(populate_existing=True)
            )
            if turn is None:
                raise ValueError("Invalid assistant dispatch identity")
            if turn.status in ("queued", "running"):
                if message.topic == QUEUED_TOPIC:
                    run_id = await dispatcher.start(payload)
                    await register_turn_workflow(
                        session, tenant_id=tenant_id, turn_id=turn_id, workflow_run_id=run_id
                    )
                else:
                    if turn.workflow_run_id is None:
                        raise ValueError("Assistant dispatch registration pending")
                    await dispatcher.cancel(payload, run_id=turn.workflow_run_id)
            # Terminal turns need no workflow start or cancellation.
            message.status = OutboxMessageStatus.PUBLISHED
            message.published_at = datetime.now(UTC)
            message.last_error = None
            message.locked_by = message.locked_at = None
            await session.flush()
        return True
    except Exception:
        failed = await session.get(OutboxMessage, message_id, populate_existing=True)
        if failed is None:
            return False
        failed.attempt_count += 1
        failed.available_at = datetime.now(UTC) + timedelta(seconds=retry_delay_seconds)
        failed.last_error = "dispatch_unavailable"
        failed.locked_by = failed.locked_at = None
        await session.flush()
    return False


async def relay_assistant_batch(
    factory: async_sessionmaker[AsyncSession],
    *,
    dispatcher: AssistantDispatcher,
    batch_size: int = 10,
    retry_delay_seconds: int = 30,
) -> int:
    """Commit each registration before issuing the next message's RPC."""
    if not 1 <= batch_size <= 100:
        raise ValueError("Invalid assistant relay limits")
    published = 0
    for _ in range(batch_size):
        async with factory() as session:
            result = await relay_assistant_message(
                session, dispatcher=dispatcher, retry_delay_seconds=retry_delay_seconds
            )
            await session.commit()
        if result is None:
            break
        published += int(result)
    return published


async def recover_stale_turns(
    factory: async_sessionmaker[AsyncSession],
    *,
    dispatcher: AssistantDispatcher,
    older_than: timedelta = timedelta(minutes=30),
    limit: int = 20,
) -> int:
    """Fail active turns whose registered workflow run has closed without finishing them.

    A turn is only closed after its own run is observed closed, so a slow but live
    execution is never interrupted by recovery.
    """
    cutoff = datetime.now(UTC) - older_than
    age = func.coalesce(NarrativeAssistantTurn.started_at, NarrativeAssistantTurn.created_at)
    async with factory() as session:
        candidates = list(
            await session.execute(
                select(
                    NarrativeAssistantTurn.id,
                    NarrativeAssistantTurn.tenant_id,
                    NarrativeAssistantTurn.workflow_run_id,
                )
                .where(
                    NarrativeAssistantTurn.status.in_(("queued", "running")),
                    NarrativeAssistantTurn.workflow_run_id.is_not(None),
                    age < cutoff,
                )
                .order_by(age, NarrativeAssistantTurn.id)
                .limit(limit)
            )
        )
    recovered = 0
    for turn_id, tenant_id, run_id in candidates:
        payload = TurnPayload(schema_version="1", tenant_id=str(tenant_id), turn_id=str(turn_id))
        try:
            if not await dispatcher.closed(payload, run_id=run_id):
                continue
        except Exception:
            continue
        async with factory() as session:
            closed = await abandon_turn(
                session, turn_id=turn_id, workflow_run_id=run_id, error_code="worker_interrupted"
            )
            await session.commit()
        recovered += int(closed is not None)
    return recovered
