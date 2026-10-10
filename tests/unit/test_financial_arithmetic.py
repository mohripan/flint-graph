import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from flint_graph.application.query_orchestration import (
    AnswerClaim,
    AnswerGenerationRequest,
    GeneratedAnswer,
    PackedContextRecord,
    QueryContextPack,
    SupportCheckResult,
)
from flint_graph.application.services.query_faithfulness import verify_generated_answer


class ApprovingChecker:
    async def check(self, request):
        return SupportCheckResult(
            method="provider-fixture",
            claims=[
                AnswerClaim(
                    claim_index=claim.claim_index,
                    text=claim.text,
                    citation_ids=claim.citation_ids,
                    support_status="supported",
                    support_score=1,
                    support_reason="provider approval",
                    method="provider-fixture",
                )
                for claim in request.claims
            ],
        )


def table_pack(
    volume="637",
    volume_scale="billions",
    transactions="5.0",
    transaction_scale="billions",
    *,
    company="American Express",
    flattened=False,
):
    text = (
        f"| company | payments volume ({volume_scale}) | "
        f"total transactions ({transaction_scale}) |\n"
        "| --- | --- | --- |\n"
        f"| {company} | {volume} | {transactions} |\n"
        "| Other Network | 900 | 30 |"
    )
    if flattened:
        text = " ".join(text.split())
    return QueryContextPack(
        pack_id="financial-pack",
        token_budget=300,
        records=[
            PackedContextRecord(
                context_id="ctx-0001",
                candidate_id="lexical:chunk:table",
                citation_id="c1",
                text=text,
                token_count=100,
                source_ids={
                    "document_id": str(uuid4()),
                    "document_version_id": str(uuid4()),
                    "chunk_id": "chunk-table",
                },
                metadata={
                    "evidence_origin": "postgresql_chunk",
                    "chunk_hash": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
                },
            )
        ],
    )


@pytest.mark.parametrize(
    "volume,volume_scale,transactions,transaction_scale,result,expected",
    [
        ("637", "billions", "5.0", "billions", "127.4", True),
        ("637", "billions", "5.0", "billions", "127,400", False),
        ("637", "millions", "5.0", "billions", "0.1274", True),
        ("637", "billions", "5.0", "millions", "127,400", True),
        ("637", "billions", "0", "billions", "127.4", False),
        ("637", "unknown", "5.0", "billions", "127.4", False),
        ("=637+1", "billions", "5.0", "billions", "127.4", False),
        ("637", "billions", "5.0", "unknown", "127.4", False),
    ],
)
@pytest.mark.parametrize("flattened", [False, True])
async def test_cited_table_ratio_is_independent_of_approving_model_and_respects_scales(
    volume, volume_scale, transactions, transaction_scale, result, expected, flattened
):
    pack = table_pack(volume, volume_scale, transactions, transaction_scale, flattened=flattened)
    text = f"American Express's average payments volume per transaction was ${result}."
    verified = await verify_generated_answer(
        tenant_id=uuid4(),
        query="What was American Express's average payments volume per transaction in dollars?",
        context_pack=pack,
        draft_answer=GeneratedAnswer(
            text=text, metadata={"draft_claims": [{"text": text, "citations": ["c1"]}]}
        ),
        support_checker=ApprovingChecker(),
    )
    assert verified.report.abstained is (not expected)
    assert verified.report.claims[0].text == text
    assert verified.report.claims[0].support_status == ("supported" if expected else "unsupported")
    audit = verified.arithmetic_audit
    assert audit is not None
    assert audit["method"] == "cited-payments-ratio-v1"
    if expected:
        assert verified.answer.text == text + " [c1]"
        calculation = audit["calculations"][0]
        assert calculation["verified"] is True
        for operand in calculation["operands"]:
            assert operand["source_ids"] == pack.records[0].source_ids
            for span in (operand["value_span"], operand["unit_span"], operand["entity_span"]):
                assert pack.records[0].text[span["start"] : span["end"]] == span["quote"]
    else:
        assert verified.answer.citations == []
        assert result not in verified.answer.text
        assert verified.report.abstain_reason == "financial_arithmetic_unverified"


@pytest.mark.parametrize("failure", ["uncited", "legacy", "ambiguous", "premises_only"])
async def test_arithmetic_cannot_borrow_uncited_or_ambiguous_operands_or_serve_only_premises(
    failure,
):
    pack = table_pack()
    if failure == "legacy":
        pack = pack.model_copy(
            update={"records": [pack.records[0].model_copy(update={"metadata": {}})]}
        )
    elif failure == "ambiguous":
        other = (
            table_pack("700")
            .records[0]
            .model_copy(
                update={
                    "citation_id": "c2",
                    "context_id": "ctx-0002",
                    "candidate_id": "other-table",
                }
            )
        )
        pack = pack.model_copy(update={"records": [pack.records[0], other]})
    text = (
        "Payments volume was $637 billion."
        if failure == "premises_only"
        else "American Express's average payments volume per transaction was $127.4."
    )
    citations = [] if failure == "uncited" else ["c1", "c2"] if failure == "ambiguous" else ["c1"]
    verified = await verify_generated_answer(
        tenant_id=uuid4(),
        query="What was American Express's average payments volume per transaction in dollars?",
        context_pack=pack,
        draft_answer=GeneratedAnswer(
            text=text,
            metadata={
                "draft_claims": [
                    {
                        "text": text,
                        "citations": citations,
                    }
                ]
            },
        ),
        support_checker=ApprovingChecker(),
    )
    assert verified.report.abstained is True
    assert verified.report.abstain_reason == "financial_arithmetic_unverified"
    assert verified.answer.citations == []


async def test_ratio_verifier_does_not_hardcode_company_or_expected_answer():
    pack = table_pack("900", transactions="30", company="Example Payments")
    text = "Example Payments's average payments volume per transaction was 30 dollars."
    verified = await verify_generated_answer(
        tenant_id=uuid4(),
        query="What was Example Payments's average payments volume per transaction in dollars?",
        context_pack=pack,
        draft_answer=GeneratedAnswer(
            text=text,
            metadata={
                "draft_claims": [
                    {
                        "text": text,
                        "citations": ["c1"],
                    }
                ]
            },
        ),
        support_checker=ApprovingChecker(),
    )
    assert verified.report.abstained is False
    assert verified.arithmetic_audit is not None
    assert verified.arithmetic_audit["calculations"][0]["computed_value"] == "30"


@pytest.mark.parametrize(
    "text",
    [
        "American Express's average payments volume per transaction was $127.4 million.",
        "American Express's average payments volume per transaction was $1.274e2.",
        "Other Network's average payments volume per transaction was $127.4.",
        "American Express's average was $127.4, calculated from $637 billion.",
        "American Express's average payments volume per transaction was $127.4 euros.",
        "American Express's average payments volume per transaction was $127.4 quadrillion.",
        "American Express's average payments volume per transaction was not $127.4.",
        "American Express's average payments volume per transaction was $127.4 (million).",
        "American Express's average payments volume per transaction was $127.4 x 1000.",
    ],
)
async def test_result_units_entity_and_atomicity_are_not_inferred_by_model_approval(text):
    verified = await verify_generated_answer(
        tenant_id=uuid4(),
        query="What was American Express's average payments volume per transaction in dollars?",
        context_pack=table_pack(),
        draft_answer=GeneratedAnswer(
            text=text,
            metadata={
                "draft_claims": [
                    {
                        "text": text,
                        "citations": ["c1"],
                    }
                ]
            },
        ),
        support_checker=ApprovingChecker(),
    )
    assert verified.report.abstained is True
    assert verified.report.claims[0].support_status == "unsupported"


@pytest.mark.parametrize("failure", ["hash", "duplicate_headers", "nonterminating", "oversized"])
async def test_unverifiable_table_contracts_cannot_produce_calculation_hints(failure):
    from flint_graph.application.financial_arithmetic import prepare_verified_calculation

    pack = table_pack()
    if failure == "hash":
        record = pack.records[0].model_copy(
            update={"text": pack.records[0].text.replace("637", "700")}
        )
        pack = pack.model_copy(update={"records": [record]})
    elif failure == "duplicate_headers":
        pack = table_pack(transaction_scale="billions")
        text = pack.records[0].text.replace("total transactions", "payments volume")
        pack = pack.model_copy(
            update={
                "records": [
                    pack.records[0].model_copy(
                        update={
                            "text": text,
                            "metadata": {
                                "evidence_origin": "postgresql_chunk",
                                "chunk_hash": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
                            },
                        }
                    )
                ]
            }
        )
    elif failure == "nonterminating":
        pack = table_pack("1", transactions="3")
    else:
        pack = table_pack("1,234,567,890,123,456,789,012")
    query = "What was American Express's average payments volume per transaction in dollars?"
    assert prepare_verified_calculation(query, pack) is None


@pytest.mark.parametrize("contradictory", [False, True])
async def test_duplicate_source_identity_deduplicates_only_identical_evidence(contradictory):
    from flint_graph.application.financial_arithmetic import prepare_verified_calculation

    pack = table_pack()
    other = (table_pack("700").records[0] if contradictory else pack.records[0]).model_copy(
        update={
            "source_ids": pack.records[0].source_ids,
            "citation_id": "c2",
            "context_id": "ctx-0002",
            "candidate_id": "second",
        }
    )
    pack = pack.model_copy(update={"records": [pack.records[0], other]})
    query = "What was American Express's average payments volume per transaction in dollars?"
    hint = prepare_verified_calculation(query, pack)
    assert (hint is None) is contradictory


async def test_correct_arithmetic_does_not_override_provider_rejection():
    class RejectingChecker(ApprovingChecker):
        async def check(self, request):
            original = await super().check(request)
            return original.model_copy(
                update={
                    "claims": [
                        claim.model_copy(
                            update={"support_status": "unsupported", "support_score": 0}
                        )
                        for claim in original.claims
                    ]
                }
            )

    text = "American Express's average payments volume per transaction was $127.4."
    verified = await verify_generated_answer(
        tenant_id=uuid4(),
        query="What was American Express's average payments volume per transaction in dollars?",
        context_pack=table_pack(),
        draft_answer=GeneratedAnswer(
            text=text,
            metadata={
                "draft_claims": [
                    {
                        "text": text,
                        "citations": ["c1"],
                    }
                ]
            },
        ),
        support_checker=RejectingChecker(),
    )
    assert verified.report.metadata["arithmetic"]["satisfied"] is False
    assert verified.report.claims[0].support_status == "unsupported"
    assert verified.report.abstained is True


async def test_calculation_count_bound_refuses_the_whole_answer_without_losing_draft_claims():
    text = "American Express's average payments volume per transaction was $127.4."
    verified = await verify_generated_answer(
        tenant_id=uuid4(),
        query="What was American Express's average payments volume per transaction in dollars?",
        context_pack=table_pack(),
        draft_answer=GeneratedAnswer(
            text=text,
            metadata={"draft_claims": [{"text": text, "citations": ["c1"]} for _ in range(9)]},
        ),
        support_checker=ApprovingChecker(),
    )
    assert verified.report.abstained is True
    assert len(verified.report.claims) == 9
    assert verified.report.claims[-1].support_reason == "financial_arithmetic_limit"
    assert verified.arithmetic_audit is not None
    assert len(verified.arithmetic_audit["calculations"]) == 8
    assert len(verified.arithmetic_audit["provider_judgments"]) == 9


async def test_rejected_correct_result_cannot_be_replaced_by_supported_premises():
    class RejectingResultChecker(ApprovingChecker):
        async def check(self, request):
            original = await super().check(request)
            return original.model_copy(
                update={
                    "claims": [
                        claim.model_copy(
                            update={"support_status": "unsupported", "support_score": 0}
                        )
                        if claim.claim_index == 2
                        else claim
                        for claim in original.claims
                    ]
                }
            )

    texts = [
        "American Express payments volume was $637 billion.",
        "American Express transactions were 5.0 billion.",
        "American Express's average payments volume per transaction was $127.4.",
    ]
    verified = await verify_generated_answer(
        tenant_id=uuid4(),
        query="What was American Express's average payments volume per transaction in dollars?",
        context_pack=table_pack(),
        draft_answer=GeneratedAnswer(
            text="draft",
            metadata={"draft_claims": [{"text": text, "citations": ["c1"]} for text in texts]},
        ),
        support_checker=RejectingResultChecker(),
    )
    assert verified.report.abstained is True
    assert verified.answer.citations == []
    assert verified.report.supported_claim_count == 2


async def test_arithmetic_audit_keeps_model_judgment_before_context_commentary_policy():
    text = (
        "The context does not provide American Express's average payments volume per transaction."
    )
    verified = await verify_generated_answer(
        tenant_id=uuid4(),
        query="What was American Express's average payments volume per transaction in dollars?",
        context_pack=table_pack(),
        draft_answer=GeneratedAnswer(
            text=text,
            metadata={
                "draft_claims": [
                    {
                        "text": text,
                        "citations": ["c1"],
                    }
                ]
            },
        ),
        support_checker=ApprovingChecker(),
    )
    assert verified.report.abstained is True
    assert verified.arithmetic_audit is not None
    assert verified.arithmetic_audit["provider_judgments"][0]["support_status"] == "supported"


async def test_mismatched_result_abstains_even_when_two_premises_satisfy_support_ratio():
    texts = [
        "American Express's payments volume was $637 billion.",
        "American Express's total transactions were 5.0 billion.",
        "American Express's average payments volume per transaction was $127,400.",
    ]
    verified = await verify_generated_answer(
        tenant_id=uuid4(),
        query="What was American Express's average payments volume per transaction in dollars?",
        context_pack=table_pack(),
        draft_answer=GeneratedAnswer(
            text="draft",
            metadata={"draft_claims": [{"text": text, "citations": ["c1"]} for text in texts]},
        ),
        support_checker=ApprovingChecker(),
    )
    assert verified.report.abstained is True
    assert verified.report.supported_claim_count == 2
    assert verified.report.unsupported_claim_count == 1
    assert [claim.text for claim in verified.report.claims] == texts
    assert verified.arithmetic_audit is not None
    assert all(
        claim["support_status"] == "supported"
        for claim in verified.arithmetic_audit["provider_judgments"]
    )


@pytest.mark.parametrize("provider", ["ollama", "anthropic"])
async def test_answer_provider_prompts_include_bounded_precomputed_ratio(provider):
    from flint_graph.application.financial_arithmetic import prepare_verified_calculation
    from flint_graph.infrastructure.anthropic import AnthropicAnswerGenerator
    from flint_graph.infrastructure.ollama import OllamaAnswerGenerator

    pack = table_pack()
    query = "What was American Express's average payments volume per transaction in dollars?"
    hint = prepare_verified_calculation(query, pack)
    request = AnswerGenerationRequest(
        tenant_id=uuid4(),
        query=query,
        retrieval_index_version_id=uuid4(),
        context_pack=pack,
        policy={"verified_calculation": hint},
    )
    response_text = json.dumps(
        {
            "insufficient_context": False,
            "claims": [
                {
                    "text": "American Express's average payments volume "
                    "per transaction was $127.4.",
                    "citations": ["c1"],
                }
            ],
        }
    )
    prompts = []

    async def create(**kwargs):
        prompts.append(kwargs["messages"][0]["content"])
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=response_text)],
            stop_reason="end_turn",
            model="fixture",
        )

    def handler(http_request):
        prompts.append(json.loads(http_request.content)["prompt"])
        return httpx.Response(200, json={"model": "fixture", "response": response_text})

    if provider == "anthropic":
        generator = AnthropicAnswerGenerator(
            model="fixture",
            max_tokens=300,
            effort="low",
            timeout_seconds=30,
            client=SimpleNamespace(messages=SimpleNamespace(create=create)),
        )
        answer = await generator.generate(request)
    else:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://fixture"
        ) as client:
            generator = OllamaAnswerGenerator(
                model="fixture",
                timeout_seconds=30,
                temperature=0,
                max_tokens=300,
                http_client=client,
            )
            answer = await generator.generate(request)
    assert "Verified calculation" in prompts[0]
    assert '"computed_value": "127.4"' in prompts[0]
    assert '"citation_id": "c1"' in prompts[0]
    assert "cited-payments-ratio-v1" in prompts[0]
    assert answer.metadata["answer_prompt_version"] == "grounded-answer-v3"
