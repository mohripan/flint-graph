from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from opentelemetry.propagate import inject
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.infrastructure.db.models import OutboxMessage


def capture_trace_context() -> dict[str, str]:
    carrier: dict[str, str] = {}
    inject(carrier)
    return carrier


async def append_outbox_message(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    topic: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict[str, Any],
    headers: dict[str, Any] | None = None,
) -> OutboxMessage:
    now = datetime.now(UTC)
    message = OutboxMessage(
        tenant_id=tenant_id,
        topic=topic,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
        headers=headers or {},
        created_at=now,
        available_at=now,
    )
    session.add(message)
    await session.flush()
    return message
