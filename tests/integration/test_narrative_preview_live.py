"""Explicit real-engine qualification of the dynamic, text-only preview boundary."""

import base64
import copy
import hashlib
import json
import os
import shutil
import struct
import subprocess
import zlib
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
    assert probe(tmp_path, cases) == [item["valid"] for item in cases]


def probe(tmp_path: Path, cases: list[dict]) -> list[bool]:
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
    results: list[bool] = json.loads(line)
    return results


def stage_png(red: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    row = b"\x00" + bytes([red, 80, 40, 255]) * 2
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * 2))
        + chunk(b"IEND", b"")
    )


def test_dynamic_preview_validates_v2_stage_rules_and_asset_identity(tmp_path: Path) -> None:
    files = {"dusk": stage_png(10), "mira": stage_png(50), "type": b"font bytes for hashing"}
    story = {
        "schema_version": "2",
        "id": "harbor",
        "title": "Harbor",
        "language": "en",
        "entry": "s0",
        "characters": {
            "mira": {
                "name": "Mira",
                "color": "#d5ae68",
                "sprites": {"neutral": "mira"},
                "stage": {"scale": 160, "top": 4},
            },
            "oren": {"name": "Oren"},
        },
        "variables": {},
        "assets": {
            "dusk": {
                "kind": "image",
                "path": "assets/dusk.png",
                "sha256": hashlib.sha256(files["dusk"]).hexdigest(),
            },
            "mira": {
                "kind": "image",
                "path": "assets/mira.png",
                "sha256": hashlib.sha256(files["mira"]).hexdigest(),
            },
            "type": {
                "kind": "font",
                "path": "assets/type.otf",
                "sha256": hashlib.sha256(files["type"]).hexdigest(),
            },
        },
        "theme": {
            "textbox": {"position": "top", "width": 80, "background": "#182635e6", "radius": 0},
            "name": {"show": False, "text": "#000000"},
            "choices": {"border": "#d5ae68"},
            "font": {"asset": "type", "size": 14},
        },
        "nodes": {
            "s0": {
                "type": "stage",
                "background": "dusk",
                "show": [{"character": "mira", "sprite": "neutral", "position": "left", "x": 30}],
                "next": "l1",
            },
            "l1": {
                "type": "line",
                "speaker": "mira",
                "expression": "neutral",
                "text_id": "l1",
                "text": "Hi.",
                "next": "s1",
            },
            "s1": {"type": "stage", "background": None, "hide": ["mira"], "next": "e"},
            "e": {"type": "end", "text_id": "e", "text": "Fin", "ending": "quiet"},
        },
    }
    notices = b"Original stage fixture.\n"
    cases: list[dict] = []

    def add(value: dict, valid: bool, supplied: dict[str, bytes] | None = None) -> None:
        raw = canonical_json(value)
        if valid:
            package = load_text_package(raw, notices, allow_asset_refs=True)
            content_hash = package.content_hash
        else:
            with pytest.raises(PackageError):
                load_text_package(raw, notices, allow_asset_refs=True)
            content_hash = load_text_package(
                canonical_json(story), notices, allow_asset_refs=True
            ).content_hash
        cases.append(
            {
                "source": base64.b64encode(raw).decode(),
                "notices": base64.b64encode(notices).decode(),
                "hash": content_hash,
                "assets": {
                    key: base64.b64encode(data).decode()
                    for key, data in (files if supplied is None else supplied).items()
                },
                "valid": valid and supplied is None,
            }
        )

    add(story, True)
    add(story, True, {key: data for key, data in files.items() if key != "type"})
    add(story, True, {**files, "extra": files["dusk"]})
    add(story, True, {**files, "dusk": files["mira"]})
    add(story, True, {})

    def node(name: str, value: dict):
        return lambda s: s["nodes"].__setitem__(name, value)

    show = {"character": "mira", "sprite": "neutral", "position": "left"}
    for change in [
        node("s1", {"type": "stage", "next": "e"}),
        node("s1", {"type": "stage", "hide": [], "next": "e"}),
        node("s1", {"type": "stage", "hide": ["mira", "mira"], "next": "e"}),
        node("s1", {"type": "stage", "hide": ["mira"], "show": [show], "next": "e"}),
        node("s1", {"type": "stage", "show": [show, {**show, "character": "oren"}], "next": "e"}),
        node("s1", {"type": "stage", "show": [{**show, "position": "middle"}], "next": "e"}),
        node("s1", {"type": "stage", "show": [{**show, "sprite": "happy"}], "next": "e"}),
        node("s1", {"type": "stage", "background": "type", "next": "e"}),
        node("s1", {"type": "stage", "background": "dusk", "next": "e", "extra": 1}),
        node("l1", {"type": "line", "expression": "neutral", "text_id": "l1", "text": "Hi.", "next": "s1"}),  # noqa: E501
        node("l1", {"type": "line", "speaker": "oren", "expression": "neutral", "text_id": "l1", "text": "Hi.", "next": "s1"}),  # noqa: E501
        node("l1", {"type": "line", "speaker": "mira", "background": "dusk", "text_id": "l1", "text": "Hi.", "next": "s1"}),  # noqa: E501
        lambda s: s["characters"]["mira"].update(color="#D5AE68"),
        lambda s: s["characters"]["mira"].update(color="#d5ae68f"),
        lambda s: s["characters"]["mira"]["sprites"].update(neutral="type"),
        lambda s: s["theme"].update(extra={}),
        lambda s: s["theme"]["textbox"].update(position="left"),
        lambda s: s["theme"]["textbox"].update(width=101),
        lambda s: s["theme"]["textbox"].update(radius=True),
        lambda s: s["theme"]["name"].update(show=1),
        lambda s: s["theme"]["font"].update(asset="dusk"),
        lambda s: s["theme"]["font"].update(size=13),
        lambda s: s["assets"]["type"].update(path="assets/type.woff"),
        lambda s: s["assets"]["dusk"].update(kind="audio"),
        lambda s: s.update(schema_version="1"),
        lambda s: s["characters"]["mira"]["stage"].update(scale=301),
        lambda s: s["characters"]["mira"]["stage"].update(top=-51),
        lambda s: s["characters"]["mira"]["stage"].update(zoom=2),
        lambda s: s["nodes"]["s0"]["show"][0].update(x=101),
        lambda s: s["nodes"]["s0"]["show"][0].update(x=True),
    ]:
        changed = copy.deepcopy(story)
        change(changed)
        add(changed, False)

    assert probe(tmp_path, cases) == [item["valid"] for item in cases]
