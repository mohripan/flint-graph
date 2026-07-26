"""Provider usage is recorded per call and rolled up onto the query run.

Milestone 09 made real providers the default; without these rows a month of
traffic produces no cost figure at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.query_orchestration import (
    AnswerGenerationRequest,
    GeneratedAnswer,
    PackedContextRecord,
    SupportCheckRequest,
    SupportCheckResult,
)
from flint_graph.application.query_orchestration import (
    QueryContextPack as ApplicationQueryContextPack,
)
from flint_graph.application.services.query_answering import generate_query_answer
from flint_graph.application.services.query_runs import (
    QueryRunCreate,
    create_query_run,
    persist_query_context_pack,
)
from flint_graph.application.services.retrieval_index_versions import (
    RetrievalIndexVersionSpec,
    activate_retrieval_index_version,
    create_retrieval_index_version,
)
from flint_graph.application.services.usage import record_provider_usage, summarize_usage
from flint_graph.application.usage import ProviderUsage
from flint_graph.domain.enums import (
    ProviderUsageOperation,
    QueryRunStatus,
    RetrievalIndexScope,
)
from flint_graph.infrastructure.db.models import ProviderUsageEvent, QueryRun, Tenant

_PRICING = {
    "anthropic:claude-opus-4-8": {
        "input_per_million": 15.0,
        "output_per_million": 75.0,
    }
}


class PricedAnswerGenerator:
    """Stands in for a real provider adapter, reporting the same usage shape."""

    async def generate(self, request: AnswerGenerationRequest) -> GeneratedAnswer:
        return GeneratedAnswer(
            text="raw draft",
            metadata={
                "provider": "anthropic",
                "model": "claude-opus-4-8",
                "usage": {
                    "input_tokens": 2_000,
                    "output_tokens": 400,
                    "duration_ms": 1_234,
                },
                "draft_claims": [
                    {
                        "claim_index": 0,
                        "text": "Acme Corporation is headquartered in Berlin.",
                        "raw_citation_markers": ["c1"],
                    }
                ],
            },
        )


class PricedSupportChecker:
    async def check(self, request: SupportCheckRequest) -> SupportCheckResult:
        from flint_graph.application.query_orchestration import AnswerClaim

        return SupportCheckResult(
            claims=[
                AnswerClaim(
                    claim_index=claim.claim_index,
                    text=claim.text,
                    citation_ids=claim.citation_ids,
                    support_status="supported",
                    support_score=1.0,
                    support_reason="cited context entails the claim",
                    method="test-entailment",
                )
                for claim in request.claims
            ],
            method="test-entailment",
            metadata={
                "provider": "anthropic",
                "model": "claude-opus-4-8",
                "usage": {"input_tokens": 500, "output_tokens": 50, "duration_ms": 300},
            },
        )


class UnpricedAnswerGenerator:
    async def generate(self, request: AnswerGenerationRequest) -> GeneratedAnswer:
        return GeneratedAnswer(
            text="raw draft",
            metadata={
                "provider": "anthropic",
                "model": "model-with-no-configured-price",
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "draft_claims": [
                    {
                        "claim_index": 0,
                        "text": "Acme Corporation is headquartered in Berlin.",
                        "raw_citation_markers": ["c1"],
                    }
                ],
            },
        )


async def _active_index_id(session: AsyncSession, tenant_id: UUID) -> UUID:
    version = await create_retrieval_index_version(
        session,
        scope=RetrievalIndexScope.TENANT,
        tenant_id=tenant_id,
        spec=RetrievalIndexVersionSpec(
            embedding_provider="deterministic",
            embedding_model="usage-accounting",
            vector_dimension=4,
            embedding_config_hash="sha256:usage-accounting",
            chunking_schema_version="1",
            chunking_config_hash="sha256:chunking",
            lexical_schema_version="1",
            neo4j_vector_index_name="flint_graph_chunks_usage_accounting",
            neo4j_vector_property_name="embedding",
            opensearch_index_name="flint_graph_chunks_usage_accounting",
            opensearch_alias_name="flint_graph_chunks_active",
        ),
    )
    active = await activate_retrieval_index_version(session, version_id=version.id)
    return active.id


async def _run_with_context(session: AsyncSession, tenant: Tenant):
    index_id = await _active_index_id(session, tenant.id)
    run = await create_query_run(
        session,
        QueryRunCreate(
            tenant_id=tenant.id,
            query_text="Where is Acme Corporation headquartered?",
            retrieval_index_version_id=index_id,
        ),
    )
    run.status = QueryRunStatus.RUNNING
    await persist_query_context_pack(
        session,
        tenant_id=tenant.id,
        query_run_id=run.id,
        context_pack=ApplicationQueryContextPack(
            pack_id="pack-1",
            token_budget=100,
            records=[
                PackedContextRecord(
                    context_id="ctx-0001",
                    candidate_id="lexical:chunk:chunk-acme",
                    citation_id="c1",
                    text="Acme Corporation is headquartered in Berlin.",
                    token_count=6,
                    source_ids={"chunk_id": "chunk-acme"},
                )
            ],
        ),
    )
    return run


async def _usage_events(session: AsyncSession, run_id) -> list[ProviderUsageEvent]:
    return list(
        await session.scalars(
            select(ProviderUsageEvent)
            .where(ProviderUsageEvent.query_run_id == run_id)
            .order_by(ProviderUsageEvent.operation)
        )
    )


async def test_answer_and_support_usage_are_recorded_separately(
    db_session: AsyncSession,
) -> None:
    tenant = Tenant(name="usage-answer")
    db_session.add(tenant)
    await db_session.flush()
    run = await _run_with_context(db_session, tenant)

    result = await generate_query_answer(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run.id,
        generator=PricedAnswerGenerator(),
        support_checker=PricedSupportChecker(),
        usage_pricing=_PRICING,
    )
    assert result.status == QueryRunStatus.COMPLETED

    events = await _usage_events(db_session, run.id)
    by_operation = {event.operation: event for event in events}

    assert set(by_operation) == {
        ProviderUsageOperation.ANSWER,
        ProviderUsageOperation.FAITHFULNESS,
    }
    answer = by_operation[ProviderUsageOperation.ANSWER]
    assert answer.provider == "anthropic"
    assert answer.model == "claude-opus-4-8"
    assert answer.input_tokens == 2_000
    assert answer.output_tokens == 400
    assert answer.duration_ms == 1_234
    # 2000 input at $15/M + 400 output at $75/M = $0.06 = 60_000 micros.
    assert answer.estimated_cost_micros == 60_000

    support = by_operation[ProviderUsageOperation.FAITHFULNESS]
    assert support.input_tokens == 500
    assert support.estimated_cost_micros == 11_250


async def test_query_run_rollups_match_the_underlying_usage_rows(
    db_session: AsyncSession,
) -> None:
    tenant = Tenant(name="usage-rollup")
    db_session.add(tenant)
    await db_session.flush()
    run = await _run_with_context(db_session, tenant)

    await generate_query_answer(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run.id,
        generator=PricedAnswerGenerator(),
        support_checker=PricedSupportChecker(),
        usage_pricing=_PRICING,
    )

    events = await _usage_events(db_session, run.id)
    stored = await db_session.scalar(select(QueryRun).where(QueryRun.id == run.id))
    assert stored is not None

    assert stored.provider_input_tokens == sum(event.input_tokens for event in events)
    assert stored.provider_output_tokens == sum(event.output_tokens for event in events)
    assert stored.provider_duration_ms == sum(event.duration_ms for event in events)
    assert stored.provider_cost_micros == sum(
        event.estimated_cost_micros or 0 for event in events
    )
    # The packing estimate is a different number and must not be conflated.
    assert stored.context_token_count != stored.provider_input_tokens


async def test_deterministic_offline_run_still_records_usage(
    db_session: AsyncSession,
) -> None:
    """Offline default paths must exercise accounting, not bypass it."""
    tenant = Tenant(name="usage-deterministic")
    db_session.add(tenant)
    await db_session.flush()
    run = await _run_with_context(db_session, tenant)

    await generate_query_answer(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run.id,
    )

    events = await _usage_events(db_session, run.id)
    answer = next(
        event for event in events if event.operation is ProviderUsageOperation.ANSWER
    )
    assert answer.provider == "deterministic"
    assert answer.input_tokens == 0
    assert answer.estimated_cost_micros is None


async def test_missing_pricing_degrades_to_null_cost_without_failing_the_run(
    db_session: AsyncSession,
) -> None:
    tenant = Tenant(name="usage-unpriced")
    db_session.add(tenant)
    await db_session.flush()
    run = await _run_with_context(db_session, tenant)

    result = await generate_query_answer(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run.id,
        generator=UnpricedAnswerGenerator(),
        usage_pricing=_PRICING,
    )

    assert result.status == QueryRunStatus.COMPLETED
    answer = next(
        event
        for event in await _usage_events(db_session, run.id)
        if event.operation is ProviderUsageOperation.ANSWER
    )
    assert answer.input_tokens == 10
    assert answer.estimated_cost_micros is None
    stored = await db_session.scalar(select(QueryRun).where(QueryRun.id == run.id))
    assert stored is not None
    assert stored.provider_cost_micros is None


async def test_usage_summary_aggregates_match_row_sums_and_stay_workspace_scoped(
    db_session: AsyncSession,
) -> None:
    first = Tenant(name="usage-summary-a")
    second = Tenant(name="usage-summary-b")
    db_session.add_all([first, second])
    await db_session.flush()

    for tokens in (100, 250):
        await record_provider_usage(
            db_session,
            tenant_id=first.id,
            usage=ProviderUsage(
                operation=ProviderUsageOperation.ANSWER,
                provider="anthropic",
                model="claude-opus-4-8",
                input_tokens=tokens,
                output_tokens=10,
                duration_ms=5,
            ),
            pricing=_PRICING,
        )
    await record_provider_usage(
        db_session,
        tenant_id=first.id,
        usage=ProviderUsage(
            operation=ProviderUsageOperation.EMBEDDING,
            provider="ollama",
            model="nomic-embed-text",
            input_tokens=40,
            embedded_item_count=4,
        ),
        pricing=_PRICING,
    )
    await record_provider_usage(
        db_session,
        tenant_id=second.id,
        usage=ProviderUsage(
            operation=ProviderUsageOperation.ANSWER,
            provider="anthropic",
            model="claude-opus-4-8",
            input_tokens=999_999,
            output_tokens=999_999,
        ),
        pricing=_PRICING,
    )

    summary = await summarize_usage(
        db_session,
        tenant_id=first.id,
        group_by="operation",
    )

    rows = {row.group: row for row in summary.rows}
    assert set(rows) == {
        ProviderUsageOperation.ANSWER.value,
        ProviderUsageOperation.EMBEDDING.value,
    }
    assert rows[ProviderUsageOperation.ANSWER.value].input_tokens == 350
    assert rows[ProviderUsageOperation.ANSWER.value].event_count == 2
    assert rows[ProviderUsageOperation.EMBEDDING.value].embedded_item_count == 4
    # Unpriced rows are counted, not silently folded into a total that looks complete.
    assert rows[ProviderUsageOperation.EMBEDDING.value].unpriced_event_count == 1
    assert summary.totals.input_tokens == 390
    assert summary.totals.estimated_cost_micros == sum(
        row.estimated_cost_micros or 0 for row in summary.rows
    )
    # The other workspace's very large usage is absent.
    assert summary.totals.input_tokens < 999_999


async def test_usage_summary_respects_the_requested_time_window(
    db_session: AsyncSession,
) -> None:
    tenant = Tenant(name="usage-window")
    db_session.add(tenant)
    await db_session.flush()

    event = await record_provider_usage(
        db_session,
        tenant_id=tenant.id,
        usage=ProviderUsage(
            operation=ProviderUsageOperation.ANSWER,
            provider="anthropic",
            model="claude-opus-4-8",
            input_tokens=100,
        ),
        pricing=_PRICING,
    )
    event.created_at = datetime.now(UTC) - timedelta(days=3)
    await db_session.flush()

    recent = await summarize_usage(
        db_session,
        tenant_id=tenant.id,
        created_after=datetime.now(UTC) - timedelta(days=1),
    )
    everything = await summarize_usage(db_session, tenant_id=tenant.id)

    assert recent.totals.event_count == 0
    assert everything.totals.event_count == 1
