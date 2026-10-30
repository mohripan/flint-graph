"""Explicit real-engine qualification of the dynamic, text-only preview boundary."""

import base64
import copy
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from flint_graph.narrative.package import load_text_package
from flint_graph.narrative.values import PackageError, canonical_json

ROOT = Path(__file__).parents[2]
ENGINE = os.environ.get("FLINT_GRAPH_NARRATIVE_GODOT_BIN")
pytestmark = pytest.mark.skipif(not ENGINE, reason="Explicit pinned Godot required")


def test_dynamic_preview_validates_text_semantics_and_package_identity(tmp_path: Path) -> None:
    source = json.loads((ROOT / "tests/fixtures/narrative/lantern_archive/story.json").read_bytes())
    source["assets"] = {}
    for node in source["nodes"].values():
        node.pop("background", None)
        node.pop("portrait", None)
    cases = []

    def identity(raw: bytes, notices: bytes) -> str:
        return hashlib.sha256(
            canonical_json(
                {
                    "schema_version": "1",
                    "assets": [],
                    "story_sha256": hashlib.sha256(raw).hexdigest(),
                    "notices_sha256": hashlib.sha256(notices).hexdigest(),
                }
            )
        ).hexdigest()

    def add(
        story: dict, valid: bool, *, notices: bytes = b"Original fixture", bad_hash: bool = False
    ) -> None:
        raw = canonical_json(story)
        if not valid:
            with pytest.raises(PackageError):
                load_text_package(raw, notices)
        content_hash = identity(raw, notices)
        if valid:
            assert content_hash == load_text_package(raw, notices).content_hash
        cases.append(
            {
                "source": base64.b64encode(raw).decode(),
                "notices": base64.b64encode(notices).decode(),
                "hash": "0" * 64 if bad_hash else content_hash,
                "valid": valid and not bad_hash,
            }
        )

    add(source, True)
    add(source, True, bad_hash=True)
    prototype = copy.deepcopy(source)
    prototype["nodes"]["constructor"] = prototype["nodes"].pop(prototype["entry"])
    prototype["entry"] = "constructor"
    add(prototype, True)
    for change in [
        lambda s: s.update(extra=True),
        lambda s: s.update(schema_version=1),
        lambda s: s.update(entry="missing"),
        lambda s: s.update(language="javascript:evil"),
        lambda s: s["characters"].update(bad={"name": ""}),
        lambda s: s["variables"].update(bad={"type": "int", "initial": True}),
        lambda s: s["variables"].update(bad={"type": "enum", "values": ["x", "x"], "initial": "x"}),
        lambda s: s["nodes"].update(
            bad={"type": "line", "text_id": "bad", "text": "x", "next": "missing"}
        ),
        lambda s: s["nodes"].update(bad={"type": "set", "next": s["entry"], "operations": []}),
        lambda s: s["nodes"].update(
            bad={
                "type": "branch",
                "condition": {"op": "eq", "variable": "missing", "value": True},
                "if_true": s["entry"],
                "if_false": s["entry"],
            }
        ),
        lambda s: s["nodes"].update(
            bad={"type": "choice", "text_id": "bad", "text": "x", "options": []}
        ),
        lambda s: s["assets"].update(image={"path": "assets/image.png", "sha256": "0" * 64}),
    ]:
        changed = copy.deepcopy(source)
        change(changed)
        add(changed, False)
    for raw in [b'{"x":1,"x":2}', b'{"x":1.5}', b'{"x":"\\ud800"}', b"\xff", b"[null]"]:
        cases.append(
            {
                "source": base64.b64encode(raw).decode(),
                "notices": "",
                "hash": identity(raw, b""),
                "valid": False,
            }
        )
    for bad in [None, True, 3, [], {}]:
        for field in ["schema_version", "id", "title", "language", "entry", "nodes"]:
            changed = copy.deepcopy(source)
            changed[field] = bad
            add(changed, False)
        for field in ["type", "text_id", "text", "next"]:
            changed = copy.deepcopy(source)
            changed["nodes"]["bad"] = {
                "type": "line",
                "text_id": "bad",
                "text": "x",
                "next": source["entry"],
                field: bad,
            }
            add(changed, False)
        for field in ["op", "variable", "value"]:
            changed = copy.deepcopy(source)
            changed["variables"]["probe_flag"] = {"type": "bool", "initial": False}
            condition = {"op": "eq", "variable": "probe_flag", "value": False, field: bad}
            changed["nodes"]["bad"] = {
                "type": "branch",
                "condition": condition,
                "if_true": source["entry"],
                "if_false": source["entry"],
            }
            add(changed, field == "value" and bad is True)
    project = tmp_path / "project"
    (project / "runtime").mkdir(parents=True)
    (project / "project.godot").write_text(
        'config_version=5\n[application]\nconfig/name="Preview boundary probe"\n'
    )
    shutil.copyfile(
        ROOT / "runtimes/godot/runtime/strict_json.gd", project / "runtime/strict_json.gd"
    )
    shutil.copyfile(
        ROOT / "runtimes/godot/preview/validate_story.gd", project / "validate_story.gd"
    )
    shutil.copyfile(ROOT / "tests/fixtures/narrative/preview_probe.gd", project / "probe.gd")
    (project / "cases.json").write_bytes(canonical_json(cases))
    assert ENGINE
    assert (
        hashlib.sha256(Path(ENGINE).read_bytes()).hexdigest()
        == "ab1824f85bfd8e0e4128182c000c4003a3e042245b2967848d089b2a04b22424"
    )
    environment = os.environ.copy()
    for key in ["APPDATA", "LOCALAPPDATA", "TEMP", "TMP"]:
        folder = tmp_path / key
        folder.mkdir()
        environment[key] = str(folder)
    result = subprocess.run(
        [ENGINE, "--headless", "--path", str(project), "--script", "res://probe.gd"],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SCRIPT ERROR" not in result.stderr, result.stderr
    line = next(
        line.removeprefix("PREVIEW_PROBE:")
        for line in result.stdout.splitlines()
        if line.startswith("PREVIEW_PROBE:")
    )
    assert json.loads(line) == [item["valid"] for item in cases]
