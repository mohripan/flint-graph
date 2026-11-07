"""Opt-in real Godot qualification of the title screen (ADR 0071, runtime 0.11.0)."""

import os

import pytest
from test_narrative_godot_live import native_ui_probe
from test_narrative_sound_live import sound_package

engine = pytest.mark.skipif(
    not os.getenv("FLINT_GRAPH_NARRATIVE_GODOT_BIN"), reason="Explicit pinned Godot required"
)
TITLED = {"title": {"background": "dusk", "music": "rain"}}


def assert_the_whole_visit(result, *, saves: bool) -> None:
    assert result["open"] is True
    assert result["heading"] == "Original sound fixture"
    assert result["art"] is True
    assert result["music"] == "rain"
    assert result["buttons"][:1] == ["Start"]
    assert "Continue" not in result["buttons"], "nothing is saved yet"
    assert "Gallery" not in result["buttons"], "nothing is unlocked yet"
    assert result["focus"] == "Start"
    assert result["started"] is False
    assert result["line_on_screen"] == "", "the story has not started"
    assert result["stage_box_visible"] is False
    assert result["auto_after_key"] is False
    assert result["same_node"] is True
    assert result["menu_open"] is True
    assert result["save_disabled"] is True
    assert result["gallery_disabled"] is False
    assert result["title_after_menu"] is True
    start = result["after_start"]
    assert (start["open"], start["music"], start["stage_box_visible"]) == (False, "theme", True)
    assert start["text"] == "Music starts."
    assert start["art_freed"] is True
    back = result["back"]
    assert (back["open"], back["music"]) == (True, "rain")
    assert ("Continue" in back["buttons"]) is saves
    assert back["voice_playing"] is False
    if saves:
        continued = result["continued"]
        assert (continued["open"], continued["same_place"]) == (False, True)
        assert continued["notice"] == "Saved game loaded."
    else:
        assert result["files_written"] == [], "a playtest never touches the player's saves"
    fresh = result["new_game"]
    assert fresh == {"open": False, "text": "Music starts.", "notice": ""}


@engine
def test_real_godot_opens_on_the_title_and_starts_the_story_from_it(tmp_path) -> None:
    package = sound_package(tmp_path, theme=TITLED)
    result = native_ui_probe(tmp_path, "title", package, frames=1200)
    assert_the_whole_visit(result, saves=True)
    assert "Quit" in result["buttons"], "a desktop game can be left from here"


@engine
def test_real_playtest_opens_on_the_title_too(tmp_path) -> None:
    package = sound_package(tmp_path, theme=TITLED)
    result = native_ui_probe(tmp_path, "title_preview", package, frames=1200)
    assert_the_whole_visit(result, saves=False)


@engine
def test_real_blocked_browser_sound_starts_the_title_music_on_the_first_press(tmp_path) -> None:
    package = sound_package(tmp_path, theme=TITLED)
    result = native_ui_probe(tmp_path, "title_gate", package, frames=400)
    assert result["gate"] is True
    assert result["before"] is None
    assert result["after"] == {"music": "rain", "open": True, "started": False}


@engine
def test_real_story_without_a_title_goes_straight_to_its_first_line(tmp_path) -> None:
    package = sound_package(tmp_path)
    result = native_ui_probe(tmp_path, "sound_gate", package, frames=400)
    assert result["after"]["same_line"] is True
