"""Opt-in native qualification using a verified task-local official Godot binary."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from flint_graph.narrative import load_package
from flint_graph.narrative.export import export_godot

ENGINE = os.environ.get("FLINT_GRAPH_NARRATIVE_GODOT_BIN")
pytestmark = pytest.mark.skipif(
    not ENGINE, reason="Set FLINT_GRAPH_NARRATIVE_GODOT_BIN for real engine checks"
)
FIXTURE = Path(__file__).parents[1] / "fixtures/narrative/lantern_archive"


def native_environment(root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for key, name in [
        ("APPDATA", "Roaming"),
        ("LOCALAPPDATA", "Local"),
        ("TEMP", "Temp"),
        ("TMP", "Temp"),
    ]:
        path = root / "profile" / name
        path.mkdir(parents=True, exist_ok=True)
        environment[key] = str(path)
    return environment


def run_engine(
    project: Path, environment: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    assert ENGINE
    return subprocess.run(
        [ENGINE, "--headless", "--path", str(project), *args],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )


def test_real_pinned_engine_imports_and_checks_the_exported_content(tmp_path: Path) -> None:
    assert ENGINE
    with Path(ENGINE).open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    toolchain = json.loads(
        (Path(__file__).parents[2] / "runtimes/godot/toolchain.json").read_bytes()
    )
    assert digest == toolchain["extracted_sha256"]["Godot_v4.7.2-stable_win64.exe"]
    project = tmp_path / "game"
    package = load_package(FIXTURE)
    export_godot(package, project)
    environment = native_environment(tmp_path)
    imported = run_engine(project, environment, "--editor", "--import")
    assert imported.returncode == 0, imported.stderr
    assert "SCRIPT ERROR" not in imported.stderr

    checked = run_engine(project, environment, "--", "--verify-content")

    assert checked.returncode == 0, checked.stderr
    assert f"CONTENT_OK:{package.content_hash}" in checked.stdout
    (project / "content/assets/archive.png").write_bytes(b"tampered source image")
    rejected = run_engine(project, environment, "--", "--verify-content")
    assert rejected.returncode != 0
    assert "asset_hash_mismatch" in rejected.stderr
