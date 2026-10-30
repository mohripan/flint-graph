"""One assistant turn: provider call, strict parsing and bounded diagnostic repair.

Provider failures raise ``AssistantModelError`` with a safe code so the durable job
decides retries. Anything the model returns that cannot be used becomes
diagnostics: they are sent back for at most ``repairs`` attempts, and the last
proposal is kept for review as invalid rather than silently dropped or patched.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from flint_graph.narrative.assistant.context import HistoryTurn, build_messages
from flint_graph.narrative.assistant.operations import Proposal, check_proposal
from flint_graph.narrative.assistant.prompts import RESPONSE_SCHEMA, prompt_sha256
from flint_graph.narrative.values import Diagnostic

RESPONSE_CHARS = 256 * 1024
REPLY_CHARS = 4000
_PARSE_DIAGNOSTICS = 20


class AssistantModelError(Exception):
    """Safe provider failure: the message is only the code, never prompt or provider text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ModelReply:
    content: str
    model: str
    input_tokens: int | None
    output_tokens: int | None


class AssistantModel(Protocol):
    provider: str

    async def respond(
        self, messages: list[dict[str, str]], schema: dict[str, Any]
    ) -> ModelReply: ...


@dataclass(frozen=True)
class TurnResult:
    """``proposal`` with empty ``diagnostics`` is reviewable; with diagnostics it is invalid."""

    reply: str
    proposal: Proposal | None
    story: dict[str, Any] | None
    diagnostics: tuple[Diagnostic, ...]
    warnings: tuple[Diagnostic, ...]
    touched: tuple[str, ...]
    attempts: int
    model: str
    input_tokens: int
    output_tokens: int
    prompt_sha256: str


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reply: str
    proposal: dict[str, Any] | None = Field(default=None)


def _parse(content: str) -> tuple[_Envelope | None, Proposal | None, tuple[Diagnostic, ...]]:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    try:
        if len(content) > RESPONSE_CHARS:
            raise ValueError("oversized")
        envelope = _Envelope.model_validate(json.loads(text))
    except (ValueError, ValidationError):
        return None, None, (Diagnostic("invalid_response", "response"),)
    if envelope.proposal is None:
        return envelope, None, ()
    try:
        return envelope, Proposal.model_validate(envelope.proposal), ()
    except ValidationError as error:
        diagnostics = tuple(
            Diagnostic("invalid_proposal", ".".join(["proposal", *map(str, item["loc"])]))
            for item in error.errors()[:_PARSE_DIAGNOSTICS]
        )
        return envelope, None, diagnostics


def _repair_request(diagnostics: Sequence[Diagnostic]) -> str:
    lines = "\n".join(f"- {item.code} at {item.location}" for item in diagnostics)
    return (
        "Your previous answer could not be used. Diagnostics (code at location):\n"
        f"{lines}\n"
        "Return the complete corrected JSON object with the same intent, fixing exactly "
        "these problems."
    )


async def run_turn(
    model: AssistantModel,
    story: dict[str, Any],
    request: str,
    *,
    focus: str | None = None,
    history: Sequence[HistoryTurn] = (),
    budget: int = 24000,
    repairs: int = 2,
) -> TurnResult:
    messages = build_messages(story, request, focus=focus, history=history, budget=budget)
    reply, proposal, model_name = "", None, ""
    diagnostics: tuple[Diagnostic, ...] = ()
    input_tokens = output_tokens = 0
    for attempt in range(1, repairs + 2):
        answer = await model.respond(messages, RESPONSE_SCHEMA)
        model_name = answer.model
        input_tokens += answer.input_tokens or 0
        output_tokens += answer.output_tokens or 0
        envelope, parsed, diagnostics = _parse(answer.content)
        if envelope is not None:
            reply = envelope.reply[:REPLY_CHARS]
        if parsed is not None:
            proposal = parsed
            check = check_proposal(story, parsed.operations)
            diagnostics = check.diagnostics
            if not diagnostics:
                return TurnResult(
                    reply,
                    parsed,
                    check.story,
                    (),
                    check.warnings,
                    check.touched,
                    attempt,
                    model_name,
                    input_tokens,
                    output_tokens,
                    prompt_sha256(),
                )
        elif not diagnostics:
            return TurnResult(
                reply,
                None,
                None,
                (),
                (),
                (),
                attempt,
                model_name,
                input_tokens,
                output_tokens,
                prompt_sha256(),
            )
        messages = [
            *messages,
            {"role": "assistant", "content": answer.content[:RESPONSE_CHARS]},
            {"role": "user", "content": _repair_request(diagnostics)},
        ]
    return TurnResult(
        reply,
        proposal,
        None,
        diagnostics,
        (),
        (),
        repairs + 1,
        model_name,
        input_tokens,
        output_tokens,
        prompt_sha256(),
    )
