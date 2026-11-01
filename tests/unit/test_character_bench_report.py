"""The report consumes measured manifests and refuses incomparable methods."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_report_aggregates_measured_runs_and_refuses_mismatched_scorers(tmp_path: Path) -> None:
    base = {
        "dataset_sha256": "dataset",
        "scorer_sha256": "scorer",
        "rows": [
            {
                "id": "sit/101",
                "identity_distance": {"ccip-caformer_b36-24": 0.2},
                "clothing_overlap_v1": 0.5,
                "seconds": 1,
            }
        ],
        "run": {
            "method": "ip",
            "load_seconds": 2,
            "images": [
                {
                    "id": "sit/101",
                    "seconds": 10,
                    "torch_peak_bytes": 1048576,
                    "device_used_bytes_after": 2097152,
                }
            ],
        },
        "load_seconds": 3,
        "cpu_rss_bytes": 4194304,
    }
    for name in ("ip", "locked"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "scores.json").write_text(
            json.dumps(base | {"run": base["run"] | {"method": name}})
        )
    command = [
        sys.executable,
        str(ROOT / "runtimes/character_eval/report.py"),
        "--scores-dir",
        str(tmp_path),
        "--out",
        str(tmp_path / "report.json"),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["methods"]["ip"]["mean_b36_distance"] == 0.2
    assert report["methods"]["ip"]["median_generation_seconds"] == 10
    assert report["methods"]["ip"]["torch_peak_mib"] == 1
    changed = base | {"scorer_sha256": "changed"}
    (tmp_path / "locked/scores.json").write_text(json.dumps(changed))
    (tmp_path / "report.json").unlink()
    result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "incompatible" in result.stderr
    assert not (tmp_path / "report.json").exists()


def test_report_preserves_unmeasured_device_memory_as_unknown(tmp_path: Path) -> None:
    folder = tmp_path / "ip-pair"
    folder.mkdir()
    run = {
        "dataset_sha256": "pair",
        "scorer_sha256": "scorer",
        "rows": [
            {
                "id": "left",
                "identity_distance": {"ccip-caformer_b36-24": 0.1},
                "clothing_overlap_v1": None,
                "seconds": 1,
            }
        ],
        "run": {
            "method": "ip-pair",
            "load_seconds": 1,
            "images": [
                {
                    "id": "left",
                    "seconds": 1,
                    "torch_peak_bytes": 1048576,
                    "device_used_bytes_after": None,
                }
            ],
        },
        "load_seconds": 1,
        "cpu_rss_bytes": 1048576,
    }
    (folder / "scores.json").write_text(json.dumps(run))
    command = [
        sys.executable,
        str(ROOT / "runtimes/character_eval/report.py"),
        "--scores-dir",
        str(tmp_path),
        "--out",
        str(tmp_path / "report.json"),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["methods"]["ip-pair"]["device_used_after_max_mib"] is None
    assert report["methods"]["ip-pair"]["unknown_clothing_count"] == 1
