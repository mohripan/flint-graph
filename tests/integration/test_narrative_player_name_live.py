"""Opt-in real Godot qualification of naming the player (ADR 0072, runtime 0.12.0)."""

import os

import pytest
from test_narrative_godot_live import native_probe, native_ui_probe, stage_package

from flint_graph.narrative.player import Player
from flint_graph.narrative.values import canonical_json, clean_name

engine = pytest.mark.skipif(
    not os.getenv("FLINT_GRAPH_NARRATIVE_GODOT_BIN"), reason="Explicit pinned Godot required"
)
MARKUP = "[b]Zoë[/b] {name} 👩‍🚀 ミラ"
TYPED = [
    "Zoë",
    "  Mira  ",
    "\u3000ミラ\u00a0",
    "",
    "   ",
    "\n\t",
    "A\nB",
    "Li\u200bnk",
    "\u202eevil",
    "[b]Bold[/b]",
    "{name}",
    "👩‍🚀",
    "x" * 40,
    " " + "x" * 31 + " y",
]


def named_story_package(tmp_path, extra_nodes=None):
    nodes = {
        "s0": {"type": "stage", "background": "dusk", "next": "ask"},
        "ask": {"type": "name", "text_id": "ask", "text": "What is your name?", "next": "hi"},
        "hi": {
            "type": "line",
            "text_id": "hi",
            "speaker": "mira",
            "text": "Hello, {name}.",
            "next": "me",
        },
        "me": {"type": "line", "text_id": "me", "speaker": "oren", "text": "It's me.", "next": "c"},
        "c": {
            "type": "choice",
            "text_id": "c",
            "text": "Well, {name}?",
            "options": [{"id": "go", "text_id": "go", "text": "Go, {name}", "target": "e1"}],
        },
        "e1": {"type": "end", "text_id": "e1", "text": "Bye, {name}.", "ending": "done"},
    }
    return stage_package(
        tmp_path, nodes=nodes, entry="s0", player={"default_name": "Alex", "character": "oren"}
    )


@engine
def test_real_godot_keeps_the_name_exactly_like_the_reference(tmp_path) -> None:
    package = named_story_package(tmp_path)
    actions = ["name:" + MARKUP, "advance", "advance", "choose:go"]
    actual = native_probe(package, tmp_path, {"actions": actions, "save_after": 1})
    reference = Player(package)
    frames = [reference.frame()]
    for action in actions:
        reference.act(action)
        frames.append(reference.frame(action))
    assert actual["frames"] == frames
    assert actual["state"] == reference.state
    assert actual["restore_error"] == ""
    # The native save loads in the reference player, and means the same thing there.
    restored = Player(package)
    restored.load_save(actual["save"].encode())
    assert restored.state["player_name"] == MARKUP


@engine
def test_real_godot_cleans_every_name_the_way_the_reference_does(tmp_path) -> None:
    package = named_story_package(tmp_path)
    result = native_ui_probe(tmp_path, "name_cleaning", package, extra={"typed": TYPED})
    assert result["cleaned"] == [clean_name(typed, "Alex") for typed in TYPED]


@engine
def test_real_player_asks_and_uses_the_name_as_plain_text(tmp_path) -> None:
    package = named_story_package(tmp_path)
    result = native_ui_probe(tmp_path, "name", package, extra={"typed": MARKUP}, frames=1200)
    assert result["asked"] is True
    assert result["prefilled"] == "Alex"
    assert result["focus"] == "field"
    assert result["confirm"] == "That's me"
    assert result["shortcut_typed"] is False, "typing a letter is typing, not a shortcut"
    assert result["text"] == f"Hello, {MARKUP}."
    assert result["bbcode"] is False
    assert result["own_line_speaker"] == MARKUP
    assert result["other_speaker"] == "Mira"
    assert result["empty_takes_default"] == "Alex"
    assert any(MARKUP in row for row in result["log"])
    assert result["auto_stopped_at_question"] is True
    assert canonical_json(result["state_after_load"]) == canonical_json(MARKUP)


@engine
def test_real_playtest_asks_too_and_keeps_nothing(tmp_path) -> None:
    package = named_story_package(tmp_path)
    result = native_ui_probe(tmp_path, "name_preview", package, extra={"typed": "Zoë"}, frames=800)
    assert result["text"] == "Hello, Zoë."
    assert result["files_written"] == []


@engine
def test_real_web_style_font_refuses_what_it_could_only_show_as_boxes(tmp_path) -> None:
    package = named_story_package(tmp_path)
    result = native_ui_probe(tmp_path, "name_font", package, frames=400)
    blocked = result["blocked"]
    assert blocked["still_asked"] is True
    assert blocked["name"] == "Alex"
    assert "can't show" in blocked["notice"]
    accepted = result["accepted"]
    assert (accepted["name"], accepted["still_asked"], accepted["notice"]) == ("Zoë", False, "")

