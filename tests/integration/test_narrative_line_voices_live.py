"""Opt-in real Godot qualification of voiced lines (ADR 0043, runtime 0.6.0)."""

import base64
import copy
import hashlib
import json
import os
import struct
from pathlib import Path

import pytest
from test_narrative_godot_live import native_probe, native_ui_probe, stage_png
from test_narrative_preview_live import probe

from flint_graph.narrative import Player, load_package
from flint_graph.narrative.package import load_text_package
from flint_graph.narrative.values import PackageError, canonical_json
from flint_graph.narrative.wav import canonical_wav, validate_wav

CASES = json.loads((Path(__file__).parents[1] / "fixtures/narrative/line_voices.json").read_bytes())
engine = pytest.mark.skipif(
    not os.getenv("FLINT_GRAPH_NARRATIVE_GODOT_BIN"), reason="Explicit pinned Godot required"
)


def tone(frames: int, level: int, channels: int = 1, rate: int = 24000) -> bytes:
    return canonical_wav(channels, rate, struct.pack("<h", level) * frames * channels)


def voice_package(tmp_path):
    story = copy.deepcopy(CASES["story"])
    files = {}
    for index, (key, asset) in enumerate(story["assets"].items()):
        data = (
            tone(72000 + index, 900 * index) if asset["kind"] == "audio" else stage_png(40 * index)
        )
        asset["sha256"] = hashlib.sha256(data).hexdigest()
        files[key] = data
    source = tmp_path / "source"
    (source / "assets").mkdir(parents=True)
    (source / "story.json").write_bytes(canonical_json(story))
    (source / "NOTICES.txt").write_bytes(b"Original voice fixture. CC0.\n")
    for key, data in files.items():
        (source / story["assets"][key]["path"]).write_bytes(data)
    return load_package(source), files


def wav_cases() -> list[bytes]:
    good = tone(480, 1000)
    truncated = good[:-2]
    stereo = tone(480, -1000, channels=2, rate=48000)
    wrong_rate = bytearray(good)
    struct.pack_into("<I", wrong_rate, 24, 11025)
    struct.pack_into("<I", wrong_rate, 28, 22050)
    extra = good[:36] + b"LIST" + struct.pack("<I", 4) + b"INFO" + good[36:]
    extra = b"RIFF" + struct.pack("<I", len(extra) - 8) + extra[8:]
    eight_bit = bytearray(good)
    struct.pack_into("<H", eight_bit, 34, 8)
    return [good, stereo, truncated, bytes(wrong_rate), extra, bytes(eight_bit)]


@engine
def test_actual_voice_frames_match_reference(tmp_path):
    package, _ = voice_package(tmp_path)
    actual = native_probe(package, tmp_path, {"actions": CASES["actions"], "save_after": 1})
    reference = Player(package)
    frames = [reference.frame()]
    for action in CASES["actions"]:
        reference.act(action)
        frames.append(reference.frame(action))
    assert actual["frames"] == frames
    assert [frame["voice"] for frame in frames] == CASES["voices"]
    assert actual["state"] == reference.state


@engine
def test_actual_preview_validates_shared_voice_cases(tmp_path):
    package, files = voice_package(tmp_path)
    cases = []
    variants = [(package.story, True)]
    for invalid in CASES["invalid"]:
        story = package.story
        story["nodes"][invalid["node"]].update(invalid.get("set", {}))
        for name in invalid.get("drop", []):
            story["nodes"][invalid["node"]].pop(name)
        variants.append((story, False))
    for invalid in CASES["invalid_assets"]:
        story = package.story
        story["assets"][invalid["key"]] = {
            **invalid["asset"],
            "sha256": story["assets"][invalid["key"]]["sha256"],
        }
        variants.append((story, False))
    for story, valid in variants:
        raw = canonical_json(story)
        if valid:
            identity = load_text_package(raw, package.notices, allow_asset_refs=True).content_hash
        else:
            with pytest.raises(PackageError):
                load_text_package(raw, package.notices, allow_asset_refs=True)
            identity = package.content_hash
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
def test_actual_voice_playback_volume_and_wav_parsing(tmp_path, preview):
    package, _ = voice_package(tmp_path)
    clips = wav_cases()
    expected = []
    for data in clips:
        try:
            info = validate_wav(data, "x")
            expected.append(
                {
                    "rate": info.sample_rate,
                    "stereo": info.channels == 2,
                    "bytes": info.frames * info.channels * 2,
                }
            )
        except PackageError:
            expected.append(None)
    assert expected[0] and expected[1] and expected[2:] == [None] * 4
    result = native_ui_probe(
        tmp_path,
        "voice_preview" if preview else "voice",
        package,
        {"wav_cases": [base64.b64encode(data).decode() for data in clips]},
    )
    assert result["parsed"] == expected
    # Screens: hello (clip), laugh (vocalization clip), pending (no clip yet), silent.
    assert result["clips"] == ["hello", "fufu", None, None]
    assert result["playing"] == [True, True, False, False]
    assert result["volume"] == 30
    assert result["volume_db"] == pytest.approx(20 * __import__("math").log10(0.3), abs=0.01)
    assert result["restarted"] == "hello"
    assert result["gallery_open"] is True
    # Exports keep the volume on the device; Studio playtests never write user://.
    assert result["stored"] is not preview
    assert result["stored_volume"] == (100 if preview else 30)


@engine
@pytest.mark.parametrize("preview", [False, True], ids=["release", "preview"])
def test_a_muted_browser_shows_a_start_screen_then_plays_the_first_line(tmp_path, preview):
    # Browsers keep sound off until a click or key press; that first input must not
    # also skip the first voiced line (runtime 0.6.1).
    package, _ = voice_package(tmp_path)
    result = native_ui_probe(
        tmp_path, "voice_gate_preview" if preview else "voice_gate", package, frames=60
    )
    gated = {"gate": True, "clip": "hello", "playing": False, "same_line": True}
    opened = {"gate": False, "clip": "hello", "playing": True, "same_line": True}
    for flow in ("click", "key"):
        assert result[flow]["before"] == gated
        assert result[flow]["opened"] == opened, flow
        assert result[flow]["next"] == {
            "gate": False,
            "clip": "fufu",
            "playing": True,
            "same_line": False,
        }
    # No voice clips, or a page that may already play sound: no start screen.
    assert result["silent"]["before"] == {
        "gate": False,
        "clip": None,
        "playing": False,
        "same_line": True,
    }
    assert result["allowed"]["before"] == {**opened, "gate": False}
