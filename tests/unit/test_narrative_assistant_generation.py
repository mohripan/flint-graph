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
