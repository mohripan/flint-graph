from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from flint_graph.application.financial_arithmetic import review_financial_arithmetic
from flint_graph.application.query_faithfulness import (
    AbstentionDecision,
    DeterministicSupportChecker,
    evaluate_abstention,
    repair_claim_citations,
)
from flint_graph.application.query_orchestration import (
    AnswerCitation,
    AnswerClaim,
    AnswerFaithfulnessReport,
    CitationRepair,
    GeneratedAnswer,
    QueryContextPack,
    SupportCheckClaim,
    SupportChecker,
    SupportCheckRequest,
)

_SAFE_ABSTENTION_ANSWER = "The available context is insufficient to answer this query."
_CITATION_MARKER_RE = re.compile(r"\s*[\[(]\s*(?:c[0-9]+|ctx-[0-9]+)\s*[\])]", re.IGNORECASE)
# Narrow English commentary patterns, not a general semantic/completeness judge.
# Explicit negative facts ("Acme does not manufacture ...") do not match.
_CONTEXT_GAP_RE = re.compile(
    r"^(?:the\s+)?(?:(?:provided|available|cited)\s+)?context\s+"
    r"(?:does\s+not|doesn't)\s+(?:provide|mention|contain|state)\b"
    r"|\b(?:is|are)\s+not\s+(?:mentioned|provided|stated|specified)\s+in\s+"
    r"(?:the\s+)?(?:(?:provided|available|cited)\s+)?context\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class QueryFaithfulnessPolicy:
    min_supported_claim_ratio: float = 0.5
    min_context_relevance: float = 0.0


@dataclass(frozen=True, slots=True)
class QueryFaithfulnessResult:
    answer: GeneratedAnswer
    report: AnswerFaithfulnessReport
    arithmetic_audit: dict[str, Any] | None = None


async def verify_generated_answer(
    *,
    tenant_id: UUID,
    query: str,
    context_pack: QueryContextPack,
    draft_answer: GeneratedAnswer,
    support_checker: SupportChecker | None = None,
    policy: QueryFaithfulnessPolicy | None = None,
    best_context_relevance: float | None = None,
) -> QueryFaithfulnessResult:
    active_policy = policy or QueryFaithfulnessPolicy()
    checker = support_checker or DeterministicSupportChecker()
    draft_claims, repairs, _structured_draft = _repair_draft_claims(
        draft_answer=draft_answer,
        context_pack=context_pack,
    )
    support_result = await checker.check(
        SupportCheckRequest(
            tenant_id=tenant_id,
            query=query,
            context_pack=context_pack,
            claims=draft_claims,
        )
    )
    provider_claims = list(support_result.claims)
    support_result = support_result.model_copy(
        update={
            "claims": [
                claim.model_copy(
                    update={
                        "support_status": "unsupported",
                        "support_score": 0.0,
                        "support_reason": "context_insufficiency_commentary",
                    }
                )
                if _CONTEXT_GAP_RE.search(claim.text.strip())
                else claim
                for claim in support_result.claims
            ]
        }
    )
    arithmetic = review_financial_arithmetic(
        query,
        support_result.claims,
        context_pack,
        provider_claims=provider_claims,
    )
    support_result = support_result.model_copy(update={"claims": arithmetic.claims})
    supported_count = sum(
        1 for claim in support_result.claims if claim.support_status == "supported"
    )
    unsupported_count = sum(
        1 for claim in support_result.claims if claim.support_status == "unsupported"
    )
    decision = evaluate_abstention(
        insufficient_context=draft_answer.insufficient_context,
        supported_claim_count=supported_count,
        total_claim_count=len(support_result.claims),
        min_supported_claim_ratio=active_policy.min_supported_claim_ratio,
        best_context_relevance=best_context_relevance,
        min_context_relevance=active_policy.min_context_relevance,
        all_citations_dropped=_all_citations_dropped(draft_claims, repairs),
    )
    if arithmetic.required and not arithmetic.satisfied and not draft_answer.insufficient_context:
        decision = AbstentionDecision(abstained=True, reason="financial_arithmetic_unverified")
    report = AnswerFaithfulnessReport(
        claims=support_result.claims,
        repairs=repairs,
        supported_claim_count=supported_count,
        unsupported_claim_count=unsupported_count,
        abstained=decision.abstained,
        abstain_reason=decision.reason,
        support_method=support_result.method,
        metadata={
            "claim_count": len(support_result.claims),
            # Carried through so usage accounting can attribute the support check
            # to the provider and model that performed it.
            "support": dict(support_result.metadata),
            **(
                {
                    "arithmetic": {
                        "method": arithmetic.metadata["method"],
                        "required": True,
                        "satisfied": arithmetic.satisfied,
                    }
                }
                if arithmetic.required
                else {}
            ),
        },
    )
    if decision.abstained:
        return QueryFaithfulnessResult(
            answer=GeneratedAnswer(
                text=_SAFE_ABSTENTION_ANSWER,
                citations=[],
                insufficient_context=True,
                metadata=_answer_metadata(draft_answer, report),
            ),
            report=report,
            arithmetic_audit=arithmetic.metadata if arithmetic.required else None,
        )

    surviving_claims = [
        claim for claim in support_result.claims if claim.support_status == "supported"
    ]
    citations = _answer_citations(surviving_claims, context_pack)
    return QueryFaithfulnessResult(
        answer=GeneratedAnswer(
            text=_structured_answer_text(surviving_claims),
            citations=citations,
            insufficient_context=False,
            metadata=_answer_metadata(draft_answer, report),
        ),
        report=report,
        arithmetic_audit=arithmetic.metadata if arithmetic.required else None,
    )


def _repair_draft_claims(
    *,
    draft_answer: GeneratedAnswer,
    context_pack: QueryContextPack,
) -> tuple[list[SupportCheckClaim], list[CitationRepair], bool]:
    metadata_claims = draft_answer.metadata.get("draft_claims")
    if isinstance(metadata_claims, list):
        repaired_claims: list[SupportCheckClaim] = []
        repairs: list[CitationRepair] = []
        for fallback_index, raw_claim in enumerate(metadata_claims):
            if not isinstance(raw_claim, dict):
                continue
            text = raw_claim.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            raw_markers = _string_list(raw_claim.get("raw_citation_markers"))
            if not raw_markers:
                raw_markers = _string_list(raw_claim.get("citations"))
            raw_markers.extend(marker.strip() for marker in _CITATION_MARKER_RE.findall(text))
            text = _strip_citation_markers(text)
            if not text:
                continue
            claim_index = raw_claim.get("claim_index")
            if not isinstance(claim_index, int) or claim_index < 0:
                claim_index = fallback_index
            repaired, claim_repairs = repair_claim_citations(
                claim_index=claim_index,
                text=text.strip(),
                raw_markers=raw_markers,
                context_pack=context_pack,
            )
            repaired_claims.append(repaired)
            repairs.extend(claim_repairs)
        return repaired_claims, repairs, True

    raw_markers = [marker.strip() for marker in _CITATION_MARKER_RE.findall(draft_answer.text)]
    if not raw_markers:
        raw_markers = [citation.marker for citation in draft_answer.citations]
    text = _strip_citation_markers(draft_answer.text)
    repaired, repairs = repair_claim_citations(
        claim_index=0,
        text=text,
        raw_markers=raw_markers,
        context_pack=context_pack,
    )
    return ([repaired] if text else []), repairs, False


def _answer_citations(
    claims: list[AnswerClaim],
    context_pack: QueryContextPack,
) -> list[AnswerCitation]:
    records_by_citation = {record.citation_id: record for record in context_pack.records}
    seen: set[str] = set()
    citations: list[AnswerCitation] = []
    for claim in claims:
        for citation_id in claim.citation_ids:
            record = records_by_citation.get(citation_id)
            if record is None or citation_id in seen:
                continue
            seen.add(citation_id)
            citations.append(
                AnswerCitation(
                    citation_id=record.citation_id,
                    context_id=record.context_id,
                    marker=f"[{record.citation_id}]",
                    source_ids=record.source_ids,
                )
            )
    return citations


def _structured_answer_text(claims: list[AnswerClaim]) -> str:
    parts: list[str] = []
    for claim in claims:
        markers = " ".join(f"[{citation_id}]" for citation_id in claim.citation_ids)
        parts.append(f"{claim.text} {markers}".strip())
    return " ".join(parts) or _SAFE_ABSTENTION_ANSWER


def _answer_metadata(
    draft_answer: GeneratedAnswer,
    report: AnswerFaithfulnessReport,
) -> dict[str, object]:
    metadata: dict[str, object] = dict(draft_answer.metadata)
    metadata["faithfulness"] = {
        "supported_claim_count": report.supported_claim_count,
        "unsupported_claim_count": report.unsupported_claim_count,
        "abstained": report.abstained,
        "abstain_reason": report.abstain_reason,
        "support_method": report.support_method,
    }
    return metadata


def _faithfulness_summary(report: AnswerFaithfulnessReport) -> dict[str, object]:
    return {
        "supported_claim_count": report.supported_claim_count,
        "unsupported_claim_count": report.unsupported_claim_count,
        "abstained": report.abstained,
        "abstain_reason": report.abstain_reason,
        "support_method": report.support_method,
    }


def faithfulness_summary(report: AnswerFaithfulnessReport) -> dict[str, object]:
    return _faithfulness_summary(report)


def _all_citations_dropped(
    claims: list[SupportCheckClaim],
    repairs: list[CitationRepair],
) -> bool:
    if not repairs:
        return False
    if any(claim.citation_ids for claim in claims):
        return False
    return True


def _strip_citation_markers(text: str) -> str:
    return " ".join(_CITATION_MARKER_RE.sub("", text).split())


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
