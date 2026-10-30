"""One assistant turn: provider call, strict parsing and bounded diagnostic repair."""

import copy
import json

import pytest

from flint_graph.narrative.assistant.prompts import RESPONSE_SCHEMA, prompt_sha256
from flint_graph.narrative.assistant.turn import (
    AssistantModelError,
    ModelReply,
    run_turn,
)


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
            "opening": {
                "type": "line",
                "text_id": "opening_text",
                "text": "Dawn.",
                "next": "finish",
            },
            "finish": {"type": "end", "text_id": "end_text", "text": "Done.", "ending": "done"},
        },
    }


def response(next_scene: str = "finish", reply: str = "Here is a storm scene.") -> str:
    return json.dumps(
        {
            "reply": reply,
            "proposal": {
                "summary": "Add a storm",
                "operations": [
                    {
                        "op": "upsert_node",
                        "id": "storm",
                        "node": {"type": "line", "text": "Thunder rolls.", "next": next_scene},
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


VALID, BROKEN = response(), response("nowhere")
ANSWER = json.dumps({"reply": "The story has one ending.", "proposal": None})


class Script:
    provider = "scripted"

    def __init__(self, *contents):
        self.contents = list(contents)
        self.calls = []

    async def respond(self, messages, schema, on_delta=None):
        self.calls.append((copy.deepcopy(messages), schema))
        content = self.contents.pop(0)
        if isinstance(content, Exception):
            raise content
        return ModelReply(content=content, model="scripted-1", input_tokens=10, output_tokens=5)


@pytest.mark.anyio
async def test_questions_get_an_answer_without_a_proposal():
    model = Script(ANSWER)
    result = await run_turn(model, story(), "How many endings are there?", focus="opening")
    assert result.reply == "The story has one ending."
    assert result.proposal is None and result.story is None and result.diagnostics == ()
    assert result.attempts == 1 and result.model == "scripted-1"
    assert (result.input_tokens, result.output_tokens) == (10, 5)
    assert result.prompt_sha256 == prompt_sha256()
    messages, schema = model.calls[0]
    assert schema is RESPONSE_SCHEMA
    assert messages[0]["role"] == "system"
    assert "<story>" in messages[-1]["content"]
    assert messages[-1]["content"].endswith("How many endings are there?")


@pytest.mark.anyio
async def test_valid_proposal_is_checked_against_the_base_story():
    result = await run_turn(Script(VALID), story(), "Add a storm.")
    assert result.diagnostics == () and result.attempts == 1
    assert result.proposal is not None and result.proposal.summary == "Add a storm"
    assert result.story["nodes"]["opening"]["next"] == "storm"
    assert result.story["nodes"]["storm"]["text_id"] == "storm_text"
    assert result.touched == ("nodes.opening", "nodes.storm")


@pytest.mark.anyio
async def test_diagnostics_are_sent_back_once_and_a_repaired_proposal_is_accepted():
    model = Script(BROKEN, VALID)
    result = await run_turn(model, story(), "Add a storm.")
    assert result.diagnostics == () and result.attempts == 2
    assert result.story["nodes"]["storm"]["next"] == "finish"
    repair = model.calls[1][0]
    assert repair[-2] == {"role": "assistant", "content": BROKEN}
    assert repair[-1]["role"] == "user"
    assert "unknown_reference at nodes.storm.next" in repair[-1]["content"]
    assert (result.input_tokens, result.output_tokens) == (20, 10)


@pytest.mark.anyio
async def test_repairs_are_bounded_and_the_last_invalid_proposal_is_kept_for_review():
    model = Script(BROKEN, BROKEN, BROKEN, VALID)
    result = await run_turn(model, story(), "Add a storm.", repairs=2)
    assert result.attempts == 3 and len(model.contents) == 1
    assert result.story is None and result.proposal is not None
    assert [(d.code, d.location) for d in result.diagnostics] == [
        ("unknown_reference", "nodes.storm.next")
    ]


@pytest.mark.anyio
async def test_malformed_responses_become_diagnostics_not_exceptions():
    unknown_op = json.dumps(
        {"reply": "ok", "proposal": {"summary": "x", "operations": [{"op": "rewrite_all"}]}}
    )
    model = Script("not json", json.dumps({"reply": 3, "proposal": None}), unknown_op)
    result = await run_turn(model, story(), "Change everything.")
    assert result.attempts == 3 and result.story is None
    assert "invalid_response at response" in model.calls[1][0][-1]["content"]
    assert "invalid_response at response" in model.calls[2][0][-1]["content"]
    assert result.diagnostics[0].code == "invalid_proposal"
    assert result.diagnostics[0].location.startswith("proposal.operations.0")
    assert result.reply == "ok"


@pytest.mark.anyio
async def test_fenced_json_is_accepted_and_oversized_output_is_rejected_unparsed():
    result = await run_turn(Script("```json\n" + VALID + "\n```"), story(), "Add a storm.")
    assert result.diagnostics == ()
    huge = await run_turn(Script("x" * 300_000), story(), "Add.", repairs=0)
    assert [(d.code, d.location) for d in huge.diagnostics] == [("invalid_response", "response")]
    assert huge.reply == ""


@pytest.mark.anyio
async def test_reply_is_bounded_and_provider_errors_propagate_for_job_retry_policy():
    result = await run_turn(Script(response(reply="y" * 5000)), story(), "Add.")
    assert len(result.reply) == 4000
    with pytest.raises(AssistantModelError) as raised:
        await run_turn(Script(AssistantModelError("provider_unavailable")), story(), "Add.")
    assert raised.value.code == "provider_unavailable"
