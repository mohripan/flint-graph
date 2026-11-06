"""Stage transitions and effects (ADR 0065): closed values that never touch story state."""

import copy
import json

import pytest

from flint_graph.narrative import Player
from flint_graph.narrative.package import load_text_package
from flint_graph.narrative.validation import validate_story
from flint_graph.narrative.values import PackageError

SHA = "a" * 64


def story(**stage):
    return {
        "schema_version": "2",
        "id": "harbor",
        "title": "Harbor",
        "language": "en",
        "entry": "open",
        "characters": {},
        "variables": {},
        "assets": {
            "dusk": {"kind": "image", "path": "assets/dusk.png", "sha256": SHA},
            "pier": {"kind": "image", "path": "assets/pier.png", "sha256": "b" * 64},
        },
        "nodes": {
            "open": {"type": "stage", "background": "dusk", "next": "first", **stage},
            "first": {"type": "line", "text_id": "first", "text": "One.", "next": "move"},
            "move": {"type": "stage", "background": "pier", "next": "second"},
            "second": {"type": "line", "text_id": "second", "text": "Two.", "next": "end"},
            "end": {"type": "end", "text_id": "end", "text": "Fin.", "ending": "done"},
        },
    }


def play(source):
    return Player(load_text_package(json.dumps(source).encode(), allow_asset_refs=True))


@pytest.mark.parametrize("transition", ["cut", "fade", "dissolve", "slide"])
def test_every_transition_in_the_closed_set_is_valid(transition):
    validate_story(story(transition=transition))


@pytest.mark.parametrize("effect", ["shake", "flash"])
def test_every_effect_in_the_closed_set_is_valid(effect):
    validate_story(story(effect=effect))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("transition", "wipe"),
        ("transition", None),
        ("transition", 1),
        ("effect", "strobe"),
        ("effect", None),
        ("effect", True),
    ],
)
def test_anything_outside_the_closed_set_is_refused(field, value):
    with pytest.raises(PackageError) as raised:
        validate_story(story(**{field: value}))
    assert raised.value.code == f"invalid_{field}"
    assert raised.value.location == f"nodes.open.{field}"


def test_a_transition_needs_something_to_transition_to():
    source = story()
    source["nodes"]["open"] = {"type": "stage", "transition": "fade", "next": "first"}
    with pytest.raises(PackageError, match="invalid_stage"):
        validate_story(source)


def test_an_effect_alone_is_a_real_stage_step():
    source = story()
    source["nodes"]["open"] = {"type": "stage", "effect": "shake", "next": "first"}
    validate_story(source)


def test_format_1_has_no_stage_so_it_cannot_have_these_fields():
    source = story(transition="fade")
    source["schema_version"] = "1"
    source["assets"] = {}
    with pytest.raises(PackageError):
        validate_story(source)


def test_the_view_reports_what_the_screen_should_play_and_only_once():
    player = play(story(transition="fade", effect="flash"))
    assert (player.view["transition"], player.view["effect"]) == ("fade", "flash")
    player.act("advance")
    # The next stage step has neither, so the player decides how to show that change.
    assert (player.view["transition"], player.view["effect"]) == (None, None)


def test_a_line_after_a_line_plays_nothing():
    source = story(transition="dissolve")
    source["nodes"]["first"]["next"] = "extra"
    source["nodes"]["extra"] = {"type": "line", "text_id": "extra", "text": "Mid.", "next": "move"}
    player = play(source)
    assert player.view["transition"] == "dissolve"
    player.act("advance")
    assert player.view["transition"] is None


def test_the_last_stage_step_crossed_decides_the_transition():
    source = story(transition="fade")
    source["nodes"]["open"]["next"] = "again"
    source["nodes"]["again"] = {
        "type": "stage",
        "background": "pier",
        "transition": "slide",
        "next": "first",
    }
    assert play(source).view["transition"] == "slide"


def test_effects_are_never_in_a_save_or_a_route_trace():
    plain, showy = play(story()), play(story(transition="fade", effect="shake"))
    assert plain.frame() == showy.frame()
    # The saves differ only in the package they belong to.
    saved_plain, saved_showy = json.loads(plain.save()), json.loads(showy.save())
    for saved in (saved_plain, saved_showy):
        saved.pop("package_hash")
    assert saved_plain == saved_showy
    assert "transition" not in saved_showy and "transition" not in saved_showy["stage"]


def test_loading_a_save_plays_nothing():
    player = play(story(transition="fade", effect="flash"))
    saved = player.save()
    player.act("advance")
    player.load_save(saved)
    assert (player.view["transition"], player.view["effect"]) == (None, None)


def test_a_save_from_before_transitions_still_loads():
    source = story(transition="fade")
    player = play(source)
    old = json.loads(player.save())
    assert set(old) == {
        "schema_version",
        "package_hash",
        "node_id",
        "variables",
        "status",
        "ending",
        "fault",
        "stage",
    }
    copy.deepcopy(old)
    player.load_save(json.dumps(old, sort_keys=True, separators=(",", ":")).encode())
    assert player.state["node_id"] == "first"
