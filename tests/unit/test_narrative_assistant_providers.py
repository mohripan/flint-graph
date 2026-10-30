"""Narrative assistant providers: Ollama default, Anthropic opt-in, deterministic tests."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from flint_graph.config import Settings
from flint_graph.infrastructure.narrative_assistant import (
    AnthropicNarrativeAssistant,
    DeterministicNarrativeAssistant,
    OllamaNarrativeAssistant,
    build_narrative_assistant,
)
from flint_graph.narrative.assistant.prompts import RESPONSE_SCHEMA
from flint_graph.narrative.assistant.turn import AssistantModelError

MESSAGES = [
    {"role": "system", "content": "SYSTEM RULES"},
    {"role": "user", "content": "PRIVATE STORY TEXT"},
]


def settings(**overrides: Any) -> Settings:
    # GraphRAG answer/support providers are unrelated; keep them offline here.
    base: dict[str, Any] = {
        "query_answer_provider": "deterministic",
        "query_support_provider": "deterministic",
    }
    return Settings(_env_file=None, **{**base, **overrides})


def ollama(handler, **options: Any) -> OllamaNarrativeAssistant:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ollama.test"
    )
    return OllamaNarrativeAssistant(
        model="gemma-local",
        context_tokens=16384,
        max_output_tokens=2048,
        temperature=0.6,
        timeout_seconds=30,
        http_client=client,
        **options,
    )


def ndjson(*chunks: Any) -> bytes:
    return b"".join(json.dumps(chunk).encode() + b"\n" for chunk in chunks)


def chat(*parts: tuple[str, str], **final: Any) -> bytes:
    lines = [{"message": {"role": "assistant", kind: text}, "done": False} for kind, text in parts]
    done = {"model": "gemma-local", "message": {"role": "assistant", "content": ""}, "done": True}
    return ndjson(*lines, {**done, **final})


class Deltas:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    async def __call__(self, kind: str, text: str) -> None:
        self.seen.append((kind, text))


@pytest.mark.anyio
async def test_ollama_streams_the_schema_bounded_chat_with_thinking_off_explicitly():
    seen: list[tuple[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content)))
        body = chat(
            ("content", '{"reply":"h'),
            ("content", 'i","proposal":null}'),
            prompt_eval_count=120,
            eval_count=30,
        )
        return httpx.Response(200, content=body)

    deltas = Deltas()
    reply = await ollama(handler).respond(MESSAGES, RESPONSE_SCHEMA, deltas)
    # Ollama thinks by default on thinking models unless it is told not to.
    assert seen == [
        (
            "/api/chat",
            {
                "model": "gemma-local",
                "messages": MESSAGES,
                "stream": True,
                "think": False,
                "format": RESPONSE_SCHEMA,
                "options": {"temperature": 0.6, "num_ctx": 16384, "num_predict": 2048},
            },
        )
    ]
    assert deltas.seen == [("content", '{"reply":"h'), ("content", 'i","proposal":null}')]
    assert reply.content == '{"reply":"hi","proposal":null}'
    assert (reply.model, reply.input_tokens, reply.output_tokens) == ("gemma-local", 120, 30)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "capabilities,thinks", [(["completion", "thinking"], True), (["completion"], False)]
)
async def test_thinking_is_requested_only_from_capable_models_with_its_own_budget(
    capabilities, thinks
):
    paths: list[str] = []
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/show":
            assert json.loads(request.content) == {"model": "gemma-local"}
            return httpx.Response(200, json={"capabilities": capabilities})
        bodies.append(json.loads(request.content))
        answer = chat(("thinking", "Plan it."), ("content", '{"reply":"ok","proposal":null}'))
        return httpx.Response(200, content=answer)

    model = ollama(handler, thinking=True, thinking_tokens=4096)
    deltas = Deltas()
    await model.respond(MESSAGES, RESPONSE_SCHEMA, deltas)
    await model.respond(MESSAGES, RESPONSE_SCHEMA)
    assert paths == ["/api/show", "/api/chat", "/api/chat"]
    for body in bodies:
        assert body["think"] is thinks
        assert body["options"]["num_predict"] == 2048 + (4096 if thinks else 0)
        assert body["options"]["num_ctx"] == 16384 + (4096 if thinks else 0)
    assert ("thinking", "Plan it.") in deltas.seen


@pytest.mark.anyio
async def test_a_failed_capability_check_is_retried_and_does_not_enable_thinking():
    shows: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            shows.append(1)
            return httpx.Response(500, text="busy")
        assert json.loads(request.content)["think"] is False
        return httpx.Response(200, content=chat(("content", '{"reply":"ok","proposal":null}')))

    model = ollama(handler, thinking=True)
    await model.respond(MESSAGES, RESPONSE_SCHEMA)
    await model.respond(MESSAGES, RESPONSE_SCHEMA)
    assert len(shows) == 2


class SlowStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield ndjson({"message": {"content": '{"reply":'}, "done": False})
        await asyncio.sleep(5)
        yield b""


@pytest.mark.anyio
async def test_the_whole_streamed_call_keeps_the_deadline_and_observers_can_stop_it():
    def slow(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=SlowStream())

    client = httpx.AsyncClient(transport=httpx.MockTransport(slow), base_url="http://o")
    model = OllamaNarrativeAssistant(
        model="gemma-local",
        context_tokens=16384,
        max_output_tokens=2048,
        temperature=0.6,
        timeout_seconds=0.2,
        http_client=client,
    )
    with pytest.raises(AssistantModelError) as raised:
        await model.respond(MESSAGES, RESPONSE_SCHEMA)
    assert raised.value.code == "provider_timeout"

    async def stop(kind: str, text: str) -> None:
        raise AssistantModelError("cancelled")

    def quick(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=chat(("content", '{"reply":"x","proposal":null}')))

    with pytest.raises(AssistantModelError) as raised:
        await ollama(quick).respond(MESSAGES, RESPONSE_SCHEMA, stop)
    assert raised.value.code == "cancelled"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "outcome,code",
    [
        (httpx.Response(500, text="model PRIVATE STORY TEXT failed"), "provider_unavailable"),
        (httpx.Response(404, text="model not found"), "provider_unavailable"),
        (httpx.Response(200, content=chat()), "invalid_response"),
        (httpx.Response(200, content=b"not json\n"), "invalid_response"),
        (httpx.Response(200, content=b'["PRIVATE"]\n'), "invalid_response"),
        (httpx.Response(200, content=ndjson({"error": "PRIVATE STORY"})), "provider_unavailable"),
        # A stream that ends without its final line is incomplete.
        (httpx.Response(200, content=ndjson({"message": {"content": "{"}})), "invalid_response"),
        (
            httpx.Response(200, content=chat(("content", "x" * (256 * 1024 + 1)))),
            "invalid_response",
        ),
        (httpx.ReadTimeout("slow"), "provider_timeout"),
        (httpx.ConnectError("refused"), "provider_unavailable"),
    ],
)
async def test_ollama_failures_are_safe_codes_without_prompt_or_provider_text(outcome, code):
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    with pytest.raises(AssistantModelError) as raised:
        await ollama(handler).respond(MESSAGES, RESPONSE_SCHEMA)
    assert raised.value.code == code
    assert str(raised.value) == code
    error = raised.value
    # No chained exception may carry provider bodies or prompt text into logs.
    assert error.__cause__ is None and (error.__context__ is None or error.__suppress_context__)


class FakeMessages:
    def __init__(self, result):
        self.result = result
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.result


def anthropic_result(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="hidden"),
            SimpleNamespace(type="text", text=text),
        ],
        stop_reason=stop_reason,
        model="claude-test",
        usage=SimpleNamespace(input_tokens=200, output_tokens=40),
    )


@pytest.mark.anyio
async def test_anthropic_is_shaped_to_alternating_turns_and_returns_text_only():
    messages = FakeMessages(anthropic_result('{"reply":"ok","proposal":null}'))
    model = AnthropicNarrativeAssistant(
        model="claude-test",
        max_tokens=4096,
        effort="medium",
        timeout_seconds=30,
        client=SimpleNamespace(messages=messages),
    )
    reply = await model.respond(
        [
            {"role": "system", "content": "SYSTEM RULES"},
            {"role": "assistant", "content": "orphaned earlier reply"},
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "draft"},
            {"role": "user", "content": "repair"},
        ],
        RESPONSE_SCHEMA,
    )
    assert messages.kwargs["system"] == "SYSTEM RULES"
    assert messages.kwargs["messages"] == [
        {"role": "user", "content": "first\n\nsecond"},
        {"role": "assistant", "content": "draft"},
        {"role": "user", "content": "repair"},
    ]
    assert messages.kwargs["model"] == "claude-test" and messages.kwargs["max_tokens"] == 4096
    assert (reply.content, reply.model, reply.input_tokens, reply.output_tokens) == (
        '{"reply":"ok","proposal":null}',
        "claude-test",
        200,
        40,
    )


@pytest.mark.anyio
async def test_anthropic_refusal_and_empty_output_are_safe_codes():
    for result, code in [
        (anthropic_result("", stop_reason="refusal"), "provider_refused"),
        (
            SimpleNamespace(content=[], stop_reason="end_turn", model="m", usage=None),
            "invalid_response",
        ),
    ]:
        model = AnthropicNarrativeAssistant(
            model="m",
            max_tokens=10,
            effort="low",
            timeout_seconds=5,
            client=SimpleNamespace(messages=FakeMessages(result)),
        )
        with pytest.raises(AssistantModelError) as raised:
            await model.respond(MESSAGES, RESPONSE_SCHEMA)
        assert raised.value.code == code


@pytest.mark.anyio
async def test_deterministic_assistant_replays_a_script_then_answers_without_proposals():
    model = DeterministicNarrativeAssistant(['{"reply":"first","proposal":null}'])
    assert (
        await model.respond(MESSAGES, RESPONSE_SCHEMA)
    ).content == '{"reply":"first","proposal":null}'
    fallback = json.loads((await model.respond(MESSAGES, RESPONSE_SCHEMA)).content)
    assert fallback["proposal"] is None and fallback["reply"]


@pytest.mark.anyio
async def test_deterministic_assistant_streams_scripted_thinking_and_content_in_chunks():
    script = [("Think.", '{"reply":"abc","proposal":null}')]
    model = DeterministicNarrativeAssistant(script, chunk_chars=8)
    deltas = Deltas()
    reply = await model.respond(MESSAGES, RESPONSE_SCHEMA, deltas)
    assert deltas.seen[0] == ("thinking", "Think.")
    assert "".join(text for kind, text in deltas.seen if kind == "content") == reply.content
    assert max(len(text) for _, text in deltas.seen) <= 8


def test_test_env_is_offline_and_other_envs_are_disabled_unless_chosen():
    assert settings(env="test").narrative_assistant_provider == "deterministic"
    assert settings(env="local").narrative_assistant_provider == "disabled"
    assert build_narrative_assistant(settings(env="local")) is None
    assert isinstance(
        build_narrative_assistant(settings(env="test")), DeterministicNarrativeAssistant
    )
    chosen = settings(
        env="local",
        narrative_assistant_provider="ollama",
        narrative_assistant_ollama_model="gemma-local",
    )
    assert isinstance(build_narrative_assistant(chosen), OllamaNarrativeAssistant)
    assert chosen.narrative_assistant_thinking is True
    assert chosen.narrative_assistant_thinking_tokens == 8192


def test_real_providers_need_an_explicit_model_or_key_and_a_context_that_fits(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValidationError, match="narrative_assistant_ollama_model"):
        settings(env="local", narrative_assistant_provider="ollama")
    with pytest.raises(ValidationError, match="anthropic_api_key"):
        settings(env="local", narrative_assistant_provider="anthropic", anthropic_api_key=None)
    with pytest.raises(ValidationError, match="narrative_assistant_ollama_context_tokens"):
        settings(
            env="local",
            narrative_assistant_provider="ollama",
            narrative_assistant_ollama_model="gemma-local",
            narrative_assistant_ollama_context_tokens=8192,
        )
    anthropic = settings(
        env="local", narrative_assistant_provider="anthropic", anthropic_api_key="test-key"
    )
    assert anthropic.narrative_assistant_anthropic_model == anthropic.anthropic_answer_model
