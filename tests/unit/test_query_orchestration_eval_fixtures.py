from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from flint_graph.application.query_orchestration import (
    AnswerGenerationRequest,
    DeterministicAnswerGenerator,
    DeterministicQueryClassifier,
    GeneratedAnswer,
    PackedContextRecord,
    QueryClassificationRequest,
)
from flint_graph.application.query_orchestration import (
    QueryContextPack as ApplicationQueryContextPack,
)
from flint_graph.application.services.query_faithfulness import verify_generated_answer

_FIXTURE_PATH = Path("tests/fixtures/query_orchestration_eval_cases.json")
_EVAL_CASES: list[dict[str, Any]] = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_query_orchestration_eval_fixtures_match_deterministic_providers() -> None:
    cases = _EVAL_CASES
    classifier = DeterministicQueryClassifier()
    answer_generator = DeterministicAnswerGenerator()
    tenant_id = uuid4()
    index_version_id = uuid4()

    assert cases
    for case in cases:
        await _assert_eval_case(
            case,
            classifier=classifier,
            answer_generator=answer_generator,
            tenant_id=tenant_id,
            index_version_id=index_version_id,
        )


@pytest.mark.asyncio
async def test_query_orchestration_eval_fixtures_cover_faithfulness_outcomes() -> None:
    tenant_id = uuid4()
    index_version_id = uuid4()

    assert _EVAL_CASES
    for case in _EVAL_CASES:
        context_pack = _context_pack(case)
        draft_answer = await _draft_answer(case, context_pack, tenant_id, index_version_id)

        result = await verify_generated_answer(
            tenant_id=tenant_id,
            query=case["query"],
            context_pack=context_pack,
            draft_answer=draft_answer,
        )

        assert result.answer.insufficient_context is case.get(
            "expected_verified_insufficient_context",
            case["expected_insufficient_context"],
        )
        assert result.answer.text == case.get("expected_verified_answer", case["expected_answer"])
        assert result.report.abstained is case["expected_abstained"]
        assert result.report.supported_claim_count == case["expected_supported_claim_count"]
        assert result.report.unsupported_claim_count == case["expected_unsupported_claim_count"]
        assert [
            citation.marker for citation in result.answer.citations
        ] == case["expected_surviving_markers"]


async def _assert_eval_case(
    case: dict[str, Any],
    *,
    classifier: DeterministicQueryClassifier,
    answer_generator: DeterministicAnswerGenerator,
    tenant_id: UUID,
    index_version_id: UUID,
) -> None:
    classification = await classifier.classify(
        QueryClassificationRequest(
            tenant_id=tenant_id,
            query=case["query"],
            retrieval_index_version_id=index_version_id,
        )
    )
    assert classification.label == case["expected_label"]
    assert classification.retrieval_plan.enabled_retrievers == case["expected_retrievers"]

    context_pack = _context_pack(case)
    answer = await answer_generator.generate(
        AnswerGenerationRequest(
            tenant_id=tenant_id,
            query=case["query"],
            retrieval_index_version_id=index_version_id,
            context_pack=context_pack,
        )
    )

    assert answer.insufficient_context is case["expected_insufficient_context"]
    assert answer.text == case["expected_answer"]
    assert [citation.marker for citation in answer.citations] == case["expected_markers"]


def _context_pack(case: dict[str, Any]) -> ApplicationQueryContextPack:
    context_records = [
        PackedContextRecord(
            context_id=f"ctx-{index:04d}",
            candidate_id=f"eval:{case['id']}:{index}",
            citation_id=f"c{index}",
            text=text,
            token_count=len(text.split()),
            source_ids={"fixture_id": case["id"], "record": str(index)},
        )
        for index, text in enumerate(case["context"], start=1)
    ]
    return ApplicationQueryContextPack(
        pack_id=f"eval-pack-{case['id']}",
        token_budget=max(1, sum(record.token_count for record in context_records)),
        records=context_records,
    )


async def _draft_answer(
    case: dict[str, Any],
    context_pack: ApplicationQueryContextPack,
    tenant_id: UUID,
    index_version_id: UUID,
) -> GeneratedAnswer:
    draft_claims = case.get("draft_claims")
    if isinstance(draft_claims, list):
        return GeneratedAnswer(
            text=" ".join(
                str(claim.get("text", ""))
                for claim in draft_claims
                if isinstance(claim, dict)
            )
            or "The available context is insufficient to answer this query.",
            insufficient_context=bool(case.get("draft_insufficient_context", False)),
            metadata={"draft_claims": draft_claims},
        )
    return await DeterministicAnswerGenerator().generate(
        AnswerGenerationRequest(
            tenant_id=tenant_id,
            query=case["query"],
            retrieval_index_version_id=index_version_id,
            context_pack=context_pack,
        )
    )
