from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from flint_graph.domain.enums import EntityType, MergeCandidateBand

TYPE_MISMATCH_PENALTY = 0.4
SHARED_DOCUMENT_BOOST = 0.1


@dataclass(frozen=True)
class MentionKey:
    normalized_text: str
    entity_type: EntityType
    document_id: UUID


@dataclass(frozen=True)
class CandidateEntity:
    entity_id: UUID
    entity_type: EntityType
    normalized_name: str
    alias_forms: tuple[str, ...]
    document_ids: frozenset[UUID]


@dataclass(frozen=True)
class CandidateFeatures:
    name_similarity: float
    type_match: bool
    alias_exact: bool
    shared_document: bool


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: CandidateEntity
    features: CandidateFeatures
    score: float
    band: MergeCandidateBand


def _tokens(text: str) -> set[str]:
    return set(text.split())


def token_jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _trigrams(text: str) -> set[str]:
    padded = f"  {text} "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


def trigram_similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0 if a else 0.0
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def name_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return max(token_jaccard(a, b), trigram_similarity(a, b))


def compute_features(mention: MentionKey, candidate: CandidateEntity) -> CandidateFeatures:
    surfaces = (candidate.normalized_name, *candidate.alias_forms)
    best_similarity = max(name_similarity(mention.normalized_text, surface) for surface in surfaces)
    alias_exact = any(mention.normalized_text == surface for surface in surfaces)
    return CandidateFeatures(
        name_similarity=best_similarity,
        type_match=mention.entity_type == candidate.entity_type,
        alias_exact=alias_exact,
        shared_document=mention.document_id in candidate.document_ids,
    )


def score_candidate(features: CandidateFeatures) -> float:
    """Combine features into a deterministic match score in [0, 1].

    Name/alias similarity dominates. An exact name or alias match is treated as a
    perfect surface match. A type mismatch heavily penalizes the score, and a
    shared source document nudges it up as a weak co-occurrence signal.
    """

    base = 1.0 if features.alias_exact else features.name_similarity
    if not features.type_match:
        base *= TYPE_MISMATCH_PENALTY
    if features.shared_document:
        base += (1.0 - base) * SHARED_DOCUMENT_BOOST
    return max(0.0, min(1.0, base))


def band_for_score(
    score: float, *, auto_threshold: float, review_threshold: float
) -> MergeCandidateBand:
    if score >= auto_threshold:
        return MergeCandidateBand.AUTO
    if score >= review_threshold:
        return MergeCandidateBand.REVIEW
    return MergeCandidateBand.REJECT


def score_candidates(
    mention: MentionKey,
    candidates: Iterable[CandidateEntity],
    *,
    auto_threshold: float,
    review_threshold: float,
) -> list[ScoredCandidate]:
    """Score every candidate and return them best-first.

    Ordering is deterministic: descending score, then ascending entity id so ties
    resolve the same way on every run.
    """

    scored: list[ScoredCandidate] = []
    for candidate in candidates:
        features = compute_features(mention, candidate)
        score = score_candidate(features)
        band = band_for_score(
            score, auto_threshold=auto_threshold, review_threshold=review_threshold
        )
        scored.append(ScoredCandidate(candidate, features, score, band))
    scored.sort(key=lambda item: (-item.score, str(item.candidate.entity_id)))
    return scored
