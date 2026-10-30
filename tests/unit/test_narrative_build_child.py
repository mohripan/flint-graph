"""Trusted child protocol: input integrity, bounded execution and safe outcomes."""

import hashlib
import json
import os
import signal
import sys
import time

import pytest

from flint_graph.narrative.build_child import run_build
from flint_graph.narrative.export import TEMPLATE_FILES, export_godot
from flint_graph.narrative.package import load_text_package


def fixture(tmp_path):
    story = {
        "schema_version": "1",
        "id": "original",
        "title": "Original fixture",
        "language": "en",
        "entry": "end",
        "characters": {},
        "variables": {},
        "assets": {},
        "nodes": {
            "end": {
                "type": "end",
                "text_id": "end_text",
                "ending": "quiet",
                "text": "A quiet ending.",
            }
        },
    }
    source = tmp_path / "input"
    export_godot(load_text_package(json.dumps(story).encode()), source)
    trusted = {
        name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in TEMPLATE_FILES
    }
    engine = tmp_path / "fixture_engine.py"
    engine.write_text(
        """import pathlib, sys
if '--export-release' in sys.argv:
    root = pathlib.Path(sys.argv[-1]).parent
    for name in ['index.html','index.js','index.wasm','index.pck','index.png',
                 'index.audio.worklet.js','index.audio.position.worklet.js']:
        (root / name).write_bytes(b'fixed trusted engine fixture')
""",
        encoding="utf-8",
    )
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return source, scratch, trusted, (sys.executable, str(engine))


def test_modified_input_script_never_reaches_the_engine(tmp_path):
    source, scratch, trusted, command = fixture(tmp_path)
    (source / "runtime/player.gd").write_bytes(b"creator script must not execute")
    manifest_path = source / "build-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"]["runtime/player.gd"] = hashlib.sha256(
        (source / "runtime/player.gd").read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    outcome = run_build(source, scratch, trusted, engine_command=command)
    assert outcome == {"schema_version": "1", "status": "failed", "code": "input_integrity"}
    assert not (scratch / "project").exists()


def test_fixed_trusted_input_produces_a_complete_safe_inventory(tmp_path):
    source, scratch, trusted, command = fixture(tmp_path)
    # An unrelated input file can never enter Godot's project tree.
    (source / "arbitrary_plugin.gd").write_bytes(b"not copied")
    outcome = run_build(source, scratch, trusted, engine_command=command)
    assert outcome["status"] == "ready"
    assert not (scratch / "project/arbitrary_plugin.gd").exists()
    assert len(outcome["files"]) == 7
    assert outcome["files"]["index.wasm"]["bytes"] == 28
    assert set(outcome) == {"schema_version", "status", "files"}


@pytest.mark.parametrize(
    "script",
    [
        "print('PRIVATE_CANARY'); raise SystemExit(3)",
        "import sys; sys.stdout.write('a' * 2000000 + 'SCRIPT ERROR PRIVATE_CANARY')",
    ],
)
def test_engine_failures_and_large_diagnostics_return_only_safe_codes(tmp_path, script):
    source, scratch, trusted, command = fixture(tmp_path)
    (tmp_path / "fixture_engine.py").write_text(script, encoding="utf-8")
    outcome = run_build(source, scratch, trusted, engine_command=command)
    assert outcome == {"schema_version": "1", "status": "failed", "code": "engine_failed"}
    assert "PRIVATE_CANARY" not in json.dumps(outcome)


def test_stalled_engine_is_stopped_with_a_safe_timeout(tmp_path):
    source, scratch, trusted, command = fixture(tmp_path)
    (tmp_path / "fixture_engine.py").write_text("import time; time.sleep(30)", encoding="utf-8")
    start = time.monotonic()
    outcome = run_build(source, scratch, trusted, engine_command=command, stage_timeout=0.1)
    assert outcome == {"schema_version": "1", "status": "failed", "code": "engine_timeout"}
    assert time.monotonic() - start < 5


def test_incomplete_output_never_reports_ready(tmp_path):
    source, scratch, trusted, command = fixture(tmp_path)
    (tmp_path / "fixture_engine.py").write_text("pass", encoding="utf-8")
    outcome = run_build(source, scratch, trusted, engine_command=command)
    assert outcome == {"schema_version": "1", "status": "failed", "code": "output_inventory"}


def test_engine_descendant_holding_stdout_cannot_bypass_the_stage_deadline(tmp_path):
    source, scratch, trusted, command = fixture(tmp_path)
    marker = tmp_path / "owned-child.pid"
    script = (
        "import pathlib, subprocess, sys\n"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(7)'])\n"
        f"pathlib.Path({str(marker)!r}).write_text(str(child.pid))\n"
    )
    (tmp_path / "fixture_engine.py").write_text(script, encoding="utf-8")
    start = time.monotonic()
    try:
        outcome = run_build(source, scratch, trusted, engine_command=command, stage_timeout=0.5)
        assert time.monotonic() - start < 3
        assert outcome["code"] == "engine_timeout"
    finally:
        if marker.exists():
            try:
                os.kill(int(marker.read_text()), signal.SIGTERM)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize(
    "manifest", [b'{"files":' + b"[" * 1500 + b"0" + b"]" * 1500 + b"}", b'{"files":{},"files":{}}']
)
def test_malformed_input_manifest_returns_safe_integrity_failure(tmp_path, manifest):
    source, scratch, trusted, command = fixture(tmp_path)
    (source / "build-manifest.json").write_bytes(manifest)
    assert run_build(source, scratch, trusted, engine_command=command) == {
        "schema_version": "1",
        "status": "failed",
        "code": "input_integrity",
    }


@pytest.mark.parametrize("duplicate", [True, False])
def test_closed_manifest_rejects_duplicates_and_unknown_fields(tmp_path, duplicate):
    source, scratch, trusted, command = fixture(tmp_path)
    path = source / "build-manifest.json"
    raw = path.read_text(encoding="utf-8")
    if duplicate:
        raw = '{"files":{},' + raw[1:]
    else:
        raw = '{"extra":"not allowed",' + raw[1:]
    path.write_text(raw, encoding="utf-8")
    assert run_build(source, scratch, trusted, engine_command=command)["code"] == "input_integrity"
