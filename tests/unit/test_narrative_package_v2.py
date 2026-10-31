"""Story package v2 (ADR 0040): stage, expressions, sprites, theme and typed assets."""

import copy
import json

import pytest

from flint_graph.narrative.package import load_text_package
from flint_graph.narrative.validation import validate_story
from flint_graph.narrative.values import PackageError


def sha(seed: str) -> str:
    return (seed * 64)[:64]


def story() -> dict:
    return {
        "schema_version": "2",
        "id": "harbor",
        "title": "Harbor",
        "language": "en",
        "entry": "s0",
        "characters": {
            "mira": {
                "name": "Mira",
                "color": "#d5ae68",
                "sprites": {"neutral": "mira_neutral", "happy": "mira_happy"},
            },
            "oren": {"name": "Oren", "sprites": {"neutral": "oren_neutral"}},
            "voice": {"name": "A voice"},
        },
        "variables": {},
        "assets": {
            "dusk": {"kind": "image", "path": "assets/dusk.png", "sha256": sha("1")},
            "mira_neutral": {
                "kind": "image",
                "path": "assets/mira_neutral.png",
                "sha256": sha("2"),
            },
            "mira_happy": {"kind": "image", "path": "assets/mira_happy.png", "sha256": sha("3")},
            "oren_neutral": {
                "kind": "image",
                "path": "assets/oren_neutral.png",
                "sha256": sha("4"),
            },
            "old_type": {"kind": "font", "path": "assets/old_type.ttf", "sha256": sha("5")},
        },
        "theme": {
            "textbox": {
                "position": "bottom",
                "width": 92,
                "background": "#182635e6",
                "text": "#f0f4f6",
                "border": "#d5ae68",
                "radius": 12,
            },
            "name": {"show": True, "background": "#d5ae68", "text": "#182635"},
            "choices": {"background": "#f0f4f6", "text": "#182635", "border": "#d5ae68"},
            "font": {"asset": "old_type", "size": 22},
        },
        "nodes": {
            "s0": {
                "type": "stage",
                "background": "dusk",
                "show": [{"character": "mira", "sprite": "neutral", "position": "left"}],
                "next": "l1",
            },
            "l1": {
                "type": "line",
                "speaker": "mira",
                "expression": "happy",
                "text_id": "l1",
                "text": "The bell!",
                "next": "s1",
            },
            "s1": {
                "type": "stage",
                "show": [{"character": "oren", "sprite": "neutral", "position": "left"}],
                "next": "c1",
            },
            "c1": {
                "type": "choice",
                "text_id": "c1",
                "text": "Now?",
                "options": [{"id": "go", "text_id": "go", "text": "Go", "target": "s2"}],
            },
            "s2": {"type": "stage", "background": None, "hide": ["oren"], "next": "end"},
            "end": {"type": "end", "text_id": "end", "text": "Fin", "ending": "quiet"},
        },
    }


def changed(edit) -> dict:
    value = copy.deepcopy(story())
    edit(value)
    return value


def test_complete_v2_story_validates_and_minimal_theme_fields_are_optional():
    assert validate_story(story()) == ()
    bare = changed(lambda s: s.pop("theme"))
    assert validate_story(bare) == ()
    partial = changed(
        lambda s: s.update(theme={"textbox": {"position": "top"}, "font": {"asset": None}})
    )
    assert validate_story(partial) == ()
    translucent = changed(lambda s: s["characters"]["mira"].update(color="#d5ae68cc"))
    assert validate_story(translucent) == ()
    no_sprites = changed(lambda s: s["characters"].update(oren={"name": "Oren"}))
    with pytest.raises(PackageError):
        validate_story(no_sprites)  # s1 shows oren with a sprite he no longer has


def node(name: str, value: dict):
    return lambda s: s["nodes"].__setitem__(name, value)


SHOW_MIRA = {"character": "mira", "sprite": "neutral", "position": "left"}


@pytest.mark.parametrize(
    ("edit", "code"),
    [
        (node("s1", {"type": "stage", "next": "c1"}), "invalid_stage"),
        (
            node("s1", {"type": "stage", "show": [SHOW_MIRA, SHOW_MIRA], "next": "c1"}),
            "invalid_stage",
        ),
        (
            node(
                "s1",
                {
                    "type": "stage",
                    "show": [
                        SHOW_MIRA,
                        {"character": "oren", "sprite": "neutral", "position": "left"},
                    ],
                    "next": "c1",
                },
            ),
            "invalid_stage",
        ),
        (
            node("s1", {"type": "stage", "hide": ["mira"], "show": [SHOW_MIRA], "next": "c1"}),
            "invalid_stage",
        ),
        (node("s1", {"type": "stage", "hide": ["mira", "mira"], "next": "c1"}), "invalid_stage"),
        (node("s1", {"type": "stage", "hide": [], "next": "c1"}), "collection_limit"),
        (
            node("s1", {"type": "stage", "show": [{**SHOW_MIRA, "sprite": "angry"}], "next": "c1"}),
            "unknown_reference",
        ),
        (
            node(
                "s1",
                {"type": "stage", "show": [{**SHOW_MIRA, "character": "nobody"}], "next": "c1"},
            ),
            "unknown_reference",
        ),
        (
            node(
                "s1", {"type": "stage", "show": [{**SHOW_MIRA, "position": "middle"}], "next": "c1"}
            ),
            "invalid_value",
        ),
        (
            node("s1", {"type": "stage", "show": [{**SHOW_MIRA, "extra": 1}], "next": "c1"}),
            "unknown_field",
        ),
        (
            node("s1", {"type": "stage", "background": "old_type", "next": "c1"}),
            "invalid_asset_kind",
        ),
        (node("s1", {"type": "stage", "background": "missing", "next": "c1"}), "unknown_reference"),
        (
            node(
                "l1",
                {
                    "type": "line",
                    "expression": "happy",
                    "text_id": "l1",
                    "text": "Hi",
                    "next": "s1",
                },
            ),
            "invalid_expression",
        ),
        (
            node(
                "l1",
                {
                    "type": "line",
                    "speaker": "mira",
                    "expression": "angry",
                    "text_id": "l1",
                    "text": "Hi",
                    "next": "s1",
                },
            ),
            "unknown_reference",
        ),
        (
            node(
                "l1",
                {
                    "type": "line",
                    "speaker": "mira",
                    "background": "dusk",
                    "text_id": "l1",
                    "text": "Hi",
                    "next": "s1",
                },
            ),
            "unknown_field",
        ),
        (
            lambda s: s["characters"]["mira"]["sprites"].update(neutral="old_type"),
            "invalid_asset_kind",
        ),
        (lambda s: s["characters"]["mira"].update(color="#ABCDEF"), "invalid_value"),
        (lambda s: s["characters"]["mira"].update(color="red"), "invalid_value"),
        (
            lambda s: s["characters"]["mira"].update(sprites={f"e{i}": "dusk" for i in range(33)}),
            "collection_limit",
        ),
        (lambda s: s["theme"].update(sparkle=True), "unknown_field"),
        (lambda s: s["theme"]["textbox"].update(position="left"), "invalid_value"),
        (lambda s: s["theme"]["textbox"].update(width=39), "invalid_value"),
        (lambda s: s["theme"]["textbox"].update(radius=49), "invalid_value"),
        (lambda s: s["theme"]["textbox"].update(background="#18263"), "invalid_value"),
        (lambda s: s["theme"]["name"].update(show="yes"), "invalid_value"),
        (lambda s: s["theme"]["font"].update(asset="dusk"), "invalid_asset_kind"),
        (lambda s: s["theme"]["font"].update(size=49), "invalid_value"),
        (lambda s: s["assets"]["old_type"].update(path="assets/old_type.png"), "unsafe_path"),
        (lambda s: s["assets"]["dusk"].update(kind="audio"), "invalid_value"),
        (lambda s: s["assets"]["dusk"].pop("kind"), "missing_field"),
    ],
)
def test_v2_errors_are_reported_with_stable_codes(edit, code):
    with pytest.raises(PackageError) as raised:
        validate_story(changed(edit))
    assert raised.value.code == code


def test_v1_stays_exactly_v1():
    v1 = {
        "schema_version": "1",
        "id": "old",
        "title": "Old",
        "language": "en",
        "entry": "end",
        "characters": {},
        "variables": {},
        "assets": {},
        "nodes": {"end": {"type": "end", "text_id": "end", "text": "Fin", "ending": "done"}},
    }
    assert validate_story(v1) == ()
    with pytest.raises(PackageError, match="unknown_field"):
        validate_story({**v1, "theme": {}})
    stage = {"type": "stage", "background": None, "next": "end"}
    with pytest.raises(PackageError, match="invalid_node"):
        validate_story({**v1, "entry": "s", "nodes": {**v1["nodes"], "s": stage}})
    with pytest.raises(PackageError, match="unsupported_schema"):
        validate_story({**v1, "schema_version": "3"})


def test_expressions_for_a_speaker_who_is_never_on_stage_warn():
    def edit(s):
        s["nodes"]["l2"] = {
            "type": "line",
            "speaker": "oren",
            "expression": "neutral",
            "text_id": "l2",
            "text": "Late.",
            "next": "end",
        }
        s["nodes"]["s2"]["next"] = "l2"

    warnings = validate_story(changed(edit))
    assert [(item.code, item.location) for item in warnings] == [
        ("expression_off_stage", "nodes.l2")
    ]

    def varies(s):
        # Reachable both with and without Oren on stage: no definite absence, no warning.
        s["nodes"]["c1"]["options"].append(
            {"id": "stay", "text_id": "stay", "text": "Stay", "target": "l3"}
        )
        s["nodes"]["l3"] = {
            "type": "line",
            "speaker": "oren",
            "expression": "neutral",
            "text_id": "l3",
            "text": "Here.",
            "next": "s2",
        }
        s["nodes"]["s2"]["next"] = "l3b"
        s["nodes"]["l3b"] = {"type": "line", "text_id": "l3b", "text": "Then.", "next": "l3"}

    codes = [item.code for item in validate_story(changed(varies))]
    assert "expression_off_stage" not in codes


def test_asset_references_enter_the_package_hash_only_when_allowed():
    source = json.dumps(story()).encode()
    with pytest.raises(PackageError, match="assets_not_supported"):
        load_text_package(source)
    package = load_text_package(source, allow_asset_refs=True)
    assert [(asset.id, asset.path, asset.data) for asset in package.assets] == [
        ("dusk", "assets/dusk.png", None),
        ("mira_happy", "assets/mira_happy.png", None),
        ("mira_neutral", "assets/mira_neutral.png", None),
        ("old_type", "assets/old_type.ttf", None),
        ("oren_neutral", "assets/oren_neutral.png", None),
    ]
    assert [entry["id"] for entry in package.manifest["assets"]] == sorted(story()["assets"])
    other = changed(lambda s: s["assets"]["dusk"].update(sha256=sha("9")))
    again = load_text_package(json.dumps(other).encode(), allow_asset_refs=True)
    assert again.content_hash != package.content_hash
