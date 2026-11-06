"""Opt-in real Godot qualification of the player controls (ADR 0064, runtime 0.8.0)."""

import os

import pytest
from test_narrative_godot_live import native_ui_probe, stage_package

engine = pytest.mark.skipif(
    not os.getenv("FLINT_GRAPH_NARRATIVE_GODOT_BIN"), reason="Explicit pinned Godot required"
)


def line(key, text, target, **extra):
    return {"type": "line", "text_id": key, "text": text, "next": target, **extra}


def conversation():
    """Two characters on stage, narration, a choice and a line after it."""
    return {
        "s0": {
            "type": "stage",
            "background": "dusk",
            "show": [
                {"character": "mira", "sprite": "neutral", "position": "left"},
                {"character": "oren", "sprite": "neutral", "position": "right"},
            ],
            "next": "l1",
        },
        "l1": line("l1", "The bell is ringing over the harbor tonight.", "l2", speaker="mira"),
        "l2": line("l2", "Then we should go down to the pier.", "l3", speaker="oren"),
        "l3": line("l3", "Rain began to fall.", "c1"),
        "c1": {
            "type": "choice",
            "text_id": "c1",
            "text": "What do you do?",
            "options": [
                {"id": "stay", "text_id": "c1_stay", "text": "Stay", "target": "l4"},
                {"id": "go", "text_id": "c1_go", "text": "Go", "target": "l4"},
            ],
        },
        "l4": line("l4", "A line [b]nobody[/b] has read.", "e1", speaker="mira"),
        "e1": {"type": "end", "text_id": "e1", "text": "The end.", "ending": "done"},
    }


@engine
def test_real_player_controls_never_change_where_the_story_goes(tmp_path) -> None:
    package = stage_package(tmp_path, nodes=conversation(), entry="s0")
    result = native_ui_probe(tmp_path, "controls", package)

    # Text appears over time, the first press finishes it and the second moves on.
    assert result["default_speed"] == "normal"
    assert result["revealing_at_start"] is True
    assert result["first_press"] == {"node": "l1", "revealing": False}
    assert result["second_press"] == {"node": "l2", "revealing": True}
    assert result["instant_stops_the_reveal"] is True

    # The speaker stands out; narration dims nobody, and the player can turn it off.
    assert result["focus"]["mira_speaks"] == {"mira": False, "oren": True}
    assert result["focus"]["oren_speaks"] == {"mira": True, "oren": False}
    assert result["focus"]["narration"] == {"mira": False, "oren": False}
    assert result["focus"]["turned_off"] == {"mira": False, "oren": False}

    # The backlog names speakers, keeps the choice taken and shows markup as plain text.
    assert result["log"]["entries"] == [
        ["Mira", "The bell is ringing over the harbor tonight."],
        ["Oren", "Then we should go down to the pier."],
        [None, "Rain began to fall."],
        [None, "What do you do?"],
        [None, "› Stay"],  # noqa: RUF001
        ["Mira", "A line [b]nobody[/b] has read."],
    ]
    assert result["log"]["pauses"] == {"advanced": False, "continue_disabled": True}
    assert result["log"]["escape_closes"] is True
    assert result["log"]["limit"] == 300

    # Auto waits out the line, advances, and never picks a choice for the player.
    assert result["auto"]["before_delay"] == "l1"
    assert result["auto"]["after_delay"] == "l2"
    assert result["auto"]["paused_by_log"] == "l2"
    assert result["auto"]["stops_at_choice"] == "c1"
    assert result["auto"]["still_on"] is True

    # Skip runs through read text only and stops at the first new line or choice.
    assert result["skip"]["stops_at"] == "c1"
    assert result["skip"]["turned_off_at_choice"] is True
    assert result["skip"]["unread"] == {"node": "l4", "skip": False}
    assert result["skip"]["changed_text_is_unread"] is True

    # Hiding the interface takes one press to undo, which never advances the story.
    assert result["hide"]["hidden"] == {"box": False, "toolbar": False}
    assert result["hide"]["after_click"] == {"box": True, "toolbar": True, "node": "l1"}
    assert result["hide"]["after_enter"] == {"box": True, "toolbar": True, "node": "l1"}
    assert result["hide"]["after_right_click"] == {"box": False}

    # Quick save is its own slot; the regular save is untouched by it.
    assert result["quick"]["slot_written"] is True
    assert result["quick"]["regular_untouched"] is True
    assert result["quick"]["loaded_node"] == "l2"
    assert result["quick"]["notice"] == "Quick save loaded."
    assert result["quick"]["log_marks_the_load"] is True

    # The menu holds the rest and pauses the story while it is open.
    assert result["menu"]["open"] is True
    assert result["menu"]["continue_disabled"] is True
    assert result["menu"]["toolbar_buttons"] == ["Log", "Auto", "Skip", "Hide", "Menu"]
    assert result["menu"]["escape_closes"] is True

    # Settings and read marks persist on this device.
    assert result["stored"] == {
        "text_speed": "slow",
        "auto_speed": "fast",
        "speaker_focus": False,
        "voice_volume": 40,
        "reduced_motion": False,
        "music_volume": 80,
        "ambience_volume": 80,
        "effects_volume": 100,
        "muted": False,
    }
    assert result["read_marks_kept"] is True


@engine
def test_real_saved_voice_volume_from_an_older_player_still_loads(tmp_path) -> None:
    package = stage_package(tmp_path, nodes=conversation(), entry="s0")
    result = native_ui_probe(tmp_path, "controls_settings", package)

    assert result["old_file"] == {
        "text_speed": "normal",
        "auto_speed": "normal",
        "speaker_focus": True,
        "voice_volume": 35,
        "reduced_motion": False,
        "music_volume": 80,
        "ambience_volume": 80,
        "effects_volume": 100,
        "muted": False,
    }
    assert result["bad_file"]["voice_volume"] == 100
    assert result["bad_file"]["text_speed"] == "normal"


@engine
def test_real_playtest_controls_stay_in_memory(tmp_path) -> None:
    package = stage_package(tmp_path, nodes=conversation(), entry="s0")
    result = native_ui_probe(tmp_path, "controls_preview", package)

    assert result["disabled"] == {
        "Save": True,
        "Load": True,
        "Quick save": True,
        "Quick load": True,
        "Restart": False,
        "Gallery": False,
    }
    assert result["log_works"] is True
    assert result["skip_works_in_memory"] == "c1"
    assert result["speed_changes"] == "instant"
    # Nothing a playtest does may touch the creator's storage.
    assert result["files_written"] == []
    # A playtest tells its parent page while an overlay needs Escape.
    assert result["overlay_calls"] == [True, False, True, False]
