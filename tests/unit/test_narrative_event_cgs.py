"""Shared CG presentation contract: overlay state, old saves and independent unlocks."""

import copy
import json
from pathlib import Path

import pytest

from flint_graph.narrative import Player, PlayerError
from flint_graph.narrative.package import load_text_package
from flint_graph.narrative.validation import validate_story
from flint_graph.narrative.values import PackageError

CASES = json.loads((Path(__file__).parents[1] / "fixtures/narrative/event_cgs.json").read_bytes())


def play(seen_cgs=()):
    package = load_text_package(json.dumps(CASES["story"]).encode(), allow_asset_refs=True)
    return Player(package, seen_cgs=seen_cgs)


def test_cg_reference_validation_and_format_1_rejection():
    validate_story(CASES["story"])
    for case in CASES["invalid"]:
        story = copy.deepcopy(CASES["story"])
        story["nodes"]["train"]["cg"] = case["value"]
        with pytest.raises(PackageError) as raised:
            validate_story(story)
        assert (raised.value.code, raised.value.location) == (case["code"], "nodes.train.cg")
    # Even null is forbidden on a v1 line or stage, with the existing closed-schema code.
    story = copy.deepcopy(CASES["story"])
    story.update(schema_version="1", characters={}, assets={})
    story["nodes"] = {
        "end": {"type": "end", "text_id": "end", "text": "Fin", "ending": "done", "cg": None}
    }
    story["entry"] = "end"
    with pytest.raises(PackageError, match="unknown_field"):
        validate_story(story)
    story["nodes"]["start"] = {"type": "stage", "cg": None, "next": "end"}
    story["nodes"]["end"].pop("cg")
    story["entry"] = "start"
    with pytest.raises(PackageError, match="unknown_field"):
        validate_story(story)


def test_cg_overlay_carries_underlying_stage_and_gallery_is_first_use_order():
    player = play()
    assert player.gallery == [{"id": key, "unlocked": False} for key in CASES["gallery"]]
    for index, action in enumerate([None, *CASES["actions"]]):
        if action:
            player.act(action)
        assert player.state["node_id"] == CASES["screens"][index]
        assert player.view["stage"]["cg"] == CASES["cgs"][index]
        assert player.frame()["stage"] == player.state["stage"]
        assert player.state["stage"]["characters"][0]["x"] == 30
    assert player.state["stage"]["characters"][0]["sprite"] == "happy"
    assert player.state["stage"]["background"] == "a_platform"
    assert player.gallery == [
        {"id": key, "unlocked": key != "unused_route"} for key in CASES["gallery"]
    ]


def test_slot_saves_carry_cg_but_do_not_rollback_or_store_unlocks():
    player = play()
    old = json.loads(player.save())
    del old["stage"]["cg"]  # runtime <= 0.4.0
    player.act("advance")
    saved = player.save()
    assert json.loads(saved)["stage"]["cg"] == "z_train"
    assert "gallery" not in json.loads(saved) and "seen_cgs" not in json.loads(saved)
    player.load_save(json.dumps(old).encode())
    assert player.state["stage"]["cg"] is None
    assert player.seen_cgs == ["z_train"]
    other = play(player.seen_cgs)
    other.load_save(saved)
    assert other.view["stage"]["cg"] == "z_train"
    for bad in ("missing", "font", [], False, 2):
        broken = json.loads(saved)
        broken["stage"]["cg"] = bad
        before = other.state
        with pytest.raises(PlayerError, match="invalid_save"):
            other.load_save(json.dumps(broken).encode())
        assert other.state == before
    # A valid loaded screen counts as seen, even in a fresh session.
    fresh = play()
    fresh.load_save(saved)
    assert fresh.seen_cgs == ["z_train"]


def test_unlock_input_is_bounded_filtered_and_defensive():
    player = play(["a_platform", "a_platform", "background", "missing"])
    assert player.seen_cgs == ["a_platform"]
    player.gallery[1]["unlocked"] = False
    player.seen_cgs.append("unused_route")
    assert player.gallery[1]["unlocked"] is True


def test_cg_cleared_before_a_screen_is_not_seen():
    story = copy.deepcopy(CASES["story"])
    story["nodes"]["train"]["next"] = "clear"
    player = Player(load_text_package(json.dumps(story).encode(), allow_asset_refs=True))
    player.act("advance")
    assert player.view["stage"]["cg"] is None
    assert player.seen_cgs == []
