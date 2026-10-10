"""Durable, payload-free accounting for request-bound query invocations.

Independent sessions own ledger writes. They never mutate the query run while
retrievers or generation are holding its writer transaction.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from time import monotonic
from typing import Literal, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flint_graph.application.services.query_runs import get_query_run
from flint_graph.application.services.usage import _record_usage_metrics
from flint_graph.application.usage import estimate_cost_micros, usage_from_metadata
from flint_graph.domain.enums import ProviderUsageOperation
from flint_graph.infrastructure.db.models import ProviderUsageEvent

T = TypeVar("T")
QUERY_USAGE_VERSION = "query-invocations-v1"


class QueryUsageRecorder:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        tenant_id: UUID,
        query_run_id: UUID,
        pricing: dict[str, dict[str, float]] | None = None,
        currency: str = "USD",
        identities: dict[ProviderUsageOperation, tuple[str, str]] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.tenant_id = tenant_id
        self.query_run_id = query_run_id
        self.execution_attempt_id = uuid4()
        self.pricing = pricing or {}
        self.currency = currency
        self.identities = identities or {}
        self.expected: dict[ProviderUsageOperation, int] = {
            ProviderUsageOperation.EMBEDDING: 0,
            ProviderUsageOperation.ANSWER: 1,
            ProviderUsageOperation.FAITHFULNESS: 1,
        }

    async def invoke(
        self,
        call: Callable[[], Awaitable[T]],
        *,
        operation: ProviderUsageOperation,
        provider: str | None = None,
        model: str | None = None,
        clause_index: int | None = None,
    ) -> T:
        invocation_id = uuid4()
        configured_provider, configured_model = self.identities.get(
            operation, ("unknown", "unknown")
        )
        provider, model = provider or configured_provider, model or configured_model
        async with self.session_factory() as writer:
            await get_query_run(writer, tenant_id=self.tenant_id, query_run_id=self.query_run_id)
            writer.add(
                ProviderUsageEvent(
                    id=invocation_id,
                    tenant_id=self.tenant_id,
                    query_run_id=self.query_run_id,
                    operation=operation,
                    provider=provider,
                    model=model,
                    currency=self.currency,
                    metadata_={
                        "accounting_version": QUERY_USAGE_VERSION,
                        "execution_attempt_id": str(self.execution_attempt_id),
                        "clause_index": clause_index,
                        "status": "started",
                        "usage_known": False,
                    },
                )
            )
            # Refuse to dispatch a provider when its attempt cannot be recorded.
            await writer.commit()
        started = monotonic()
        try:
            result = await call()
            await self.finish(
                invocation_id,
                result=result,
                status="completed",
                duration_ms=int((monotonic() - started) * 1000),
            )
        except (Exception, asyncio.CancelledError) as error:
            # Preserve the original failure. If the writer itself is unavailable,
            # the committed started row remains an explicit unknown attempt.
            try:
                async with asyncio.timeout(10):
                    await self.finish(
                        invocation_id,
                        result=None,
                        status="cancelled"
                        if isinstance(error, asyncio.CancelledError)
                        else "failed",
                        duration_ms=int((monotonic() - started) * 1000),
                    )
            except (Exception, asyncio.CancelledError):
                pass
            raise
        return result

    async def finish(
        self,
        invocation_id: UUID,
        *,
        result: object | None,
        status: Literal["completed", "failed", "cancelled"],
        duration_ms: int,
    ) -> None:
        async with self.session_factory() as writer:
            event = await writer.scalar(
                select(ProviderUsageEvent)
                .where(
                    ProviderUsageEvent.id == invocation_id,
                    ProviderUsageEvent.tenant_id == self.tenant_id,
                    ProviderUsageEvent.query_run_id == self.query_run_id,
                    ProviderUsageEvent.metadata_["execution_attempt_id"].as_string()
                    == str(self.execution_attempt_id),
                )
                .with_for_update()
            )
            if event is None or event.metadata_.get("status") != "started":
                return
            metadata = getattr(result, "metadata", None)
            source = dict(metadata) if isinstance(metadata, dict) else {}
            source.setdefault("provider", getattr(result, "provider", event.provider))
            source.setdefault("model", getattr(result, "model", event.model))
            usage = usage_from_metadata(
                source,
                operation=event.operation,
                duration_ms=duration_ms,
                embedded_item_count=1 if event.operation is ProviderUsageOperation.EMBEDDING else 0,
            )
            if status != "completed":
                usage = replace(usage, usage_known=False)
            event.provider, event.model = usage.provider, usage.model
            event.input_tokens, event.output_tokens = usage.input_tokens, usage.output_tokens
            event.embedded_item_count, event.duration_ms = (
                usage.embedded_item_count,
                usage.duration_ms,
            )
            event.estimated_cost_micros = estimate_cost_micros(usage, self.pricing)
            event.metadata_ = {
                **event.metadata_,
                "status": status,
                "usage_known": usage.usage_known,
            }
            await writer.commit()
        _record_usage_metrics(usage, cost_micros=event.estimated_cost_micros)

    async def reconcile(self, session: AsyncSession) -> None:
        """Replace rollups from the ledger, never add them twice on retry/replay."""
        run = await get_query_run(session, tenant_id=self.tenant_id, query_run_id=self.query_run_id)
        events = await list_query_provider_invocations(
            session,
            tenant_id=self.tenant_id,
            query_run_id=self.query_run_id,
        )
        current = [
            event
            for event in events
            if event.metadata_.get("execution_attempt_id") == str(self.execution_attempt_id)
        ]
        actual = {
            operation: sum(event.operation is operation for event in current)
            for operation in self.expected
        }
        complete = (
            actual == self.expected
            and all(
                event.metadata_.get("status") == "completed"
                and event.metadata_.get("usage_known") is True
                for event in events
            )
        )
        run.provider_input_tokens = sum(event.input_tokens for event in events)
        run.provider_output_tokens = sum(event.output_tokens for event in events)
        run.provider_duration_ms = sum(event.duration_ms for event in events)
        priced = [
            event.estimated_cost_micros
            for event in events
            if event.estimated_cost_micros is not None
        ]
        run.provider_cost_micros = sum(priced) if priced else None
        run.metadata_ = {
            **run.metadata_,
            "usage_accounting": {
                "version": QUERY_USAGE_VERSION,
                "execution_attempt_id": str(self.execution_attempt_id),
                "expected": {operation.value: count for operation, count in self.expected.items()},
                "recorded": {operation.value: count for operation, count in actual.items()},
                "unknown_event_count": sum(
                    event.metadata_.get("usage_known") is not True for event in events
                ),
                "unpriced_event_count": sum(
                    event.estimated_cost_micros is None for event in events
                ),
                "complete": complete,
            },
        }
        await session.flush()


async def list_query_provider_invocations(
    session: AsyncSession, *, tenant_id: UUID, query_run_id: UUID
) -> list[ProviderUsageEvent]:
    await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
    return list(
        await session.scalars(
            select(ProviderUsageEvent)
            .where(
                ProviderUsageEvent.tenant_id == tenant_id,
                ProviderUsageEvent.query_run_id == query_run_id,
            )
            .order_by(ProviderUsageEvent.created_at, ProviderUsageEvent.id)
        )
    )
