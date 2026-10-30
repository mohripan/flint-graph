"""Narrative-assistant provider adapters at the infrastructure edge.

Ollama is the development default (local, no per-call cost); Anthropic is an
explicit opt-in; the deterministic adapter keeps ``env=test`` offline. Every
failure is reduced to a safe ``AssistantModelError`` code: provider bodies and
prompts never reach exceptions, logs or persisted job state.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

import httpx

from flint_graph.config import Settings
from flint_graph.domain.enums import ProviderUsageOperation
from flint_graph.infrastructure.provider_telemetry import provider_call
from flint_graph.narrative.assistant.turn import (
    RESPONSE_CHARS,
    AssistantModel,
    AssistantModelError,
    DeltaSink,
    ModelReply,
)

_OPERATION = ProviderUsageOperation.NARRATIVE_ASSISTANT


def _count(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _chunk(line: str) -> dict[str, Any]:
    try:
        chunk = json.loads(line)
    except ValueError:
        raise AssistantModelError("invalid_response") from None
    if type(chunk) is not dict:
        raise AssistantModelError("invalid_response")
    if "error" in chunk:
        raise AssistantModelError("provider_unavailable")
    return chunk


class OllamaNarrativeAssistant:
    """Streams ``/api/chat`` with a JSON-schema format under one per-call deadline.

    Ollama thinks by default on thinking-capable models when ``think`` is omitted,
    which can spend the whole output budget before any answer. ``think`` is
    therefore always explicit: it is enabled only when requested and the model
    reports the capability, and thinking gets its own token allowance.
    """

    provider = "ollama"

    def __init__(
        self,
        *,
        model: str,
        context_tokens: int,
        max_output_tokens: int,
        temperature: float,
        timeout_seconds: float,
        http_client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
        thinking: bool = False,
        thinking_tokens: int = 8192,
    ) -> None:
        self._model = model
        self._context, self._output, self._temperature = (
            context_tokens,
            max_output_tokens,
            temperature,
        )
        self._timeout = timeout_seconds
        self._thinking, self._thinking_tokens = thinking, thinking_tokens
        self._capable: bool | None = None
        self._client = http_client or httpx.AsyncClient(
            base_url=base_url or "http://localhost:11434"
        )

    async def _thinks(self) -> bool:
        if not self._thinking:
            return False
        if self._capable is None:
            try:
                response = await self._client.post(
                    "/api/show", json={"model": self._model}, timeout=self._timeout
                )
                capabilities = response.json().get("capabilities") if response.is_success else None
            except (httpx.HTTPError, ValueError, AttributeError):
                capabilities = None
            if type(capabilities) is not list:
                return False  # Unknown: answer without thinking and ask again next call.
            self._capable = "thinking" in capabilities
        return self._capable

    async def respond(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        on_delta: DeltaSink | None = None,
    ) -> ModelReply:
        thinks = await self._thinks()
        extra = self._thinking_tokens if thinks else 0
        body = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "think": thinks,
            "format": schema,
            "options": {
                "temperature": self._temperature,
                "num_ctx": self._context + extra,
                "num_predict": self._output + extra,
            },
        }
        parts: list[str] = []
        size, final = 0, None
        try:
            async with (
                provider_call(provider=self.provider, model=self._model, operation=_OPERATION),
                asyncio.timeout(self._timeout),
                self._client.stream(
                    "POST", "/api/chat", json=body, timeout=self._timeout
                ) as response,
            ):
                if not response.is_success:
                    raise AssistantModelError("provider_unavailable")
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = _chunk(line)
                    message = chunk.get("message")
                    if type(message) is dict:
                        thinking, content = message.get("thinking"), message.get("content")
                        if type(thinking) is str and thinking and on_delta is not None:
                            await on_delta("thinking", thinking)
                        if type(content) is str and content:
                            size += len(content)
                            if size > RESPONSE_CHARS:
                                raise AssistantModelError("invalid_response")
                            parts.append(content)
                            if on_delta is not None:
                                await on_delta("content", content)
                    if chunk.get("done") is True:
                        final = chunk
                        break
        except (TimeoutError, httpx.TimeoutException):
            raise AssistantModelError("provider_timeout") from None
        except httpx.HTTPError:
            raise AssistantModelError("provider_unavailable") from None
        content = "".join(parts)
        if final is None or not content:
            raise AssistantModelError("invalid_response")
        model = final.get("model")
        return ModelReply(
            content=content,
            model=model if isinstance(model, str) and model else self._model,
            input_tokens=_count(final.get("prompt_eval_count")),
            output_tokens=_count(final.get("eval_count")),
        )


def _anthropic_turns(messages: Sequence[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    # The Messages API takes the system prompt separately and alternating turns
    # starting with the user; merge repeats and drop a truncated leading reply.
    system = "\n\n".join(item["content"] for item in messages if item["role"] == "system")
    turns: list[dict[str, str]] = []
    for item in messages:
        if item["role"] == "system" or (not turns and item["role"] != "user"):
            continue
        if turns and turns[-1]["role"] == item["role"]:
            turns[-1] = {
                "role": item["role"],
                "content": turns[-1]["content"] + "\n\n" + item["content"],
            }
        else:
            turns.append({"role": item["role"], "content": item["content"]})
    return system, turns


class AnthropicNarrativeAssistant:
    provider = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        max_tokens: int,
        effort: str,
        timeout_seconds: float,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._model, self._max_tokens, self._effort = model, max_tokens, effort
        if client is None:
            # Imported lazily so offline tests never need the SDK or a key.
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=api_key, timeout=timeout_seconds)
        self._client: Any = client

    async def respond(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        on_delta: DeltaSink | None = None,
    ) -> ModelReply:
        # Not streamed yet (opt-in, offline-tested only): turn steps and the parsed
        # reply are still published by the turn loop.
        system, turns = _anthropic_turns(messages)
        try:
            async with provider_call(
                provider=self.provider, model=self._model, operation=_OPERATION
            ):
                message = await self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=system,
                    messages=turns,
                    thinking={"type": "adaptive"},
                    output_config={"effort": self._effort},
                )
        except Exception:
            raise AssistantModelError("provider_unavailable") from None
        if getattr(message, "stop_reason", None) == "refusal":
            raise AssistantModelError("provider_refused")
        text = "".join(
            getattr(block, "text", "")
            for block in getattr(message, "content", None) or []
            if getattr(block, "type", None) == "text"
        )
        if not text:
            raise AssistantModelError("invalid_response")
        usage = getattr(message, "usage", None)
        model = getattr(message, "model", None)
        return ModelReply(
            content=text,
            model=model if isinstance(model, str) and model else self._model,
            input_tokens=_count(getattr(usage, "input_tokens", None)),
            output_tokens=_count(getattr(usage, "output_tokens", None)),
        )


class DeterministicNarrativeAssistant:
    """Replays scripted responses in chunks, then answers without proposing changes.

    A script entry is the response text, or ``(thinking, response)``.
    """

    provider = "deterministic"

    def __init__(
        self, script: Sequence[str | tuple[str, str]] = (), *, chunk_chars: int = 64
    ) -> None:
        self._script = list(script)
        self._chunk = chunk_chars

    async def respond(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        on_delta: DeltaSink | None = None,
    ) -> ModelReply:
        item = (
            self._script.pop(0)
            if self._script
            else json.dumps(
                {"reply": "The offline assistant does not propose story changes.", "proposal": None}
            )
        )
        thinking, content = item if isinstance(item, tuple) else ("", item)
        if on_delta is not None:
            for kind, text in (("thinking", thinking), ("content", content)):
                for start in range(0, len(text), self._chunk):
                    await on_delta(kind, text[start : start + self._chunk])  # type: ignore[arg-type]
        return ModelReply(
            content=content,
            model="deterministic-narrative-assistant",
            input_tokens=0,
            output_tokens=0,
        )


def build_narrative_assistant(settings: Settings) -> AssistantModel | None:
    """Return the configured provider, or ``None`` when conversational authoring is off."""
    provider = settings.narrative_assistant_provider
    if provider == "deterministic":
        return DeterministicNarrativeAssistant()
    if provider == "ollama":
        assert settings.narrative_assistant_ollama_model is not None
        return OllamaNarrativeAssistant(
            model=settings.narrative_assistant_ollama_model,
            context_tokens=settings.narrative_assistant_ollama_context_tokens,
            max_output_tokens=settings.narrative_assistant_max_output_tokens,
            temperature=settings.narrative_assistant_temperature,
            timeout_seconds=settings.narrative_assistant_turn_deadline_seconds,
            base_url=settings.ollama_base_url,
            thinking=settings.narrative_assistant_thinking,
            thinking_tokens=settings.narrative_assistant_thinking_tokens,
        )
    if provider == "anthropic":
        assert settings.narrative_assistant_anthropic_model is not None
        return AnthropicNarrativeAssistant(
            model=settings.narrative_assistant_anthropic_model,
            max_tokens=settings.narrative_assistant_max_output_tokens,
            effort=settings.anthropic_effort,
            timeout_seconds=settings.narrative_assistant_turn_deadline_seconds,
            api_key=settings.anthropic_api_key,
        )
    return None
