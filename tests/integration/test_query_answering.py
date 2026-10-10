from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.query_orchestration import (
    AnswerClaim,
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
from flint_graph.application.services.query_scope import financial_scope_clarification
from flint_graph.application.services.retrieval_index_versions import (
    RetrievalIndexVersionSpec,
    activate_retrieval_index_version,
    create_retrieval_index_version,
)
from flint_graph.domain.enums import (
    DocumentIndexCoverageStatus,
    DocumentVersionStatus,
    QueryRunStatus,
    RetrievalIndexScope,
    SourceType,
)
from flint_graph.infrastructure.db.models import (
    Document,
    DocumentIndexCoverage,
    DocumentVersion,
    ProviderUsageEvent,
    QueryAnswerClaim,
    QueryRun,
    QueryRunEvent,
    Tenant,
)


@pytest.mark.parametrize("query", ["What was revenue?", "What was revenue in 2019?"])
async def test_ambiguous_financial_query_clarifies_without_model_calls(
    extraction_db_session: AsyncSession,
    query: str,
) -> None:
    session = extraction_db_session
    tenant = Tenant(name="Ambiguous financial scope")
    session.add(tenant)
    await session.flush()
    index_id = await _active_index_id(session, tenant.id)
    for number in range(2):
        document = Document(
            tenant_id=tenant.id, title=f"Synthetic report {number}", source_type=SourceType.UPLOAD
        )
        session.add(document)
        await session.flush()
        version = DocumentVersion(
            document_id=document.id, version_number=1, status=DocumentVersionStatus.ACTIVE
        )
        session.add(version)
        await session.flush()
        session.add(
            DocumentIndexCoverage(
                tenant_id=tenant.id,
                document_id=document.id,
                document_version_id=version.id,
                retrieval_index_version_id=index_id,
                status=DocumentIndexCoverageStatus.COMPLETED,
            )
        )
    run = await create_query_run(
        session,
        QueryRunCreate(tenant_id=tenant.id, query_text=query, retrieval_index_version_id=index_id),
    )
    run.status = QueryRunStatus.RUNNING
    await persist_query_context_pack(
        session,
        tenant_id=tenant.id,
        query_run_id=run.id,
        context_pack=ApplicationQueryContextPack(
            pack_id="ambiguous-pack",
            token_budget=100,
            records=[
                PackedContextRecord(
                    context_id="ctx-1",
                    candidate_id="lexical:chunk:1",
                    citation_id="c1",
                    text="Synthetic revenue was 123.",
                    token_count=5,
                    source_ids={"chunk_id": "1"},
                )
            ],
        ),
    )

    class ForbiddenGenerator:
        async def generate(self, request: AnswerGenerationRequest) -> GeneratedAnswer:
            raise AssertionError("Ambiguous query must not invoke the answer model")

    class ForbiddenChecker:
        async def check(self, request):
            raise AssertionError("Clarification must not invoke the support model")

    result = await generate_query_answer(
        session,
        tenant_id=tenant.id,
        query_run_id=run.id,
        generator=ForbiddenGenerator(),
        support_checker=ForbiddenChecker(),
    )
    await session.commit()
    assert result.status == QueryRunStatus.COMPLETED
    assert result.insufficient_context is True
    assert "Which company or document" in (result.answer_text or "")
    assert run.abstained is True and run.abstain_reason == "ambiguous_financial_scope"
    assert run.answer_provider == "scope-policy" and run.support_method == "scope-policy"
    assert run.answer_citations == []
    assert run.supported_claim_count == run.unsupported_claim_count == 0
    assert not list(
        await session.scalars(
            select(QueryAnswerClaim).where(QueryAnswerClaim.query_run_id == run.id)
        )
    )
    assert not list(
        await session.scalars(
            select(ProviderUsageEvent).where(ProviderUsageEvent.query_run_id == run.id)
        )
    )
    events = list(
        await session.scalars(
            select(QueryRunEvent)
            .where(QueryRunEvent.query_run_id == run.id)
            .order_by(QueryRunEvent.sequence)
        )
    )
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert any(event.event_type == "query.clarification_required" for event in events)
    assert not any(event.payload.get("provisional") for event in events)
    assert events[-1].event_type == "query.completed"


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


@pytest.mark.parametrize(
    "case,expected",
    [
        ("two_current", True),
        ("one_current", False),
        ("foreign_tenant", False),
        ("deleted", False),
        ("superseded", False),
        ("failed_coverage", False),
        ("other_index", False),
        ("same_document", False),
        ("document_filter", False),
        ("version_filter", False),
        ("malformed_filter", True),
    ],
)
async def test_financial_scope_uses_authorized_current_distinct_documents(
    extraction_db_session: AsyncSession,
    case: str,
    expected: bool,
) -> None:
    from datetime import UTC, datetime

    session = extraction_db_session
    tenant = Tenant(name="Scope ownership")
    other = Tenant(name="Foreign scope")
    session.add_all([tenant, other])
    await session.flush()
    index_id = await _active_index_id(session, tenant.id)
    other_index_id = await _active_index_id(session, other.id)
    first_id = None
    first_version_id = None
    for number in range(2):
        owner = other.id if number and case == "foreign_tenant" else tenant.id
        if number and case == "same_document":
            document = await session.get(Document, first_id)
            assert document is not None
        else:
            document = Document(
                tenant_id=owner, title="Synthetic scope", source_type=SourceType.UPLOAD
            )
            if number and case == "deleted":
                document.deleted_at = datetime.now(UTC)
            session.add(document)
            await session.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_number=number + 1,
            status=DocumentVersionStatus.SUPERSEDED
            if number and case == "superseded"
            else DocumentVersionStatus.ACTIVE,
        )
        session.add(version)
        await session.flush()
        if not number:
            first_id, first_version_id = document.id, version.id
        if number and case == "one_current":
            continue
        session.add(
            DocumentIndexCoverage(
                tenant_id=owner,
                document_id=document.id,
                document_version_id=version.id,
                retrieval_index_version_id=other_index_id
                if number and case == "other_index"
                else index_id,
                status=DocumentIndexCoverageStatus.FAILED
                if number and case == "failed_coverage"
                else DocumentIndexCoverageStatus.COMPLETED,
            )
        )
    await session.flush()
    filters = {}
    if case == "document_filter":
        filters = {"document_id": str(first_id)}
    elif case == "version_filter":
        filters = {"document_version_id": str(first_version_id)}
    elif case == "malformed_filter":
        filters = {"document_id": "not-a-uuid"}
    result = await financial_scope_clarification(
        session,
        tenant_id=tenant.id,
        retrieval_index_version_id=index_id,
        query="What was revenue?",
        filters=filters,
    )
    assert (result is not None) is expected
    # Foreign/missing selectors never expand scope into another tenant's sources.
    foreign = await financial_scope_clarification(
        session,
        tenant_id=tenant.id,
        retrieval_index_version_id=index_id,
        query="What was revenue?",
        filters={"document_id": str(uuid4())},
    )
    assert foreign is None


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


@pytest.mark.parametrize("result_amount,abstained", [("127400", True), ("127.4", False)])
async def test_arithmetic_audit_and_original_claim_survive_authorized_persistence(
    extraction_db_session: AsyncSession,
    result_amount: str,
    abstained: bool,
) -> None:
    session = extraction_db_session
    tenant = Tenant(name="Arithmetic audit")
    session.add(tenant)
    await session.flush()
    index_id = await _active_index_id(session, tenant.id)
    document = Document(
        tenant_id=tenant.id, title="Synthetic payments", source_type=SourceType.UPLOAD
    )
    session.add(document)
    await session.flush()
    version = DocumentVersion(
        document_id=document.id, version_number=1, status=DocumentVersionStatus.ACTIVE
    )
    session.add(version)
    await session.flush()
    table = (
        "| company | payments volume (billions) | total transactions (billions) |\n"
        "| --- | --- | --- |\n| Example Payments | 637 | 5.0 |"
    )
    text = f"Example Payments's average payments volume per transaction was ${result_amount}."
    source_ids = {
        "document_id": str(document.id),
        "document_version_id": str(version.id),
        "chunk_id": "table-chunk",
    }
    run = await create_query_run(
        session,
        QueryRunCreate(
            tenant_id=tenant.id,
            query_text="What was Example Payments's average payments volume "
            "per transaction in dollars?",
            retrieval_index_version_id=index_id,
        ),
    )
    run.status = QueryRunStatus.RUNNING
    await persist_query_context_pack(
        session,
        tenant_id=tenant.id,
        query_run_id=run.id,
        context_pack=ApplicationQueryContextPack(
            pack_id="arithmetic",
            token_budget=300,
            records=[
                PackedContextRecord(
                    context_id="ctx-0001",
                    candidate_id="table",
                    citation_id="c1",
                    text=table,
                    token_count=100,
                    source_ids=source_ids,
                    metadata={
                        "evidence_origin": "postgresql_chunk",
                        "chunk_hash": "sha256:" + hashlib.sha256(table.encode()).hexdigest(),
                    },
                )
            ],
        ),
    )

    class Generator:
        async def generate(self, request: AnswerGenerationRequest) -> GeneratedAnswer:
            hint = request.policy["verified_calculation"]
            assert hint["computed_value"] == "127.4"
            assert hint["citation_id"] == "c1"
            return GeneratedAnswer(
                text=text,
                metadata={
                    "draft_claims": [
                        {
                            "text": text,
                            "citations": ["c1"],
                        }
                    ]
                },
            )

    class Checker:
        async def check(self, request: SupportCheckRequest) -> SupportCheckResult:
            return SupportCheckResult(
                method="provider-fixture",
                claims=[
                    AnswerClaim(
                        claim_index=claim.claim_index,
                        text=claim.text,
                        citation_ids=claim.citation_ids,
                        support_status="supported",
                        support_score=1,
                        support_reason="approved",
                        method="provider-fixture",
                    )
                    for claim in request.claims
                ],
            )

    result = await generate_query_answer(
        session,
        tenant_id=tenant.id,
        query_run_id=run.id,
        generator=Generator(),
        support_checker=Checker(),
    )
    assert result.status == QueryRunStatus.COMPLETED
    assert run.abstained is abstained
    await session.flush()
    await session.refresh(run)
    audit = run.metadata_["arithmetic_verification"]
    assert audit["calculations"][0]["computed_value"] == "127.4"
    assert audit["calculations"][0]["verified"] is (not abstained)
    assert audit["calculations"][0]["operands"][0]["source_ids"] == source_ids
    assert audit["provider_judgments"][0]["support_status"] == "supported"
    claim = await session.scalar(
        select(QueryAnswerClaim).where(QueryAnswerClaim.query_run_id == run.id)
    )
    assert claim is not None and claim.text == text
    assert claim.support_status == ("unsupported" if abstained else "supported")
    assert run.answer_citations == (
        []
        if abstained
        else [
            {
                "citation_id": "c1",
                "context_id": "ctx-0001",
                "marker": "[c1]",
                "source_ids": source_ids,
            }
        ]
    )
    from flint_graph.application.services.query_provenance import get_query_answer_provenance
    from flint_graph.domain.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await get_query_answer_provenance(session, tenant_id=uuid4(), query_run_id=run.id)
