"""Opt-in measured 12 GB resource contract; no shared services are stopped."""

import json
import os
import subprocess
from pathlib import Path

import pytest

MODELS = os.environ.get("FLINT_GRAPH_CHARACTER_GPU_MODELS")
pytestmark = pytest.mark.skipif(not MODELS, reason="Set FLINT_GRAPH_CHARACTER_GPU_MODELS")
ROOT = Path(__file__).resolve().parents[2]


def test_cached_control_renders_fixed_matrix_with_device_headroom(tmp_path: Path) -> None:
    output = Path(os.environ.get("FLINT_GRAPH_CHARACTER_CACHED_OUTPUT", str(tmp_path / "run")))
    python = ROOT / "runtimes/character_lab/.venv/Scripts/python.exe"
    if not python.exists():
        python = ROOT / "runtimes/character_lab/.venv/bin/python"
    result = subprocess.run(
        [
            str(python),
            str(ROOT / "runtimes/character_lab/generate.py"),
            "--dataset",
            str(ROOT / "evals/character-preservation/pilot-v1/dataset.json"),
            "--models",
            str(MODELS),
            "--method",
            "control",
            "--cache-text-embeddings",
            "--out",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=900,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    run = json.loads((output / "run.json").read_text())
    assert len(run["images"]) == 16
    assert max(row["torch_peak_bytes"] for row in run["images"]) < 9.5 * 2**30
    assert max(row["device_used_bytes_after"] for row in run["images"]) < 11 * 2**30
    assert all((output / row["image"]).is_file() for row in run["images"])
