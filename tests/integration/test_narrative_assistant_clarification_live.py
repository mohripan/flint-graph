"""Explicit local-model qualification; synthetic stories, no project/worker mutation."""

import os

import pytest

from flint_graph.infrastructure.narrative_assistant import OllamaNarrativeAssistant
from flint_graph.narrative.assistant.context import HistoryTurn
from flint_graph.narrative.assistant.turn import run_turn

MODEL = os.getenv("FLINT_GRAPH_ASSISTANT_CLARIFICATION_MODEL")
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not MODEL, reason="requires explicit local Ollama model"),
]
STORY = {
    "schema_version": "2",
    "id": "clarification",
    "title": "Clarification",
    "language": "en",
    "entry": "ending",
    "characters": {},
    "variables": {},
    "assets": {},
    "nodes": {"ending": {"type": "end", "text_id": "ending", "text": "Fin.", "ending": "done"}},
}
REQUEST = (
    "Create me a character, a boy, with shoulder-length white hair, red eyes, and androgynous."
)


async def test_character_clarification_then_answer_and_background_without_unnecessary_questions():
    model = OllamaNarrativeAssistant(
        model=MODEL,
        context_tokens=16384,
        max_output_tokens=4096,
        temperature=0,
        timeout_seconds=180,
        base_url="http://127.0.0.1:11434",
        thinking=False,
    )
    result = await run_turn(model, STORY, REQUEST)
    assert not result.diagnostics
    assert result.proposal is None, result.reply
    assert "?" in result.reply
    print("CLARIFICATION:", result.reply)
    completed = await run_turn(
        model,
        STORY,
        "Name him Ren. He wears a blue coat and dark trousers. "
        "Generate a transparent full-body stage sprite.",
        history=[HistoryTurn("user", REQUEST), HistoryTurn("assistant", result.reply)],
    )
    assert not completed.diagnostics, completed.diagnostics
    assert completed.proposal is not None, completed.reply
    actions = [op for op in completed.proposal.operations if op.op == "generate_character_images"]
    assert len(actions) == 1
    assert actions[0].transparent and actions[0].hires and actions[0].framing == "full_body"
    assert "coat" in actions[0].appearance.lower()
    assert (
        "white hair" in actions[0].appearance.lower()
        and "red eyes" in actions[0].appearance.lower()
    )
    print("ANSWERED:", completed.reply)
    background = await run_turn(
        model, STORY, "Generate a background of a school courtyard at night, without people."
    )
    assert not background.diagnostics
    assert background.proposal is not None
    assert any(op.op == "generate_backgrounds" for op in background.proposal.operations)
    print("BACKGROUND:", background.reply)
    delegated = await run_turn(
        model,
        STORY,
        REQUEST
        + " You choose his name and outfit, and generate a transparent full-body stage sprite.",
    )
    assert not delegated.diagnostics, delegated.diagnostics
    assert delegated.proposal is not None, delegated.reply
    assert any(op.op == "upsert_character" for op in delegated.proposal.operations)
    assert any(
        op.op == "generate_character_images" and op.hires for op in delegated.proposal.operations
    )
    print("DELEGATED:", delegated.reply)
