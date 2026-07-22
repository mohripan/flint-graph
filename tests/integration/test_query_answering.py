from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.query_orchestration import (
    AnswerGenerationRequest,
    GeneratedAnswer,
    PackedContextRecord,
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
from flint_graph.domain.enums import QueryRunStatus, RetrievalIndexScope
from flint_graph.infrastructure.db.models import QueryAnswerClaim, QueryRun, QueryRunEvent, Tenant


class DraftAnswerGenerator:
    async def generate(self, request: AnswerGenerationRequest) -> GeneratedAnswer:
        return GeneratedAnswer(
            text="raw draft",
            metadata={
                "draft_claims": [
                    {
                        "claim_index": 0,
                        "text": "Acme Corporation is headquartered in Berlin.",
                        "raw_citation_markers": ["C1", "c9"],
                    }
                ]
            },
        )


class StreamingDraftAnswerGenerator(DraftAnswerGenerator):
    async def stream_generate(
        self,
        request: AnswerGenerationRequest,
        on_delta: Any,
    ) -> GeneratedAnswer:
        await on_delta("Acme Corporation ")
        await on_delta("is headquartered in Berlin.")
        return await self.generate(request)


class UnsupportedDraftAnswerGenerator:
    async def generate(self, request: AnswerGenerationRequest) -> GeneratedAnswer:
        return GeneratedAnswer(
            text="raw draft",
            metadata={
                "draft_claims": [
                    {
                        "claim_index": 0,
                        "text": "Quarterly revenue doubled in Singapore.",
                        "raw_citation_markers": ["c1"],
                    }
                ]
            },
        )


async def test_generate_query_answer_persists_verified_answer_and_citations(
    db_session: AsyncSession,
) -> None:
    tenant = Tenant(name="query-answering")
    db_session.add(tenant)
    await db_session.flush()
    index_id = await _active_index_id(db_session, tenant.id)
    run = await create_query_run(
        db_session,
        QueryRunCreate(
            tenant_id=tenant.id,
            query_text="Where is Acme Corporation headquartered?",
            retrieval_index_version_id=index_id,
        ),
    )
    run.status = QueryRunStatus.RUNNING
    await persist_query_context_pack(
        db_session,
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

    result = await generate_query_answer(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run.id,
        generator=DraftAnswerGenerator(),
    )

    stored_run = await db_session.scalar(select(QueryRun).where(QueryRun.id == run.id))
    claims = list(
        await db_session.scalars(
            select(QueryAnswerClaim)
            .where(QueryAnswerClaim.query_run_id == run.id)
            .order_by(QueryAnswerClaim.claim_index)
        )
    )
    events = list(
        await db_session.scalars(
            select(QueryRunEvent)
            .where(QueryRunEvent.query_run_id == run.id)
            .order_by(QueryRunEvent.sequence)
        )
    )
    assert result.status == QueryRunStatus.COMPLETED
    assert result.answer_text == "Acme Corporation is headquartered in Berlin. [c1]"
    assert result.answer_citation_count == 1
    assert stored_run is not None
    assert stored_run.answer_text == "Acme Corporation is headquartered in Berlin. [c1]"
    assert stored_run.abstained is False
    assert stored_run.abstain_reason is None
    assert stored_run.supported_claim_count == 1
    assert stored_run.unsupported_claim_count == 0
    assert stored_run.support_method == "deterministic-lexical"
    assert stored_run.answer_provider == "unknown"
    assert stored_run.answer_citations == [
        {
            "citation_id": "c1",
            "context_id": "ctx-0001",
            "marker": "[c1]",
            "source_ids": {"chunk_id": "chunk-acme"},
        }
    ]
    assert len(claims) == 1
    assert claims[0].tenant_id == tenant.id
    assert claims[0].claim_index == 0
    assert claims[0].text == "Acme Corporation is headquartered in Berlin."
    assert claims[0].citation_ids == ["c1"]
    assert claims[0].support_status == "supported"
    assert claims[0].support_score == 1.0
    assert claims[0].method == "deterministic-lexical"
    assert [event.event_type for event in events[-5:]] == [
        "answer.delta",
        "answer.citation",
        "support.checked",
        "answer.finalized",
        "query.completed",
    ]
    assert events[-5].payload["provisional"] is False
    assert events[-3].payload == {
        "supported_claim_count": 1,
        "unsupported_claim_count": 0,
        "support_method": "deterministic-lexical",
        "abstained": False,
    }
    assert events[-2].payload["answer_text"] == stored_run.answer_text
    assert events[-2].payload["answer_citations"] == stored_run.answer_citations
    assert events[-1].payload["faithfulness"]["supported_claim_count"] == 1


async def test_generate_query_answer_records_provisional_streaming_deltas(
    db_session: AsyncSession,
) -> None:
    tenant = Tenant(name="query-answering-streaming")
    db_session.add(tenant)
    await db_session.flush()
    index_id = await _active_index_id(db_session, tenant.id)
    run = await create_query_run(
        db_session,
        QueryRunCreate(
            tenant_id=tenant.id,
            query_text="Where is Acme Corporation headquartered?",
            retrieval_index_version_id=index_id,
        ),
    )
    run.status = QueryRunStatus.RUNNING
    await persist_query_context_pack(
        db_session,
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

    await generate_query_answer(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run.id,
        generator=StreamingDraftAnswerGenerator(),
    )

    events = list(
        await db_session.scalars(
            select(QueryRunEvent)
            .where(QueryRunEvent.query_run_id == run.id)
            .order_by(QueryRunEvent.sequence)
        )
    )
    answer_deltas = [event for event in events if event.event_type == "answer.delta"]
    assert [event.payload["text"] for event in answer_deltas] == [
        "Acme Corporation ",
        "is headquartered in Berlin.",
        "Acme Corporation is headquartered in Berlin. [c1]",
    ]
    assert [event.payload["provisional"] for event in answer_deltas] == [
        True,
        True,
        False,
    ]
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))


async def test_generate_query_answer_emits_abstention_and_finalized_events(
    db_session: AsyncSession,
) -> None:
    tenant = Tenant(name="query-answering-abstention")
    db_session.add(tenant)
    await db_session.flush()
    index_id = await _active_index_id(db_session, tenant.id)
    run = await create_query_run(
        db_session,
        QueryRunCreate(
            tenant_id=tenant.id,
            query_text="Where is Acme Corporation headquartered?",
            retrieval_index_version_id=index_id,
        ),
    )
    run.status = QueryRunStatus.RUNNING
    await persist_query_context_pack(
        db_session,
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

    result = await generate_query_answer(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run.id,
        generator=UnsupportedDraftAnswerGenerator(),
    )

    stored_run = await db_session.scalar(select(QueryRun).where(QueryRun.id == run.id))
    events = list(
        await db_session.scalars(
            select(QueryRunEvent)
            .where(QueryRunEvent.query_run_id == run.id)
            .order_by(QueryRunEvent.sequence)
        )
    )
    assert result.status == QueryRunStatus.COMPLETED
    assert result.insufficient_context is True
    assert stored_run is not None
    assert stored_run.abstained is True
    assert stored_run.answer_citations == []
    assert [event.event_type for event in events[-5:]] == [
        "answer.delta",
        "support.checked",
        "answer.abstained",
        "answer.finalized",
        "query.completed",
    ]
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert events[-3].payload["reason"] == stored_run.abstain_reason
    assert events[-2].payload["answer_text"] == stored_run.answer_text
    assert events[-2].payload["answer_citations"] == []


async def _active_index_id(session: AsyncSession, tenant_id: UUID) -> UUID:
    version = await create_retrieval_index_version(
        session,
        scope=RetrievalIndexScope.TENANT,
        tenant_id=tenant_id,
        spec=RetrievalIndexVersionSpec(
            embedding_provider="deterministic",
            embedding_model="query-answering",
            vector_dimension=4,
            embedding_config_hash="sha256:query-answering",
            chunking_schema_version="1",
            chunking_config_hash="sha256:chunking",
            lexical_schema_version="1",
            neo4j_vector_index_name="flint_graph_chunks_query_answering",
            neo4j_vector_property_name="embedding",
            opensearch_index_name="flint_graph_chunks_query_answering",
            opensearch_alias_name="flint_graph_chunks_active",
        ),
    )
    active = await activate_retrieval_index_version(session, version_id=version.id)
    return active.id
