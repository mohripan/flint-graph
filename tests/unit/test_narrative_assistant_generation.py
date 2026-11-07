"""The assistant's generation actions, and what it knows and is told when it gets them wrong."""

import json
import struct
import zlib

import pytest
from pydantic import ValidationError

from flint_graph.narrative.assistant.assets import (
    LibraryRow,
    add_library_assets,
    library_entries,
)
from flint_graph.narrative.assistant.context import build_turn_messages
from flint_graph.narrative.assistant.operations import (
    GenerateCg,
    GenerateExpressions,
    GenerateVoice,
    Proposal,
    apply_operations,
    check_proposal,
)
from flint_graph.narrative.assistant.prompts import RESPONSE_SCHEMA, response_schema
from flint_graph.narrative.assistant.turn import ModelReply, run_turn
from flint_graph.narrative.face_box import face_box_from_png
from flint_graph.narrative.values import Diagnostic


def sha(seed: str) -> str:
    return (seed * 64)[:64]


def story() -> dict:
    return {
        "schema_version": "2",
        "id": "harbor",
        "title": "Harbor",
        "language": "en",
        "entry": "opening",
        "characters": {"mira": {"name": "Mira", "sprites": {"neutral": "mira_neutral"}}},
        "variables": {},
        "assets": {
            "mira_neutral": {
                "kind": "image",
                "path": "assets/mira_neutral.png",
                "sha256": sha("1"),
            }
        },
        "nodes": {
            "opening": {
                "type": "line",
                "text_id": "opening_text",
                "speaker": "mira",
                "text": "Fog again.",
                "next": "ending",
            },
            "narration": {
                "type": "line",
                "text_id": "narration_text",
                "text": "The bell rang.",
                "next": "ending",
            },
            "ending": {"type": "end", "text_id": "ending_text", "text": "Done.", "ending": "done"},
        },
    }


def proposal(*operations: dict) -> Proposal:
    return Proposal.model_validate({"summary": "Do it", "operations": list(operations)})


class Scripted:
    provider = "deterministic"

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.calls: list[list[dict[str, str]]] = []

    async def respond(self, messages, schema, on_delta=None):
        self.calls.append(list(messages))
        return ModelReply(self.answers.pop(0), "scripted", 1, 1)


def answer(*operations: dict, reply: str = "Here.") -> str:
    return json.dumps(
        {"reply": reply, "proposal": {"summary": "Change", "operations": list(operations)}}
    )


def test_expression_voice_and_cg_actions_never_change_the_story():
    operations = proposal(
        {"op": "generate_expressions", "character": "mira", "expressions": ["happy", "angry"]},
        {"op": "generate_voice", "character": "mira", "lines": ["opening"], "voice": "af_heart"},
        {"op": "generate_cg", "characters": ["mira"], "description": "Mira rings the harbor bell"},
    ).operations
    edit = apply_operations(story(), operations)
    assert edit.story == story()
    assert edit.touched == (
        "actions.cg.2",
        "actions.expressions.mira.0",
        "actions.voice.mira.1",
    )


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (GenerateExpressions, {"character": "mira", "expressions": []}),
        (GenerateExpressions, {"character": "mira", "expressions": ["a", "b", "c", "d", "e"]}),
        (GenerateVoice, {"character": "mira", "lines": []}),
        (GenerateVoice, {"character": "mira", "lines": [f"l{i}" for i in range(25)]}),
        (GenerateCg, {"characters": [], "description": "x"}),
        (GenerateCg, {"characters": ["a", "b", "c"], "description": "x"}),
        (GenerateCg, {"characters": ["a"], "description": ""}),
    ],
)
def test_actions_stay_within_what_their_jobs_accept(model, data):
    op = model.model_fields["op"].annotation.__args__[0]
    with pytest.raises(ValidationError):
        model.model_validate({"op": op, **data})


def test_an_action_must_name_things_that_exist_so_the_model_can_fix_it():
    check = check_proposal(
        story(),
        proposal(
            {"op": "generate_expressions", "character": "ghost", "expressions": ["happy"]},
            {"op": "generate_cg", "characters": ["mira", "ghost"], "description": "A meeting"},
            {"op": "generate_voice", "character": "mira", "lines": ["nowhere"]},
            {"op": "generate_voice", "character": "mira", "lines": ["ending"]},
            {"op": "generate_voice", "character": "mira", "lines": ["narration"]},
        ).operations,
    )
    assert check.story is None
    assert [(item.code, item.location) for item in check.diagnostics] == [
        ("unknown_reference", "operations.0.character"),
        ("unknown_reference", "operations.1.characters"),
        ("invalid_voice_line", "operations.2.lines"),
        ("invalid_voice_line", "operations.3.lines"),
        ("invalid_voice_line", "operations.4.lines"),
    ]


def test_an_action_may_name_what_the_same_proposal_adds():
    check = check_proposal(
        story(),
        proposal(
            {"op": "upsert_character", "id": "anna", "name": "Anna"},
            {
                "op": "upsert_node",
                "id": "hello",
                "node": {"type": "line", "speaker": "anna", "text": "Hi.", "next": "ending"},
            },
            {"op": "generate_expressions", "character": "anna", "expressions": ["happy"]},
            {"op": "generate_voice", "character": "anna", "lines": ["hello"]},
        ).operations,
    )
    assert check.diagnostics == ()


class Recording(Scripted):
    def __init__(self, *answers: str) -> None:
        super().__init__(*answers)
        self.schemas: list[dict] = []

    async def respond(self, messages, schema, on_delta=None):
        self.schemas.append(schema)
        return await super().respond(messages, schema, on_delta)


def _ops(schema: dict) -> set[str]:
    items = schema["properties"]["proposal"]["anyOf"][0]["properties"]["operations"]["items"]
    return {shape["properties"]["op"].get("const") for shape in items["anyOf"]}


@pytest.mark.anyio
async def test_a_child_session_cannot_write_another_child_session():
    """Asked nicely, the live model tried anyway, and so did no work on its task."""
    child = {"op": "start_child_session", "title": "Deeper", "task": "Do it again."}
    edit = {
        "op": "upsert_node",
        "id": "hi",
        "node": {"type": "line", "text": "Hi.", "next": "ending"},
    }
    inner = Recording(answer(child, edit))
    result = await run_turn(inner, story(), "Do the task.", child_session=True)
    assert "start_child_session" not in _ops(inner.schemas[0])
    assert [item.op for item in result.proposal.operations] == ["upsert_node"]

    outer = Recording(answer(child, edit))
    result = await run_turn(outer, story(), "Split the work.")
    assert "start_child_session" in _ops(outer.schemas[0])
    assert "start_child_session" in [item.op for item in result.proposal.operations]


def test_library_keeps_audio_after_pictures_and_says_whose_picture_it_is():
    rows = [
        LibraryRow("line one", "voice", "audio/wav", sha("a")),
        LibraryRow("Rainy street", "background", "image/png", sha("b")),
        LibraryRow("Anna smile", "sprite", "image/png", sha("c"), "anna"),
    ]
    entries = library_entries(story(), rows)
    assert [entry.key for entry in entries] == ["rainy_street", "anna_smile", "line_one"]
    clip = entries[-1]
    assert (clip.kind, clip.path, clip.library_kind) == ("audio", "assets/line_one.wav", "voice")
    assert entries[1].character_id == "anna"
    messages, _ = build_turn_messages(story(), "Hi", library=entries)
    assert '  anna_smile: sprite "Anna smile" of anna' in messages[-1]["content"]


def test_a_cg_or_a_voice_clip_from_the_library_is_added_to_the_story():
    rows = [
        LibraryRow("Bell CG", "image", "image/png", sha("b")),
        LibraryRow("Line one", "voice", "audio/wav", sha("a")),
    ]
    entries = library_entries(story(), rows)
    done = add_library_assets(
        story(),
        proposal(
            {
                "op": "upsert_node",
                "id": "bell",
                "node": {"type": "stage", "cg": "bell_cg", "next": "opening"},
            },
            {
                "op": "upsert_node",
                "id": "opening",
                "node": {
                    "type": "line",
                    "speaker": "mira",
                    "text": "Fog again.",
                    "voice": {"mode": "full", "audio": "line_one"},
                    "next": "ending",
                },
            },
        ),
        entries,
    )
    added = {item.id: item.asset for item in done.operations if item.op == "add_asset"}
    assert added["bell_cg"]["kind"] == "image"
    assert added["line_one"] == {"kind": "audio", "path": "assets/line_one.wav", "sha256": sha("a")}
    assert check_proposal(story(), done.operations).diagnostics == ()


@pytest.mark.anyio
async def test_a_narrator_speaker_is_narration_without_another_model_call():
    """The live model invented this repeatedly; each retry costs about a minute."""
    node = {"type": "line", "speaker": "narrator", "text": "Rain.", "next": "ending"}
    model = Scripted(answer({"op": "upsert_node", "id": "rain", "node": node}))
    result = await run_turn(model, story(), "Add rain.")
    assert result.diagnostics == () and result.attempts == 1 and len(model.calls) == 1
    assert "speaker" not in result.story["nodes"]["rain"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("voice", "speaker", "expected"),
    [
        ({"mode": "full"}, None, None),
        ({"mode": "full", "text": "I can hear it."}, "mira", {"mode": "full"}),
        (
            {"mode": "vocalization", "text": "fufu"},
            "mira",
            {"mode": "vocalization", "text": "fufu"},
        ),
    ],
)
async def test_common_voice_slips_are_corrected_without_another_model_call(
    voice, speaker, expected
):
    node = {"type": "line", "text": "Hi.", "next": "ending", "voice": voice}
    if speaker:
        node["speaker"] = speaker
    model = Scripted(answer({"op": "upsert_node", "id": "hi", "node": node}))
    result = await run_turn(model, story(), "Add a line.")
    assert result.diagnostics == () and len(model.calls) == 1
    assert result.story["nodes"]["hi"].get("voice") == expected


@pytest.mark.anyio
async def test_an_asset_id_where_an_expression_belongs_needs_no_repair():
    """The live model wrote sprite: mira_neutral, and then repeated it through both repairs."""
    node = {
        "type": "stage",
        "next": "opening",
        "show": [{"character": "mira", "sprite": "mira_neutral", "position": "center"}],
    }
    model = Scripted(answer({"op": "upsert_node", "id": "enter", "node": node}))
    result = await run_turn(model, story(), "Bring her on.")
    assert result.diagnostics == () and len(model.calls) == 1
    assert result.story["nodes"]["enter"]["show"][0]["sprite"] == "neutral"


@pytest.mark.anyio
async def test_a_repair_about_the_stage_lists_each_characters_expressions():
    broken = {
        "type": "stage",
        "next": "opening",
        "show": [{"character": "mira", "sprite": "grinning", "position": "center"}],
    }
    fixed = {**broken, "show": [{"character": "mira", "sprite": "neutral", "position": "center"}]}
    model = Scripted(
        answer({"op": "upsert_node", "id": "enter", "node": broken}),
        answer({"op": "upsert_node", "id": "enter", "node": fixed}),
    )
    result = await run_turn(model, story(), "Bring her on.")
    assert result.attempts == 2 and result.diagnostics == ()
    repair = model.calls[1][-1]["content"]
    assert "mira: neutral" in repair and "not an asset id" in repair


@pytest.mark.anyio
async def test_a_cg_still_being_generated_is_not_used_by_a_made_up_id():
    node = {
        "type": "stage",
        "next": "opening",
        "cg": "bell_cg",
        "show": [{"character": "mira", "sprite": "neutral", "position": "center"}],
    }
    model = Scripted(
        answer(
            {"op": "upsert_node", "id": "bell", "node": node},
            {"op": "generate_cg", "characters": ["mira"], "description": "Mira at the bell"},
        )
    )
    result = await run_turn(model, story(), "A CG of her at the bell.")
    assert result.diagnostics == () and len(model.calls) == 1
    assert "cg" not in result.story["nodes"]["bell"]
    assert [op.op for op in result.proposal.operations] == ["upsert_node", "generate_cg"]


@pytest.mark.anyio
async def test_an_invented_cg_with_nothing_generating_is_still_a_mistake():
    node = {
        "type": "stage",
        "next": "opening",
        "cg": "bell_cg",
        "show": [{"character": "mira", "sprite": "neutral", "position": "center"}],
    }
    fixed = {key: value for key, value in node.items() if key != "cg"}
    model = Scripted(
        answer({"op": "upsert_node", "id": "bell", "node": node}),
        answer({"op": "upsert_node", "id": "bell", "node": fixed}),
    )
    result = await run_turn(model, story(), "A stage.")
    assert result.attempts == 2
    assert "no asset of that kind" in model.calls[1][-1]["content"]


@pytest.mark.anyio
async def test_a_voices_name_in_the_clip_field_is_dropped_without_another_call():
    node = {
        "type": "line",
        "speaker": "mira",
        "text": "Hi.",
        "next": "ending",
        "voice": {"mode": "full", "audio": "af_jessica"},
    }
    model = Scripted(answer({"op": "upsert_node", "id": "hi", "node": node}))
    result = await run_turn(model, story(), "Add a voiced line.")
    assert result.diagnostics == () and len(model.calls) == 1
    assert result.story["nodes"]["hi"]["voice"] == {"mode": "full"}


def voiced_story() -> dict:
    current = story()
    current["assets"]["clip"] = {"kind": "audio", "path": "assets/clip.wav", "sha256": sha("9")}
    current["nodes"]["opening"]["voice"] = {"mode": "full", "audio": "clip"}
    return current


def test_rewriting_a_line_with_the_same_words_keeps_its_clip():
    node = {
        "type": "line",
        "speaker": "mira",
        "text": "Fog again.",
        "next": "narration",
        "voice": {"mode": "full"},
    }
    edit = apply_operations(
        voiced_story(), proposal({"op": "upsert_node", "id": "opening", "node": node}).operations
    )
    assert edit.story["nodes"]["opening"]["voice"] == {"mode": "full", "audio": "clip"}


def test_new_words_do_not_keep_a_clip_of_the_old_ones():
    node = {
        "type": "line",
        "speaker": "mira",
        "text": "Sunshine at last.",
        "next": "narration",
        "voice": {"mode": "full"},
    }
    edit = apply_operations(
        voiced_story(), proposal({"op": "upsert_node", "id": "opening", "node": node}).operations
    )
    assert edit.story["nodes"]["opening"]["voice"] == {"mode": "full"}


@pytest.mark.anyio
async def test_an_expression_still_being_generated_shows_the_usual_face_for_now():
    node = {
        "type": "stage",
        "next": "opening",
        "show": [{"character": "mira", "sprite": "nervous", "position": "center"}],
    }
    model = Scripted(
        answer(
            {"op": "generate_expressions", "character": "mira", "expressions": ["nervous"]},
            {"op": "upsert_node", "id": "enter", "node": node},
        )
    )
    result = await run_turn(model, story(), "She looks nervous.")
    assert result.diagnostics == () and len(model.calls) == 1
    assert result.story["nodes"]["enter"]["show"][0]["sprite"] == "neutral"


@pytest.mark.anyio
async def test_a_narrator_the_story_really_has_keeps_speaking():
    current = story()
    current["characters"]["narrator"] = {"name": "The Narrator"}
    node = {"type": "line", "speaker": "narrator", "text": "Rain.", "next": "ending"}
    result = await run_turn(
        Scripted(answer({"op": "upsert_node", "id": "rain", "node": node})), current, "Add rain."
    )
    assert result.story["nodes"]["rain"]["speaker"] == "narrator"


@pytest.mark.anyio
async def test_a_repair_says_what_exists_instead_of_only_where_the_problem_is():
    broken = {"type": "line", "speaker": "aya", "text": "Hi.", "next": "nowhere"}
    fixed = {"type": "line", "speaker": "mira", "text": "Hi.", "next": "ending"}
    model = Scripted(
        answer({"op": "upsert_node", "id": "hi", "node": broken}),
        answer({"op": "upsert_node", "id": "hi", "node": fixed}),
    )
    result = await run_turn(model, story(), "Add a line.")
    assert result.attempts == 2 and result.diagnostics == ()
    repair = model.calls[1][-1]["content"]
    # One line per problem, naming the ids that do exist.
    assert "no character has this id" in repair and "mira" in repair
    assert "Leave out speaker for narration" in repair


@pytest.mark.anyio
async def test_a_repair_names_the_scenes_that_exist():
    broken = {"type": "line", "text": "Hi.", "next": "nowhere"}
    fixed = {"type": "line", "text": "Hi.", "next": "ending"}
    model = Scripted(
        answer({"op": "upsert_node", "id": "hi", "node": broken}),
        answer({"op": "upsert_node", "id": "hi", "node": fixed}),
    )
    await run_turn(model, story(), "Add a line.")
    repair = model.calls[1][-1]["content"]
    assert "no scene has this id" in repair and "ending" in repair and "hi" in repair


@pytest.mark.anyio
async def test_a_repair_about_music_lists_the_files_that_exist():
    invented = {"type": "stage", "music": "piano_track", "next": "ending"}
    fixed = {"type": "stage", "music": "harbor_theme", "next": "ending"}
    source = story()
    rows = [
        LibraryRow("Harbor theme", "music", "audio/ogg", sha("4")),
        LibraryRow("Door slam", "sound", "audio/wav", sha("5")),
    ]
    model = Scripted(
        answer({"op": "upsert_node", "id": "hi", "node": invented}),
        answer({"op": "upsert_node", "id": "hi", "node": fixed}),
    )
    await run_turn(model, source, "Add music.", library=library_entries(source, rows))
    repair = model.calls[1][-1]["content"]
    assert "harbor_theme" in repair and "upload one in Assets" in repair
    assert "door_slam" not in repair, "A sound effect is not a music file"


@pytest.mark.anyio
async def test_an_empty_cast_list_on_a_stage_step_needs_no_repair():
    source = story()
    source["assets"]["dusk"] = {"kind": "image", "path": "assets/dusk.png", "sha256": sha("7")}
    node = {"type": "stage", "background": "dusk", "show": [], "hide": [], "next": "ending"}
    result = await run_turn(
        Scripted(answer({"op": "upsert_node", "id": "hi", "node": node})), source, "Add a step."
    )
    assert result.diagnostics == ()
    assert result.attempts == 1
    assert result.proposal.operations[0].node == {
        "type": "stage",
        "background": "dusk",
        "next": "ending",
    }


@pytest.mark.anyio
async def test_a_stage_step_that_changes_nothing_is_left_out_without_another_call():
    pointed = {**story()["nodes"]["opening"], "next": "hi"}
    model = Scripted(
        answer(
            {"op": "upsert_node", "id": "opening", "node": pointed},
            {"op": "upsert_node", "id": "hi", "node": {"type": "stage", "next": "ending"}},
        )
    )
    result = await run_turn(model, story(), "Add a step.")
    assert len(model.calls) == 1
    # Without the empty step the opening is exactly as saved, so nothing is left to propose.
    assert result.proposal is None


@pytest.mark.anyio
async def test_when_nothing_is_left_to_propose_the_reply_stands_alone():
    empty = {"type": "stage", "next": "ending"}
    model = Scripted(answer({"op": "upsert_node", "id": "opening", "node": empty}, reply="Well."))
    result = await run_turn(model, story(), "Add a step.")
    assert result.proposal is None
    assert result.diagnostics == ()
    assert result.reply == "Well."


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("capabilities", "advice"),
    [(("music",), "add a generate_music action"), ((), "upload one in Assets")],
)
async def test_a_repair_for_missing_music_only_offers_to_make_it_where_it_can(capabilities, advice):
    source = with_files()
    node = {"type": "stage", "background": "dusk", "music": "sad_piano", "next": "ending"}
    fixed = {"type": "stage", "background": "dusk", "next": "ending"}
    model = Scripted(
        answer({"op": "upsert_node", "id": "hi", "node": node}),
        answer({"op": "upsert_node", "id": "hi", "node": fixed}),
    )
    await run_turn(model, source, "Music.", capabilities=capabilities)
    assert advice in model.calls[1][-1]["content"]


def test_a_stage_step_is_written_seen_things_first_then_sound():
    """A grammar writes fields in this order, so a model can never go back for an earlier one."""
    operations = RESPONSE_SCHEMA["properties"]["proposal"]["anyOf"][0]["properties"]["operations"]
    upsert = next(
        item
        for item in operations["items"]["anyOf"]
        if item["properties"]["op"].get("const") == "upsert_node"
    )
    stage = next(
        item
        for item in upsert["properties"]["node"]["anyOf"]
        if item["properties"]["type"].get("const") == "stage"
    )
    assert list(stage["properties"]) == [
        "type",
        "next",
        "background",
        "cg",
        "show",
        "hide",
        "music",
        "ambience",
        "sound",
        "transition",
        "effect",
    ]


@pytest.mark.anyio
async def test_music_can_be_generated_and_a_made_up_id_for_it_is_left_out():
    source = story()
    source["assets"]["dusk"] = {"kind": "image", "path": "assets/dusk.png", "sha256": sha("7")}
    node = {"type": "stage", "background": "dusk", "music": "sad_piano", "next": "ending"}
    action = {"op": "generate_music", "description": "sad piano", "seconds": 45}
    result = await run_turn(
        Scripted(answer({"op": "upsert_node", "id": "hi", "node": node}, action)),
        source,
        "Add sad piano music.",
        capabilities=("music",),
    )
    assert result.diagnostics == ()
    assert result.attempts == 1
    made = result.proposal.operations
    assert made[0].node == {"type": "stage", "background": "dusk", "next": "ending"}
    assert (made[1].description, made[1].seconds) == ("sad piano", 45)


@pytest.mark.anyio
async def test_a_new_step_only_for_a_track_being_made_is_left_out_and_the_story_joins_up():
    edits = (
        {
            "op": "upsert_node",
            "id": "opening",
            "node": {**story()["nodes"]["opening"], "next": "hi"},
        },
        {
            "op": "upsert_node",
            "id": "hi",
            "node": {"type": "stage", "music": "sad_piano", "transition": "fade", "next": "ending"},
        },
        {"op": "generate_music", "description": "sad piano"},
    )
    result = await run_turn(Scripted(answer(*edits)), story(), "Music.", capabilities=("music",))
    assert result.diagnostics == ()
    assert result.attempts == 1
    # The opening went straight back to where it led, so only the track is left to make.
    assert [item.op for item in result.proposal.operations] == ["generate_music"]
    assert result.story["nodes"]["opening"]["next"] == "ending"


@pytest.mark.anyio
async def test_a_saved_scene_rewritten_only_for_a_track_being_made_stays_as_it_was():
    node = {"type": "stage", "music": "sad_piano", "next": "ending"}
    result = await run_turn(
        Scripted(
            answer(
                {"op": "upsert_node", "id": "opening", "node": node},
                {"op": "generate_music", "description": "sad piano"},
            )
        ),
        story(),
        "Music.",
        capabilities=("music",),
    )
    assert result.diagnostics == ()
    assert result.attempts == 1
    assert [item.op for item in result.proposal.operations] == ["generate_music"]


def test_the_grammar_only_offers_music_where_it_can_be_made():
    def offered(schema):
        branch = schema["properties"]["proposal"]["anyOf"][0]
        shapes = branch["properties"]["operations"]["items"]["anyOf"]
        return {shape["properties"]["op"].get("const") for shape in shapes}

    assert "generate_music" in offered(response_schema())
    assert "generate_music" not in offered(response_schema(music=False))
    assert "generate_voice" in offered(response_schema(music=False))


@pytest.mark.anyio
async def test_a_turn_without_music_refuses_it_whatever_the_provider_writes():
    class Recording(Scripted):
        schema = None

        async def respond(self, messages, schema, on_delta=None):
            self.schema = schema
            return await super().respond(messages, schema, on_delta)

    model = Recording(
        answer(
            {"op": "set_title", "title": "New title"},
            {"op": "generate_music", "description": "sad piano"},
        )
    )
    result = await run_turn(model, story(), "Music.", capabilities=())
    assert [item.op for item in result.proposal.operations] == ["set_title"]
    assert "generate_music" not in json.dumps(model.schema)


def with_files():
    source = story()
    for key, kind, path in (
        ("dusk", "image", "assets/dusk.png"),
        ("theme_a", "music", "assets/theme_a.ogg"),
    ):
        source["assets"][key] = {"kind": kind, "path": path, "sha256": sha("7")}
    return source


def title_screen(**fields):
    return proposal({"op": "set_title_screen", **fields}).operations


def test_a_title_screen_leaves_the_rest_of_the_look_alone():
    source = with_files()
    source["theme"] = {"textbox": {"position": "top"}}
    edit = apply_operations(source, title_screen(background="dusk", music="theme_a"))
    assert edit.story["theme"] == {
        "textbox": {"position": "top"},
        "title": {"background": "dusk", "music": "theme_a"},
    }
    assert edit.touched == ("theme.title",)


def test_what_a_title_screen_leaves_out_stays_and_null_removes_it():
    source = with_files()
    source["theme"] = {"title": {"background": "dusk", "music": "theme_a"}}
    edit = apply_operations(source, title_screen(music=None))
    assert edit.story["theme"] == {"title": {"background": "dusk"}}
    gone = apply_operations(source, title_screen(music=None, background=None))
    assert "theme" not in gone.story


def test_a_new_look_does_not_drop_the_title_screen():
    source = with_files()
    source["theme"] = {"title": {"background": "dusk"}, "font": {"size": 30}}
    look = proposal({"op": "set_theme", "theme": {"textbox": {"position": "top"}}}).operations
    assert apply_operations(source, look).story["theme"] == {
        "textbox": {"position": "top"},
        "title": {"background": "dusk"},
    }
    reset = proposal({"op": "set_theme", "theme": None}).operations
    assert apply_operations(source, reset).story["theme"] == {"title": {"background": "dusk"}}


def test_a_title_screen_needs_real_files_of_the_right_kind():
    source = with_files()
    for bad in ({"background": "theme_a"}, {"music": "dusk"}, {"background": "nothing"}):
        assert check_proposal(source, title_screen(**bad)).diagnostics, bad


@pytest.mark.anyio
async def test_a_title_screen_waiting_on_a_new_file_keeps_the_rest_of_the_choice():
    answered = answer(
        {"op": "set_title_screen", "background": "dusk", "music": "sad_piano"},
        {"op": "generate_music", "description": "sad piano"},
    )
    result = await run_turn(Scripted(answered), with_files(), "Do it.", capabilities=("music",))
    assert result.diagnostics == ()
    assert result.attempts == 1
    made = result.proposal.operations[0]
    assert (made.op, made.background, made.model_fields_set) == (
        "set_title_screen",
        "dusk",
        {"op", "background"},
    )


@pytest.mark.anyio
async def test_a_theme_full_of_blanks_means_only_what_it_says():
    theme = {
        "textbox": {"position": "top", "border": None},
        "choices": {"background": None},
        "font": {"asset": None, "size": None},
    }
    result = await run_turn(
        Scripted(answer({"op": "set_theme", "theme": theme})), story(), "Move the box up."
    )
    assert result.diagnostics == ()
    assert result.proposal.operations[0].theme == {
        "textbox": {"position": "top"},
        "font": {"asset": None},
    }


def test_set_player_names_who_the_player_is():
    edit = apply_operations(
        story(),
        proposal({"op": "set_player", "default_name": "Alex", "character": "mira"}).operations,
    )
    assert edit.story["player"] == {"default_name": "Alex", "character": "mira"}
    assert edit.touched == ("player",)


ASKING = {
    "op": "upsert_node",
    "id": "ask",
    "node": {"type": "name", "text": "Name?", "next": "ending"},
}


@pytest.mark.anyio
async def test_asking_for_a_name_brings_the_player_it_needs():
    result = await run_turn(Scripted(answer(ASKING)), story(), "Ask the player's name.")
    assert result.diagnostics == ()
    assert result.attempts == 1
    assert [item.op for item in result.proposal.operations] == ["set_player", "upsert_node"]
    assert result.proposal.operations[0].default_name == "Alex"
    assert result.story["nodes"]["ask"]["text_id"], "text IDs are filled in like any other"


@pytest.mark.anyio
async def test_writing_the_placeholder_brings_the_player_it_needs():
    line = {"type": "line", "text": "Hello, {name}.", "next": "ending"}
    made = answer({"op": "upsert_node", "id": "hi", "node": line})
    result = await run_turn(Scripted(made), story(), "Greet the player.")
    assert result.proposal.operations[0].op == "set_player"
    assert result.story["player"] == {"default_name": "Alex"}


@pytest.mark.anyio
async def test_a_player_the_model_or_the_story_already_set_is_left_alone():
    chosen = answer(ASKING, {"op": "set_player", "default_name": "Sam"})
    result = await run_turn(Scripted(chosen), story(), "Ask the player's name.")
    assert [
        item.default_name for item in result.proposal.operations if item.op == "set_player"
    ] == ["Sam"]
    source = {**story(), "player": {"default_name": "Sam"}}
    again = await run_turn(Scripted(answer(ASKING)), source, "Ask again.")
    assert [item.op for item in again.proposal.operations] == ["upsert_node"]


@pytest.mark.anyio
async def test_an_ordinary_scene_brings_no_player():
    line = {"type": "line", "text": "Hello, {nobody}.", "next": "ending"}
    made = answer({"op": "upsert_node", "id": "hi", "node": line})
    result = await run_turn(Scripted(made), story(), "Say hello.")
    assert [item.op for item in result.proposal.operations] == ["upsert_node"]


@pytest.mark.anyio
async def test_a_name_nobody_asked_for_gets_a_question_before_the_story_starts():
    line = {"type": "line", "text": "Hello, {name}.", "next": "ending"}
    made = answer({"op": "upsert_node", "id": "hi", "node": line}, {"op": "set_entry", "id": "hi"})
    result = await run_turn(Scripted(made), story(), "Greet the player by name.")
    assert result.diagnostics == ()
    edited = result.story
    assert edited["entry"] == "ask_name"
    assert edited["nodes"]["ask_name"]["type"] == "name"
    assert edited["nodes"]["ask_name"]["next"] == "hi", "then on to where the story was to begin"
    assert edited["player"] == {"default_name": "Alex"}


@pytest.mark.anyio
async def test_setting_a_player_alone_also_gets_the_question():
    made = answer({"op": "set_player", "default_name": "Kai", "character": "mira"})
    result = await run_turn(Scripted(made), story(), "Let the player name Mira.")
    assert result.story["entry"] == "ask_name"
    assert result.story["nodes"]["ask_name"]["next"] == story()["entry"]
    assert result.story["player"]["default_name"] == "Kai"


@pytest.mark.anyio
async def test_showing_someone_with_no_pictures_is_left_out():
    show = [{"character": "ren", "sprite": "neutral", "position": "left"}]
    first = {"type": "stage", "show": show, "next": "hi"}
    line = {"type": "line", "text": "Hi.", "next": "ending"}
    made = answer(
        {"op": "upsert_node", "id": "s1", "node": first},
        {"op": "upsert_node", "id": "hi", "node": line},
        {"op": "set_entry", "id": "s1"},
    )
    source = story()
    source["characters"]["ren"] = {"name": "Ren"}
    result = await run_turn(Scripted(made), source, "Show Ren.")
    assert result.diagnostics == ()
    assert result.attempts == 1
    assert "s1" not in result.story["nodes"], "there was nothing else to this step"
    assert result.story["entry"] == "hi", "and the story joins up around it"


@pytest.mark.anyio
async def test_what_leads_into_a_rewritten_scene_with_nothing_left_goes_straight_on():
    empty = {"type": "stage", "next": "hi"}
    line = {"type": "line", "text": "Hi.", "next": "ending"}
    lead = {"type": "line", "text": "First.", "next": "opening"}
    made = answer(
        {"op": "upsert_node", "id": "lead", "node": lead},
        {"op": "upsert_node", "id": "opening", "node": empty},
        {"op": "upsert_node", "id": "hi", "node": line},
        {"op": "set_entry", "id": "lead"},
    )
    result = await run_turn(Scripted(made), story(), "Add these.")
    assert result.diagnostics == ()
    assert result.story["nodes"]["lead"]["next"] == "hi"
    assert result.story["nodes"]["opening"] == story()["nodes"]["opening"]


@pytest.mark.anyio
async def test_a_story_with_no_files_cannot_use_made_up_ones_and_joins_up_around_them():
    source = story()
    source["assets"] = {}
    for character in source["characters"].values():
        character.pop("sprites", None)
    first = {"type": "stage", "background": "pier_night", "ambience": "waves", "next": "second"}
    second = {"type": "stage", "cg": "moon", "sound": "bell", "next": "hi"}
    line = {"type": "line", "text": "Hi.", "next": "ending"}
    made = answer(
        {"op": "upsert_node", "id": "first", "node": first},
        {"op": "upsert_node", "id": "second", "node": second},
        {"op": "upsert_node", "id": "hi", "node": line},
        {"op": "set_entry", "id": "first"},
    )
    result = await run_turn(Scripted(made), source, "Write it.")
    assert result.diagnostics == ()
    assert result.attempts == 1
    assert result.story["entry"] == "hi"
    assert "first" not in result.story["nodes"]
    assert "second" not in result.story["nodes"]


@pytest.mark.anyio
async def test_a_made_up_file_is_sent_back_when_a_real_one_could_replace_it():
    source = with_files()
    node = {"type": "stage", "background": "dusk_two", "next": "ending"}
    fixed = {"type": "stage", "background": "dusk", "next": "ending"}
    model = Scripted(
        answer({"op": "upsert_node", "id": "hi", "node": node}),
        answer({"op": "upsert_node", "id": "hi", "node": fixed}),
    )
    result = await run_turn(model, source, "Show the dusk.")
    assert result.attempts == 2
    assert "dusk" in model.calls[1][-1]["content"]


@pytest.mark.anyio
async def test_an_enums_first_value_joins_its_list():
    declaration = {"type": "enum", "initial": "unknown", "values": ["work", "love"]}
    made = answer({"op": "upsert_variable", "id": "secret", "declaration": declaration})
    result = await run_turn(Scripted(made), story(), "Track her secret.")
    assert result.diagnostics == ()
    assert result.story["variables"]["secret"]["values"] == ["unknown", "work", "love"]


def blank_project():
    return {
        **story(),
        "characters": {},
        "assets": {},
        "entry": "opening",
        "nodes": {
            "opening": {
                "type": "line",
                "text_id": "o",
                "text": "A new story begins.",
                "next": "ending",
            },
            "ending": {"type": "end", "text_id": "e", "text": "To be continued.", "ending": "done"},
        },
    }


FIRST = {"type": "line", "text": "One.", "next": "second"}
SECOND = {"type": "end", "text": "Two.", "ending": "fin"}


@pytest.mark.anyio
async def test_a_first_story_written_beside_the_starter_is_where_the_game_begins():
    made = answer(
        {"op": "upsert_node", "id": "first", "node": FIRST},
        {"op": "upsert_node", "id": "second", "node": SECOND},
    )
    result = await run_turn(Scripted(made), blank_project(), "Write a story.")
    assert result.diagnostics == ()
    assert result.story["entry"] == "first"
    assert set(result.story["nodes"]) == {"first", "second"}, "no stray starter scenes"


@pytest.mark.anyio
async def test_the_starters_ending_stays_if_the_story_uses_it():
    first = {"type": "line", "text": "One.", "next": "ending"}
    made = answer({"op": "upsert_node", "id": "first", "node": first})
    result = await run_turn(Scripted(made), blank_project(), "Write a story.")
    assert result.story["entry"] == "first"
    assert set(result.story["nodes"]) == {"first", "ending"}


@pytest.mark.anyio
async def test_a_story_that_already_links_itself_in_is_left_alone():
    rewritten = {"type": "line", "text": "Now.", "next": "first"}
    made = answer(
        {"op": "upsert_node", "id": "opening", "node": rewritten},
        {"op": "upsert_node", "id": "first", "node": {**FIRST, "next": "ending"}},
    )
    result = await run_turn(Scripted(made), blank_project(), "Write a story.")
    assert result.story["entry"] == "opening"
    assert "ending" in result.story["nodes"]


@pytest.mark.anyio
async def test_an_unlinked_scene_in_a_real_story_is_not_moved_to_the_start():
    made = answer({"op": "upsert_node", "id": "aside", "node": {**FIRST, "next": "ending"}})
    result = await run_turn(Scripted(made), story(), "Add a scene.")
    assert result.story["entry"] == story()["entry"]


@pytest.mark.anyio
async def test_a_first_story_that_uses_the_name_asks_it_before_the_story_not_the_starter():
    named = {"type": "line", "text": "Hello, {name}.", "next": "second"}
    made = answer(
        {"op": "upsert_node", "id": "first", "node": named},
        {"op": "upsert_node", "id": "second", "node": SECOND},
    )
    result = await run_turn(Scripted(made), blank_project(), "Write a story.")
    assert result.diagnostics == ()
    assert result.warnings == ()
    entry = result.story["entry"]
    assert result.story["nodes"][entry]["type"] == "name"
    assert result.story["nodes"][entry]["next"] == "first"
    assert set(result.story["nodes"]) == {entry, "first", "second"}


@pytest.mark.anyio
async def test_a_first_story_that_rewrites_the_opening_lets_go_of_the_starters_ending():
    # The Third Ferry: every scene was reachable but the starter's unused ending stayed behind.
    rewritten = {"type": "line", "text": "Now.", "next": "first"}
    made = answer(
        {"op": "upsert_node", "id": "opening", "node": rewritten},
        {"op": "upsert_node", "id": "first", "node": FIRST},
        {"op": "upsert_node", "id": "second", "node": SECOND},
    )
    result = await run_turn(Scripted(made), blank_project(), "Write a story.")
    assert result.diagnostics == ()
    assert result.warnings == ()
    assert result.story["entry"] == "opening"
    assert set(result.story["nodes"]) == {"opening", "first", "second"}


@pytest.mark.anyio
async def test_a_first_story_starting_elsewhere_lets_go_of_a_rewritten_opening_too():
    rewritten = {"type": "line", "text": "Now.", "next": "ending"}
    made = answer(
        {"op": "upsert_node", "id": "opening", "node": rewritten},
        {"op": "upsert_node", "id": "first", "node": FIRST},
        {"op": "upsert_node", "id": "second", "node": SECOND},
        {"op": "set_entry", "id": "first"},
    )
    result = await run_turn(Scripted(made), blank_project(), "Write a story.")
    assert result.diagnostics == ()
    assert result.warnings == ()
    assert set(result.story["nodes"]) == {"first", "second"}


@pytest.mark.anyio
async def test_a_broken_first_story_reports_its_broken_link_and_nothing_invented():
    rewritten = {"type": "line", "text": "Now.", "next": "nowhere"}
    made = answer({"op": "upsert_node", "id": "opening", "node": rewritten})
    model = Scripted(made, made, made)
    result = await run_turn(model, blank_project(), "Write a story.")
    assert result.diagnostics == (Diagnostic("unknown_reference", "nodes.opening.next"),)


@pytest.mark.anyio
async def test_a_first_story_with_no_ending_of_its_own_keeps_the_starters():
    looping = {"type": "line", "text": "Now.", "next": "first"}
    back = {"type": "line", "text": "Again.", "next": "opening"}
    made = answer(
        {"op": "upsert_node", "id": "opening", "node": looping},
        {"op": "upsert_node", "id": "first", "node": back},
    )
    result = await run_turn(Scripted(made), blank_project(), "Write a story.")
    assert "ending" in (result.story or {}).get("nodes", {"ending": None})


@pytest.mark.anyio
async def test_a_short_story_the_creator_wrote_is_not_a_blank_starter():
    source = blank_project()
    source["nodes"]["opening"]["text"] = "My own first line."
    made = answer({"op": "upsert_node", "id": "aside", "node": {**FIRST, "next": "ending"}})
    result = await run_turn(Scripted(made), source, "Add a scene.")
    assert result.story["entry"] == "opening"
    assert result.story["nodes"]["opening"]["text"] == "My own first line."


SPRITES_FOR_MIRA = {
    "op": "generate_character_images",
    "character": "mira",
    "appearance": "a raincoat and short grey hair",
    "character_type": "woman",
}


@pytest.mark.anyio
async def test_writing_a_character_out_unchanged_is_not_a_change():
    source = story()
    source["characters"]["mira"]["color"] = "#ffb6c1"
    made = answer(
        {"op": "upsert_character", "id": "mira", "name": "Mira", "color": "#ffb6c1"},
        SPRITES_FOR_MIRA,
    )
    result = await run_turn(Scripted(made), source, "Make sprites of Mira.")
    assert result.diagnostics == ()
    assert [item.op for item in result.proposal.operations] == ["generate_character_images"]
    assert result.story == source


@pytest.mark.anyio
async def test_a_character_who_really_changes_stays_in_the_proposal():
    made = answer(
        {"op": "upsert_character", "id": "mira", "name": "Mira Vale"},
        SPRITES_FOR_MIRA,
    )
    result = await run_turn(Scripted(made), story(), "Rename her.")
    assert [item.op for item in result.proposal.operations] == [
        "upsert_character",
        "generate_character_images",
    ]


@pytest.mark.anyio
async def test_a_scene_rewritten_word_for_word_is_not_a_change():
    source = story()
    same = {"type": "line", "speaker": "mira", "text": "Fog again.", "next": "ending"}
    changed = {"type": "line", "text": "The bell rang twice.", "next": "ending"}
    made = answer(
        {"op": "upsert_node", "id": "opening", "node": same},
        {"op": "upsert_node", "id": "narration", "node": changed},
    )
    result = await run_turn(Scripted(made), source, "Change the bell line.")
    assert [item.id for item in result.proposal.operations] == ["narration"]
    assert result.story["nodes"]["opening"] == source["nodes"]["opening"]


@pytest.mark.anyio
async def test_when_nothing_really_changes_the_reply_stands_alone():
    same = {"type": "line", "speaker": "mira", "text": "Fog again.", "next": "ending"}
    made = answer({"op": "upsert_node", "id": "opening", "node": same}, reply="It already says so.")
    result = await run_turn(Scripted(made), story(), "Does she mention the fog?")
    assert result.proposal is None
    assert result.reply == "It already says so."


ON_STAGE = {"character": "mira", "position": "center", "sprite": "neutral"}


def staged():
    source = story()
    source["entry"] = "meeting"
    source["nodes"]["meeting"] = {
        "type": "stage",
        "background": "mira_neutral",
        "show": [ON_STAGE],
        "next": "opening",
    }
    return source


REWRITTEN = {"type": "stage", "background": "mira_neutral", "effect": "shake", "next": "opening"}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "request_text",
    ["Make Mira closer.", "More closer, up to the waist.", "Add a shake here."],
)
async def test_rewriting_a_stage_step_does_not_take_people_off_it(request_text):
    # A real thread: asked to bring Kaito closer, the model rewrote the step without him.
    made = answer(
        {"op": "upsert_node", "id": "meeting", "node": REWRITTEN},
        {"op": "upsert_character", "id": "mira", "name": "Mira", "stage": {"scale": 200}},
    )
    result = await run_turn(Scripted(made), staged(), request_text)
    assert result.diagnostics == ()
    meeting = result.story["nodes"]["meeting"]
    assert meeting["show"] == [ON_STAGE]
    assert meeting["effect"] == "shake"
    assert result.story["characters"]["mira"]["stage"] == {"scale": 200}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "request_text",
    [
        "Take Mira off the stage here.",
        "Remove Mira from this scene.",
        "Mira leaves before this.",
        "Hide her here.",
        "Show the street without anyone in it.",
    ],
)
async def test_asked_to_take_someone_off_they_do_go(request_text):
    made = answer({"op": "upsert_node", "id": "meeting", "node": REWRITTEN})
    result = await run_turn(Scripted(made), staged(), request_text)
    assert "show" not in result.story["nodes"]["meeting"]


@pytest.mark.anyio
async def test_a_step_that_hides_someone_is_not_given_them_back():
    node = {**REWRITTEN, "hide": ["mira"]}
    made = answer({"op": "upsert_node", "id": "meeting", "node": node})
    result = await run_turn(Scripted(made), staged(), "Add a shake.")
    assert "show" not in result.story["nodes"]["meeting"]
    assert result.story["nodes"]["meeting"]["hide"] == ["mira"]


@pytest.mark.anyio
async def test_someone_new_on_stage_joins_those_already_there():
    source = staged()
    source["characters"]["ren"] = {"name": "Ren", "sprites": {"neutral": "mira_neutral"}}
    ren = {"character": "ren", "position": "left", "sprite": "neutral"}
    made = answer({"op": "upsert_node", "id": "meeting", "node": {**REWRITTEN, "show": [ren]}})
    result = await run_turn(Scripted(made), source, "Bring Ren in on the left.")
    assert result.story["nodes"]["meeting"]["show"] == [ON_STAGE, ren]


@pytest.mark.anyio
async def test_someone_new_in_the_same_spot_replaces_who_was_there():
    source = staged()
    source["characters"]["ren"] = {"name": "Ren", "sprites": {"neutral": "mira_neutral"}}
    ren = {"character": "ren", "position": "center", "sprite": "neutral"}
    made = answer({"op": "upsert_node", "id": "meeting", "node": {**REWRITTEN, "show": [ren]}})
    result = await run_turn(Scripted(made), source, "Put Ren there instead.")
    assert result.story["nodes"]["meeting"]["show"] == [ren]


@pytest.mark.anyio
async def test_an_exact_copy_of_a_rewritten_step_that_nothing_reaches_is_left_out():
    # The same thread also added a copy of the step that nothing ever led to.
    made = answer(
        {"op": "upsert_node", "id": "meeting", "node": REWRITTEN},
        {"op": "upsert_node", "id": "meeting_update", "node": REWRITTEN},
    )
    result = await run_turn(Scripted(made), staged(), "Make Mira closer.")
    assert result.diagnostics == ()
    assert "meeting_update" not in result.story["nodes"]
    assert result.story["nodes"]["meeting"]["show"] == [ON_STAGE]


@pytest.mark.anyio
async def test_a_new_stage_step_someone_forgot_to_link_stays_and_is_warned_about():
    step = {"type": "stage", "background": "mira_neutral", "effect": "flash", "next": "ending"}
    made = answer({"op": "upsert_node", "id": "dusk", "node": step})
    result = await run_turn(Scripted(made), story(), "Add a flash here.")
    assert "dusk" in result.story["nodes"]
    assert any(item.location == "nodes.dusk" for item in result.warnings)


@pytest.mark.anyio
async def test_a_new_scene_with_words_nothing_leads_to_is_kept_for_the_creator_to_link():
    made = answer({"op": "upsert_node", "id": "aside", "node": {**FIRST, "next": "ending"}})
    result = await run_turn(Scripted(made), story(), "Write a scene I can link later.")
    assert "aside" in result.story["nodes"]


def test_the_model_sees_a_player_and_a_question_in_the_story():
    source = {
        **story(),
        "player": {"default_name": "Sam", "character": "mira"},
        "nodes": {
            **story()["nodes"],
            "ask": {"type": "name", "text_id": "ask", "text": "Name?", "next": "ending"},
        },
    }
    messages, _ = build_turn_messages(source, "Hi")
    content = messages[-1]["content"]
    assert 'player: {"character":"mira","default_name":"Sam"}' in content or (
        '"default_name":"Sam"' in content
    )
    assert "ask | asks the player's name | " in content


@pytest.mark.parametrize("seconds", [14, 181])
def test_a_track_length_outside_the_limits_is_refused(seconds):
    with pytest.raises(ValidationError):
        Proposal.model_validate(
            {
                "summary": "Music",
                "operations": [{"op": "generate_music", "description": "x", "seconds": seconds}],
            }
        )


def test_a_track_defaults_to_a_minute():
    proposal = Proposal.model_validate(
        {"summary": "Music", "operations": [{"op": "generate_music", "description": "x"}]}
    )
    assert proposal.operations[0].seconds == 60


def test_context_says_music_can_be_generated_only_when_it_can():
    messages, _ = build_turn_messages(story(), "Hi", capabilities=("music",))
    assert "generation available: music" in messages[-1]["content"]
    assert "music cannot be generated" not in messages[-1]["content"]
    messages, _ = build_turn_messages(story(), "Hi", capabilities=("pictures",))
    assert "music cannot be generated" in messages[-1]["content"]
    messages, _ = build_turn_messages(story(), "Hi", capabilities=())
    assert "generation available" not in messages[-1]["content"]


@pytest.mark.anyio
async def test_a_broken_action_is_left_out_once_repairs_are_spent_and_the_edits_survive():
    edit = {
        "op": "upsert_node",
        "id": "hi",
        "node": {"type": "line", "text": "Hi.", "next": "ending"},
    }
    action = {"op": "generate_voice", "character": "mira", "lines": ["nowhere"]}
    result = await run_turn(
        Scripted(answer(edit, action), answer(edit, action), answer(edit, action)),
        story(),
        "Add a line and voice it.",
    )
    assert result.diagnostics == () and result.story is not None
    assert [operation.op for operation in result.proposal.operations] == ["upsert_node"]
    assert Diagnostic("image_action_dropped", "proposal.operations.1") in result.warnings


def voiced(key="hi", speaker="mira", **voice):
    return {
        "op": "upsert_node",
        "id": key,
        "node": {
            "type": "line",
            "speaker": speaker,
            "text": "Hi.",
            "next": "ending",
            "voice": {"mode": "full", **voice},
        },
    }


@pytest.mark.anyio
async def test_a_line_marked_for_voice_gets_its_action_when_the_model_forgets():
    """Without one the line would stay silent, which is not what anyone asked for."""
    result = await run_turn(
        Scripted(answer(voiced("hi"), voiced("again"))),
        story(),
        "Add two lines and voice them.",
        capabilities=("voices",),
    )
    actions = [item for item in result.proposal.operations if isinstance(item, GenerateVoice)]
    assert [(item.character, item.lines) for item in actions] == [("mira", ["hi", "again"])]
    assert result.diagnostics == ()


@pytest.mark.anyio
async def test_a_voice_action_the_model_wrote_is_not_repeated():
    action = {"op": "generate_voice", "character": "mira", "lines": ["hi"], "voice": "af_bella"}
    result = await run_turn(
        Scripted(answer(voiced("hi"), action)),
        story(),
        "Add a line and voice it.",
        capabilities=("voices",),
    )
    actions = [item for item in result.proposal.operations if isinstance(item, GenerateVoice)]
    assert [(item.lines, item.voice) for item in actions] == [(["hi"], "af_bella")]


@pytest.mark.anyio
async def test_only_lines_the_voice_action_missed_get_a_new_one():
    action = {"op": "generate_voice", "character": "mira", "lines": ["hi"]}
    result = await run_turn(
        Scripted(answer(voiced("hi"), voiced("again"), action)),
        story(),
        "Add two lines and voice them.",
        capabilities=("voices",),
    )
    actions = [item for item in result.proposal.operations if isinstance(item, GenerateVoice)]
    assert [item.lines for item in actions] == [["hi"], ["again"]]


@pytest.mark.anyio
async def test_no_voice_action_appears_where_voices_are_unavailable():
    result = await run_turn(Scripted(answer(voiced())), story(), "Add a line.", capabilities=())
    assert [item.op for item in result.proposal.operations] == ["upsert_node"]


@pytest.mark.anyio
async def test_a_line_that_already_has_its_clip_needs_no_action():
    source = story()
    source["assets"]["clip"] = {"kind": "audio", "path": "assets/clip.wav", "sha256": sha("2")}
    result = await run_turn(
        Scripted(answer(voiced(audio="clip"))), source, "Add a line.", capabilities=("voices",)
    )
    assert [item.op for item in result.proposal.operations] == ["upsert_node"]


@pytest.mark.anyio
async def test_unvoiced_lines_never_cost_the_creator_credits():
    plain = {
        "op": "upsert_node",
        "id": "hi",
        "node": {"type": "line", "speaker": "mira", "text": "Hi.", "next": "ending"},
    }
    result = await run_turn(Scripted(answer(plain)), story(), "Add.", capabilities=("voices",))
    assert [item.op for item in result.proposal.operations] == ["upsert_node"]


def test_context_tells_the_model_what_can_be_generated_and_each_characters_voice():
    row = LibraryRow("Mira", "sprite", "image/png", sha("c"), "mira")
    entries = library_entries(story(), [row])
    messages, _ = build_turn_messages(
        story(),
        "Hi",
        library=entries,
        voices={"mira": "af_bella"},
        capabilities=("pictures", "voices"),
    )
    context = messages[-1]["content"]
    assert "generation available: pictures, voices" in context
    assert "voice af_bella" in context
    assert "af_heart" in context and "am_michael" in context


def test_context_says_nothing_about_voices_when_they_are_unavailable():
    messages, _ = build_turn_messages(story(), "Hi", capabilities=("pictures",))
    context = messages[-1]["content"]
    assert "generation available: pictures" in context and "af_heart" not in context


def _png(pixels: list[list[tuple[int, int, int, int]]], color: int = 6) -> bytes:
    """A minimal PNG: Sub filter on odd rows so the decoder really has to unfilter."""
    height, width = len(pixels), len(pixels[0])
    raw = bytearray()
    for y, row in enumerate(pixels):
        flat = bytes(value for pixel in row for value in (pixel if color == 6 else pixel[:3]))
        if y % 2:
            step = 4 if color == 6 else 3
            filtered = bytearray(flat)
            for x in range(len(flat) - 1, step - 1, -1):
                filtered[x] = (flat[x] - flat[x - step]) & 255
            raw += b"\x01" + bytes(filtered)
        else:
            raw += b"\x00" + flat

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw)))
        + chunk(b"IEND", b"")
    )


def test_face_box_sits_on_the_head_of_a_cut_out_figure():
    # A 40 wide, 100 tall figure standing in a 200x200 image, 20 rows down.
    clear, solid = (0, 0, 0, 0), (9, 9, 9, 255)
    image = [
        [solid if 80 <= x < 120 and 20 <= y < 120 else clear for x in range(200)]
        for y in range(200)
    ]
    left, top, right, bottom = face_box_from_png(_png(image), (200, 200))
    # Mirrors faceBoxFromAlpha: 11% of the figure, centred on its top band.
    assert (right - left, bottom - top) == (16, 16)
    assert (left + right) / 2 == pytest.approx(100, abs=1)
    assert (top + bottom) / 2 == pytest.approx(20 + 100 * 0.075, abs=1)


def test_face_box_scales_from_a_thumbnail_to_the_full_image():
    clear, solid = (0, 0, 0, 0), (9, 9, 9, 255)
    thumbnail = [
        [solid if 80 <= x < 120 and 20 <= y < 120 else clear for x in range(200)]
        for y in range(200)
    ]
    left, top, right, bottom = face_box_from_png(_png(thumbnail), (1000, 1000))
    assert (right - left, bottom - top) == (55, 55)
    assert (left + right) / 2 == pytest.approx(500, abs=5)


def test_an_opaque_image_gets_a_portrait_style_guess():
    image = [[(9, 9, 9, 255)] * 100 for _ in range(100)]
    for png in (_png(image), _png(image, color=2)):
        assert face_box_from_png(png, (100, 100)) == (35, 5, 65, 35)


def test_face_box_refuses_what_it_cannot_read():
    with pytest.raises(ValueError):
        face_box_from_png(b"not a png", (100, 100))
