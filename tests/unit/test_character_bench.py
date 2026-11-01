"""Research contract: absent clothing evidence must never become a perfect match."""

import pytest

from flint_graph.narrative.character_bench import (
    calibrate,
    clothing_overlap,
    compare_runs,
    reviewed_distances,
)


def test_clothing_score_ignores_identity_and_rating_tags_and_reports_unknown() -> None:
    assert clothing_overlap({"blue_coat": 0.9}, {"blue_coat": 0.8}) == pytest.approx(8 / 9)
    assert clothing_overlap({"white_hair": 1.0}, {"white_hair": 1.0}) is None
    assert clothing_overlap({"blue_coat": 0.9}, {"rating:safe": 1.0}) is None
    assert clothing_overlap({"blue_coat": 0.9}, {"red_dress": 0.9}) == 0
    assert clothing_overlap({"pants": 0.9}, {"no_pants": 0.9}) is None


def test_run_comparison_requires_identical_cases_references_and_scorer() -> None:
    left = {"dataset_sha256": "a", "scorer_sha256": "b", "cases": {"sit/101": 0.2}}
    right = {"dataset_sha256": "a", "scorer_sha256": "b", "cases": {"sit/101": 0.1}}
    assert compare_runs(left, right) == {"sit/101": -0.1}
    for change in ({"dataset_sha256": "c"}, {"scorer_sha256": "c"}, {"cases": {}}):
        with pytest.raises(ValueError, match="incompatible"):
            compare_runs(left, right | change)


def test_calibration_preserves_review_provenance_and_never_promotes_fixture_labels() -> None:
    result = calibrate([(0.1, True), (0.2, True), (0.3, False), (0.4, False)], "agent")
    assert result.threshold == pytest.approx(0.25)
    assert result.f1 == 1
    assert result.review_kind == "agent"
    assert result.production_ready is False
    with pytest.raises(ValueError, match="both classes"):
        calibrate([(0.1, True)], "creator")


@pytest.mark.parametrize("probability", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_model_probabilities_are_rejected(probability: float) -> None:
    with pytest.raises(ValueError):
        clothing_overlap({"coat": probability}, {"coat": 0.9})


def test_zero_confidence_is_unknown_even_with_zero_cutoff() -> None:
    assert clothing_overlap({"coat": 0.0}, {"coat": 0.0}, threshold=0) is None


def test_reviews_cannot_be_applied_to_different_images_or_duplicate_cases() -> None:
    review = {
        "scores_sha256": "abc",
        "review_kind": "agent",
        "ratings": [
            {"id": "sit/101", "identity": "same"},
            {"id": "back/101", "identity": "unknown"},
        ],
    }
    distances = {"sit/101": 0.1, "back/101": 0.2}
    assert reviewed_distances(review, "abc", distances) == [(0.1, True)]
    with pytest.raises(ValueError, match="different"):
        reviewed_distances(review, "changed", distances)
    with pytest.raises(ValueError, match="coverage"):
        reviewed_distances(review | {"ratings": [review["ratings"][0]] * 2}, "abc", distances)
    with pytest.raises(ValueError, match="reviewer"):
        reviewed_distances(review | {"review_kind": "unreviewed"}, "abc", distances)


def test_clothing_calibration_keeps_missing_score_unknown_despite_a_review() -> None:
    review = {
        "scores_sha256": "a",
        "review_kind": "creator",
        "ratings": [{"id": "visible", "clothes": "same"}, {"id": "hidden", "clothes": "drifted"}],
    }
    assert reviewed_distances(review, "a", {"visible": 0.1, "hidden": None}, axis="clothes") == [
        (0.1, True)
    ]
