"""Assistant tools for story format 2: characters, stage, theme, library assets, image actions."""

import copy
import json

import pytest
from pydantic import ValidationError

from flint_graph.narrative.assistant.assets import (
    LibraryRow,
    add_library_assets,
    library_entries,
    slug,
)
from flint_graph.narrative.assistant.context import build_turn_messages
from flint_graph.narrative.assistant.operations import (
    GenerateCharacterImages,
    Proposal,
    apply_operations,
    check_proposal,
)
from flint_graph.narrative.assistant.turn import ModelReply, run_turn


def sha(seed: str) -> str:
    return (seed * 64)[:64]


def test_assistant_sprites_default_to_high_resolution_and_allow_an_explicit_opt_out():
    action = {
        "op": "generate_character_images",
        "character": "ren",
        "appearance": "white hair",
        "character_type": "boy",
        "transparent": True,
    }
    assert GenerateCharacterImages.model_validate(action).hires is True
    assert GenerateCharacterImages.model_validate({**action, "hires": False}).hires is False
    assert GenerateCharacterImages.model_validate({**action, "transparent": False}).hires is False


def story() -> dict:
    return {
        "schema_version": "2",
        "id": "harbor",
        "title": "Harbor",
        "language": "en",
        "entry": "opening",
        "characters": {
            "mira": {"name": "Mira", "sprites": {"neutral": "mira_neutral"}, "color": "#d5ae68"}
        },
        "variables": {},
        "assets": {
            "mira_neutral": {
                "kind": "image",
                "path": "assets/mira_neutral.png",
                "sha256": sha("1"),
            }
        },
        "nodes": {
            "opening": {"type": "line", "text_id": "o", "text": "Fog.", "next": "end"},
            "end": {"type": "end", "text_id": "e", "text": "Fin", "ending": "done"},
        },
    }


ROWS = [
    LibraryRow("Harbor Fog", "background", "image/png", sha("2")),
    LibraryRow("Ren neutral", "sprite", "image/png", sha("3")),
    LibraryRow("Mira neutral copy", "sprite", "image/png", sha("1")),  # already in the story
    LibraryRow("Old Type", "font", "font/otf", sha("4")),
]


def proposal(*operations: dict) -> Proposal:
    return Proposal.model_validate({"summary": "Change", "operations": list(operations)})


def test_library_entries_get_story_ready_keys_once_per_file():
    entries = library_entries(story(), ROWS)
    assert [(item.key, item.kind, item.path) for item in entries] == [
        ("harbor_fog", "image", "assets/harbor_fog.png"),
        ("ren_neutral", "image", "assets/ren_neutral.png"),
        ("old_type", "font", "assets/old_type.otf"),
    ]
    assert slug("9 Lives!") == "asset_9_lives" and slug("CON") == "asset_con"
    clash = story()
    clash["assets"]["harbor_fog"] = {
        "kind": "image",
        "path": "assets/harbor_fog.png",
        "sha256": sha("9"),
    }
    assert library_entries(clash, ROWS)[0].key == "harbor_fog_2"


def test_new_character_fields_merge_and_theme_and_assets_apply():
    edit = apply_operations(
        story(),
        proposal(
            {"op": "upsert_character", "id": "mira", "name": "Mira Vale"},
            {
                "op": "upsert_character",
                "id": "ren",
                "name": "Ren",
                "color": "#c94f4fcc",
                "sprites": {"neutral": "ren_neutral"},
                "stage": {"scale": 160, "top": 4},
            },
            {"op": "set_theme", "theme": {"textbox": {"position": "top"}}},
            {
                "op": "add_asset",
                "id": "ren_neutral",
                "asset": {"kind": "image", "path": "assets/ren_neutral.png", "sha256": sha("3")},
            },
        ).operations,
    )
    assert edit.story["characters"]["mira"] == {
        "name": "Mira Vale",
        "sprites": {"neutral": "mira_neutral"},
        "color": "#d5ae68",
    }
    assert edit.story["characters"]["ren"]["stage"] == {"scale": 160, "top": 4}
    assert edit.story["theme"] == {"textbox": {"position": "top"}}
    assert "assets.ren_neutral" in edit.touched
    cleared = apply_operations(edit.story, proposal({"op": "set_theme", "theme": None}).operations)
    assert "theme" not in cleared.story


def test_image_actions_never_change_the_story_and_are_validated():
    actions = proposal(
        {
            "op": "generate_character_images",
            "character": "mira",
            "appearance": "medium hair, white hair, red eyes",
            "character_type": "boy",
            "framing": "full_body",
            "transparent": True,
        },
        {"op": "generate_backgrounds", "description": "harbor at night, rain"},
    )
    check = check_proposal(story(), actions.operations)
    assert check.diagnostics == () and check.story == story()
    assert check.touched == ("actions.backgrounds.1", "actions.images.mira.0")
    # A transparent cut-out is a stage sprite, so a portrait request becomes full-body.
    cutout = proposal(
        {
            "op": "generate_character_images",
            "character": "mira",
            "appearance": "x",
            "character_type": "boy",
            "framing": "portrait",
            "transparent": True,
        }
    ).operations[0]
    assert isinstance(cutout, GenerateCharacterImages) and cutout.framing == "full_body"
    for bad in (
        {
            "op": "generate_character_images",
            "character": "mira",
            "appearance": "x",
            "character_type": "robot",
        },
        {"op": "generate_backgrounds", "description": ""},
    ):
        with pytest.raises(ValidationError):
            proposal(bad)


def test_library_keys_the_model_uses_become_explicit_asset_additions():
    library = library_entries(story(), ROWS)
    staged = proposal(
        {
            "op": "upsert_character",
            "id": "ren",
            "name": "Ren",
            "sprites": {"neutral": "ren_neutral"},
        },
        {
            "op": "upsert_node",
            "id": "opening",
            "node": {
                "type": "stage",
                "background": "harbor_fog",
                "show": [{"character": "ren", "sprite": "neutral", "position": "left"}],
                "next": "line",
            },
        },
        {
            "op": "upsert_node",
            "id": "line",
            "node": {"type": "line", "text": "Fog.", "next": "end"},
        },
        {"op": "set_theme", "theme": {"font": {"asset": "old_type"}}},
    )
    resolved = add_library_assets(story(), staged, library)
    added = [item for item in resolved.operations if item.op == "add_asset"]
    assert sorted(item.id for item in added) == ["harbor_fog", "old_type", "ren_neutral"]
    check = check_proposal(story(), resolved.operations)
    assert check.diagnostics == (), check.diagnostics
    assert check.story["assets"]["old_type"]["kind"] == "font"
    # Unknown keys stay unknown, so validation asks the model to fix them.
    unknown = proposal(
        {
            "op": "upsert_node",
            "id": "opening",
            "node": {"type": "stage", "background": "nowhere", "next": "end"},
        }
    )
    assert add_library_assets(story(), unknown, library) == unknown


def test_context_shows_format_looks_assets_library_and_theme():
    value = copy.deepcopy(story())
    value["theme"] = {"textbox": {"position": "top"}}
    messages, _ = build_turn_messages(
        value,
        "Add Ren",
        library=library_entries(value, ROWS),
        profiles={"mira": "medium hair, black hair, glasses"},
    )
    text = messages[-1]["content"]
    assert "format: 2" in text
    assert 'looks: "medium hair, black hair, glasses"' in text
    assert "story assets:" in text and "mira_neutral: image" in text
    assert "library (approved" in text and "harbor_fog: background" in text
    assert "old_type: font" in text
    assert 'theme: {"textbox":{"position":"top"}}' in text
    plain, _ = build_turn_messages(
        {**story(), "schema_version": "1", "characters": {}, "assets": {}}, "x"
    )
    assert "format: 1" in plain[-1]["content"] and "library" not in plain[-1]["content"]


class Scripted:
    provider = "scripted"

    def __init__(self, *contents: str) -> None:
        self.contents, self.calls = list(contents), 0

    async def respond(self, messages, schema, on_delta=None):
        self.calls += 1
        return ModelReply(self.contents.pop(0), "scripted", 1, 1)


@pytest.mark.anyio
async def test_a_turn_resolves_library_assets_before_checking():
    content = json.dumps(
        {
            "reply": "Ren is ready; generate his sprites when you like.",
            "proposal": {
                "summary": "Add Ren on stage",
                "operations": [
                    {
                        "op": "upsert_character",
                        "id": "ren",
                        "name": "Ren",
                        "sprites": {"neutral": "ren_neutral"},
                    },
                    {
                        "op": "upsert_node",
                        "id": "opening",
                        "node": {
                            "type": "stage",
                            "background": "harbor_fog",
                            "show": [{"character": "ren", "sprite": "neutral", "position": "left"}],
                            "next": "line",
                        },
                    },
                    {
                        "op": "upsert_node",
                        "id": "line",
                        "node": {
                            "type": "line",
                            "speaker": "ren",
                            "expression": "neutral",
                            "text": "Fog.",
                            "next": "end",
                        },
                    },
                    {
                        "op": "generate_character_images",
                        "character": "ren",
                        "appearance": "medium hair, white hair, red eyes",
                        "character_type": "boy",
                        "framing": "full_body",
                        "transparent": True,
                    },
                ],
            },
        }
    )
    model = Scripted(content)
    result = await run_turn(model, story(), "Add Ren", library=library_entries(story(), ROWS))
    assert result.diagnostics == () and model.calls == 1
    assert result.story is not None and "harbor_fog" in result.story["assets"]
    assert any(item.op == "add_asset" for item in result.proposal.operations)
