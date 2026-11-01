"""Compare fully compatible scored runs and write a blank, provenance-aware rating file."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from flint_graph.narrative.character_bench import compare_runs


def compare(baseline, candidate, out):
    a, b = [json.loads(path.read_text(encoding="utf-8")) for path in (baseline, candidate)]
    metric = "ccip-caformer_b36-24"
    summaries = [
        {
            "dataset_sha256": r["dataset_sha256"],
            "scorer_sha256": r["scorer_sha256"],
            "cases": {row["id"]: row["identity_distance"][metric] for row in r["rows"]},
        }
        for r in (a, b)
    ]
    differences = compare_runs(*summaries)
    result = {
        "schema": 1,
        "baseline": a["run"]["method"],
        "candidate": b["run"]["method"],
        "dataset_sha256": a["dataset_sha256"],
        "scorer_sha256": a["scorer_sha256"],
        "distance_change_b36": differences,
        "mean_distance_change": sum(differences.values()) / len(differences),
        "warning": "Metric changes are not creator approval or pose accuracy.",
    }
    with out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compare(args.baseline, args.candidate, args.out)))
