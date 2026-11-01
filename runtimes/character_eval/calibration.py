"""Fit provisional single-character thresholds from explicitly pinned reviews.

Each --entry is scores, review, dataset. Mixed datasets are intentional here;
scorer versions and reviewer kind must agree. This is not a method comparison or
production activation. Duplicate image/reference/crop pairs count only once.
"""

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from flint_graph.narrative.character_bench import (
    calibrate,
    clothing_overlap,
    reviewed_distances,
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def fit(pairs, kind):
    if {same for _, same in pairs} != {True, False}:
        return {"unavailable": "both labelled classes required", "labelled_pairs": len(pairs)}
    result = asdict(calibrate(pairs, kind))
    cutoff = result["threshold"]
    result.update(
        labelled_pairs=len(pairs),
        confusion={
            "tp": sum(v <= cutoff and same for v, same in pairs),
            "fp": sum(v <= cutoff and not same for v, same in pairs),
            "tn": sum(v > cutoff and not same for v, same in pairs),
            "fn": sum(v > cutoff and same for v, same in pairs),
        },
    )
    return result


def collect(args):
    samples = {}
    parents = []
    fingerprints = set()
    observations = 0
    for score_name, review_name, dataset_name in args.entry:
        score_path, review_path, dataset_path = map(Path, (score_name, review_name, dataset_name))
        scores = json.loads(score_path.read_text(encoding="utf-8"))
        review = json.loads(review_path.read_text(encoding="utf-8"))
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        if review["review_kind"] != args.review_kind:
            raise ValueError("reviewer kind mismatch; never promote agent labels to creator labels")
        if canonical(dataset) != scores["dataset_sha256"]:
            raise ValueError("different dataset")
        distances = {
            r["id"]: r["identity_distance"]["ccip-caformer_b36-24"] for r in scores["rows"]
        }
        reviewed_distances(review, digest(score_path), distances)
        # Validate clothing labels/coverage too, preserving unknown observations.
        reviewed_distances(
            review, digest(score_path), dict.fromkeys(distances, None), axis="clothes"
        )
        cases = {c["id"]: c for c in dataset["cases"]}
        images = {r["id"]: r for r in scores["run"]["images"]}
        if cases.keys() != distances.keys() or images.keys() != distances.keys():
            raise ValueError("incomplete calibration source coverage")
        fingerprints.add(scores["scorer_sha256"])
        parents.append(
            {
                "scores_sha256": digest(score_path),
                "review_sha256": digest(review_path),
                "dataset_sha256": scores["dataset_sha256"],
                "method": scores["run"]["method"],
            }
        )
        ratings = {r["id"]: r for r in review["ratings"]}
        for row in scores["rows"]:
            case = cases[row["id"]]
            if len(case.get("participants", [])) > 1:
                raise ValueError(
                    "multi-person calibration requires separately qualified crop audits"
                )
            reference = dataset["references"][case["character"]]
            candidate = images[row["id"]]
            key = (
                reference["sha256"],
                tuple(reference.get("box", [])),
                candidate["sha256"],
                tuple(candidate.get("box", [])),
            )
            sample = {
                "identity": row["identity_distance"]["ccip-caformer_b36-24"],
                "reference_tags": scores["references"][case["character"]]["general_tags"],
                "candidate_tags": row["general_tags"],
                "labels": {axis: ratings[row["id"]][axis] for axis in ("identity", "clothes")},
            }
            observations += 1
            if key in samples:
                old = samples[key]
                if abs(old["identity"] - sample["identity"]) > 1e-5:
                    raise ValueError("inconsistent scores for identical image/reference pair")
                for axis in ("identity", "clothes"):
                    a, b = old["labels"][axis], sample["labels"][axis]
                    if a != "unknown" and b != "unknown" and a != b:
                        raise ValueError("conflicting reviews for identical image/reference pair")
                    if a == "unknown":
                        old["labels"][axis] = b
            else:
                samples[key] = sample
    if len(fingerprints) != 1:
        raise ValueError("incompatible scorers in calibration pool")
    values = list(samples.values())
    identity = fit(
        [
            (s["identity"], s["labels"]["identity"] == "same")
            for s in values
            if s["labels"]["identity"] != "unknown"
        ],
        args.review_kind,
    )
    clothing = {}
    for confidence in (0.15, 0.25, 0.35, 0.5):
        pairs = []
        unavailable = 0
        for sample in values:
            if sample["labels"]["clothes"] == "unknown":
                continue
            overlap = clothing_overlap(
                sample["reference_tags"], sample["candidate_tags"], threshold=confidence
            )
            if overlap is None:
                unavailable += 1
            else:
                pairs.append((1 - overlap, sample["labels"]["clothes"] == "same"))
        fitted = fit(pairs, args.review_kind)
        if "threshold" in fitted:
            fitted["overlap_minimum"] = 1 - fitted["threshold"]
        fitted["unknown_metric_count"] = unavailable
        clothing[str(confidence)] = fitted
    result = {
        "schema": 1,
        "review_kind": args.review_kind,
        "production_ready": False,
        "scorer_sha256": next(iter(fingerprints)),
        "parents": parents,
        "unique_pairs": len(values),
        "duplicate_pairs_removed": observations - len(values),
        "identity": identity,
        "clothing": clothing,
        "warning": "Fit statistics only. Confidence and match thresholds share the fit set; "
        "no held-out qualification. Coarse garment labels do not establish fine outfit fidelity.",
    }
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-kind", choices=("agent", "creator"), required=True)
    parser.add_argument(
        "--entry", nargs=3, action="append", required=True, metavar=("SCORES", "REVIEW", "DATASET")
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args)))
