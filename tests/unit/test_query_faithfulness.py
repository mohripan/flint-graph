from uuid import uuid4

import pytest
from pydantic import ValidationError

from flint_graph.application.query_faithfulness import (
    DeterministicSupportChecker,
    evaluate_abstention,
    repair_claim_citations,
)
from flint_graph.application.query_orchestration import (
    AnswerDraft,
    AnswerFaithfulnessReport,
    PackedContextRecord,
    QueryContextPack,
    SupportCheckClaim,
    SupportCheckRequest,
)


def _context_pack() -> QueryContextPack:
    return QueryContextPack(
        pack_id="pack-1",
        token_budget=100,
        records=[
            PackedContextRecord(
                context_id="ctx-1",
                candidate_id="lexical:chunk:chunk-000001",
                citation_id="c1",
                text="Acme Corporation is headquartered in Berlin.",
                token_count=6,
                source_ids={"chunk_id": "chunk-000001"},
            ),
            PackedContextRecord(
                context_id="ctx-2",
                candidate_id="vector:chunk:chunk-000002",
                citation_id="c2",
                text="Acme opened a research office in Paris.",
                token_count=7,
                source_ids={"chunk_id": "chunk-000002"},
            ),
        ],
    )


def test_answer_draft_and_faithfulness_report_reject_oversized_metadata() -> None:
    with pytest.raises(ValidationError, match="metadata exceeds"):
        AnswerDraft(
            text="Acme is headquartered in Berlin. [c1]",
            raw_citation_markers=["[c1]"],
            metadata={"large": "x" * 5000},
        )

    with pytest.raises(ValidationError, match="metadata exceeds"):
        AnswerFaithfulnessReport(
            claims=[],
            repairs=[],
            supported_claim_count=0,
            unsupported_claim_count=0,
            abstained=False,
            support_method="deterministic-lexical",
            metadata={"large": "x" * 5000},
        )


def test_repair_claim_citations_normalizes_drops_unknown_and_deduplicates() -> None:
    repaired, repairs = repair_claim_citations(
        claim_index=0,
        text="Acme is headquartered in Berlin.",
        raw_markers=["[C1]", "(c1)", "c9", "[c2]"],
        context_pack=_context_pack(),
    )

    assert repaired.citation_ids == ["c1", "c2"]
    assert [
        (repair.original_marker, repair.resolved_citation_id, repair.action)
        for repair in repairs
    ] == [
        ("[C1]", "c1", "normalized"),
        ("(c1)", "c1", "deduplicated"),
        ("c9", None, "dropped_unknown"),
        ("[c2]", "c2", "kept"),
    ]


@pytest.mark.anyio
async def test_deterministic_support_checker_scores_claims() -> None:
    checker = DeterministicSupportChecker()
    result = await checker.check(
        SupportCheckRequest(
            tenant_id=uuid4(),
            query="Where is Acme headquartered?",
            context_pack=_context_pack(),
            claims=[
                SupportCheckClaim(
                    claim_index=0,
                    text="Acme Corporation is headquartered in Berlin.",
                    citation_ids=["c1"],
                ),
                SupportCheckClaim(
                    claim_index=1,
                    text="Acme Corporation has offices in Berlin and Paris.",
                    citation_ids=["c1"],
                ),
                SupportCheckClaim(
                    claim_index=2,
                    text="Acme Corporation acquired Contoso.",
                    citation_ids=[],
                ),
            ],
        )
    )

    assert result.method == "deterministic-lexical"
    assert [claim.support_status for claim in result.claims] == [
        "supported",
        "partial",
        "unsupported",
    ]
    assert result.claims[0].support_score == 1.0
    assert 0.0 < result.claims[1].support_score < 1.0
    assert result.claims[2].support_score == 0.0


def test_evaluate_abstention_uses_insufficient_context_ratio_relevance_and_repair_state() -> None:
    assert evaluate_abstention(
        insufficient_context=True,
        supported_claim_count=1,
        total_claim_count=1,
        min_supported_claim_ratio=0.5,
    ).abstained

    weak_support = evaluate_abstention(
        insufficient_context=False,
        supported_claim_count=1,
        total_claim_count=3,
        min_supported_claim_ratio=0.5,
    )
    assert weak_support.abstained
    assert weak_support.reason == "supported_claim_ratio_below_threshold"

    weak_context = evaluate_abstention(
        insufficient_context=False,
        supported_claim_count=1,
        total_claim_count=1,
        min_supported_claim_ratio=0.5,
        best_context_relevance=0.2,
        min_context_relevance=0.3,
    )
    assert weak_context.abstained
    assert weak_context.reason == "context_relevance_below_threshold"

    no_citations = evaluate_abstention(
        insufficient_context=False,
        supported_claim_count=1,
        total_claim_count=1,
        min_supported_claim_ratio=0.5,
        all_citations_dropped=True,
    )
    assert no_citations.abstained
    assert no_citations.reason == "all_citations_dropped"
