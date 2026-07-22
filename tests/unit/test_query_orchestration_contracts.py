from uuid import uuid4

import pytest
from pydantic import ValidationError

from flint_graph.application.query_orchestration import (
    AnswerGenerationRequest,
    DeterministicAnswerGenerator,
    DeterministicQueryClassifier,
    DeterministicQueryReranker,
    GeneratedAnswer,
    PackedContextRecord,
    QueryCandidate,
    QueryClassificationRequest,
    QueryContextPack,
    QueryEntityLink,
    QueryRerankRequest,
    QueryStreamEvent,
)


def test_entity_link_requires_target_for_accepted_link() -> None:
    with pytest.raises(ValidationError, match="accepted entity links require"):
        QueryEntityLink(
            mention_text="Acme Corporation",
            status="accepted",
            score=0.96,
            method="deterministic-exact",
        )


def test_context_pack_enforces_token_budget_and_unique_citation_ids() -> None:
    candidate_id = "lexical:chunk:chunk-000001"

    with pytest.raises(ValidationError, match="token budget"):
        QueryContextPack(
            pack_id="pack-1",
            token_budget=10,
            records=[
                PackedContextRecord(
                    context_id="ctx-1",
                    candidate_id=candidate_id,
                    citation_id="c1",
                    text="Acme Corporation is headquartered in Berlin.",
                    token_count=11,
                    source_ids={"chunk_id": "chunk-000001"},
                )
            ],
        )

    with pytest.raises(ValidationError, match="duplicate citation id"):
        QueryContextPack(
            pack_id="pack-1",
            token_budget=100,
            records=[
                PackedContextRecord(
                    context_id="ctx-1",
                    candidate_id=candidate_id,
                    citation_id="c1",
                    text="Acme Corporation is headquartered in Berlin.",
                    token_count=7,
                    source_ids={"chunk_id": "chunk-000001"},
                ),
                PackedContextRecord(
                    context_id="ctx-2",
                    candidate_id="vector:chunk:chunk-000002",
                    citation_id="c1",
                    text="Acme expanded its Berlin office.",
                    token_count=6,
                    source_ids={"chunk_id": "chunk-000002"},
                ),
            ],
        )


def test_stream_event_rejects_payloads_that_are_too_large() -> None:
    with pytest.raises(ValidationError, match="payload exceeds"):
        QueryStreamEvent(event_type="answer.delta", payload={"text": "x" * 9000})


@pytest.mark.anyio
async def test_deterministic_classifier_selects_relationship_strategy() -> None:
    tenant_id = uuid4()
    index_version_id = uuid4()
    classifier = DeterministicQueryClassifier()

    result = await classifier.classify(
        QueryClassificationRequest(
            tenant_id=tenant_id,
            query="How are Acme Corporation and Berlin connected?",
            retrieval_index_version_id=index_version_id,
        )
    )

    assert result.label == "relationship"
    assert result.confidence == 0.85
    assert result.retrieval_plan.requires_entity_linking
    assert result.retrieval_plan.requires_graph_expansion
    assert result.retrieval_plan.enabled_retrievers == ["lexical", "vector", "graph"]
    assert result.retrieval_plan.candidate_limits["graph"] == 10


@pytest.mark.anyio
async def test_deterministic_reranker_prefers_query_term_overlap_then_score() -> None:
    tenant_id = uuid4()
    index_version_id = uuid4()
    reranker = DeterministicQueryReranker()
    candidates = [
        QueryCandidate(
            candidate_id="lexical:chunk:2",
            source="lexical",
            candidate_type="chunk",
            tenant_id=tenant_id,
            retrieval_index_version_id=index_version_id,
            source_ids={"chunk_id": "chunk-000002"},
            text_preview="Quarterly revenue increased in Paris.",
            raw_score=0.9,
            normalized_score=0.9,
            rank=1,
        ),
        QueryCandidate(
            candidate_id="vector:chunk:1",
            source="vector",
            candidate_type="chunk",
            tenant_id=tenant_id,
            retrieval_index_version_id=index_version_id,
            source_ids={"chunk_id": "chunk-000001"},
            text_preview="Acme Corporation opened a Berlin office.",
            raw_score=0.6,
            normalized_score=0.6,
            rank=2,
        ),
    ]

    result = await reranker.rerank(
        QueryRerankRequest(
            query="Where is Acme Corporation in Berlin?",
            candidates=candidates,
            max_results=2,
        )
    )

    assert [candidate.candidate_id for candidate in result.candidates] == [
        "vector:chunk:1",
        "lexical:chunk:2",
    ]
    assert result.candidates[0].rerank_rank == 1
    assert result.candidates[0].rerank_score > result.candidates[1].rerank_score


@pytest.mark.anyio
async def test_deterministic_answer_generator_uses_only_context_and_citations() -> None:
    tenant_id = uuid4()
    index_version_id = uuid4()
    generator = DeterministicAnswerGenerator()
    pack = QueryContextPack(
        pack_id="pack-1",
        token_budget=100,
        records=[
            PackedContextRecord(
                context_id="ctx-1",
                candidate_id="lexical:chunk:chunk-000001",
                citation_id="c1",
                text="Acme Corporation is headquartered in Berlin.",
                token_count=7,
                source_ids={"chunk_id": "chunk-000001"},
            )
        ],
    )

    answer = await generator.generate(
        AnswerGenerationRequest(
            tenant_id=tenant_id,
            query="Where is Acme Corporation headquartered?",
            retrieval_index_version_id=index_version_id,
            context_pack=pack,
        )
    )

    assert isinstance(answer, GeneratedAnswer)
    assert answer.insufficient_context is False
    assert answer.text == "Acme Corporation is headquartered in Berlin. [c1]"
    assert [citation.citation_id for citation in answer.citations] == ["c1"]
    assert answer.citations[0].context_id == "ctx-1"


@pytest.mark.anyio
async def test_deterministic_answer_generator_reports_insufficient_context() -> None:
    generator = DeterministicAnswerGenerator()

    answer = await generator.generate(
        AnswerGenerationRequest(
            tenant_id=uuid4(),
            query="What is FlintGraph?",
            retrieval_index_version_id=uuid4(),
            context_pack=QueryContextPack(pack_id="pack-empty", token_budget=100),
        )
    )

    assert answer.insufficient_context
    assert answer.text == "The available context is insufficient to answer this query."
    assert answer.citations == []
