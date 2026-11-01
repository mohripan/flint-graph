"""Aggregate complete compatible measured runs; never overwrite an accepted report."""

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from flint_graph.narrative.character_bench import compare_runs


def summary(scores_dir, output):
    runs = []
    for path in sorted(scores_dir.glob("*/scores.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        run["source_scores_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        runs.append(run)
    if not runs:
        raise ValueError("no scored runs")
    compatible = []
    for run in runs:
        cases = {row["id"]: row["identity_distance"]["ccip-caformer_b36-24"] for row in run["rows"]}
        if len(cases) != len(run["rows"]) or cases.keys() != {
            r["id"] for r in run["run"]["images"]
        }:
            raise ValueError("incompatible duplicate or incomplete cases")
        compatible.append(
            {
                "cases": cases,
                "dataset_sha256": run["dataset_sha256"],
                "scorer_sha256": run["scorer_sha256"],
            }
        )
        compare_runs(compatible[0], compatible[-1])
    methods = {}
    for run, comparable in zip(runs, compatible, strict=True):
        name = run["run"]["method"]
        if name in methods:
            raise ValueError("duplicate method")
        garments = [
            r["clothing_overlap_v1"] for r in run["rows"] if r["clothing_overlap_v1"] is not None
        ]
        images = run["run"]["images"]
        device_samples = [
            r["device_used_bytes_after"] for r in images if r["device_used_bytes_after"] is not None
        ]
        methods[name] = {
            "cases": len(run["rows"]),
            "mean_b36_distance": statistics.mean(comparable["cases"].values()),
            "mean_clothing_overlap": statistics.mean(garments) if garments else None,
            "unknown_clothing_count": len(run["rows"]) - len(garments),
            "median_generation_seconds": statistics.median(r["seconds"] for r in images),
            "generation_load_seconds": run["run"]["load_seconds"],
            "torch_peak_mib": max(r["torch_peak_bytes"] for r in images) / 2**20,
            "device_used_after_max_mib": max(device_samples) / 2**20 if device_samples else None,
            "scoring_load_seconds": run["load_seconds"],
            "median_scoring_seconds": statistics.median(r["seconds"] for r in run["rows"]),
            "scoring_rss_end_mib": run["cpu_rss_bytes"] / 2**20,
            "source_scores_sha256": run["source_scores_sha256"],
        }
    result = {
        "schema": 1,
        "dataset_sha256": runs[0]["dataset_sha256"],
        "scorer_sha256": runs[0]["scorer_sha256"],
        "methods": methods,
        "warning": "Metrics do not establish pose success, fine outfits or creator approval.",
    }
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(summary(args.scores_dir, args.out)))
