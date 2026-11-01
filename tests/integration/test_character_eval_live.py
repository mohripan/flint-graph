"""Opt-in pinned CPU inference. Never downloads models or reads Studio projects."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

MODELS = os.environ.get("FLINT_GRAPH_CHARACTER_EVAL_MODELS")
pytestmark = pytest.mark.skipif(not MODELS, reason="Set FLINT_GRAPH_CHARACTER_EVAL_MODELS")
ROOT = Path(__file__).resolve().parents[2]


def test_offline_scorer_self_match_and_tamper_refusal(tmp_path: Path) -> None:
    original = json.loads((ROOT / "evals/character-preservation/pilot-v1/dataset.json").read_text())
    ref = ROOT / "evals/character-preservation/pilot-v1/references/aster.png"
    (tmp_path / "reference.png").write_bytes(ref.read_bytes())
    entry = {"image": "reference.png", "sha256": hashlib.sha256(ref.read_bytes()).hexdigest()}
    other = ROOT / "evals/character-preservation/pilot-v1/references/nera.png"
    (tmp_path / "other.png").write_bytes(other.read_bytes())
    other_entry = {"image": "other.png", "sha256": hashlib.sha256(other.read_bytes()).hexdigest()}
    dataset = original | {
        "references": {"aster": entry, "nera": other_entry},
        "cases": [{"id": "self", "character": "aster"}],
    }
    dataset_file = tmp_path / "dataset.json"
    dataset_file.write_text(json.dumps(dataset))
    run = {
        "dataset_sha256": hashlib.sha256(
            json.dumps(dataset, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "images": [entry | {"id": "self"}],
    }
    run_file = tmp_path / "run.json"
    run_file.write_text(json.dumps(run))
    python = ROOT / "runtimes/character_eval/.venv/Scripts/python.exe"
    if not python.exists():
        python = ROOT / "runtimes/character_eval/.venv/bin/python"
    command = [
        str(python),
        str(ROOT / "runtimes/character_eval/score.py"),
        "--dataset",
        str(dataset_file),
        "--run",
        str(run_file),
        "--models",
        str(MODELS),
        "--out",
        str(tmp_path / "scores"),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    scores = json.loads((tmp_path / "scores/scores.json").read_text())
    assert max(scores["rows"][0]["identity_distance"].values()) < 1e-5
    contrasts = scores["rows"][0]["identity_by_reference"]
    assert max(contrasts["aster"].values()) < 1e-5
    assert min(contrasts["nera"].values()) > 0.1
    assert scores["rows"][0]["clothing_overlap_v1"] == pytest.approx(1)
    assert scores["rows"][0]["rating_tags_never_prompt"]
    assert not (
        scores["rows"][0]["rating_tags_never_prompt"].keys()
        & scores["rows"][0]["general_tags"].keys()
    )
    assert (tmp_path / "scores/contact-sheet.jpg").is_file()
    # Input hashes are enforced before loading the models, even on repeat runs.
    (tmp_path / "reference.png").write_bytes(b"tampered")
    rejected = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert rejected.returncode != 0
    assert "fixture hash mismatch" in rejected.stderr
