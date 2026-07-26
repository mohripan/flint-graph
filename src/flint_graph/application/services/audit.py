"""Audit ledger writes and reads.

The ledger answers "who did this, when, and was it allowed". Writes are flushed
into the caller's transaction so an audited mutation cannot commit without its
record, and there is deliberately no update or delete helper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.domain.enums import AuditAction, AuditOutcome
from flint_graph.infrastructure.db.models import AuditEvent
from flint_graph.observability import metrics
from flint_graph.observability.instruments import AUDIT_EVENTS


@dataclass(frozen=True, slots=True)
class AuditActor:
    """Who acted, captured at the request boundary.

    Identity is denormalized (issuer and subject alongside the user id) so the
    ledger stays readable after a user row is removed.
    """

    user_id: UUID | None = None
    issuer: str | None = None
    subject: str | None = None
    request_id: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None


async def record_audit_event(
    session: AsyncSession,
    *,
    action: AuditAction,
    actor: AuditActor,
    tenant_id: UUID | None = None,
    outcome: AuditOutcome = AuditOutcome.ALLOWED,
    resource_type: str | None = None,
    resource_id: str | UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        tenant_id=tenant_id,
        actor_user_id=actor.user_id,
        actor_issuer=actor.issuer,
        actor_subject=actor.subject,
        action=action,
        outcome=outcome,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        request_id=actor.request_id,
        client_ip=actor.client_ip,
        user_agent=actor.user_agent,
        metadata_=metadata or {},
    )
    session.add(event)
    await session.flush()
    metrics.add(
        AUDIT_EVENTS,
        **{
            "flint_graph.audit.action": action.value,
            "flint_graph.audit.outcome": outcome.value,
        },
    )
    return event


async def list_audit_events(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    action: AuditAction | None = None,
    outcome: AuditOutcome | None = None,
    actor_user_id: UUID | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    limit: int = 100,
) -> list[AuditEvent]:
    stmt: Select[tuple[AuditEvent]] = select(AuditEvent).where(
        AuditEvent.tenant_id == tenant_id
    )
    if action is not None:
        stmt = stmt.where(AuditEvent.action == action)
    if outcome is not None:
        stmt = stmt.where(AuditEvent.outcome == outcome)
    if actor_user_id is not None:
        stmt = stmt.where(AuditEvent.actor_user_id == actor_user_id)
    if created_after is not None:
        stmt = stmt.where(AuditEvent.created_at >= created_after)
    if created_before is not None:
        stmt = stmt.where(AuditEvent.created_at < created_before)
    stmt = stmt.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit)
    return list(await session.scalars(stmt))
