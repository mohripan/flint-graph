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
    ACTIONS,
    AddAsset,
    GenerateBackgrounds,
    GenerateCg,
    GenerateCharacterImages,
    GenerateExpressions,
    GenerateVoice,
    Proposal,
    StartChildSession,
    UpsertCharacter,
    UpsertNode,
    apply_operations,
    check_proposal,
    field_choices,
)
from flint_graph.narrative.assistant.prompts import prompt_sha256, response_schema
from flint_graph.narrative.assistant.stream import ReplyScanner
from flint_graph.narrative.values import Diagnostic, PackageError
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


_NARRATION_SPEAKERS = {"narrator", "narration", "none", "system"}


def _tidied_line(node: dict[str, Any], known: set[str], assets: set[str]) -> dict[str, Any]:
    """Correct the line mistakes local models keep making, whose meaning is unambiguous."""
    speaker = node.get("speaker")
    if isinstance(speaker, str) and speaker.lower() in _NARRATION_SPEAKERS and speaker not in known:
        node = {k: v for k, v in node.items() if k not in ("speaker", "expression")}
    voice = node.get("voice")
    if "voice" in node and "speaker" not in node:
        node = {k: v for k, v in node.items() if k != "voice"}  # Narration is silent.
    elif isinstance(voice, dict):
        # A clip that does not exist yet is simply not there; models write the voice's name.
        drop = {"audio"} if voice.get("audio") not in assets else set()
        if voice.get("mode") == "full":
            drop.add("text")
        if drop.intersection(voice):
            node = {**node, "voice": {k: v for k, v in voice.items() if k not in drop}}
    return node


def _tidied_stage(
    node: dict[str, Any],
    sprites: Mapping[str, Mapping[str, str]],
    assets: set[str],
    generating: set[str],
    pending: Mapping[str, set[str]],
) -> dict[str, Any]:
    """A stage entry names an expression, so an asset ID has one meaning; and a file still
    being generated has no ID yet, so a made-up one for it can only be left out."""
    changed = dict(node)
    for field in ("background", "cg"):
        if field in generating and isinstance(node.get(field), str) and node[field] not in assets:
            del changed[field]
    show = node.get("show")
    if isinstance(show, list):
        entries = []
        for entry in show:
            if isinstance(entry, dict):
                character = str(entry.get("character"))
                own = sprites.get(character) or {}
                wanted = entry.get("sprite")
                if wanted not in own and wanted in own.values():
                    named = next(name for name, key in own.items() if key == wanted)
                    entry = {**entry, "sprite": named}
                elif wanted not in own and wanted in pending.get(character, ()) and own:
                    # An expression still being generated: the usual face until it is approved.
                    entry = {**entry, "sprite": "neutral" if "neutral" in own else next(iter(own))}
            entries.append(entry)
        changed["show"] = entries
    return changed


def _with_tidied_nodes(story: dict[str, Any], proposal: Proposal) -> Proposal:
    """Each round trip to correct these costs seconds to minutes, so correct them here."""
    upserted = {item.id: item for item in proposal.operations if isinstance(item, UpsertCharacter)}
    characters = story.get("characters") or {}
    known = set(characters) | set(upserted)
    sprites: dict[str, Mapping[str, str]] = {
        key: (upserted[key].sprites if key in upserted and upserted[key].sprites else None)
        or (characters.get(key) or {}).get("sprites")
        or {}
        for key in known
    }
    assets = set(story.get("assets") or {}) | {
        item.id for item in proposal.operations if isinstance(item, AddAsset)
    }
    generating = {
        field
        for field, kind in (("background", GenerateBackgrounds), ("cg", GenerateCg))
        if any(isinstance(item, kind) for item in proposal.operations)
    }
    pending: dict[str, set[str]] = {}
    for item in proposal.operations:
        if isinstance(item, GenerateExpressions):
            pending.setdefault(item.character, set()).update(item.expressions)
    operations = []
    for item in proposal.operations:
        if isinstance(item, UpsertNode):
            kind = item.node.get("type")
            if kind == "line":
                item = item.model_copy(update={"node": _tidied_line(item.node, known, assets)})
            elif kind == "stage":
                node = _tidied_stage(item.node, sprites, assets, generating, pending)
                item = item.model_copy(update={"node": node})
        operations.append(item)
    return proposal.model_copy(update={"operations": operations})


def _with_voice_actions(proposal: Proposal, capabilities: Sequence[str]) -> Proposal:
    """A line marked for voice stays silent without its action, and local models often write
    only the mark. The mark comes from a request for voice, so it can stand for the action."""
    if "voices" not in capabilities:
        return proposal
    covered = {
        line
        for item in proposal.operations
        if isinstance(item, GenerateVoice)
        for line in item.lines
    }
    wanted: dict[str, list[str]] = {}
    for item in proposal.operations:
        if isinstance(item, UpsertNode) and item.id not in covered:
            node = item.node
            voice = node.get("voice")
            if node.get("type") == "line" and isinstance(voice, dict) and "audio" not in voice:
                speaker = node.get("speaker")
                if isinstance(speaker, str):
                    wanted.setdefault(speaker, []).append(item.id)
    added = [
        GenerateVoice(op="generate_voice", character=speaker, lines=lines[start : start + 24])
        for speaker, lines in wanted.items()
        for start in range(0, len(lines), 24)
    ]
    if not added:
        return proposal
    return proposal.model_copy(update={"operations": [*proposal.operations, *added]})


_ACTION_PROBLEM = re.compile(r"proposal\.operations\.(\d+)\.generate_[a-z_]+(\.|$)")
_ACTION_CHECK = re.compile(r"operations\.(\d+)\.(character|characters|lines)$")


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


def _without_unusable_actions(
    story: dict[str, Any], proposal: Proposal, diagnostics: Sequence[Diagnostic]
) -> tuple[Proposal, tuple[Diagnostic, ...]] | None:
    """Drop actions the story cannot satisfy, once repairs are spent, if only they are wrong."""
    broken: set[int] = set()
    for item in diagnostics:
        match = _ACTION_CHECK.match(item.location)
        if match is None or not isinstance(proposal.operations[int(match.group(1))], ACTIONS):
            return None
        broken.add(int(match.group(1)))
    kept = [item for index, item in enumerate(proposal.operations) if index not in broken]
    if not broken or not kept:
        return None
    notes = tuple(
        Diagnostic("image_action_dropped", f"proposal.operations.{index}")
        for index in sorted(broken)
    )
    return proposal.model_copy(update={"operations": kept}), notes


def _listed(values: Sequence[str]) -> str:
    shown = ", ".join(list(values)[:30])
    if not shown:
        return "none"
    return shown + (f" and {len(values) - 30} more" if len(values) > 30 else "")


def _problem_reasons(
    story: dict[str, Any], proposal: Proposal, diagnostics: Sequence[Diagnostic]
) -> dict[str, str]:
    """Say what exists, so a repair can fix a bad reference on its first try."""
    try:
        edited = apply_operations(story, proposal.operations).story
    except PackageError:
        edited = story
    characters, nodes = list(edited["characters"]), list(edited["nodes"])
    assets = list(edited.get("assets") or {})
    expressions = "; ".join(
        f"{key}: {_listed(list(item.get('sprites') or {}))}"
        for key, item in edited["characters"].items()
        if isinstance(item, dict)
    )
    reasons: dict[str, str] = {}
    for item in diagnostics:
        field = item.location.rsplit(".", 1)[-1]
        if field == "show" or ".show." in item.location:
            reasons[item.location] = (
                "each entry names a character and the name of one of their expressions, "
                f"not an asset id. Expressions: {expressions or 'none'}"
            )
        elif field in ("speaker", "character", "characters", "hide"):
            reasons[item.location] = (
                f"no character has this id. Characters: {_listed(characters)}. "
                "Leave out speaker for narration."
            )
        elif field in ("next", "target", "if_true", "if_false", "entry"):
            reasons[item.location] = f"no scene has this id. Scenes: {_listed(nodes)}"
        elif field in ("background", "cg", "audio", "asset") or item.code == "invalid_asset_kind":
            reasons[item.location] = (
                f"no asset of that kind has this id. Assets: {_listed(assets)}. "
                "A file still being generated has no id yet, so leave it out for now."
            )
        elif field in ("expression", "sprite"):
            reasons[item.location] = "this character has no such sprite; use one it lists"
        elif item.code == "invalid_voice":
            reasons[item.location] = (
                "a voice needs a speaker on this line, and only a vocalization has its own text"
            )
        elif item.code == "invalid_voice_line":
            reasons[item.location] = (
                "each line must be a line node spoken by this character, saved or added here"
            )
    return reasons


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
    earlier: Sequence[str] = (),
    voices: Mapping[str, str] | None = None,
    capabilities: Sequence[str] = (),
    attached: Sequence[str] = (),
    child_session: bool = False,
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
        earlier=earlier,
        voices=voices,
        capabilities=capabilities,
        attached=attached,
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
        schema = response_schema(child_session=child_session)
        answer = await model.respond(messages, schema, stream)
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
            parsed = _with_voice_actions(_with_tidied_nodes(story, parsed), capabilities)
            if child_session:
                # A provider without a grammar could still write one; it can only be refused.
                parsed = parsed.model_copy(
                    update={
                        "operations": [
                            item
                            for item in parsed.operations
                            if not isinstance(item, StartChildSession)
                        ]
                    }
                )
            check = check_proposal(story, parsed.operations)
            if check.diagnostics and attempt == calls:
                # Repairs are spent: keep the story edits if only actions are unusable.
                trimmed = _without_unusable_actions(story, parsed, check.diagnostics)
                if trimmed is not None:
                    parsed, dropped = trimmed[0], (*dropped, *trimmed[1])
                    check = check_proposal(story, parsed.operations)
            proposal = parsed
            diagnostics = check.diagnostics
            reasons = {**reasons, **_problem_reasons(story, parsed, diagnostics)}
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
