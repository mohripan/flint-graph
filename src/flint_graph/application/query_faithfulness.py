from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from flint_graph.application.query_orchestration import (
    AnswerClaim,
    CitationRepair,
    QueryContextPack,
    SupportCheckClaim,
    SupportCheckRequest,
    SupportCheckResult,
    SupportStatus,
)

DETERMINISTIC_SUPPORT_METHOD = "deterministic-lexical"
_MARKER_RE = re.compile(r"^\s*[\[(]?\s*([A-Za-z0-9_-]+)\s*[\])]?\s*$")
_WORD_RE = re.compile(r"[a-z0-9]+")


class AbstentionDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    abstained: bool
    reason: str | None = Field(default=None, max_length=500)


def repair_claim_citations(
    *,
    claim_index: int,
    text: str,
    raw_markers: list[str],
    context_pack: QueryContextPack,
) -> tuple[SupportCheckClaim, list[CitationRepair]]:
    citation_lookup = {
        record.citation_id.casefold(): record.citation_id for record in context_pack.records
    }
    seen: set[str] = set()
    resolved_ids: list[str] = []
    repairs: list[CitationRepair] = []

    for marker in raw_markers:
        normalized = _normalize_marker(marker)
        resolved = citation_lookup.get(normalized.casefold()) if normalized else None
        if resolved is None:
            repairs.append(
                CitationRepair(
                    original_marker=marker,
                    resolved_citation_id=None,
                    action="dropped_unknown",
                    reason="citation marker does not resolve to the context pack",
                )
            )
            continue

        if resolved in seen:
            repairs.append(
                CitationRepair(
                    original_marker=marker,
                    resolved_citation_id=resolved,
                    action="deduplicated",
                    reason="citation marker duplicates an earlier resolved citation",
                )
            )
            continue

        seen.add(resolved)
        resolved_ids.append(resolved)
        expected_marker = f"[{resolved}]"
        action = "kept" if marker == expected_marker else "normalized"
        repairs.append(
            CitationRepair(
                original_marker=marker,
                resolved_citation_id=resolved,
                action=action,
                reason=(
                    "citation marker already matched the canonical marker"
                    if action == "kept"
                    else "citation marker was normalized to the canonical citation id"
                ),
            )
        )

    return (
        SupportCheckClaim(
            claim_index=claim_index,
            text=text,
            citation_ids=resolved_ids,
        ),
        repairs,
    )


class DeterministicSupportChecker:
    async def check(self, request: SupportCheckRequest) -> SupportCheckResult:
        records_by_citation = {
            record.citation_id: record for record in request.context_pack.records
        }
        claims: list[AnswerClaim] = []

        for claim in request.claims:
            context_text = " ".join(
                records_by_citation[citation_id].text
                for citation_id in claim.citation_ids
                if citation_id in records_by_citation
            )
            score = _support_score(claim.text, context_text)
            status = _support_status(score)
            claims.append(
                AnswerClaim(
                    claim_index=claim.claim_index,
                    text=claim.text,
                    citation_ids=claim.citation_ids,
                    support_status=status,
                    support_score=score,
                    support_reason=_support_reason(status, score),
                    method=DETERMINISTIC_SUPPORT_METHOD,
                )
            )

        return SupportCheckResult(
            claims=claims,
            method=DETERMINISTIC_SUPPORT_METHOD,
            metadata={"algorithm": "claim-token-overlap-and-substring"},
        )


def evaluate_abstention(
    *,
    insufficient_context: bool,
    supported_claim_count: int,
    total_claim_count: int,
    min_supported_claim_ratio: float,
    best_context_relevance: float | None = None,
    min_context_relevance: float | None = None,
    all_citations_dropped: bool = False,
) -> AbstentionDecision:
    if insufficient_context:
        return AbstentionDecision(abstained=True, reason="insufficient_context")
    if all_citations_dropped:
        return AbstentionDecision(abstained=True, reason="all_citations_dropped")
    if total_claim_count <= 0:
        return AbstentionDecision(abstained=True, reason="no_answer_claims")

    supported_ratio = supported_claim_count / total_claim_count
    if supported_claim_count <= 0 or supported_ratio < min_supported_claim_ratio:
        return AbstentionDecision(
            abstained=True,
            reason="supported_claim_ratio_below_threshold",
        )

    if (
        best_context_relevance is not None
        and min_context_relevance is not None
        and best_context_relevance < min_context_relevance
    ):
        return AbstentionDecision(abstained=True, reason="context_relevance_below_threshold")

    return AbstentionDecision(abstained=False)


def _normalize_marker(marker: str) -> str:
    match = _MARKER_RE.match(marker)
    if match is None:
        return ""
    return match.group(1).casefold()


def _support_score(claim_text: str, context_text: str) -> float:
    if not context_text.strip():
        return 0.0

    normalized_claim = " ".join(_WORD_RE.findall(claim_text.casefold()))
    normalized_context = " ".join(_WORD_RE.findall(context_text.casefold()))
    if normalized_claim and normalized_claim in normalized_context:
        return 1.0

    claim_terms = set(_WORD_RE.findall(claim_text.casefold()))
    if not claim_terms:
        return 0.0
    context_terms = set(_WORD_RE.findall(context_text.casefold()))
    return round(len(claim_terms & context_terms) / len(claim_terms), 4)


def _support_status(score: float) -> SupportStatus:
    if score >= 0.8:
        return "supported"
    if score >= 0.25:
        return "partial"
    return "unsupported"


def _support_reason(status: SupportStatus, score: float) -> str:
    return f"deterministic lexical checker marked the claim {status} with score {score:.4f}"
