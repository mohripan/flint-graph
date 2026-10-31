"""Character framing and free horizontal placement in story format 2 (runtime 0.4.0)."""

import copy
import json

import pytest
from test_narrative_package_v2 import story

from flint_graph.narrative import Player, PlayerError
from flint_graph.narrative.package import load_text_package
from flint_graph.narrative.validation import validate_story
from flint_graph.narrative.values import PackageError


def framed() -> dict:
    value = copy.deepcopy(story())
    value["characters"]["mira"]["stage"] = {"scale": 160, "top": 4}
    value["characters"]["oren"]["stage"] = {"scale": 140}
    value["nodes"]["s0"]["show"][0]["x"] = 30
    return value


def play(source: dict) -> Player:
    return Player(load_text_package(json.dumps(source).encode(), allow_asset_refs=True))


def test_framing_and_placement_are_optional_and_bounded():
    assert validate_story(framed()) == ()
    for edit, code in [
        (lambda s: s["characters"]["mira"]["stage"].update(scale=39), "invalid_value"),
        (lambda s: s["characters"]["mira"]["stage"].update(scale=301), "invalid_value"),
        (lambda s: s["characters"]["mira"]["stage"].update(scale=150.5), "invalid_value"),
        (lambda s: s["characters"]["mira"]["stage"].update(top=-51), "invalid_value"),
        (lambda s: s["characters"]["mira"]["stage"].update(top=101), "invalid_value"),
        (lambda s: s["characters"]["mira"]["stage"].update(zoom=2), "unknown_field"),
        (lambda s: s["characters"]["mira"].update(stage=[]), "invalid_object"),
        (lambda s: s["nodes"]["s0"]["show"][0].update(x=-1), "invalid_value"),
        (lambda s: s["nodes"]["s0"]["show"][0].update(x=101), "invalid_value"),
        (lambda s: s["nodes"]["s0"]["show"][0].update(x="30"), "invalid_value"),
        (lambda s: s["nodes"]["s0"]["show"][0].update(y=10), "unknown_field"),
    ]:
        value = framed()
        edit(value)
        with pytest.raises(PackageError) as raised:
            validate_story(value)
        assert raised.value.code == code
    empty = framed()
    empty["characters"]["mira"]["stage"] = {}
    assert validate_story(empty) == ()


def test_placement_x_lives_in_the_stage_state_until_the_character_is_placed_again():
    player = play(framed())
    # s0 placed Mira at x 30; her expression on the settled line keeps it.
    assert player.view["stage"]["characters"] == [
        {"id": "mira", "sprite": "happy", "position": "left", "x": 30}
    ]
    assert player.frame()["stage"] == player.view["stage"]
    player.act("advance")
    # s1 places Oren at left without x, replacing Mira; no x is carried over.
    assert player.state["stage"]["characters"] == [
        {"id": "oren", "sprite": "neutral", "position": "left"}
    ]


def test_saves_keep_placement_and_reject_bad_values():
    player = play(framed())
    saved = player.save()
    restored = play(framed())
    restored.act("advance")
    restored.load_save(saved)
    assert restored.state == player.state
    for value in (-1, 101, "30", 30.5, None):
        broken = json.loads(saved)
        broken["stage"]["characters"][0]["x"] = value
        with pytest.raises(PlayerError):
            play(framed()).load_save(json.dumps(broken).encode())
    extra = json.loads(saved)
    extra["stage"]["characters"][0]["scale"] = 150
    with pytest.raises(PlayerError):
        play(framed()).load_save(json.dumps(extra).encode())
    # Saves without x (format 2 before runtime 0.4.0) stay valid.
    plain = play(story())
    assert "x" not in plain.state["stage"]["characters"][0]
    play(story()).load_save(plain.save())


def test_format_1_has_no_framing():
    v1 = {
        "schema_version": "1",
        "id": "old",
        "title": "Old",
        "language": "en",
        "entry": "end",
        "characters": {"mira": {"name": "Mira", "stage": {"scale": 150}}},
        "variables": {},
        "assets": {},
        "nodes": {"end": {"type": "end", "text_id": "end", "text": "Fin", "ending": "done"}},
    }
    with pytest.raises(PackageError, match="unknown_field"):
        validate_story(v1)
