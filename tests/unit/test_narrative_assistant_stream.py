"""Streamed turns: reply-text scanning over partial JSON and observable turn steps."""

import json

import pytest

from flint_graph.infrastructure.narrative_assistant import DeterministicNarrativeAssistant
from flint_graph.narrative.assistant.stream import ReplyScanner
from flint_graph.narrative.assistant.turn import run_turn

REPLY = 'Line one\nquote " slash \\ tab\t snow ☃ emoji 😀 é'
DOCUMENT = {
    "proposal": {
        "summary": "Add a scene",
        "operations": [
            {
                "op": "upsert_node",
                "id": "hall",
                "node": {
                    "type": "choice",
                    "text": 'Say "reply"?',
                    "options": [{"id": "yes", "text": "Yes", "target": "end"}],
                    "reply": "nested, not the reply",
                },
            },
            {"op": "set_title", "title": "T"},
            {"op": "set_entry", "id": "hall"},
        ],
    },
    "reply": REPLY,
}


def scan(text: str, size: int) -> tuple[ReplyScanner, str]:
    scanner = ReplyScanner()
    return scanner, "".join(scanner.feed(text[i : i + size]) for i in range(0, len(text), size))


@pytest.mark.parametrize("ascii_only", [True, False])
@pytest.mark.parametrize("size", [1, 2, 3, 5, 11, 4096])
def test_scanner_streams_only_the_top_level_reply_across_any_chunking(size, ascii_only):
    scanner, text = scan(json.dumps(DOCUMENT, ensure_ascii=ascii_only), size)
    assert text == REPLY
    # Only objects directly inside proposal.operations count, not nested options.
    assert scanner.operations == 3 and scanner.proposal_started


def test_scanner_emits_the_reply_progressively_before_the_document_ends():
    scanner = ReplyScanner()
    assert scanner.feed('```json\n{"reply": "The bell') == "The bell"
    assert scanner.feed(" rings") == " rings"
    assert not scanner.proposal_started
    assert scanner.feed('", "proposal": {"summary": "s", "operations": [{"op"') == ""
    assert scanner.proposal_started and scanner.operations == 1


def test_scanner_ignores_non_string_replies_and_replaces_lone_surrogates():
    assert scan('{"reply": null, "proposal": null}', 3)[1] == ""
    assert scan('{"reply": "a\\ud83d b \\ude00"}', 1)[1] == "a� b �"
    scanner, text = scan('{"proposal": null, "reply": "after"} trailing {"reply": "x"}', 2)
    assert text == "after" and not scanner.proposal_started


def story() -> dict:
    return {
        "schema_version": "1",
        "id": "dawn",
        "title": "A door at dawn",
        "language": "en",
        "entry": "opening",
        "characters": {},
        "variables": {},
        "assets": {},
        "nodes": {
            "opening": {"type": "line", "text_id": "t1", "text": "Dawn.", "next": "finish"},
            "finish": {"type": "end", "text_id": "t2", "text": "Done.", "ending": "done"},
        },
    }


def response(next_scene: str, reply: str) -> str:
    return json.dumps(
        {
            "reply": reply,
            "proposal": {
                "summary": "Add a storm",
                "operations": [
                    {
                        "op": "upsert_node",
                        "id": "storm",
                        "node": {"type": "line", "text": "Thunder.", "next": next_scene},
                    },
                    {
                        "op": "upsert_node",
                        "id": "opening",
                        "node": {"type": "line", "text": "Dawn.", "next": "storm"},
                    },
                ],
            },
        }
    )


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    async def step(self, name, state, detail):
        self.events.append(("step", name, state, dict(detail)))

    async def thinking(self, call, text):
        self.events.append(("thinking", call, text))

    async def text(self, call, text):
        self.events.append(("text", call, text))

    def steps(self) -> list[tuple]:
        return [event[1:3] for event in self.events if event[0] == "step"]

    def joined(self, kind: str, call: int) -> str:
        return "".join(e[2] for e in self.events if e[0] == kind and e[1] == call)


@pytest.mark.anyio
async def test_turn_reports_context_thinking_reply_drafting_validation_and_repair():
    model = DeterministicNarrativeAssistant(
        [
            ("Check the targets.", response("nowhere", "First try.")),
            ("Fix the target.", response("finish", "A storm before the end.")),
        ],
        chunk_chars=7,
    )
    recorder = Recorder()
    result = await run_turn(model, story(), "Add a storm.", focus="opening", observer=recorder)
    assert result.diagnostics == () and result.attempts == 2
    assert recorder.steps() == [
        ("context", "done"),
        ("model", "started"),
        ("drafting", "started"),
        ("drafting", "progress"),
        ("drafting", "progress"),
        ("model", "done"),
        ("validating", "done"),
        ("repair", "started"),
        ("model", "started"),
        ("drafting", "started"),
        ("drafting", "progress"),
        ("drafting", "progress"),
        ("model", "done"),
        ("validating", "done"),
    ]
    details = [event[3] for event in recorder.events if event[0] == "step"]
    context = {"scenes": 2, "outlined": 2, "omitted": 0, "focus": "opening", "history": 0}
    assert details[0] == context
    assert details[1] == {"call": 1, "of": 3, "provider": "deterministic"}
    assert details[4] == {"call": 1, "operations": 2}
    assert details[6] == {"call": 1, "valid": False, "problems": 1, "codes": ["unknown_reference"]}
    assert details[7] == {"call": 2, "of": 3, "problems": 1}
    assert details[13] == {"call": 2, "valid": True, "problems": 0, "codes": []}
    assert recorder.joined("thinking", 1) == "Check the targets."
    assert recorder.joined("text", 1) == "First try."
    assert recorder.joined("text", 2) == "A storm before the end." == result.reply
    # Raw proposal JSON never reaches the reply stream.
    assert all("upsert_node" not in e[2] for e in recorder.events if e[0] == "text")


@pytest.mark.anyio
async def test_answers_and_unreadable_output_report_without_a_drafting_step():
    answer = json.dumps({"reply": "One ending.", "proposal": None})
    recorder = Recorder()
    await run_turn(
        DeterministicNarrativeAssistant([answer]), story(), "How many endings?", observer=recorder
    )
    assert recorder.steps() == [("context", "done"), ("model", "started"), ("model", "done")]
    assert recorder.joined("text", 1) == "One ending."

    recorder = Recorder()
    await run_turn(
        DeterministicNarrativeAssistant(["not json", "still not", "nope"]),
        story(),
        "Add a storm.",
        observer=recorder,
    )
    validations = [e[3] for e in recorder.events if e[:3] == ("step", "validating", "done")]
    assert validations == [
        {"call": call, "valid": False, "problems": 1, "codes": ["invalid_response"]}
        for call in (1, 2, 3)
    ]
    assert ("repair", "started") in recorder.steps()


class Unstreamed:
    """A provider without deltas still shows its parsed reply once per call."""

    provider = "batch"

    async def respond(self, messages, schema, on_delta=None):
        from flint_graph.narrative.assistant.turn import ModelReply

        return ModelReply(json.dumps({"reply": "Whole reply.", "proposal": None}), "batch-1", 1, 1)


@pytest.mark.anyio
async def test_providers_without_deltas_still_publish_the_parsed_reply():
    recorder = Recorder()
    await run_turn(Unstreamed(), story(), "Hello", observer=recorder)
    assert recorder.joined("text", 1) == "Whole reply."
