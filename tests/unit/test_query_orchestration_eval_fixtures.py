from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from atlas_rag.application.query_orchestration import (
    AnswerGenerationRequest,
    DeterministicAnswerGenerator,
    DeterministicQueryClassifier,
    PackedContextRecord,
    QueryClassificationRequest,
)
from atlas_rag.application.query_orchestration import (
    QueryContextPack as ApplicationQueryContextPack,
)

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
    context_pack = ApplicationQueryContextPack(
        pack_id=f"eval-pack-{case['id']}",
        token_budget=max(1, sum(record.token_count for record in context_records)),
        records=context_records,
    )
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
