"""Opt-in actual CG player, preview, gallery UI/storage and Linux release qualification."""

import asyncio
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import pytest
from test_narrative_godot_live import native_probe, native_ui_probe, stage_png, static_font
from test_narrative_preview_live import probe

from flint_graph.infrastructure.narrative_builder import DockerNarrativeBuilder
from flint_graph.narrative import Player, load_package
from flint_graph.narrative.package import load_text_package
from flint_graph.narrative.values import canonical_json

CASES = json.loads((Path(__file__).parents[1] / "fixtures/narrative/event_cgs.json").read_bytes())
engine = pytest.mark.skipif(
    not os.getenv("FLINT_GRAPH_NARRATIVE_GODOT_BIN"), reason="Explicit pinned Godot required"
)


def cg_package(tmp_path):
    story = copy.deepcopy(CASES["story"])
    files = {}
    for index, (key, asset) in enumerate(story["assets"].items()):
        data = static_font() if asset["kind"] == "font" else stage_png(20 + index * 25, 16, 9)
        asset["sha256"] = hashlib.sha256(data).hexdigest()
        files[key] = data
    source = tmp_path / "source"
    (source / "assets").mkdir(parents=True)
    (source / "story.json").write_bytes(canonical_json(story))
    (source / "NOTICES.txt").write_bytes(b"Original CG fixture. CC0.\n")
    for key, data in files.items():
        (source / story["assets"][key]["path"]).write_bytes(data)
    return load_package(source), files


@engine
def test_actual_cg_frames_saves_and_unlocks_match_reference(tmp_path):
    package, _ = cg_package(tmp_path)
    actual = native_probe(
        package, tmp_path, {"actions": CASES["actions"], "save_after": 1, "gallery": True}
    )
    reference = Player(package)
    frames, galleries = [reference.frame()], [reference.gallery]
    for action in CASES["actions"]:
        reference.act(action)
        frames.append(reference.frame(action))
        galleries.append(reference.gallery)
    assert actual["frames"] == frames
    assert actual["galleries"] == galleries
    assert actual["state"] == reference.state
    assert actual["restore_error"] == ""
    assert json.loads(actual["save"])["stage"]["cg"] == "z_train"


@engine
def test_actual_cg_old_and_invalid_saves(tmp_path):
    package, _ = cg_package(tmp_path)
    player = Player(package)
    old = json.loads(player.save())
    del old["stage"]["cg"]
    invalid = []
    for case in CASES["invalid"]:
        saved = json.loads(player.save())
        saved["stage"]["cg"] = case["value"]
        invalid.append(canonical_json(saved))
    result = native_probe(
        package,
        tmp_path,
        {
            "restore_cases": [
                base64.b64encode(data).decode() for data in [canonical_json(old), *invalid]
            ]
        },
    )
    assert result["restored"][0] == {"error": "", "preserved": True, "generation_change": 1}
    assert all(
        item == {"error": "invalid_save", "preserved": True, "generation_change": 0}
        for item in result["restored"][1:]
    )


@engine
def test_actual_transient_cg_is_not_unlocked(tmp_path):
    package, files = cg_package(tmp_path)
    story = package.story
    story["nodes"]["train"]["next"] = "clear"
    from flint_graph.narrative.package import attach_assets

    changed = attach_assets(
        load_text_package(canonical_json(story), package.notices, allow_asset_refs=True), files
    )
    result = native_probe(changed, tmp_path, {"actions": ["advance"], "gallery": True})
    assert result["galleries"][-1] == [{"id": key, "unlocked": False} for key in CASES["gallery"]]


@engine
def test_actual_preview_validates_shared_cg_cases(tmp_path):
    package, files = cg_package(tmp_path)
    cases = []
    variants = [(package.story, True)]
    cleared = package.story
    cleared["nodes"]["train"]["cg"] = None
    variants.append((cleared, True))
    for invalid in CASES["invalid"]:
        value = package.story
        value["nodes"]["train"]["cg"] = invalid["value"]
        variants.append((value, False))
    for story, valid in variants:
        raw = canonical_json(story)
        identity = (
            load_text_package(raw, package.notices, allow_asset_refs=True).content_hash
            if valid
            else package.content_hash
        )
        cases.append(
            {
                "source": base64.b64encode(raw).decode(),
                "notices": base64.b64encode(package.notices).decode(),
                "hash": identity,
                "assets": {key: base64.b64encode(data).decode() for key, data in files.items()},
                "valid": valid,
            }
        )
    assert probe(tmp_path, cases) == [case["valid"] for case in cases]


@engine
@pytest.mark.parametrize("preview", [False, True], ids=["release_persistent", "preview_memory"])
def test_actual_gallery_controls_overlay_and_persistence(tmp_path, preview):
    package, _ = cg_package(tmp_path)
    result = native_ui_probe(tmp_path, "cg_preview" if preview else "cg_gallery", package)
    assert result["overlay"] and result["dialogue_above"] and result["cover"]
    assert result["locked_disabled"] and result["gallery_pauses"] and result["view_unlocked"]
    assert result["retained_on_restart"] and result["retained_on_load"]
    assert result["disk_exists"] is (not preview)
    assert result["fresh_unlocked"] is (not preview)
    assert result["cleared"]


@engine
def test_enter_press_and_release_advance_one_cg_screen(tmp_path):
    package, _ = cg_package(tmp_path)
    assert native_ui_probe(tmp_path, "cg_keyboard", package)["node_id"] == "during"


@engine
def test_keyboard_gallery_does_not_advance_the_story(tmp_path):
    package, _ = cg_package(tmp_path)
    assert native_ui_probe(tmp_path, "cg_keyboard_gallery", package) == {
        "node_id": "before",
        "gallery_open": True,
    }


@pytest.mark.anyio
async def test_actual_linux_release_build_with_cg(tmp_path):
    image, pin = (
        os.getenv("FLINT_GRAPH_NARRATIVE_BUILDER_IMAGE"),
        os.getenv("FLINT_GRAPH_NARRATIVE_BUILDER_TOOLCHAIN"),
    )
    if not image or not pin:
        pytest.skip("Explicit owned builder required")
    package, files = cg_package(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    runner = DockerNarrativeBuilder(image=image, toolchain_sha256=pin, work_root=scratch)

    async def current():
        pass

    result = await runner.build(package, execution_id=uuid4(), check=current)
    with ZipFile(io.BytesIO(result.source_zip)) as source:
        assert json.loads(source.read("build-manifest.json"))["runtime_version"] == "0.5.0"
        assert source.read("content/assets/z_train.png") == files["z_train"]
        assert json.loads(source.read("content/story.json"))["nodes"]["train"]["cg"] == "z_train"
    with ZipFile(io.BytesIO(result.web_zip)) as web:
        assert len(web.read("index.pck")) > 10000
    evidence = os.getenv("FLINT_GRAPH_CG_EVIDENCE_DIR")
    if evidence:
        output = Path(evidence)
        await asyncio.to_thread(output.mkdir)
        (output / "source.zip").write_bytes(result.source_zip)
        (output / "web.zip").write_bytes(result.web_zip)
        (output / "receipt.json").write_bytes(
            canonical_json(
                {
                    "package_hash": package.content_hash,
                    "image": image,
                    "toolchain": pin,
                    "source_sha256": hashlib.sha256(result.source_zip).hexdigest(),
                    "web_sha256": hashlib.sha256(result.web_zip).hexdigest(),
                }
            )
        )
