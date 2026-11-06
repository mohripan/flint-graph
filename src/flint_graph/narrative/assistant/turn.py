"""One assistant turn: provider call, strict parsing and bounded diagnostic repair.

Provider failures raise ``AssistantModelError`` with a safe code so the durable job
decides retries. Anything the model returns that cannot be used becomes
diagnostics: they are sent back for at most ``repairs`` attempts, and the last
proposal is kept for review as invalid rather than silently dropped or patched.

An optional ``TurnObserver`` sees each step (counts and diagnostic codes only),
the model's thinking and the reply text as they stream; it never sees raw proposal
JSON and may stop the turn by raising ``AssistantModelError``.
"""

import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from flint_graph.narrative.assistant.assets import LibraryEntry, add_library_assets
from flint_graph.narrative.assistant.context import HistoryTurn, build_turn_messages
from flint_graph.narrative.assistant.operations import (
    AddAsset,
    GenerateCharacterImages,
    Proposal,
    UpsertCharacter,
    check_proposal,
    field_choices,
)
from flint_graph.narrative.assistant.prompts import prompt_sha256, response_schema
from flint_graph.narrative.assistant.stream import ReplyScanner
from flint_graph.narrative.values import Diagnostic
from flint_graph.prompts.source import render, snapshot_async

RESPONSE_CHARS = 256 * 1024
REPLY_CHARS = 4000
_PARSE_DIAGNOSTICS = 20
_STEP_CODES = 5


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


# Providers report streamed output as ("thinking" | "content", text) deltas.
DeltaSink = Callable[[Literal["thinking", "content"], str], Awaitable[None]]


class AssistantModel(Protocol):
    provider: str

    async def respond(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        on_delta: DeltaSink | None = None,
    ) -> ModelReply: ...


class TurnObserver(Protocol):
    async def step(self, name: str, state: str, detail: Mapping[str, Any]) -> None: ...

    async def thinking(self, call: int, text: str) -> None: ...

    async def text(self, call: int, text: str) -> None: ...


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


def _reason(error: Any) -> str:
    """A short, plain explanation of one validation error for the repair request."""
    kind, loc = error.get("type"), error.get("loc", ())
    if kind == "missing":
        choices = (
            field_choices(str(loc[2]), str(loc[3]))
            if len(loc) == 4 and loc[0] == "operations"
            else ()
        )
        return "required, but missing" + (f"; use one of: {', '.join(choices)}" if choices else "")
    if kind == "extra_forbidden":
        return "not allowed here; remove it or use the field this operation defines"
    return str(error.get("msg", "invalid")).lower()[:120]


def _parse(
    content: str,
) -> tuple[_Envelope | None, Proposal | None, tuple[Diagnostic, ...], dict[str, str]]:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    try:
        if len(content) > RESPONSE_CHARS:
            raise ValueError("oversized")
        envelope = _Envelope.model_validate(json.loads(text))
    except (ValueError, ValidationError):
        return None, None, (Diagnostic("invalid_response", "response"),), {}
    if envelope.proposal is None:
        return envelope, None, (), {}
    try:
        return envelope, Proposal.model_validate(envelope.proposal), (), {}
    except ValidationError as error:
        errors = error.errors()[:_PARSE_DIAGNOSTICS]
        diagnostics = tuple(
            Diagnostic("invalid_proposal", ".".join(["proposal", *map(str, item["loc"])]))
            for item in errors
        )
        reasons = {
            item.location: _reason(raw) for item, raw in zip(diagnostics, errors, strict=True)
        }
        return envelope, None, diagnostics, reasons


def _without_pending_sprites(
    story: dict[str, Any], proposal: Proposal, dropped_for: frozenset[str] = frozenset()
) -> Proposal:
    """Drop sprite links to pictures the same proposal only suggests generating.

    The model cannot know a future picture's asset id; approving the generated
    pictures in Characters binds the sprites. Other unknown links stay errors.
    ``dropped_for`` names characters whose broken suggestions were left out.
    """
    known = set(story.get("assets") or {})
    known |= {item.id for item in proposal.operations if isinstance(item, AddAsset)}
    generating = set(dropped_for) | {
        item.character for item in proposal.operations if isinstance(item, GenerateCharacterImages)
    }
    operations = []
    for item in proposal.operations:
        if isinstance(item, UpsertCharacter) and item.id in generating and item.sprites:
            sprites = {name: asset for name, asset in item.sprites.items() if asset in known}
            if sprites != item.sprites:
                item = item.model_copy(update={"sprites": sprites or None})
        operations.append(item)
    return proposal.model_copy(update={"operations": operations})


_ACTION_PROBLEM = re.compile(r"proposal\.operations\.(\d+)\.generate_[a-z_]+(\.|$)")


def _without_broken_actions(
    raw: dict[str, Any] | None, diagnostics: Sequence[Diagnostic]
) -> tuple[Proposal, tuple[Diagnostic, ...], frozenset[str]] | None:
    """Drop picture suggestions that are still invalid, if nothing else is wrong.

    Suggestions are never applied with a proposal; the creator starts them separately.
    """
    broken: set[int] = set()
    for item in diagnostics:
        match = _ACTION_PROBLEM.match(item.location)
        if item.code != "invalid_proposal" or match is None:
            return None
        broken.add(int(match.group(1)))
    operations = raw.get("operations") if raw is not None else None
    if not broken or not isinstance(operations, list):
        return None
    kept = [operation for index, operation in enumerate(operations) if index not in broken]
    if not kept:
        return None
    try:
        proposal = Proposal.model_validate({**raw, "operations": kept})  # type: ignore[dict-item]
    except ValidationError:
        return None
    notes = tuple(
        Diagnostic("image_action_dropped", f"proposal.operations.{index}")
        for index in sorted(broken)
    )
    characters = frozenset(
        str(operations[index]["character"])
        for index in broken
        if index < len(operations)
        and isinstance(operations[index], dict)
        and isinstance(operations[index].get("character"), str)
    )
    return proposal, notes, characters


def _repair_request(
    diagnostics: Sequence[Diagnostic], reasons: Mapping[str, str] | None = None
) -> str:
    # Saying what is wrong, not only where, lets a local model fix a misnamed field.
    lines = (
        f"- {item.code} at {item.location}"
        + (f": {reasons[item.location]}" if reasons and item.location in reasons else "")
        for item in diagnostics
    )
    return render("narrative.assistant.repair", diagnostics="\n".join(lines))


class _Silent:
    async def step(self, name: str, state: str, detail: Mapping[str, Any]) -> None:
        return None

    async def thinking(self, call: int, text: str) -> None:
        return None

    async def text(self, call: int, text: str) -> None:
        return None


def _codes(diagnostics: Sequence[Diagnostic]) -> list[str]:
    return list(dict.fromkeys(item.code for item in diagnostics))[:_STEP_CODES]


class _CallStream:
    """Turns one call's provider deltas into thinking, reply text and drafting steps."""

    def __init__(self, observer: TurnObserver, call: int) -> None:
        self.observer, self.call = observer, call
        self.scanner = ReplyScanner()
        self.reply = ""
        self.drafting = False
        self.operations = 0

    async def __call__(self, kind: Literal["thinking", "content"], text: str) -> None:
        if kind == "thinking":
            await self.observer.thinking(self.call, text)
            return
        await self.publish(self.scanner.feed(text))
        if self.scanner.proposal_started and not self.drafting:
            self.drafting = True
            await self.observer.step("drafting", "started", {"call": self.call})
        if self.scanner.operations > self.operations:
            self.operations = self.scanner.operations
            await self.observer.step(
                "drafting", "progress", {"call": self.call, "operations": self.operations}
            )

    async def publish(self, text: str) -> None:
        text = text[: REPLY_CHARS - len(self.reply)]
        if text:
            self.reply += text
            await self.observer.text(self.call, text)


@snapshot_async
async def run_turn(
    model: AssistantModel,
    story: dict[str, Any],
    request: str,
    *,
    focus: str | None = None,
    history: Sequence[HistoryTurn] = (),
    budget: int = 24000,
    repairs: int = 2,
    observer: TurnObserver | None = None,
    library: Sequence[LibraryEntry] = (),
    profiles: Mapping[str, str] | None = None,
) -> TurnResult:
    watch = observer or _Silent()
    messages, stats = build_turn_messages(
        story,
        request,
        focus=focus,
        history=history,
        budget=budget,
        library=library,
        profiles=profiles,
    )
    await watch.step(
        "context",
        "done",
        {
            "scenes": stats.scenes,
            "outlined": stats.outlined,
            "omitted": stats.scenes - stats.outlined,
            "focus": stats.focus,
            "history": stats.history,
        },
    )
    reply, proposal, model_name = "", None, ""
    diagnostics: tuple[Diagnostic, ...] = ()
    input_tokens = output_tokens = 0
    calls = repairs + 1
    for attempt in range(1, calls + 1):
        await watch.step(
            "model", "started", {"call": attempt, "of": calls, "provider": model.provider}
        )
        stream = _CallStream(watch, attempt)
        answer = await model.respond(messages, response_schema(), stream)
        done: dict[str, Any] = {"call": attempt}
        if answer.output_tokens is not None:
            done["output_tokens"] = answer.output_tokens
        await watch.step("model", "done", done)
        model_name = answer.model
        input_tokens += answer.input_tokens or 0
        output_tokens += answer.output_tokens or 0
        envelope, parsed, diagnostics, reasons = _parse(answer.content)
        if envelope is not None:
            reply = envelope.reply[:REPLY_CHARS]
            # Providers without deltas (or a reply the scanner missed) still show it.
            if reply.startswith(stream.reply):
                await stream.publish(reply[len(stream.reply) :])
        dropped: tuple[Diagnostic, ...] = ()
        dropped_for: frozenset[str] = frozenset()
        if parsed is None and attempt == calls and envelope is not None:
            # Repairs are spent: keep the story edits if only picture suggestions are broken.
            kept = _without_broken_actions(envelope.proposal, diagnostics)
            if kept is not None:
                parsed, dropped, dropped_for = kept
        if parsed is not None:
            # Library IDs the model used become explicit, stored asset additions.
            parsed = _without_pending_sprites(
                story, add_library_assets(story, parsed, library), dropped_for
            )
            proposal = parsed
            check = check_proposal(story, parsed.operations)
            diagnostics = check.diagnostics
        if parsed is not None or diagnostics:
            await watch.step(
                "validating",
                "done",
                {
                    "call": attempt,
                    "valid": not diagnostics,
                    "problems": len(diagnostics),
                    "codes": _codes(diagnostics),
                },
            )
        if parsed is not None and not diagnostics:
            return TurnResult(
                reply,
                parsed,
                check.story,
                (),
                check.warnings + dropped,
                check.touched,
                attempt,
                model_name,
                input_tokens,
                output_tokens,
                prompt_sha256(),
            )
        if parsed is None and not diagnostics:
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
        if attempt < calls:
            await watch.step(
                "repair",
                "started",
                {"call": attempt + 1, "of": calls, "problems": len(diagnostics)},
            )
        messages = [
            *messages,
            {"role": "assistant", "content": answer.content[:RESPONSE_CHARS]},
            {"role": "user", "content": _repair_request(diagnostics, reasons)},
        ]
    return TurnResult(
        reply,
        proposal,
        None,
        diagnostics,
        (),
        (),
        calls,
        model_name,
        input_tokens,
        output_tokens,
        prompt_sha256(),
    )
