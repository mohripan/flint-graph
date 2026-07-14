from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.query_orchestration import (
    AnswerGenerationRequest,
    GeneratedAnswer,
    PackedContextRecord,
)
from atlas_rag.application.query_orchestration import (
    QueryContextPack as ApplicationQueryContextPack,
)
from atlas_rag.application.services.query_answering import generate_query_answer
from atlas_rag.application.services.query_runs import (
    QueryRunCreate,
    create_query_run,
    persist_query_context_pack,
)
from atlas_rag.application.services.retrieval_index_versions import (
    RetrievalIndexVersionSpec,
    activate_retrieval_index_version,
    create_retrieval_index_version,
)
from atlas_rag.domain.enums import QueryRunStatus, RetrievalIndexScope
from atlas_rag.infrastructure.db.models import QueryRun, QueryRunEvent, Tenant


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
    assert stored_run.answer_citations == [
        {
            "citation_id": "c1",
            "context_id": "ctx-0001",
            "marker": "[c1]",
            "source_ids": {"chunk_id": "chunk-acme"},
        }
    ]
    assert events[-2].event_type == "answer.citation"
    assert events[-1].event_type == "query.completed"
    assert events[-1].payload["faithfulness"]["supported_claim_count"] == 1


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
            neo4j_vector_index_name="atlas_chunks_query_answering",
            neo4j_vector_property_name="embedding",
            opensearch_index_name="atlas_chunks_query_answering",
            opensearch_alias_name="atlas_chunks_active",
        ),
    )
    active = await activate_retrieval_index_version(session, version_id=version.id)
    return active.id
