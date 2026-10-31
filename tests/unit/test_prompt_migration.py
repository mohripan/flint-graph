"""Golden bytes captured from b4b6729 before extracting any legacy builder."""

import json
from pathlib import Path

import pytest
from test_anthropic_adapters import _FakeClient, _message, _RecordingMessages

from flint_graph.application.extraction import build_extraction_prompt
from flint_graph.application.extraction_proposals import (
    ExtractionBatchRequest,
    ExtractionInputChunk,
)
from flint_graph.application.query_orchestration import AnswerGenerationRequest, SupportCheckRequest
from flint_graph.infrastructure import anthropic, ollama
from flint_graph.narrative.assistant.context import build_messages
from flint_graph.narrative.assistant.prompts import prompt_sha256
from flint_graph.prompts.catalog import PromptEntry
from flint_graph.prompts.source import PromptBundle, current_snapshot, use_snapshot

GOLDEN = json.loads(
    (Path(__file__).parents[1] / "fixtures/prompts/legacy_renderings.json").read_text(
        encoding="utf-8"
    )
)


def test_migrated_builders_preserve_recorded_prompt_bytes_and_legacy_identity():
    from dataclasses import asdict

    from flint_graph.narrative import imagegen
    from flint_graph.narrative.assistant.turn import _repair_request
    from flint_graph.narrative.values import Diagnostic

    answer = AnswerGenerationRequest.model_validate(GOLDEN["answer_request"])
    support = SupportCheckRequest.model_validate(GOLDEN["support_request"])
    expected = GOLDEN["expected"]
    actual = {
        "answer_anthropic_system": anthropic._answer_system_prompt(),
        "answer_anthropic_user": anthropic._answer_user_prompt(answer),
        "answer_ollama": ollama._build_answer_generation_prompt(answer),
        "support_anthropic_system": anthropic._support_system_prompt(),
        "support_anthropic_user": anthropic._support_user_prompt(support),
        "support_ollama": ollama._build_support_check_prompt(support),
        "extraction_builtin": build_extraction_prompt(GOLDEN["chunks"]),
        "extraction_proposals": ollama._build_proposal_extraction_prompt(
            ExtractionBatchRequest(
                chunks=[ExtractionInputChunk(chunk_id=k, text=v) for k, v in GOLDEN["chunks"]]
            )
        ),
        "extraction_schema": ollama._proposal_extraction_schema(),
        "assistant_messages": build_messages(GOLDEN["story"], GOLDEN["request"]),
        "assistant_hash": prompt_sha256(),
        "assistant_repair": _repair_request([Diagnostic("unknown_asset", "operations.0")]),
        "portrait": asdict(
            imagegen.portrait_request("white hair, blue coat", "boy", "full_body", transparent=True)
        ),
        "background": asdict(imagegen.background_request("courtyard at night")),
        "image_policy": {
            "negative": imagegen.DEFAULT_POLICY.negative,
            "blocked": list(imagegen.DEFAULT_POLICY.blocked),
        },
    }
    assert actual == {key: expected[key] for key in actual}


@pytest.mark.anyio
async def test_provider_uses_the_selected_reviewed_bundle():
    bundle = current_snapshot()
    original = bundle.entry("grounded.answer.anthropic").data
    original.pop("type")
    original["catalog_version"] = 2
    original["template"][0]["content"] = "A reviewed replacement from the catalog."
    replacement = PromptEntry.create(**original)
    changed = PromptBundle.create(
        [replacement if e.name == replacement.name else e for e in bundle.entries],
        source_revision="fixture",
        evaluation_record="fixture",
    )
    messages = _RecordingMessages(_message('{"insufficient_context":true,"claims":[]}'))
    generator = anthropic.AnthropicAnswerGenerator(
        model="synthetic",
        max_tokens=100,
        effort="medium",
        timeout_seconds=1,
        client=_FakeClient(messages),
    )
    with use_snapshot(changed):
        await generator.generate(AnswerGenerationRequest.model_validate(GOLDEN["answer_request"]))
    assert messages.create_calls[0]["system"] == "A reviewed replacement from the catalog."


@pytest.mark.anyio
async def test_ollama_uses_the_selected_reviewed_template_without_retemplating_inputs():
    import httpx

    bundle = current_snapshot()
    data = bundle.entry("grounded.answer.ollama").data
    data.pop("type")
    data["catalog_version"] = 2
    data["template"] = "Reviewed: {{query}}\n{{context}}{{verified_calculations}}"
    entry = PromptEntry.create(**data)
    selected = PromptBundle.create(
        [entry if e.name == entry.name else e for e in bundle.entries],
        source_revision="fixture",
        evaluation_record="fixture",
    )
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200, json={"done": True, "response": '{"insufficient_context":true,"claims":[]}'}
        )

    async with httpx.AsyncClient(
        base_url="http://model.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        generator = ollama.OllamaAnswerGenerator(
            model="synthetic", timeout_seconds=1, temperature=0, max_tokens=100, http_client=client
        )
        with use_snapshot(selected):
            await generator.generate(
                AnswerGenerationRequest.model_validate(GOLDEN["answer_request"])
            )
    assert calls[0]["prompt"].startswith("Reviewed: Where is Acme")


def test_narrative_messages_and_image_policy_use_the_selected_bundle():
    from flint_graph.narrative.imagegen import background_request, content_policy

    bundle = current_snapshot()
    replacements = {}
    for name in ("narrative.assistant.system", "narrative.image.content_policy"):
        data = bundle.entry(name).data
        data.pop("type")
        data["catalog_version"] = 2
        if name.endswith("system"):
            data["template"][0]["content"] = "Reviewed narrative instructions."
        else:
            data["config"]["blocked"] = ["courtyard"]
        replacements[name] = PromptEntry.create(**data)
    selected = PromptBundle.create(
        [replacements.get(e.name, e) for e in bundle.entries],
        source_revision="fixture",
        evaluation_record="fixture",
    )
    with use_snapshot(selected):
        assert (
            build_messages(GOLDEN["story"], "A question")[0]["content"]
            == "Reviewed narrative instructions."
        )
        with pytest.raises(ValueError, match="blocked"):
            background_request("courtyard at night", policy=content_policy(None))


@pytest.mark.anyio
async def test_identity_is_recorded_before_provider_dispatch():
    from flint_graph.prompts.identity import identified, observe_identity

    calls = []

    class Result:
        def __init__(self):
            self.metadata = {}

    class Provider:
        _model = "synthetic-local-model"
        _max_tokens = 128

        @identified("grounded.answer.ollama")
        async def generate(self):
            calls.append("dispatch")
            return Result()

    async def record(identity):
        assert identity["effective_config"] == {"model": "synthetic-local-model", "max_tokens": 128}
        assert identity["bundle_sha256"] == current_snapshot().sha256
        calls.append("durable-identity")

    with observe_identity(record):
        result = await Provider().generate()
    assert calls == ["durable-identity", "dispatch"]
    assert result.metadata["prompt_identity"]["name"] == "grounded.answer.ollama"
