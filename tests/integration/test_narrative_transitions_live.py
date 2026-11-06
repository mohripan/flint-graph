"""Opt-in real Godot qualification of transitions and effects (ADR 0065, runtime 0.9.0)."""

import os

import pytest
from test_narrative_godot_live import native_ui_probe, stage_package

from flint_graph.narrative import Player

engine = pytest.mark.skipif(
    not os.getenv("FLINT_GRAPH_NARRATIVE_GODOT_BIN"), reason="Explicit pinned Godot required"
)


def line(key, text, target, **extra):
    return {"type": "line", "text_id": key, "text": text, "next": target, **extra}


def staged(key, target, **extra):
    return {"type": "stage", "next": target, **extra}


def scenes():
    """One line per way of changing the screen."""
    mira = {"character": "mira", "sprite": "neutral", "position": "left"}
    return {
        "s0": staged("s0", "l0", background="dusk", show=[mira]),
        "l0": line("l0", "Opening.", "s1", speaker="mira"),
        "s1": staged("s1", "l1", background="pier", transition="dissolve"),
        "l1": line("l1", "Dissolved.", "s2"),
        "s2": staged("s2", "l2", background="dusk", transition="fade"),
        "l2": line("l2", "Faded.", "s3"),
        "s3": staged("s3", "l3", background="pier", transition="slide"),
        "l3": line("l3", "Slid.", "s4"),
        "s4": staged("s4", "l4", background="dusk", transition="cut"),
        "l4": line("l4", "Cut.", "s5"),
        "s5": staged("s5", "l5", background="pier"),
        "l5": line("l5", "Soft by default.", "s6"),
        "s6": staged("s6", "l6", effect="shake"),
        "l6": line("l6", "Shaken.", "s7"),
        "s7": staged("s7", "l7", effect="flash"),
        "l7": line("l7", "Flashed.", "e1"),
        "e1": {"type": "end", "text_id": "e1", "text": "Fin.", "ending": "done"},
    }


@engine
def test_real_godot_reports_the_same_presentation_as_the_reference(tmp_path) -> None:
    package = stage_package(tmp_path, nodes=scenes(), entry="s0")
    reference = Player(package)
    expected = []
    for _ in range(8):
        expected.append([reference.view["transition"], reference.view["effect"]])
        reference.act("advance")
    result = native_ui_probe(tmp_path, "transitions", package, frames=3000)
    assert result["presentation"] == expected
    assert expected[1] == ["dissolve", None]
    assert expected[6] == [None, "shake"]


@engine
def test_real_transitions_settle_on_exactly_the_screen_a_cut_shows(tmp_path) -> None:
    package = stage_package(tmp_path, nodes=scenes(), entry="s0")
    result = native_ui_probe(tmp_path, "transitions", package, frames=3000)

    # Each one really runs, and at the end nothing of it is left on screen.
    assert result["ran"] == {
        "dissolve": True,
        "fade": True,
        "slide": True,
        "cut": False,
        "soft": True,
    }
    assert result["settled_leftovers"] == []
    # The settled figures match a run with motion reduced, screen by screen.
    assert result["settled_screens_match"] is True
    # A press during a transition finishes it instead of skipping a line.
    assert result["press_finishes"] == {"node": "l2", "transitioning": False}
    # Auto and the text reveal wait until it has finished.
    assert result["auto_waits"] == {"during": "l2", "transitioning_then": True}
    # Effects leave the stage where it was.
    assert result["shake"] == {"moved": True, "settled_at_origin": True}
    assert result["flash"] == {"visible": True, "settled_clear": True, "once": True}
    # Reduced motion and Skip show none of it.
    assert result["reduced"] == {"transitioned": False, "shook": False, "flashed": False}
    assert result["skip_transitioned"] is False
    assert result["stored_reduced_motion"] is True
    # Restart and Load are cuts, whatever the first scene asks for.
    assert result["restart_transitioned"] is False
    assert result["load_transitioned"] is False


@engine
def test_real_saves_during_a_transition_hold_the_settled_screen(tmp_path) -> None:
    package = stage_package(tmp_path, nodes=scenes(), entry="s0")
    result = native_ui_probe(tmp_path, "transitions", package, frames=3000)
    assert result["save_mid_transition"] == {"node": "l2", "background": "dusk"}
