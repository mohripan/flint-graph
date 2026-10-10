"""Authorized conversation organization; grounded memory is a separate boundary."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from flint_graph.application.services.query_runs import (
    QueryRunCreate,
    create_query_run,
    transition_query_run,
)
from flint_graph.application.services.retrieval import resolve_index_version
from flint_graph.application.services.search_readiness import require_searchable_content
from flint_graph.domain.enums import QueryRunStatus
from flint_graph.domain.errors import BadRequestError, ConflictError, NotFoundError
from flint_graph.infrastructure.db.models import Conversation, ConversationTurn, QueryRun


async def create_conversation(
    session: AsyncSession, *, tenant_id: UUID, title: str
) -> Conversation:
    title = title.strip()
    if not title or len(title) > 200 or "\x00" in title:
        raise BadRequestError("Conversation title must contain 1..200 characters.")
    conversation = Conversation(tenant_id=tenant_id, title=title)
    session.add(conversation)
    await session.flush()
    return conversation


async def get_conversation(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    include_archived: bool = False,
    for_update: bool = False,
) -> Conversation:
    statement = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.tenant_id == tenant_id
    )
    if not include_archived:
        statement = statement.where(Conversation.archived_at.is_(None))
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    conversation = await session.scalar(statement)
    if conversation is None:
        raise NotFoundError("Conversation was not found.")
    return conversation


async def list_conversations(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    limit: int = 50,
    before_id: UUID | None = None,
    include_archived: bool = False,
    query: str | None = None,
) -> list[Conversation]:
    if not 1 <= limit <= 100:
        raise BadRequestError("Conversation page limit must be 1..100.")
    if query is not None and (len(query) > 200 or "\x00" in query):
        raise BadRequestError("Conversation search must not exceed 200 characters.")
    statement = select(Conversation).where(Conversation.tenant_id == tenant_id)
    if query is not None and query.strip():
        literal = query.strip().replace("!", "!!").replace("%", "!%").replace("_", "!_")
        statement = statement.where(Conversation.title.ilike(f"%{literal}%", escape="!"))
    if not include_archived:
        statement = statement.where(Conversation.archived_at.is_(None))
    if before_id is not None:
        cursor = await get_conversation(
            session,
            tenant_id=tenant_id,
            conversation_id=before_id,
            include_archived=include_archived,
        )
        # Compare persisted timestamps in the database. SQLite server timestamps
        # omit fractional seconds, unlike a rebound Python datetime parameter.
        cursor_time = (
            select(Conversation.created_at)
            .where(
                Conversation.id == cursor.id,
                Conversation.tenant_id == tenant_id,
            )
            .correlate(None)
            .scalar_subquery()
        )
        statement = statement.where(
            or_(
                Conversation.created_at < cursor_time,
                and_(Conversation.created_at == cursor_time, Conversation.id < cursor.id),
            )
        )
    return list(
        await session.scalars(
            statement.order_by(Conversation.created_at.desc(), Conversation.id.desc()).limit(limit)
        )
    )


async def rename_conversation(
    session: AsyncSession, *, tenant_id: UUID, conversation_id: UUID, title: str
) -> Conversation:
    title = title.strip()
    if not title or len(title) > 200 or "\x00" in title:
        raise BadRequestError("Conversation title must contain 1..200 characters.")
    conversation = await get_conversation(
        session, tenant_id=tenant_id, conversation_id=conversation_id, for_update=True
    )
    conversation.title = title
    await session.flush()
    await session.refresh(conversation, attribute_names=["updated_at"])
    return conversation


@dataclass(frozen=True, slots=True)
class ConversationTurnCreate:
    query: str
    idempotency_key: UUID
    retrieval_index_version_id: UUID | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    stream: bool = True


async def create_conversation_turn(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    spec: ConversationTurnCreate,
) -> ConversationTurn:
    conversation = await get_conversation(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        for_update=True,
    )
    request_hash = sha256(
        json.dumps(
            {
                "query": spec.query,
                "retrieval_index_version_id": str(spec.retrieval_index_version_id)
                if spec.retrieval_index_version_id is not None
                else None,
                "filters": spec.filters,
                "stream": spec.stream,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    existing = await session.scalar(
        select(ConversationTurn)
        .where(
            ConversationTurn.tenant_id == tenant_id,
            ConversationTurn.conversation_id == conversation_id,
            ConversationTurn.idempotency_key == spec.idempotency_key,
        )
        .options(selectinload(ConversationTurn.run))
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ConflictError("Idempotency key was used for a different turn request.")
        return existing
    await _require_no_active_turn(session, tenant_id=tenant_id, conversation_id=conversation_id)
    index = await resolve_index_version(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=spec.retrieval_index_version_id,
    )
    readiness = await require_searchable_content(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=index.id,
    )
    if not readiness.ready:
        raise ConflictError(
            "No searchable document content is available for the active retrieval index."
        )
    number = conversation.next_turn_number
    run = await create_query_run(
        session,
        QueryRunCreate(
            tenant_id=tenant_id,
            query_text=spec.query,
            retrieval_index_version_id=index.id,
            metadata={
                "filters": dict(spec.filters),
                "stream": spec.stream,
                "conversation": {
                    "id": str(conversation_id),
                    "turn_number": number,
                    "memory_mode": "independent",
                },
            },
        ),
    )
    turn = ConversationTurn(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        query_run_id=run.id,
        turn_number=number,
        idempotency_key=spec.idempotency_key,
        request_hash=request_hash,
        run=run,
    )
    session.add(turn)
    conversation.next_turn_number = number + 1
    await session.flush()
    return turn


async def _require_no_active_turn(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
) -> None:
    active = await session.scalar(
        select(ConversationTurn.id)
        .join(
            QueryRun,
            (QueryRun.id == ConversationTurn.query_run_id)
            & (QueryRun.tenant_id == ConversationTurn.tenant_id),
        )
        .where(
            ConversationTurn.tenant_id == tenant_id,
            ConversationTurn.conversation_id == conversation_id,
            QueryRun.status.in_([QueryRunStatus.QUEUED, QueryRunStatus.RUNNING]),
        )
        .limit(1)
    )
    if active is not None:
        raise ConflictError("A conversation turn is still queued or running.")


async def get_conversation_turn(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    turn_id: UUID,
    include_archived: bool = False,
) -> ConversationTurn:
    await get_conversation(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        include_archived=include_archived,
    )
    turn = await session.scalar(
        select(ConversationTurn)
        .where(
            ConversationTurn.id == turn_id,
            ConversationTurn.tenant_id == tenant_id,
            ConversationTurn.conversation_id == conversation_id,
        )
        .options(selectinload(ConversationTurn.run))
    )
    if turn is None:
        raise NotFoundError("Conversation turn was not found.")
    return turn


async def list_conversation_turns(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    limit: int = 50,
    after_id: UUID | None = None,
    include_archived: bool = False,
) -> list[ConversationTurn]:
    if not 1 <= limit <= 100:
        raise BadRequestError("Turn page limit must be 1..100.")
    await get_conversation(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        include_archived=include_archived,
    )
    statement = (
        select(ConversationTurn)
        .where(
            ConversationTurn.tenant_id == tenant_id,
            ConversationTurn.conversation_id == conversation_id,
        )
        .options(selectinload(ConversationTurn.run))
    )
    if after_id is not None:
        cursor = await get_conversation_turn(
            session,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_id=after_id,
            include_archived=include_archived,
        )
        statement = statement.where(ConversationTurn.turn_number > cursor.turn_number)
    return list(
        await session.scalars(statement.order_by(ConversationTurn.turn_number).limit(limit))
    )


async def set_conversation_archived(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    archived: bool,
) -> Conversation:
    conversation = await get_conversation(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        include_archived=True,
        for_update=True,
    )
    if archived:
        await _require_no_active_turn(session, tenant_id=tenant_id, conversation_id=conversation_id)
        if conversation.archived_at is None:
            conversation.archived_at = datetime.now(UTC)
    else:
        conversation.archived_at = None
    await session.flush()
    await session.refresh(conversation)
    return conversation


async def cancel_queued_conversation_turn(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    turn_id: UUID,
) -> ConversationTurn:
    await get_conversation(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        include_archived=True,
        for_update=True,
    )
    turn = await get_conversation_turn(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
        include_archived=True,
    )
    run = await session.scalar(
        select(QueryRun)
        .where(
            QueryRun.id == turn.query_run_id,
            QueryRun.tenant_id == tenant_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run is None:
        raise NotFoundError("Conversation run was not found.")
    if run.status == QueryRunStatus.CANCELLED:
        return turn
    if run.status != QueryRunStatus.QUEUED:
        raise ConflictError("Only a queued conversation turn can be cancelled by this endpoint.")
    await transition_query_run(
        session,
        tenant_id=tenant_id,
        query_run_id=run.id,
        target_status=QueryRunStatus.CANCELLED,
        event_type="query.cancelled",
        payload={"reason": "queued_turn_cancelled"},
    )
    await session.refresh(run)
    return turn
