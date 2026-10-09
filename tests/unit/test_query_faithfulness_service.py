from uuid import uuid4

import pytest

from flint_graph.application.query_faithfulness import DeterministicSupportChecker
from flint_graph.application.query_orchestration import (
    AnswerCitation,
    GeneratedAnswer,
    PackedContextRecord,
    QueryContextPack,
)
from flint_graph.application.services.query_faithfulness import (
    QueryFaithfulnessPolicy,
    verify_generated_answer,
)


def _context_pack() -> QueryContextPack:
    return QueryContextPack(
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
            ),
            PackedContextRecord(
                context_id="ctx-0002",
                candidate_id="vector:chunk:chunk-paris",
                citation_id="c2",
                text="Acme opened a research office in Paris.",
                token_count=7,
                source_ids={"chunk_id": "chunk-paris"},
            ),
        ],
    )


@pytest.mark.anyio
async def test_verified_answer_omits_partially_supported_claims() -> None:
    draft = GeneratedAnswer(
        text="The draft is provisional.",
        metadata={
            "draft_claims": [
                {"text": "Acme Corporation is headquartered in Berlin.", "citations": ["c1"]},
                {
                    "text": "Acme opened a profitable research office in Paris in 2025.",
                    "citations": ["c2"],
                },
            ]
        },
    )
    result = await verify_generated_answer(
        tenant_id=uuid4(),
        query="Where does Acme operate?",
        context_pack=_context_pack(),
        draft_answer=draft,
    )

    assert [claim.support_status for claim in result.report.claims] == ["supported", "partial"]
    assert result.answer.text == "Acme Corporation is headquartered in Berlin. [c1]"
    assert [citation.citation_id for citation in result.answer.citations] == ["c1"]


@pytest.mark.anyio
async def test_zero_support_threshold_cannot_publish_an_unverified_answer() -> None:
    result = await verify_generated_answer(
        tenant_id=uuid4(),
        query="When did Acme open its profitable Paris office?",
        context_pack=_context_pack(),
        draft_answer=GeneratedAnswer(
            text="Provisional draft",
            metadata={
                "draft_claims": [
                    {
                        "text": "Acme opened a profitable research office in Paris in 2025.",
                        "citations": ["c2"],
                    },
                ]
            },
        ),
        policy=QueryFaithfulnessPolicy(min_supported_claim_ratio=0.0),
    )

    assert result.report.claims[0].support_status == "partial"
    assert result.report.abstained is True
    assert result.answer.insufficient_context is True
    assert result.answer.citations == []


@pytest.mark.anyio
async def test_verify_generated_answer_repairs_citations_and_keeps_supported_claims() -> None:
    draft = GeneratedAnswer(
        text="raw draft should not be authoritative",
        metadata={
            "draft_claims": [
                {
                    "claim_index": 0,
                    "text": "Acme Corporation is headquartered in Berlin.",
                    "raw_citation_markers": ["[C1]", "c9"],
                }
            ]
        },
    )

    result = await verify_generated_answer(
        tenant_id=uuid4(),
        query="Where is Acme headquartered?",
        context_pack=_context_pack(),
        draft_answer=draft,
        support_checker=DeterministicSupportChecker(),
        policy=QueryFaithfulnessPolicy(min_supported_claim_ratio=1.0),
    )

    assert result.answer.text == "Acme Corporation is headquartered in Berlin. [c1]"
    assert result.answer.insufficient_context is False
    assert [citation.citation_id for citation in result.answer.citations] == ["c1"]
    assert result.report.abstained is False
    assert result.report.supported_claim_count == 1
    assert result.report.unsupported_claim_count == 0
    assert [
        (repair.original_marker, repair.resolved_citation_id, repair.action)
        for repair in result.report.repairs
    ] == [
        ("[C1]", "c1", "normalized"),
        ("c9", None, "dropped_unknown"),
    ]


@pytest.mark.anyio
async def test_verify_generated_answer_abstains_when_support_is_insufficient() -> None:
    draft = GeneratedAnswer(
        text="Contoso acquired Globex. [c1]",
        metadata={
            "draft_claims": [
                {
                    "claim_index": 0,
                    "text": "Contoso acquired Globex.",
                    "raw_citation_markers": ["c1"],
                }
            ]
        },
    )

    result = await verify_generated_answer(
        tenant_id=uuid4(),
        query="Who did Acme acquire?",
        context_pack=_context_pack(),
        draft_answer=draft,
        support_checker=DeterministicSupportChecker(),
        policy=QueryFaithfulnessPolicy(min_supported_claim_ratio=0.5),
    )

    assert result.answer.insufficient_context is True
    assert result.answer.text == "The available context is insufficient to answer this query."
    assert result.answer.citations == []
    assert result.report.abstained is True
    assert result.report.abstain_reason == "supported_claim_ratio_below_threshold"
    assert result.report.unsupported_claim_count == 1


@pytest.mark.anyio
async def test_verify_generated_answer_preserves_legacy_generated_answer_shape() -> None:
    draft = GeneratedAnswer(
        text="Acme Corporation is headquartered in Berlin. [c1]",
        citations=[
            AnswerCitation(
                citation_id="c1",
                context_id="ctx-0001",
                marker="[c1]",
                source_ids={"chunk_id": "chunk-acme"},
            ),
            AnswerCitation(
                citation_id="c2",
                context_id="ctx-0002",
                marker="[c2]",
                source_ids={"chunk_id": "chunk-paris"},
            ),
        ],
        metadata={"algorithm": "legacy"},
    )

    result = await verify_generated_answer(
        tenant_id=uuid4(),
        query="Where is Acme headquartered?",
        context_pack=_context_pack(),
        draft_answer=draft,
        support_checker=DeterministicSupportChecker(),
        policy=QueryFaithfulnessPolicy(min_supported_claim_ratio=0.5),
    )

    assert result.answer.text == "Acme Corporation is headquartered in Berlin. [c1]"
    assert [citation.citation_id for citation in result.answer.citations] == ["c1", "c2"]
    assert result.report.abstained is False
    assert result.report.supported_claim_count == 1
