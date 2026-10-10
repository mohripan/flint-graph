from uuid import uuid4

import pytest

from flint_graph.application.query_faithfulness import DeterministicSupportChecker
from flint_graph.application.query_orchestration import (
    AnswerCitation,
    AnswerClaim,
    GeneratedAnswer,
    PackedContextRecord,
    QueryContextPack,
    SupportCheckRequest,
    SupportCheckResult,
)
from flint_graph.application.services.query_faithfulness import (
    QueryFaithfulnessPolicy,
    verify_generated_answer,
)


class _ApprovingChecker:
    async def check(self, request: SupportCheckRequest) -> SupportCheckResult:
        return SupportCheckResult(
            method="approving-fixture",
            claims=[
                AnswerClaim(
                    claim_index=claim.claim_index,
                    text=claim.text,
                    citation_ids=claim.citation_ids,
                    support_status="supported",
                    support_score=1.0,
                    support_reason="approved",
                    method="approving-fixture",
                )
                for claim in request.claims
            ],
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "text",
    [
        "Acme Corporation's annual revenue is not mentioned in the context.",
        "The context does not provide the name of Initech's chief executive officer.",
        "The provided context does not contain Acme's annual revenue.",
    ],
)
async def test_context_insufficiency_commentary_cannot_be_a_supported_answer(text: str) -> None:
    result = await verify_generated_answer(
        tenant_id=uuid4(),
        query="What is Acme's annual revenue?",
        context_pack=_context_pack(),
        draft_answer=GeneratedAnswer(
            text=text,
            metadata={"draft_claims": [{"text": text, "citations": ["c1"]}]},
        ),
        support_checker=_ApprovingChecker(),
    )
    assert result.answer.insufficient_context is True
    assert result.answer.citations == []
    assert result.report.claims[0].support_status == "unsupported"
    assert result.report.claims[0].support_reason == "context_insufficiency_commentary"


@pytest.mark.anyio
async def test_explicit_negative_fact_is_not_context_insufficiency_commentary() -> None:
    text = "Acme Corporation does not manufacture consumer appliances."
    pack = _context_pack()
    pack = pack.model_copy(update={"records": [pack.records[0].model_copy(update={"text": text})]})
    result = await verify_generated_answer(
        tenant_id=uuid4(),
        query="Does Acme manufacture consumer appliances?",
        context_pack=pack,
        draft_answer=GeneratedAnswer(
            text=text, metadata={"draft_claims": [{"text": text, "citations": ["c1"]}]}
        ),
    )
    assert result.answer.insufficient_context is False
    assert result.report.claims[0].support_status == "supported"


@pytest.mark.anyio
@pytest.mark.parametrize("structured", [True, False])
async def test_inline_citations_are_repaired_without_stripping_factual_parentheses(structured):
    text = "Acme Corporation is headquartered in Berlin (Germany). [c1] [c999]"
    pack = _context_pack()
    pack = pack.model_copy(
        update={
            "records": [
                pack.records[0].model_copy(
                    update={"text": "Acme Corporation is headquartered in Berlin (Germany)."}
                )
            ]
        }
    )
    draft = GeneratedAnswer(
        text=text,
        citations=[
            AnswerCitation(
                citation_id="c1",
                context_id="ctx-0001",
                marker="[c1]",
                source_ids={"chunk_id": "chunk-acme"},
            )
        ],
        metadata={"draft_claims": [{"text": text, "citations": ["c1"]}]} if structured else {},
    )
    result = await verify_generated_answer(
        tenant_id=uuid4(),
        query="Where is Acme headquartered?",
        context_pack=pack,
        draft_answer=draft,
    )
    assert result.answer.text == "Acme Corporation is headquartered in Berlin (Germany). [c1]"
    assert result.report.claims[0].text == "Acme Corporation is headquartered in Berlin (Germany)."
    assert any(
        repair.action == "dropped_unknown" and "c999" in repair.original_marker
        for repair in result.report.repairs
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
async def test_unsupported_draft_is_not_rendered_or_hidden_from_audit() -> None:
    result = await verify_generated_answer(
        tenant_id=uuid4(),
        query="Where does Acme operate?",
        context_pack=_context_pack(),
        draft_answer=GeneratedAnswer(
            text="Provisional",
            metadata={
                "draft_claims": [
                    {"text": "Acme Corporation is headquartered in Berlin.", "citations": ["c1"]},
                    {"text": "Elephants invented quantum submarines.", "citations": ["c2"]},
                ]
            },
        ),
    )
    assert result.answer.text == "Acme Corporation is headquartered in Berlin. [c1]"
    assert result.report.unsupported_claim_count == 1
    assert result.report.claims[1].support_status == "unsupported"
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
async def test_verify_generated_answer_preserves_legacy_text_without_unused_citations() -> None:
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
    assert [citation.citation_id for citation in result.answer.citations] == ["c1"]
    assert result.report.abstained is False
    assert result.report.supported_claim_count == 1
