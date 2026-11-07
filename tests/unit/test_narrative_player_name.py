"""The player names the protagonist (ADR 0072). The Godot player is held to this in live tests."""

import copy
import json

import pytest

from flint_graph.narrative.package import load_text_package
from flint_graph.narrative.player import Player, PlayerError
from flint_graph.narrative.validation import validate_story
from flint_graph.narrative.values import PackageError, clean_name

CLEANING = [
    ("Zoë", "Zoë"),
    ("  Mira  ", "Mira"),
    ("\u3000ミラ\u00a0", "ミラ"),
    ("", "Alex"),
    ("   ", "Alex"),
    ("\n\t", "Alex"),
    ("A\nB", "AB"),
    ("Li\u200bnk", "Link"),
    ("\u202eevil", "evil"),
    ("Sa\u0000m", "Sam"),
    ("[b]Bold[/b]", "[b]Bold[/b]"),
    ("{name}", "{name}"),
    ("👩‍🚀", "👩‍🚀"),
    ("x" * 40, "x" * 32),
    (" " + "x" * 31 + " y", "x" * 31),
]


def story() -> dict:
    return {
        "schema_version": "2",
        "id": "named",
        "title": "Named",
        "language": "en",
        "entry": "ask",
        "characters": {"hero": {"name": "Hero"}, "mira": {"name": "Mira"}},
        "variables": {},
        "assets": {},
        "player": {"default_name": "Alex", "character": "hero"},
        "nodes": {
            "ask": {"type": "name", "text_id": "ask", "text": "Your name?", "next": "hi"},
            "hi": {
                "type": "line",
                "text_id": "hi",
                "speaker": "mira",
                "text": "Hello, {name}. {name}!",
                "next": "me",
            },
            "me": {"type": "line", "text_id": "me", "speaker": "hero", "text": "Hi.", "next": "c"},
            "c": {
                "type": "choice",
                "text_id": "c",
                "text": "Well, {name}?",
                "options": [
                    {"id": "go", "text_id": "go", "text": "Go, {name}", "target": "e"},
                ],
            },
            "e": {"type": "end", "text_id": "e", "text": "Bye, {name}.", "ending": "done"},
        },
    }


def player(source=None) -> Player:
    return Player(load_text_package(json.dumps(source or story()).encode(), b"Original fixture."))


@pytest.mark.parametrize(("typed", "expected"), CLEANING)
def test_a_typed_name_is_cleaned_the_same_way_every_time(typed, expected):
    assert clean_name(typed, "Alex") == expected
    # What it makes is already clean.
    assert clean_name(expected, "Alex") == expected


def test_the_game_stops_to_ask_and_uses_the_answer_everywhere():
    game = player()
    assert game.view["type"] == "name"
    assert game.view["player_name"] == "Alex"
    assert game.state["player_name"] == "Alex"
    game.act("name:Zoë")
    assert game.view["text"] == "Hello, Zoë. Zoë!"
    assert game.view["speaker_name"] == "Mira", "only the player's own character takes the name"
    game.act("advance")
    assert game.view["speaker_name"] == "Zoë"
    game.act("advance")
    assert game.view["text"] == "Well, Zoë?"
    assert game.view["options"][0]["text"] == "Go, Zoë"
    game.act("choose:go")
    assert game.view["text"] == "Bye, Zoë."


def test_an_empty_answer_takes_the_default():
    game = player()
    game.act("name:   ")
    assert game.state["player_name"] == "Alex"


def test_a_name_is_shown_as_it_was_typed_and_never_as_a_placeholder_or_markup():
    game = player()
    game.act("name:[b]{name}[/b]")
    assert game.view["text"] == "Hello, [b]{name}[/b]. [b]{name}[/b]!"


def test_asking_is_the_only_way_past_the_question():
    game = player()
    with pytest.raises(PlayerError):
        game.act("advance")
    game.act("name:Mira")
    with pytest.raises(PlayerError):
        game.act("name:Someone else")
    assert game.state["player_name"] == "Mira"


def test_the_name_survives_a_save_and_a_tampered_one_is_refused():
    game = player()
    game.act("name:Zoë")
    saved = game.save()
    fresh = player()
    fresh.load_save(saved)
    assert fresh.state["player_name"] == "Zoë"
    assert fresh.view["text"] == "Hello, Zoë. Zoë!"
    for bad in ("", "x" * 33, " padded", 7, None):
        changed = json.loads(saved)
        changed["player_name"] = bad
        with pytest.raises(PlayerError):
            player().load_save(json.dumps(changed).encode())
    missing = json.loads(saved)
    del missing["player_name"]
    with pytest.raises(PlayerError):
        player().load_save(json.dumps(missing).encode())


def test_a_save_can_be_made_on_the_question_itself():
    game = player()
    fresh = player()
    fresh.load_save(game.save())
    assert fresh.view["type"] == "name"


def test_the_route_trace_records_the_name():
    game = player()
    game.act("name:Zoë")
    assert game.frame("name:Zoë")["player_name"] == "Zoë"


def test_a_story_without_a_player_is_exactly_as_it_was():
    source = story()
    del source["player"]
    source["entry"] = "hi"
    del source["nodes"]["ask"]
    game = player(source)
    assert "player_name" not in game.state
    assert "player_name" not in game.frame()
    assert "player_name" not in game.view
    assert game.view["text"] == "Hello, {name}. {name}!", "without a player it is ordinary text"
    assert "player_name" not in json.loads(game.save())


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda s: s["player"].update(default_name=""), "invalid_text"),
        (lambda s: s["player"].update(default_name=" Padded"), "invalid_text"),
        (lambda s: s["player"].update(default_name="x" * 33), "invalid_text"),
        (lambda s: s["player"].update(default_name=7), "invalid_text"),
        (lambda s: s["player"].update(character="nobody"), "unknown_reference"),
        (lambda s: s["player"].update(sparkle=True), "unknown_field"),
        (lambda s: s.pop("player"), "invalid_node"),
        (lambda s: s["nodes"]["ask"].update(next="nowhere"), "unknown_reference"),
        (lambda s: s["nodes"]["ask"].update(speaker="mira"), "unknown_field"),
    ],
)
def test_what_a_story_may_say_about_its_player(change, code):
    source = copy.deepcopy(story())
    change(source)
    with pytest.raises(PackageError) as caught:
        validate_story(source)
    assert caught.value.code == code


def test_format_one_has_no_player():
    source = story()
    source["schema_version"] = "1"
    with pytest.raises(PackageError):
        validate_story(source)
