from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from uuid import UUID

from flint_graph.application.entity_resolution.scoring import token_jaccard
from flint_graph.domain.enums import CandidateOutcome, EntityType

TYPE_MISMATCH_PENALTY = 0.4
ACRONYM_MATCH_SCORE = 0.92

_ACRONYM_STOPWORDS = frozenset({"a", "an", "and", "for", "in", "of", "the", "to"})


@dataclass(frozen=True, slots=True)
class ProposalCandidateEntity:
    entity_id: UUID
    entity_type: EntityType
    normalized_name: str
    alias_forms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProposalCandidateFeatures:
    normalized_name_equal: bool
    alias_exact: bool
    sequence_similarity: float
    token_jaccard: float
    acronym_match: bool
    type_compatible: bool


@dataclass(frozen=True, slots=True)
class ScoredProposalCandidate:
    target: ProposalCandidateEntity
    features: ProposalCandidateFeatures
    score: float
    outcome: CandidateOutcome
    reasons: tuple[str, ...]


def score_proposal_candidate(
    source: ProposalCandidateEntity,
    target: ProposalCandidateEntity,
    *,
    auto_threshold: float,
    review_threshold: float,
) -> ScoredProposalCandidate:
    features = compute_proposal_candidate_features(source, target)
    score = _score_features(features)
    outcome = _outcome_for_score(
        score, auto_threshold=auto_threshold, review_threshold=review_threshold
    )
    return ScoredProposalCandidate(
        target=target,
        features=features,
        score=score,
        outcome=outcome,
        reasons=_reasons_for_features(features),
    )


def compute_proposal_candidate_features(
    source: ProposalCandidateEntity, target: ProposalCandidateEntity
) -> ProposalCandidateFeatures:
    source_surfaces = _surfaces(source)
    target_surfaces = _surfaces(target)
    normalized_name_equal = source.normalized_name == target.normalized_name
    return ProposalCandidateFeatures(
        normalized_name_equal=normalized_name_equal,
        alias_exact=_alias_exact(source, target),
        sequence_similarity=max(
            _sequence_similarity(source_surface, target_surface)
            for source_surface in source_surfaces
            for target_surface in target_surfaces
        ),
        token_jaccard=max(
            token_jaccard(source_surface, target_surface)
            for source_surface in source_surfaces
            for target_surface in target_surfaces
        ),
        acronym_match=any(
            _acronym_matches(source_surface, target_surface)
            for source_surface in source_surfaces
            for target_surface in target_surfaces
        ),
        type_compatible=_types_compatible(source.entity_type, target.entity_type),
    )


def _score_features(features: ProposalCandidateFeatures) -> float:
    if features.normalized_name_equal or features.alias_exact:
        base = 1.0
    elif features.acronym_match:
        base = max(
            features.sequence_similarity,
            features.token_jaccard,
            ACRONYM_MATCH_SCORE,
        )
    else:
        base = max(features.sequence_similarity, features.token_jaccard)

    if not features.type_compatible:
        base *= TYPE_MISMATCH_PENALTY
    return max(0.0, min(1.0, base))


def _outcome_for_score(
    score: float, *, auto_threshold: float, review_threshold: float
) -> CandidateOutcome:
    if score >= auto_threshold:
        return CandidateOutcome.AUTO
    if score >= review_threshold:
        return CandidateOutcome.REVIEW
    return CandidateOutcome.REJECT


def _reasons_for_features(features: ProposalCandidateFeatures) -> tuple[str, ...]:
    reasons: list[str] = []
    if features.normalized_name_equal:
        reasons.append("normalized_name_equal")
    if features.alias_exact:
        reasons.append("alias_exact")
    if features.sequence_similarity >= 0.8:
        reasons.append("sequence_similarity")
    if features.token_jaccard >= 0.5:
        reasons.append("token_jaccard")
    if features.acronym_match:
        reasons.append("acronym_match")
    reasons.append("type_compatible" if features.type_compatible else "type_mismatch")
    return tuple(reasons)


def _surfaces(entity: ProposalCandidateEntity) -> tuple[str, ...]:
    values = (entity.normalized_name, *entity.alias_forms)
    return tuple(dict.fromkeys(value for value in values if value))


def _alias_exact(source: ProposalCandidateEntity, target: ProposalCandidateEntity) -> bool:
    source_aliases = frozenset(alias for alias in source.alias_forms if alias)
    target_aliases = frozenset(alias for alias in target.alias_forms if alias)
    return (
        source.normalized_name in target_aliases
        or target.normalized_name in source_aliases
        or bool(source_aliases & target_aliases)
    )


def _sequence_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(a=a, b=b, autojunk=False).ratio()


def _acronym_matches(a: str, b: str) -> bool:
    return _acronym(a) == b or _acronym(b) == a


def _acronym(text: str) -> str:
    tokens = [token for token in text.split() if token not in _ACRONYM_STOPWORDS]
    if len(tokens) < 2:
        return ""
    return "".join(token[0] for token in tokens if token)


def _types_compatible(a: EntityType, b: EntityType) -> bool:
    return a == b or EntityType.OTHER in {a, b}
