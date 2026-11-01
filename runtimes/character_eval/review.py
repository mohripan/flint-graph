"""Create a blank review, or fit a provisional threshold from explicit reviewed labels."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from score import digest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from flint_graph.narrative.character_bench import calibrate, reviewed_distances


def review(args):
    scores = json.loads(args.scores.read_text(encoding="utf-8"))
    score_hash = digest(args.scores)
    if args.ratings:
        document = json.loads(args.ratings.read_text(encoding="utf-8"))
        result = {
            "scores_sha256": score_hash,
            "review_kind": document["review_kind"],
            "note": "Fit only; evaluate on held-out characters before adoption.",
            "production_ready": False,
            "calibrations": {},
        }
        for axis in ("identity", "clothes"):
            distances = {
                row["id"]: (
                    row["identity_distance"]["ccip-caformer_b36-24"]
                    if axis == "identity"
                    else 1 - row["clothing_overlap_v1"]
                    if row["clothing_overlap_v1"] is not None
                    else None
                )
                for row in scores["rows"]
            }
            pairs = reviewed_distances(document, score_hash, distances, axis=axis)
            if {same for _, same in pairs} == {True, False}:
                fitted = asdict(calibrate(pairs, document["review_kind"]))
                if axis == "clothes":
                    fitted["overlap_minimum"] = 1 - fitted["threshold"]
                result["calibrations"][axis] = fitted | {"labelled_pairs": len(pairs)}
            else:
                result["calibrations"][axis] = {
                    "unavailable": "both labelled classes required",
                    "labelled_pairs": len(pairs),
                }
    else:
        result = {
            "schema": 1,
            "scores_sha256": score_hash,
            "review_kind": "unreviewed",
            "reviewer": "",
            "ratings": [
                {
                    "id": row["id"],
                    "identity": "unknown",
                    "clothes": "unknown",
                    "pose": "unknown",
                    "note": "",
                }
                for row in scores["rows"]
            ],
        }
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    print(json.dumps({"written": str(args.out), "review_kind": result.get("review_kind")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--ratings", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    review(parser.parse_args())
