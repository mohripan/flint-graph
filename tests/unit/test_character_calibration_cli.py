import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_calibration_deduplicates_images_and_keeps_agent_reviews_out_of_creator_fits(
    tmp_path: Path,
) -> None:
    dataset = {
        "references": {"a": {"sha256": "a" * 64}},
        "cases": [{"id": "same", "character": "a"}, {"id": "other", "character": "a"}],
    }
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(dataset))
    dataset_hash = hashlib.sha256(
        json.dumps(dataset, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    command = [
        sys.executable,
        str(ROOT / "runtimes/character_eval/calibration.py"),
        "--review-kind",
        "agent",
        "--out",
        str(tmp_path / "fit.json"),
    ]
    for method in ("original", "cached"):
        scores = {
            "dataset_sha256": dataset_hash,
            "scorer_sha256": "frozen-scorer",
            "run": {
                "method": method,
                "images": [{"id": "same", "sha256": "1" * 64}, {"id": "other", "sha256": "2" * 64}],
            },
            "references": {"a": {"general_tags": {"coat": 0.8}}},
            "rows": [
                {
                    "id": "same",
                    "identity_distance": {"ccip-caformer_b36-24": 0.1},
                    "general_tags": {"coat": 0.8},
                },
                {
                    "id": "other",
                    "identity_distance": {"ccip-caformer_b36-24": 0.3},
                    "general_tags": {"dress": 0.8},
                },
            ],
        }
        score_path = tmp_path / f"{method}.json"
        score_path.write_text(json.dumps(scores))
        review = {
            "review_kind": "agent",
            "scores_sha256": hashlib.sha256(score_path.read_bytes()).hexdigest(),
            "ratings": [
                {"id": "same", "identity": "same", "clothes": "same"},
                {"id": "other", "identity": "drifted", "clothes": "drifted"},
            ],
        }
        review_path = tmp_path / f"{method}-review.json"
        review_path.write_text(json.dumps(review))
        command += ["--entry", str(score_path), str(review_path), str(dataset_path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "fit.json").read_text())
    assert report["unique_pairs"] == 2
    assert report["duplicate_pairs_removed"] == 2
    assert report["identity"]["threshold"] == 0.2
    assert report["clothing"]["0.35"]["overlap_minimum"] == 0.5
    assert report["production_ready"] is False
    (tmp_path / "fit.json").unlink()
    changed = command.copy()
    changed[changed.index("agent")] = "creator"
    result = subprocess.run(changed, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "reviewer kind" in result.stderr
    assert not (tmp_path / "fit.json").exists()
