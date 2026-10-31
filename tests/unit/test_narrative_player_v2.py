"""Reference player for story package v2: persistent stage state and saves (ADR 0040)."""

import json

import pytest
from test_narrative_package_v2 import story

from flint_graph.narrative import Player, PlayerError
from flint_graph.narrative.package import load_text_package


def play(source: dict | None = None) -> Player:
    return Player(load_text_package(json.dumps(source or story()).encode(), allow_asset_refs=True))


def at(stage: dict) -> list[tuple[str, str, str]]:
    return [(item["id"], item["sprite"], item["position"]) for item in stage["characters"]]


def test_stage_persists_across_lines_choices_and_endings():
    player = play()
    view = player.view
    assert view["type"] == "line" and view["speaker_color"] == "#d5ae68"
    # s0 placed Mira; the settled line then applied her "happy" expression.
    assert view["stage"]["background"] == "dusk"
    assert at(view["stage"]) == [("mira", "happy", "left")]
    assert "portrait" not in view and "background" not in view

    player.act("advance")
    assert player.view["type"] == "choice"
    # s1 showed Oren at Mira's position, so Mira left the stage.
    assert player.view["stage"] == {
        "background": "dusk",
        "characters": [{"id": "oren", "sprite": "neutral", "position": "left"}],
    }

    player.act("choose:go")
    assert player.state["status"] == "ended"
    assert player.view["stage"] == {"background": None, "characters": []}
    assert player.frame()["stage"] == {"background": None, "characters": []}


def test_moves_replacements_and_canonical_order():
    source = story()
    source["nodes"]["s1"] = {
        "type": "stage",
        "show": [
            {"character": "oren", "sprite": "neutral", "position": "center"},
            {"character": "mira", "sprite": "neutral", "position": "right"},
        ],
        "next": "c1",
    }
    player = play(source)
    player.act("advance")
    assert at(player.view["stage"]) == [("oren", "neutral", "center"), ("mira", "neutral", "right")]


def test_saves_restore_the_stage_without_reapplying_effects():
    player = play()
    player.act("advance")
    saved = player.save()
    assert json.loads(saved)["schema_version"] == "2"
    other = play()
    other.load_save(saved)
    assert other.state == player.state
    assert other.view == player.view
    # Loading at the line does not apply its expression again, and reloads stay exact.
    line = play()
    snapshot = line.save()
    reloaded = play()
    reloaded.load_save(snapshot)
    assert reloaded.state == line.state


def corrupt(field_edit):
    player = play()
    saved = json.loads(player.save())
    field_edit(saved)
    return json.dumps(saved).encode()


@pytest.mark.parametrize(
    "edit",
    [
        lambda s: s.update(schema_version="1"),
        lambda s: s.pop("stage"),
        lambda s: s["stage"].update(background="old_type"),
        lambda s: s["stage"].update(background="missing"),
        lambda s: s["stage"]["characters"].append(
            {"id": "nobody", "sprite": "neutral", "position": "right"}
        ),
        lambda s: s["stage"]["characters"].append(
            {"id": "oren", "sprite": "angry", "position": "right"}
        ),
        lambda s: s["stage"]["characters"].append(
            {"id": "oren", "sprite": "neutral", "position": "left"}
        ),
        lambda s: s["stage"]["characters"].append(
            {"id": "mira", "sprite": "neutral", "position": "right"}
        ),
        lambda s: s["stage"]["characters"].insert(
            0, {"id": "oren", "sprite": "neutral", "position": "right"}
        ),
        lambda s: s["stage"]["characters"][0].update(position="middle"),
        lambda s: s["stage"]["characters"][0].update(extra=True),
    ],
)
def test_invalid_stage_saves_never_replace_the_running_game(edit):
    player = play()
    before = player.state
    with pytest.raises(PlayerError, match="invalid_save"):
        player.load_save(corrupt(edit))
    assert player.state == before


def test_stage_loops_fault_at_the_transition_bound_and_keep_the_stage():
    source = story()
    source["nodes"]["s0"] = {"type": "stage", "background": "dusk", "next": "s0b"}
    source["nodes"]["s0b"] = {"type": "stage", "background": None, "next": "s0"}
    player = play(source)
    assert player.state["fault"] == "automatic_transition_limit"
    assert player.view["type"] == "fault"
    assert "stage" in player.view
    restored = play(source)
    restored.load_save(player.save())
    assert restored.state == player.state


def test_v1_frames_and_views_have_no_stage():
    v1 = {
        "schema_version": "1",
        "id": "old",
        "title": "Old",
        "language": "en",
        "entry": "l",
        "characters": {},
        "variables": {},
        "assets": {},
        "nodes": {
            "l": {"type": "line", "text_id": "l", "text": "Hi", "next": "end"},
            "end": {"type": "end", "text_id": "end", "text": "Fin", "ending": "done"},
        },
    }
    player = Player(load_text_package(json.dumps(v1).encode()))
    assert (
        "stage" not in player.view and "stage" not in player.frame() and "stage" not in player.state
    )
    assert set(player.view) == {
        "type",
        "text_id",
        "text",
        "speaker",
        "speaker_name",
        "portrait",
        "background",
        "options",
    }
    assert json.loads(player.save())["schema_version"] == "1"
    with pytest.raises(PlayerError):
        player.load_save(json.dumps({**json.loads(player.save()), "stage": {}}).encode())
