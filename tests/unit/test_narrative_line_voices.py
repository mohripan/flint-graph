"""Shared voiced-line contract: audio assets, line voices and what each screen plays."""

import copy
import hashlib
import json
import struct
from pathlib import Path

import pytest

from flint_graph.narrative import Player
from flint_graph.narrative.package import attach_assets, load_text_package
from flint_graph.narrative.validation import validate_story
from flint_graph.narrative.values import PackageError

CASES = json.loads((Path(__file__).parents[1] / "fixtures/narrative/line_voices.json").read_bytes())


def variant(case):
    story = copy.deepcopy(CASES["story"])
    node = story["nodes"][case["node"]]
    node.update(case.get("set", {}))
    for name in case.get("drop", []):
        node.pop(name)
    return story


def play():
    package = load_text_package(json.dumps(CASES["story"]).encode(), allow_asset_refs=True)
    return Player(package)


def test_voices_validate_with_stable_codes():
    assert [item.code for item in validate_story(CASES["story"])] == ["structural_cycle"]
    assert len(CASES["invalid"][8]["set"]["voice"]["text"]) == 41
    for case in CASES["invalid"]:
        with pytest.raises(PackageError) as raised:
            validate_story(variant(case))
        assert (raised.value.code, raised.value.location) == (case["code"], case["location"]), case
    for case in CASES["invalid_assets"]:
        story = copy.deepcopy(CASES["story"])
        story["assets"][case["key"]] = case["asset"]
        with pytest.raises(PackageError) as raised:
            validate_story(story)
        assert (raised.value.code, raised.value.location) == (case["code"], case["location"])


def test_format_1_refuses_voices():
    story = {
        "schema_version": "1",
        "id": "old",
        "title": "Old",
        "language": "en",
        "entry": "start",
        "characters": {"mira": {"name": "Mira"}},
        "variables": {},
        "assets": {},
        "nodes": {
            "start": {
                "type": "line",
                "text_id": "start",
                "text": "Hi",
                "speaker": "mira",
                "voice": {"mode": "full"},
                "next": "end",
            },
            "end": {"type": "end", "text_id": "end", "text": "Fin", "ending": "done"},
        },
    }
    with pytest.raises(PackageError) as raised:
        validate_story(story)
    assert (raised.value.code, raised.value.location) == ("unknown_field", "nodes.start")


def test_each_settled_line_plays_its_clip_and_nothing_else_does():
    player = play()
    for index, action in enumerate([None, *CASES["actions"]]):
        if action:
            player.act(action)
        assert player.state["node_id"] == CASES["screens"][index]
        assert player.view["voice"] == CASES["voices"][index]
        assert player.frame(action)["voice"] == CASES["voices"][index]
    # Saves carry no voice: it follows from the line, and loading replays that line's clip.
    replay = play()
    saved = replay.save()
    assert "voice" not in json.loads(saved)
    replay.act("advance")
    replay.load_save(saved)
    assert replay.view["voice"] == "hello"


def test_audio_bytes_must_be_canonical_wav():
    samples = struct.pack("<h", 1) * 240
    body = b"WAVE" + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 24000, 48000, 2, 16)
    body += b"data" + struct.pack("<I", len(samples)) + samples
    clip = b"RIFF" + struct.pack("<I", len(body)) + body

    def package(fufu: bytes):
        story = copy.deepcopy(CASES["story"])
        story["entry"] = "hello"
        del story["nodes"]["opening"], story["characters"]["mira"]["sprites"]
        story["assets"] = {key: story["assets"][key] for key in ("hello", "fufu")}
        story["assets"]["hello"]["sha256"] = hashlib.sha256(clip).hexdigest()
        story["assets"]["fufu"]["sha256"] = hashlib.sha256(fufu).hexdigest()
        return load_text_package(json.dumps(story).encode(), allow_asset_refs=True)

    attached = attach_assets(package(clip), {"hello": clip, "fufu": clip})
    assert {asset.id for asset in attached.assets} == {"hello", "fufu"}
    with pytest.raises(PackageError) as raised:
        attach_assets(package(clip[:-2]), {"hello": clip, "fufu": clip[:-2]})
    assert (raised.value.code, raised.value.location) == ("invalid_audio", "assets.fufu")
