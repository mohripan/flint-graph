from uuid import UUID

from flint_graph.application.proposal_candidates import (
    ProposalCandidateEntity,
    score_proposal_candidate,
)
from flint_graph.domain.enums import CandidateOutcome, EntityType


def test_scores_alias_exact_candidate_as_auto_with_explainable_features() -> None:
    source = ProposalCandidateEntity(
        entity_id=UUID("00000000-0000-0000-0000-000000000001"),
        entity_type=EntityType.ORGANIZATION,
        normalized_name="acme corp",
        alias_forms=("acme",),
    )
    target = ProposalCandidateEntity(
        entity_id=UUID("00000000-0000-0000-0000-000000000002"),
        entity_type=EntityType.ORGANIZATION,
        normalized_name="acme corporation",
        alias_forms=("acme corp",),
    )

    scored = score_proposal_candidate(
        source,
        target,
        auto_threshold=0.92,
        review_threshold=0.62,
    )

    assert scored.outcome == CandidateOutcome.AUTO
    assert scored.score == 1.0
    assert scored.features.alias_exact is True
    assert scored.features.normalized_name_equal is False
    assert scored.features.type_compatible is True
    assert "alias_exact" in scored.reasons


def test_acronym_agreement_surfaces_review_candidate_without_exact_name() -> None:
    source = ProposalCandidateEntity(
        entity_id=UUID("00000000-0000-0000-0000-000000000003"),
        entity_type=EntityType.ORGANIZATION,
        normalized_name="nasa",
    )
    target = ProposalCandidateEntity(
        entity_id=UUID("00000000-0000-0000-0000-000000000004"),
        entity_type=EntityType.ORGANIZATION,
        normalized_name="national aeronautics and space administration",
    )

    scored = score_proposal_candidate(
        source,
        target,
        auto_threshold=0.95,
        review_threshold=0.62,
    )

    assert scored.outcome == CandidateOutcome.REVIEW
    assert scored.features.acronym_match is True
    assert "acronym_match" in scored.reasons


def test_type_mismatch_penalizes_candidate_to_reject() -> None:
    source = ProposalCandidateEntity(
        entity_id=UUID("00000000-0000-0000-0000-000000000005"),
        entity_type=EntityType.PERSON,
        normalized_name="berlin",
    )
    target = ProposalCandidateEntity(
        entity_id=UUID("00000000-0000-0000-0000-000000000006"),
        entity_type=EntityType.PLACE,
        normalized_name="berlin",
    )

    scored = score_proposal_candidate(
        source,
        target,
        auto_threshold=0.92,
        review_threshold=0.62,
    )

    assert scored.outcome == CandidateOutcome.REJECT
    assert scored.features.normalized_name_equal is True
    assert scored.features.alias_exact is False
    assert scored.features.type_compatible is False
    assert "type_mismatch" in scored.reasons
