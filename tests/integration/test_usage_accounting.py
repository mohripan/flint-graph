"""Provider usage is recorded per call and rolled up onto the query run.

Milestone 09 made real providers the default; without these rows a month of
traffic produces no cost figure at all.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


async def test_query_embedding_attempt_is_durable_and_payload_free(
    extraction_db_session: AsyncSession,
) -> None:
    from flint_graph.application.embeddings import (
        DeterministicEmbeddingModel,
        EmbeddingBatchRequest,
        EmbeddingInput,
    )
    from flint_graph.application.services.query_usage import (
        QueryUsageRecorder,
        list_query_provider_invocations,
    )

    session = extraction_db_session
    tenant = Tenant(name="embedding-usage")
    session.add(tenant)
    await session.flush()
    run = await _run_with_context(session, tenant)
    run_id, tenant_id = run.id, tenant.id
    await session.commit()
    recorder = QueryUsageRecorder(
        async_sessionmaker(session.bind, expire_on_commit=False),
        tenant_id=tenant_id,
        query_run_id=run_id,
    )
    request = EmbeddingBatchRequest(
        provider="deterministic",
        model="fixture-embedder",
        dimensions=4,
        inputs=[EmbeddingInput(input_id="query", text="PRIVATE QUERY")],
    )
    result = await recorder.invoke(
        lambda: DeterministicEmbeddingModel().embed_batch(request),
        operation=ProviderUsageOperation.EMBEDDING,
        provider="deterministic",
        model="fixture-embedder",
        clause_index=0,
    )
    assert len(result.embeddings) == 1
    # Rollback the caller's unrelated transaction; accounting owns its commits.
    await session.rollback()
    events = await list_query_provider_invocations(
        session,
        tenant_id=tenant_id,
        query_run_id=run_id,
    )
    assert len(events) == 1
    assert events[0].operation is ProviderUsageOperation.EMBEDDING
    assert events[0].metadata_["status"] == "completed"
    assert events[0].metadata_["usage_known"] is True
    assert events[0].metadata_["execution_attempt_id"] == str(recorder.execution_attempt_id)
    assert events[0].metadata_["clause_index"] == 0
    assert events[0].input_tokens == events[0].output_tokens == 0
    assert "PRIVATE QUERY" not in str(events[0].metadata_)
    assert "vector" not in str(events[0].metadata_)


async def test_usage_summary_distinguishes_unknown_counts_from_known_zero(
    extraction_db_session: AsyncSession,
) -> None:
    from flint_graph.application.usage import usage_from_metadata

    session = extraction_db_session
    tenant = Tenant(name="unknown-usage-summary")
    session.add(tenant)
    await session.flush()
    for provider in ("ollama", "deterministic"):
        await record_provider_usage(
            session,
            tenant_id=tenant.id,
            usage=usage_from_metadata(
                {"provider": provider, "model": "embed"}, operation=ProviderUsageOperation.EMBEDDING
            ),
            pricing={"ollama:*": {"input_per_million": 0.0}},
        )
    summary = await summarize_usage(session, tenant_id=tenant.id)
    assert summary.totals.event_count == 2
    assert summary.totals.unknown_event_count == 1
    assert summary.totals.estimated_cost_micros is None


async def test_query_usage_reconciliation_detects_missing_clauses_and_is_idempotent(
    extraction_db_session: AsyncSession,
) -> None:
    from flint_graph.application.services.query_usage import QueryUsageRecorder
    from flint_graph.domain.errors import NotFoundError

    session = extraction_db_session
    tenant = Tenant(name="embedding-completeness")
    foreign = Tenant(name="embedding-foreign")
    session.add_all([tenant, foreign])
    await session.flush()
    run = await _run_with_context(session, tenant)
    run_id, tenant_id, foreign_id = run.id, tenant.id, foreign.id
    await session.commit()
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    recorder = QueryUsageRecorder(factory, tenant_id=tenant_id, query_run_id=run_id)
    recorder.expected = {
        ProviderUsageOperation.EMBEDDING: 2,
        ProviderUsageOperation.ANSWER: 0,
        ProviderUsageOperation.FAITHFULNESS: 0,
    }

    async def embed():
        return SimpleNamespace(
            metadata={"provider": "ollama", "model": "embed", "usage": {"input_tokens": 17}}
        )

    foreign_recorder = QueryUsageRecorder(factory, tenant_id=foreign_id, query_run_id=run_id)
    with pytest.raises(NotFoundError):
        await foreign_recorder.invoke(embed, operation=ProviderUsageOperation.EMBEDDING)
    await recorder.invoke(embed, operation=ProviderUsageOperation.EMBEDDING, clause_index=0)
    await recorder.reconcile(session)
    assert run.provider_usage_complete is False
    assert run.provider_input_tokens == 17
    await recorder.reconcile(session)
    assert run.provider_input_tokens == 17
    await session.commit()
    await recorder.invoke(embed, operation=ProviderUsageOperation.EMBEDDING, clause_index=1)
    await recorder.reconcile(session)
    assert run.provider_usage_complete is True
    assert run.provider_input_tokens == 34


async def test_cancelling_in_flight_embedding_keeps_the_committed_attempt(
    extraction_db_session: AsyncSession,
) -> None:
    from flint_graph.application.services.query_usage import (
        QueryUsageRecorder,
        list_query_provider_invocations,
    )

    session = extraction_db_session
    tenant = Tenant(name="embedding-in-flight")
    session.add(tenant)
    await session.flush()
    run = await _run_with_context(session, tenant)
    run_id, tenant_id = run.id, tenant.id
    await session.commit()
    recorder = QueryUsageRecorder(
        async_sessionmaker(session.bind, expire_on_commit=False),
        tenant_id=tenant_id,
        query_run_id=run_id,
    )
    dispatched = asyncio.Event()

    async def blocked():
        dispatched.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        recorder.invoke(
            blocked,
            operation=ProviderUsageOperation.EMBEDDING,
            provider="ollama",
            model="embed",
            clause_index=0,
        )
    )
    await asyncio.wait_for(dispatched.wait(), timeout=5)
    before = await list_query_provider_invocations(
        session, tenant_id=tenant_id, query_run_id=run_id
    )
    assert len(before) == 1 and before[0].metadata_["status"] == "started"
    await session.rollback()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)
    after = await list_query_provider_invocations(session, tenant_id=tenant_id, query_run_id=run_id)
    assert len(after) == 1 and after[0].metadata_["status"] == "cancelled"
    assert after[0].metadata_["usage_known"] is False


@pytest.mark.parametrize("failure", [ConnectionError, asyncio.CancelledError])
async def test_failed_query_embedding_and_retry_remain_separate_attempts(
    extraction_db_session: AsyncSession,
    failure: type[BaseException],
) -> None:
    from flint_graph.application.services.query_usage import (
        QueryUsageRecorder,
        list_query_provider_invocations,
    )

    session = extraction_db_session
    tenant = Tenant(name="embedding-retry")
    session.add(tenant)
    await session.flush()
    run = await _run_with_context(session, tenant)
    run_id, tenant_id = run.id, tenant.id
    await session.commit()
    recorder = QueryUsageRecorder(
        async_sessionmaker(session.bind, expire_on_commit=False),
        tenant_id=tenant_id,
        query_run_id=run_id,
        pricing={"ollama:*": {"input_per_million": 1.0}},
    )

    async def failed_call():
        raise failure("PRIVATE QUERY secret-key")

    with pytest.raises(failure):
        await recorder.invoke(
            failed_call,
            operation=ProviderUsageOperation.EMBEDDING,
            provider="ollama",
            model="embed",
            clause_index=1,
        )

    async def successful_call():
        return SimpleNamespace(
            metadata={
                "provider": "ollama",
                "model": "embed",
                "usage": {"input_tokens": 7},
            }
        )

    await recorder.invoke(
        successful_call,
        operation=ProviderUsageOperation.EMBEDDING,
        provider="ollama",
        model="embed",
        clause_index=1,
    )
    events = await list_query_provider_invocations(
        session,
        tenant_id=tenant_id,
        query_run_id=run_id,
    )
    assert len(events) == 2
    by_status = {event.metadata_["status"]: event for event in events}
    status = "cancelled" if failure is asyncio.CancelledError else "failed"
    assert status in by_status
    assert by_status[status].metadata_["usage_known"] is False
    assert by_status[status].estimated_cost_micros is None
    assert by_status["completed"].input_tokens == 7
    assert by_status["completed"].estimated_cost_micros == 7
    assert len({event.id for event in events}) == 2
    assert all(event.metadata_["clause_index"] == 1 for event in events)
    assert "PRIVATE QUERY" not in str([event.metadata_ for event in events])
    await recorder.finish(
        by_status["completed"].id,
        result=None,
        status="failed",
        duration_ms=999,
    )
    await session.refresh(by_status["completed"])
    assert by_status["completed"].metadata_["status"] == "completed"
    assert by_status["completed"].input_tokens == 7


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
    assert stored.provider_cost_micros == sum(event.estimated_cost_micros or 0 for event in events)
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
    answer = next(event for event in events if event.operation is ProviderUsageOperation.ANSWER)
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
