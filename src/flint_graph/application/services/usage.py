"""Persistence and aggregation for provider usage.

Adapters never write to the database; they report usage and this service records
it. Recording also rolls the totals onto the owning query run so query history
stays a single-row read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Select, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.usage import ProviderUsage, estimate_cost_micros
from flint_graph.infrastructure.db.models import ProviderUsageEvent, QueryRun
from flint_graph.observability import metrics
from flint_graph.observability.instruments import PROVIDER_TOKENS, UNPRICED_USAGE_EVENTS

UsageGroupBy = Literal["day", "operation", "model"]


@dataclass(frozen=True, slots=True)
class UsageRollupRow:
    group: str
    event_count: int
    input_tokens: int
    output_tokens: int
    embedded_item_count: int
    duration_ms: int
    estimated_cost_micros: int | None
    unpriced_event_count: int
    unknown_event_count: int = 0


@dataclass(frozen=True, slots=True)
class UsageSummary:
    currency: str
    group_by: UsageGroupBy
    rows: tuple[UsageRollupRow, ...]
    totals: UsageRollupRow


async def record_provider_usage(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    usage: ProviderUsage,
    pricing: dict[str, dict[str, float]],
    currency: str = "USD",
    query_run_id: UUID | None = None,
    ingestion_job_id: UUID | None = None,
    document_version_id: UUID | None = None,
    request_id: str | None = None,
    workflow_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ProviderUsageEvent:
    cost_micros = estimate_cost_micros(usage, pricing)
    event = ProviderUsageEvent(
        tenant_id=tenant_id,
        operation=usage.operation,
        provider=usage.provider,
        model=usage.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        embedded_item_count=usage.embedded_item_count,
        duration_ms=usage.duration_ms,
        estimated_cost_micros=cost_micros,
        currency=currency,
        query_run_id=query_run_id,
        ingestion_job_id=ingestion_job_id,
        document_version_id=document_version_id,
        request_id=request_id,
        workflow_id=workflow_id,
        metadata_={**usage.metadata, **(metadata or {}), "usage_known": usage.usage_known},
    )
    session.add(event)
    await session.flush()

    _record_usage_metrics(usage, cost_micros=cost_micros)
    if query_run_id is not None:
        await _roll_up_query_run(
            session,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
            usage=usage,
            cost_micros=cost_micros,
        )
    return event


def _record_usage_metrics(usage: ProviderUsage, *, cost_micros: int | None) -> None:
    for direction, tokens in (
        ("input", usage.input_tokens),
        ("output", usage.output_tokens),
    ):
        if tokens:
            metrics.add(
                PROVIDER_TOKENS,
                tokens,
                **{
                    "flint_graph.provider": usage.provider,
                    "flint_graph.model": usage.model,
                    "flint_graph.operation": usage.operation.value,
                    "flint_graph.token.direction": direction,
                },
            )
    if cost_micros is None and (not usage.usage_known or usage.input_tokens or usage.output_tokens):
        # Only tokens that could have been priced count as unpriced. A
        # deterministic provider burning zero tokens is not a pricing gap.
        metrics.add(
            UNPRICED_USAGE_EVENTS,
            **{
                "flint_graph.provider": usage.provider,
                "flint_graph.model": usage.model,
            },
        )


async def _roll_up_query_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    usage: ProviderUsage,
    cost_micros: int | None,
) -> None:
    run = await session.scalar(
        select(QueryRun).where(
            QueryRun.id == query_run_id,
            QueryRun.tenant_id == tenant_id,
        )
    )
    if run is None:
        return
    run.provider_input_tokens += usage.input_tokens
    run.provider_output_tokens += usage.output_tokens
    run.provider_duration_ms += usage.duration_ms
    if cost_micros is not None:
        run.provider_cost_micros = (run.provider_cost_micros or 0) + cost_micros
    await session.flush()


async def summarize_usage(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    group_by: UsageGroupBy = "day",
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    currency: str = "USD",
) -> UsageSummary:
    group_column = _group_column(group_by)
    stmt: Select[Any] = select(
        group_column.label("group"),
        func.count(ProviderUsageEvent.id).label("event_count"),
        func.coalesce(func.sum(ProviderUsageEvent.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(ProviderUsageEvent.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(ProviderUsageEvent.embedded_item_count), 0).label(
            "embedded_item_count"
        ),
        func.coalesce(func.sum(ProviderUsageEvent.duration_ms), 0).label("duration_ms"),
        func.sum(ProviderUsageEvent.estimated_cost_micros).label("estimated_cost_micros"),
        func.count(ProviderUsageEvent.id)
        .filter(ProviderUsageEvent.estimated_cost_micros.is_(None))
        .label("unpriced_event_count"),
        func.count(ProviderUsageEvent.id)
        .filter(ProviderUsageEvent.metadata_["usage_known"].as_boolean().is_not(True))
        .label("unknown_event_count"),
    ).where(ProviderUsageEvent.tenant_id == tenant_id)
    if created_after is not None:
        stmt = stmt.where(ProviderUsageEvent.created_at >= created_after)
    if created_before is not None:
        stmt = stmt.where(ProviderUsageEvent.created_at < created_before)
    stmt = stmt.group_by(group_column).order_by(group_column)

    rows = tuple(
        UsageRollupRow(
            group=str(row.group),
            event_count=int(row.event_count),
            input_tokens=int(row.input_tokens),
            output_tokens=int(row.output_tokens),
            embedded_item_count=int(row.embedded_item_count),
            duration_ms=int(row.duration_ms),
            estimated_cost_micros=(
                int(row.estimated_cost_micros) if row.estimated_cost_micros is not None else None
            ),
            unpriced_event_count=int(row.unpriced_event_count),
            unknown_event_count=int(row.unknown_event_count),
        )
        for row in (await session.execute(stmt)).all()
    )
    return UsageSummary(
        currency=currency,
        group_by=group_by,
        rows=rows,
        totals=_totals(rows),
    )


def _group_column(group_by: UsageGroupBy) -> Any:
    match group_by:
        case "day":
            # Truncating a stringified timestamp keeps the group key identical on
            # PostgreSQL and SQLite, which their date functions do not.
            return func.substr(func.cast(ProviderUsageEvent.created_at, String), 1, 10)
        case "operation":
            return ProviderUsageEvent.operation
        case "model":
            return ProviderUsageEvent.model


def _totals(rows: tuple[UsageRollupRow, ...]) -> UsageRollupRow:
    priced = [row.estimated_cost_micros for row in rows if row.estimated_cost_micros is not None]
    return UsageRollupRow(
        group="total",
        event_count=sum(row.event_count for row in rows),
        input_tokens=sum(row.input_tokens for row in rows),
        output_tokens=sum(row.output_tokens for row in rows),
        embedded_item_count=sum(row.embedded_item_count for row in rows),
        duration_ms=sum(row.duration_ms for row in rows),
        estimated_cost_micros=sum(priced) if priced else None,
        unpriced_event_count=sum(row.unpriced_event_count for row in rows),
        unknown_event_count=sum(row.unknown_event_count for row in rows),
    )
