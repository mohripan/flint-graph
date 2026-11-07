"""Someone the assistant writes a line for, with a picture to show, is on stage when it plays.

A real thread wrote a scene for a character with four approved sprites. None was attached to the
story, so its stage step was left empty and the game showed nobody.
"""

import hashlib
import json

import pytest

from flint_graph.narrative.assistant.assets import LibraryEntry
from flint_graph.narrative.assistant.turn import ModelReply, run_turn


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sprite_entry(key: str = "agnes_sprite_1", character: str = "agnes") -> LibraryEntry:
    return LibraryEntry(
        key, "image", "sprite", key, f"assets/{key}.png", sha(key), character_id=character
    )


def story(*, sprites: dict[str, str] | None = None) -> dict:
    agnes: dict = {"name": "Agnes"}
    ren: dict = {"name": "Ren", "sprites": {"neutral": "ren_neutral", "happy": "ren_happy"}}
    if sprites:
        agnes["sprites"] = sprites
    return {
        "schema_version": "2",
        "id": "night",
        "title": "Night",
        "language": "en",
        "entry": "opening",
        "characters": {"agnes": agnes, "ren": ren},
        "variables": {},
        "assets": {
            name: {"kind": "image", "path": f"assets/{name}.png", "sha256": sha(name)}
            for name in ("ren_neutral", "ren_happy", "agnes_neutral", "street")
        },
        "nodes": {
            "opening": {"type": "line", "text_id": "opening_text", "text": "Dusk.", "next": "end"},
            "end": {"type": "end", "text_id": "end_text", "text": "Done.", "ending": "done"},
        },
    }


class Scripted:
    provider = "deterministic"

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.seen: list[list[dict[str, str]]] = []

    async def respond(self, messages, schema, on_delta=None):
        self.seen.append(list(messages))
        return ModelReply(self.answers.pop(0), "scripted", 1, 1)


def answer(*operations: dict) -> str:
    return json.dumps(
        {"reply": "Here.", "proposal": {"summary": "Change", "operations": list(operations)}}
    )


def line(key: str, speaker: str | None, following: str, **fields) -> dict:
    node: dict = {
        "type": "line",
        "text_id": f"{key}_text",
        "text": f"Words of {key}.",
        "next": following,
    }
    if speaker:
        node["speaker"] = speaker
    return {"op": "upsert_node", "id": key, "node": {**node, **fields}}


def stage(key: str, following: str, **fields) -> dict:
    return {
        "op": "upsert_node",
        "id": key,
        "node": {"type": "stage", "next": following, "transition": "fade", **fields},
    }


LINK = line("opening", None, "scene")


async def turn(source: dict, *operations: dict, request: str = "Write a scene.", library=()):
    return await run_turn(Scripted(answer(*operations)), source, request, library=library)


@pytest.mark.anyio
async def test_the_real_thread_shows_the_character_and_attaches_her_picture():
    result = await turn(
        story(),
        LINK,
        stage("scene", "talk", background=None),
        line("talk", "agnes", "end"),
        library=(sprite_entry(), sprite_entry("agnes_sprite_2")),
    )
    assert result.diagnostics == ()
    agnes = result.story["characters"]["agnes"]
    assert agnes["sprites"] == {"default": "agnes_sprite_1"}
    assert agnes["name"] == "Agnes"
    assert result.story["assets"]["agnes_sprite_1"]["sha256"] == sha("agnes_sprite_1")
    assert result.story["nodes"]["scene"]["show"] == [
        {"character": "agnes", "sprite": "default", "position": "center"}
    ]


@pytest.mark.anyio
async def test_a_step_that_asks_for_her_keeps_her_once_she_has_a_picture():
    # This used to be dropped, as "someone with no pictures cannot be shown yet".
    # The model still writes "neutral" sometimes, which here is her default.
    wanted = {"character": "agnes", "sprite": "neutral", "position": "left"}
    result = await turn(
        story(),
        LINK,
        stage("scene", "talk", show=[wanted]),
        line("talk", "agnes", "end", expression="neutral"),
        library=(sprite_entry(),),
    )
    assert result.diagnostics == ()
    assert result.story["nodes"]["scene"]["show"] == [{**wanted, "sprite": "default"}]
    assert result.story["nodes"]["talk"]["expression"] == "default"


@pytest.mark.anyio
async def test_a_picture_the_story_already_has_is_used_rather_than_another():
    result = await turn(
        story(sprites={"neutral": "agnes_neutral"}),
        LINK,
        stage("scene", "talk", background="street"),
        line("talk", "agnes", "end"),
        library=(sprite_entry(),),
    )
    assert result.story["characters"]["agnes"]["sprites"] == {"neutral": "agnes_neutral"}
    assert "agnes_sprite_1" not in result.story["assets"]
    assert result.story["nodes"]["scene"]["show"][0]["character"] == "agnes"


@pytest.mark.anyio
async def test_with_no_stage_step_written_one_is_added_before_the_line():
    result = await turn(story(), line("opening", None, "talk"), line("talk", "ren", "end"))
    assert result.diagnostics == ()
    nodes = result.story["nodes"]
    added = nodes["opening"]["next"]
    assert added != "talk"
    assert nodes[added]["type"] == "stage"
    assert nodes[added]["next"] == "talk"
    assert nodes[added]["show"] == [{"character": "ren", "sprite": "neutral", "position": "center"}]


@pytest.mark.anyio
async def test_a_new_first_line_gets_its_step_at_the_start_of_the_story():
    result = await turn(story(), line("talk", "ren", "opening"), {"op": "set_entry", "id": "talk"})
    assert result.diagnostics == ()
    entry = result.story["entry"]
    assert result.story["nodes"][entry]["type"] == "stage"
    assert result.story["nodes"][entry]["next"] == "talk"


@pytest.mark.anyio
async def test_the_line_asks_for_a_face_and_she_arrives_wearing_it():
    result = await turn(
        story(),
        LINK,
        stage("scene", "talk", background="street"),
        line("talk", "ren", "end", expression="happy"),
    )
    assert result.story["nodes"]["scene"]["show"][0]["sprite"] == "happy"


@pytest.mark.anyio
async def test_two_speakers_do_not_stand_in_the_same_place():
    result = await turn(
        story(sprites={"neutral": "agnes_neutral"}),
        LINK,
        stage("scene", "first", background="street"),
        line("first", "agnes", "second"),
        line("second", "ren", "end"),
    )
    shown = result.story["nodes"]["scene"]["show"]
    assert {entry["character"] for entry in shown} == {"agnes", "ren"}
    assert len({entry["position"] for entry in shown}) == 2


@pytest.mark.anyio
async def test_both_branches_of_a_choice_are_covered_by_the_step_before_it():
    choice = {
        "type": "choice",
        "text_id": "ask_text",
        "text": "Well?",
        "options": [
            {"id": "a", "text_id": "ask_a", "text": "A", "target": "left_path"},
            {"id": "b", "text_id": "ask_b", "text": "B", "target": "right_path"},
        ],
    }
    result = await turn(
        story(),
        LINK,
        stage("scene", "ask", background="street"),
        {"op": "upsert_node", "id": "ask", "node": choice},
        line("left_path", "ren", "end"),
        line("right_path", "ren", "end"),
    )
    assert result.diagnostics == ()
    assert [entry["character"] for entry in result.story["nodes"]["scene"]["show"]] == ["ren"]
    assert result.story["nodes"]["ask"]["type"] == "choice"


@pytest.mark.anyio
async def test_someone_already_on_stage_is_left_where_they_are():
    there = {"character": "ren", "sprite": "neutral", "position": "right"}
    result = await turn(
        story(),
        LINK,
        stage("scene", "talk", show=[there]),
        line("talk", "ren", "end"),
    )
    assert result.story["nodes"]["scene"]["show"] == [there]


@pytest.mark.anyio
async def test_on_stage_by_only_one_route_is_not_on_stage():
    source = story()
    source["nodes"]["opening"] = {
        "type": "choice",
        "text_id": "pick_text",
        "text": "Which way?",
        "options": [
            {"id": "a", "text_id": "pick_a", "text": "A", "target": "with_her"},
            {"id": "b", "text_id": "pick_b", "text": "B", "target": "alone_here"},
        ],
    }
    source["nodes"]["with_her"] = {
        "type": "stage",
        "show": [{"character": "ren", "sprite": "neutral", "position": "left"}],
        "next": "end",
    }
    source["nodes"]["alone_here"] = {
        "type": "line",
        "text_id": "alone_text",
        "text": "Nobody.",
        "next": "end",
    }
    result = await turn(
        source,
        {**stage("with_her", "talk"), "node": {**source["nodes"]["with_her"], "next": "talk"}},
        line("alone_here", None, "talk"),
        line("talk", "ren", "end"),
    )
    assert result.diagnostics == ()
    nodes = result.story["nodes"]
    # Coming through with_her she is there already, so a step just before the line covers both.
    assert nodes["alone_here"]["next"] != "talk"
    assert nodes[nodes["alone_here"]["next"]]["type"] == "stage"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "request_text",
    ["She speaks from off screen.", "Ren leaves before this.", "The stage stays empty here."],
)
async def test_asked_for_nobody_on_stage_nobody_is_added(request_text):
    result = await turn(
        story(),
        LINK,
        stage("scene", "talk", background="street"),
        line("talk", "ren", "end"),
        request=request_text,
    )
    assert "show" not in result.story["nodes"]["scene"]


@pytest.mark.anyio
async def test_a_step_that_hides_them_means_it():
    result = await turn(
        story(),
        LINK,
        stage("scene", "talk", hide=["ren"]),
        line("talk", "ren", "end"),
    )
    assert "show" not in result.story["nodes"]["scene"]


@pytest.mark.anyio
async def test_changing_the_words_of_a_saved_line_stages_nobody():
    source = story()
    source["nodes"]["talk"] = {
        "type": "line",
        "text_id": "talk_text",
        "speaker": "ren",
        "text": "Old words.",
        "next": "end",
    }
    source["nodes"]["opening"]["next"] = "talk"
    result = await turn(source, line("talk", "ren", "end"), request="Reword Ren's line.")
    assert result.story["nodes"]["opening"]["next"] == "talk"
    assert not any(node["type"] == "stage" for node in result.story["nodes"].values())


SCENE_FOR_AGNES = (
    LINK,
    stage("scene", "talk", background="street"),
    line("talk", "agnes", "end"),
)
CHARACTER_FIRST = (
    {"op": "upsert_character", "id": "agnes", "name": "Agnes"},
    {
        "op": "generate_character_images",
        "character": "agnes",
        "appearance": "long pink hair, black coat",
        "character_type": "girl",
        "framing": "full_body",
        "transparent": True,
    },
)


@pytest.mark.anyio
async def test_a_scene_for_someone_with_no_picture_is_refused_until_the_model_makes_them_first():
    source = story()
    model = Scripted(answer(*SCENE_FOR_AGNES), answer(*CHARACTER_FIRST))
    result = await run_turn(model, source, "Write a scene.", capabilities=("images",))
    assert result.attempts == 2
    assert result.diagnostics == ()
    assert "talk" not in result.story["nodes"]
    # The repair says what to do, in words a small model can follow.
    assert "no approved picture" in model.seen[1][-1]["content"]


@pytest.mark.anyio
async def test_a_model_that_keeps_writing_the_scene_gets_nothing_it_can_accept():
    answers = [answer(*SCENE_FOR_AGNES)] * 4
    result = await run_turn(Scripted(*answers), story(), "Write a scene.")
    assert [item.code for item in result.diagnostics] == ["needs_approved_picture"]
    assert result.story is None


@pytest.mark.anyio
async def test_another_characters_picture_does_not_count():
    answers = [answer(*SCENE_FOR_AGNES)] * 4
    result = await run_turn(
        Scripted(*answers), story(), "Write a scene.", library=(sprite_entry("ren_extra", "ren"),)
    )
    assert [item.code for item in result.diagnostics] == ["needs_approved_picture"]


@pytest.mark.anyio
async def test_a_portrait_will_do_when_there_is_no_cut_out_and_a_cut_out_is_preferred():
    portrait = LibraryEntry(
        "agnes_portrait",
        "image",
        "character_portrait",
        "p",
        "assets/agnes_portrait.png",
        sha("agnes_portrait"),
        character_id="agnes",
    )
    alone = await turn(story(), *SCENE_FOR_AGNES, library=(portrait,))
    assert alone.story["characters"]["agnes"]["sprites"] == {"default": "agnes_portrait"}
    both = await turn(story(), *SCENE_FOR_AGNES, library=(portrait, sprite_entry()))
    assert both.story["characters"]["agnes"]["sprites"] == {"default": "agnes_sprite_1"}


@pytest.mark.anyio
async def test_narration_needs_no_picture():
    result = await turn(story(), line("opening", None, "more"), line("more", None, "end"))
    assert result.diagnostics == ()


@pytest.mark.anyio
async def test_a_saved_line_for_someone_with_no_picture_can_still_be_reworded():
    # Stories from before this rule stay editable.
    source = story()
    source["nodes"]["talk"] = {
        "type": "line",
        "text_id": "talk_text",
        "speaker": "agnes",
        "text": "Old words.",
        "next": "end",
    }
    source["nodes"]["opening"]["next"] = "talk"
    result = await turn(source, line("talk", "agnes", "end"), request="Reword her line.")
    assert result.diagnostics == ()


@pytest.mark.anyio
async def test_a_full_stage_is_left_for_the_creator_to_arrange():
    source = story(sprites={"neutral": "agnes_neutral"})
    source["characters"]["kei"] = {"name": "Kei", "sprites": {"neutral": "ren_neutral"}}
    source["characters"]["tomo"] = {"name": "Tomo", "sprites": {"neutral": "ren_neutral"}}
    trio = [
        {"character": "ren", "sprite": "neutral", "position": "left"},
        {"character": "kei", "sprite": "neutral", "position": "center"},
        {"character": "tomo", "sprite": "neutral", "position": "right"},
    ]
    result = await turn(
        source,
        LINK,
        stage("scene", "talk", show=trio),
        line("talk", "agnes", "end"),
    )
    assert result.diagnostics == ()
    assert result.story["nodes"]["scene"]["show"] == trio
