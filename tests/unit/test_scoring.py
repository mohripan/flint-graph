from uuid import UUID

from flint_graph.application.entity_resolution import (
    CandidateEntity,
    CandidateFeatures,
    MentionKey,
    band_for_score,
    compute_features,
    name_similarity,
    score_candidate,
    score_candidates,
)
from flint_graph.domain.enums import EntityType, MergeCandidateBand

DOC = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER_DOC = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _entity(
    entity_id: str,
    name: str,
    *,
    aliases: tuple[str, ...] = (),
    docs: frozenset[UUID] = frozenset(),
) -> CandidateEntity:
    return CandidateEntity(
        entity_id=UUID(entity_id),
        entity_type=EntityType.ORGANIZATION,
        normalized_name=name,
        alias_forms=aliases,
        document_ids=docs,
    )


def _mention(text: str, *, entity_type: EntityType = EntityType.ORGANIZATION) -> MentionKey:
    return MentionKey(normalized_text=text, entity_type=entity_type, document_id=DOC)


def test_name_similarity_exact_and_empty() -> None:
    assert name_similarity("acme corporation", "acme corporation") == 1.0
    assert name_similarity("", "acme") == 0.0
    assert name_similarity("acme", "") == 0.0


def test_name_similarity_is_token_order_invariant() -> None:
    assert name_similarity("jane doe", "doe jane") == 1.0


def test_name_similarity_rewards_near_matches_over_unrelated() -> None:
    near = name_similarity("acme corp", "acme corporation")
    unrelated = name_similarity("acme corp", "globex industries")
    assert 0.0 <= unrelated < near < 1.0


def test_compute_features_detects_alias_exact_and_shared_document() -> None:
    candidate = _entity(
        "11111111-1111-4111-8111-111111111111",
        "acme corporation",
        aliases=("acme corp",),
        docs=frozenset({DOC}),
    )
    features = compute_features(_mention("acme corp"), candidate)

    assert features.alias_exact is True
    assert features.name_similarity == 1.0
    assert features.type_match is True
    assert features.shared_document is True


def test_compute_features_marks_type_mismatch() -> None:
    candidate = _entity("11111111-1111-4111-8111-111111111111", "acme corporation")
    features = compute_features(
        _mention("acme corporation", entity_type=EntityType.PERSON), candidate
    )

    assert features.type_match is False


def test_score_candidate_rewards_exact_and_penalizes_type_mismatch() -> None:
    exact = CandidateFeatures(
        name_similarity=1.0, type_match=True, alias_exact=True, shared_document=False
    )
    assert score_candidate(exact) == 1.0

    mismatch = CandidateFeatures(
        name_similarity=1.0, type_match=False, alias_exact=True, shared_document=False
    )
    assert score_candidate(mismatch) == 0.4


def test_score_candidate_shared_document_nudges_up() -> None:
    without = CandidateFeatures(
        name_similarity=0.5, type_match=True, alias_exact=False, shared_document=False
    )
    with_doc = CandidateFeatures(
        name_similarity=0.5, type_match=True, alias_exact=False, shared_document=True
    )
    assert score_candidate(without) == 0.5
    assert score_candidate(with_doc) > 0.5
    assert score_candidate(with_doc) <= 1.0


def test_band_for_score_boundaries() -> None:
    def band(score: float) -> MergeCandidateBand:
        return band_for_score(score, auto_threshold=0.85, review_threshold=0.6)

    assert band(0.9) == MergeCandidateBand.AUTO
    assert band(0.85) == MergeCandidateBand.AUTO
    assert band(0.7) == MergeCandidateBand.REVIEW
    assert band(0.6) == MergeCandidateBand.REVIEW
    assert band(0.59) == MergeCandidateBand.REJECT


def test_score_candidates_orders_by_score_then_entity_id() -> None:
    mention = _mention("acme corporation")
    a = _entity("11111111-1111-4111-8111-111111111111", "acme corporation")
    c = _entity("33333333-3333-4333-8333-333333333333", "acme corporation")
    b = _entity("22222222-2222-4222-8222-222222222222", "acme corp")

    scored = score_candidates(
        mention, [b, c, a], auto_threshold=0.85, review_threshold=0.6
    )

    # a and c are exact ties (score 1.0) -> ordered by ascending entity id; b is lower.
    assert [item.candidate.entity_id for item in scored] == [a.entity_id, c.entity_id, b.entity_id]
    assert scored[0].score == 1.0 and scored[0].band == MergeCandidateBand.AUTO
    assert scored[-1].candidate is b
