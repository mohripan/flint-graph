"""Offline research scoring contracts; these are advisory, never approval rules."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

# Version 1 is deliberately small and inspectable. Colour variants inherit their
# garment's membership. Identity, character-name and rating tags are never clothes.
CLOTHING_V1 = frozenset(
    "coat jacket shirt blouse sweater cardigan vest dress skirt pants trousers shorts "
    "scarf necktie bowtie boots shoes sneakers sandals gloves hat beret cap uniform "
    "kimono yukata hoodie cape cloak socks thighhighs pantyhose leggings belt ribbon "
    "overalls apron suspenders corset bodysuit leotard armor robe footwear suit".split()
)


def clothing_overlap(
    reference: Mapping[str, float], candidate: Mapping[str, float], *, threshold: float = 0.35
) -> float | None:
    """Weighted Jaccard of visible garment tags; None means insufficient evidence.

    Low probabilities are discarded. A back view or occlusion can lower the score;
    it is a reason to review, never proof that an outfit changed.
    """
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("invalid threshold")

    def clothes(tags: Mapping[str, float]) -> dict[str, float]:
        for value in tags.values():
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("invalid tag probability")
        return {
            tag: value
            for tag, value in tags.items()
            if value > 0
            and value >= threshold
            and not tag.startswith(("no_", "removed_"))
            and tag.rsplit("_", 1)[-1] in CLOTHING_V1
        }

    a, b = clothes(reference), clothes(candidate)
    if not a or not b:
        return None
    keys = a.keys() | b.keys()
    return sum(min(a.get(k, 0), b.get(k, 0)) for k in keys) / sum(
        max(a.get(k, 0), b.get(k, 0)) for k in keys
    )


def compare_runs(left: Mapping[str, object], right: Mapping[str, object]) -> dict[str, float]:
    """Candidate minus baseline CCIP difference; negative means improved identity.

    The dataset hash covers case IDs, seeds, prompts and reference bytes. Methods
    may change; dataset, scorer, and completed case coverage must match exactly.
    """
    if any(
        not left.get(key) or left.get(key) != right.get(key)
        for key in ("dataset_sha256", "scorer_sha256")
    ):
        raise ValueError("incompatible dataset or scorer")
    a, b = left.get("cases"), right.get("cases")
    if not isinstance(a, dict) or not isinstance(b, dict) or a.keys() != b.keys() or not a:
        raise ValueError("incompatible case coverage")
    for value in (*a.values(), *b.values()):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("incompatible missing or nonfinite score")
    return {key: float(b[key]) - float(value) for key, value in a.items()}


@dataclass(frozen=True)
class Calibration:
    threshold: float
    f1: float
    review_kind: Literal["agent", "creator"]
    # A fitted training-set threshold is never qualified for production by itself.
    production_ready: bool = False


def calibrate(
    labelled_distances: list[tuple[float, bool]], review_kind: Literal["agent", "creator"]
) -> Calibration:
    """Fit a provisional lower-is-same cutoff, retaining who supplied the labels.

    Evaluate on held-out characters/seeds before adoption; this is a fit statistic,
    not a cross-validated accuracy estimate. Clothing uses a separate calibration.
    """
    if review_kind not in ("agent", "creator"):
        raise ValueError("invalid reviewer")
    if {label for _, label in labelled_distances} != {True, False}:
        raise ValueError("calibration requires both classes")
    if any(not math.isfinite(v) or v < 0 for v, _ in labelled_distances):
        raise ValueError("invalid distance")
    values = sorted({v for v, _ in labelled_distances})
    cutoffs = [values[0] - 1e-9, *[(a + b) / 2 for a, b in pairwise(values)], values[-1]]
    best = (0.0, cutoffs[0])
    for cutoff in cutoffs:
        tp = sum(v <= cutoff and same for v, same in labelled_distances)
        fp = sum(v <= cutoff and not same for v, same in labelled_distances)
        fn = sum(v > cutoff and same for v, same in labelled_distances)
        f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
        if f1 > best[0]:
            best = f1, cutoff
    return Calibration(best[1], best[0], review_kind)


def reviewed_distances(
    review: Mapping[str, object],
    scores_sha256: str,
    distances: Mapping[str, float | None],
    *,
    axis: Literal["identity", "clothes"] = "identity",
) -> list[tuple[float, bool]]:
    """Read identity labels only when the review pins these exact scored images.

    Unknown labels are omitted, never filled with a predicted verdict. Full case
    coverage prevents silently calibrating a different or duplicated subset.
    """
    if review.get("scores_sha256") != scores_sha256:
        raise ValueError("review belongs to different scores/images")
    if review.get("review_kind") not in ("agent", "creator"):
        raise ValueError("explicit reviewer kind required")
    ratings = review.get("ratings")
    if not isinstance(ratings, list) or any(not isinstance(row, dict) for row in ratings):
        raise ValueError("invalid review coverage")
    ids = [row.get("id") for row in ratings]
    if any(not isinstance(key, str) for key in ids):
        raise ValueError("invalid review coverage")
    if len(ids) != len(set(ids)) or set(ids) != distances.keys():
        raise ValueError("invalid review coverage")
    result = []
    for row in ratings:
        label = row.get(axis)
        if label not in ("same", "drifted", "unknown"):
            raise ValueError("explicit review label required")
        distance = distances[row["id"]]
        if label != "unknown" and distance is not None:
            if not math.isfinite(distance) or distance < 0:
                raise ValueError("invalid distance")
            result.append((distance, label == "same"))
    return result
