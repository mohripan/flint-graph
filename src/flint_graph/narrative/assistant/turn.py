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
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from flint_graph.narrative.assistant.assets import LibraryEntry, add_library_assets
from flint_graph.narrative.assistant.context import HistoryTurn, build_turn_messages
from flint_graph.narrative.assistant.operations import (
    ACTIONS,
    AddAsset,
    DeleteNode,
    GenerateBackgrounds,
    GenerateCg,
    GenerateCharacterImages,
    GenerateExpressions,
    GenerateMusic,
    GenerateVoice,
    Proposal,
    SetEntry,
    SetPlayer,
    SetTheme,
    SetTitle,
    SetTitleScreen,
    StartChildSession,
    UpsertCharacter,
    UpsertNode,
    UpsertVariable,
    apply_operations,
    check_proposal,
    field_choices,
)
from flint_graph.narrative.assistant.prompts import prompt_sha256, response_schema
from flint_graph.narrative.assistant.stream import ReplyScanner
from flint_graph.narrative.pictures import CODE as PICTURE_CODE
from flint_graph.narrative.pictures import picture_diagnostics, without_pictures
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


def _usual_face(sprites: Mapping[str, str]) -> str:
    """The first approved image is "default"; stories from before that may call it "neutral"."""
    return next((name for name in ("default", "neutral") if name in sprites), next(iter(sprites)))


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
    for field in ("show", "hide"):
        if node.get(field) == []:
            del changed[field]  # Models write an empty list to mean none, which is not allowed.
    for field in ("background", "cg", "music", "ambience", "sound"):
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
                elif wanted not in own and own and wanted in ("default", "neutral"):
                    entry = {**entry, "sprite": _usual_face(own)}
                elif wanted not in own and wanted in pending.get(character, ()) and own:
                    # An expression still being generated: the usual face until it is approved.
                    entry = {**entry, "sprite": _usual_face(own)}
                elif not own and character in sprites:
                    continue  # Someone with no pictures cannot be shown yet, whatever was asked.
            entries.append(entry)
        if entries:
            changed["show"] = entries
        else:
            changed.pop("show", None)
    return changed


_STAGE_CHANGES = ("background", "cg", "show", "hide", "effect", "music", "ambience", "sound")


def _repointed(node: dict[str, Any], gone: Mapping[str, str]) -> dict[str, Any]:
    """Point a node past the steps that were left out."""

    def past(target: Any) -> Any:
        seen = set()
        while target in gone and target not in seen:
            seen.add(target)
            target = gone[target]
        return target

    changed = {
        key: past(value) if key in ("next", "if_true", "if_false") else value
        for key, value in node.items()
    }
    if isinstance(node.get("options"), list):
        changed["options"] = [
            {**option, "target": past(option.get("target"))}
            if isinstance(option, dict) and "target" in option
            else option
            for option in node["options"]
        ]
    return changed


def _without_blanks(theme: dict[str, Any]) -> dict[str, Any]:
    """Models write null for what they mean to leave alone; only a font's asset can be null."""
    tidied = {}
    for part, section in theme.items():
        if isinstance(section, dict):
            section = {k: v for k, v in section.items() if v is not None or k == "asset"}
            if not section:
                continue
        tidied[part] = section
    return tidied


def _tidied_variable(item: UpsertVariable) -> UpsertVariable:
    """An enum's first value not in its list is plainly meant to be one of them."""
    declaration = item.declaration
    values = declaration.get("values")
    initial = declaration.get("initial")
    if declaration.get("type") != "enum" or not isinstance(values, list) or initial in values:
        return item
    return item.model_copy(update={"declaration": {**declaration, "values": [initial, *values]}})


def _with_tidied_nodes(
    story: dict[str, Any], proposal: Proposal, library: Sequence[LibraryEntry] = ()
) -> Proposal:
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
        for field, kind in (
            ("background", GenerateBackgrounds),
            ("cg", GenerateCg),
            ("music", GenerateMusic),
            ("ambience", GenerateMusic),
        )
        if any(isinstance(item, kind) for item in proposal.operations)
    }
    # With no file of a kind at all, an ID for one is made up and nothing could correct it.
    have = {
        (asset.get("kind") if isinstance(asset, dict) else asset.kind)
        for asset in (story.get("assets") or {}).values()
    } | {item.asset.get("kind") for item in proposal.operations if isinstance(item, AddAsset)}
    have |= {entry.kind for entry in library}
    for fields, wanted in (
        (("background", "cg"), "image"),
        (("music", "ambience"), "music"),
        (("sound",), "audio"),
    ):
        if wanted not in have:
            generating.update(fields)
    pending: dict[str, set[str]] = {}
    for item in proposal.operations:
        if isinstance(item, GenerateExpressions):
            pending.setdefault(item.character, set()).update(item.expressions)
    operations: list[Any] = []
    # A title screen waiting on a file still being generated keeps the rest of its choice.
    title_fields = {"background": GenerateBackgrounds, "music": GenerateMusic}
    # Steps that had nothing left to do, and where each one led.
    gone: dict[str, str] = {}
    for item in proposal.operations:
        if isinstance(item, UpsertVariable):
            item = _tidied_variable(item)
        if isinstance(item, UpsertNode):
            kind = item.node.get("type")
            if kind == "line":
                node = _tidied_line(item.node, known, assets)
                face = sprites.get(str(node.get("speaker"))) or {}
                asked = node.get("expression")
                if face and asked not in face and asked in ("default", "neutral"):
                    node = {**node, "expression": _usual_face(face)}
                item = item.model_copy(update={"node": node})
            elif kind == "stage":
                node = _tidied_stage(item.node, sprites, assets, generating, pending)
                target = node.get("next")
                if isinstance(target, str) and not any(key in node for key in _STAGE_CHANGES):
                    # It only played a file still being generated, so there is no step yet. What
                    # this proposal leads into it goes straight on; a saved scene stays as it was.
                    gone[item.id] = target
                    continue
                item = item.model_copy(update={"node": node})
        elif isinstance(item, SetTheme) and item.theme is not None:
            item = item.model_copy(update={"theme": _without_blanks(item.theme)})
        elif isinstance(item, SetTitleScreen):
            kept = {
                field: getattr(item, field)
                for field in item.model_fields_set - {"op"}
                if getattr(item, field) is None
                or getattr(item, field) in assets
                or not any(isinstance(other, title_fields[field]) for other in proposal.operations)
            }
            if not kept:
                continue
            item = SetTitleScreen(op="set_title_screen", **kept)
        operations.append(item)
    if gone:
        operations = [
            item.model_copy(update={"node": _repointed(item.node, gone)})
            if isinstance(item, UpsertNode)
            else item.model_copy(update={"id": _repointed({"next": item.id}, gone)["next"]})
            if isinstance(item, SetEntry)
            else item
            for item in operations
        ]
    return proposal.model_copy(update={"operations": operations})


def _with_player(story: dict[str, Any], proposal: Proposal) -> Proposal:
    """Asking for a name, or writing {name}, only works in a story with a player, and local
    models often write the node and forget the rest. The name's default is theirs to change."""
    if story.get("schema_version") != "2" or story.get("player"):
        return proposal

    def uses_name(node: dict[str, Any]) -> bool:
        texts = [node.get("text"), *(option.get("text") for option in node.get("options", []))]
        return node.get("type") == "name" or any(
            isinstance(text, str) and "{name}" in text for text in texts
        )

    operations = list(proposal.operations)
    chosen = any(isinstance(item, SetPlayer) for item in operations)
    if not chosen and not any(
        isinstance(item, UpsertNode) and uses_name(item.node) for item in operations
    ):
        return proposal
    if not chosen:
        operations.insert(0, SetPlayer(op="set_player", default_name="Alex"))
    # A name nobody is asked for is only ever the default, so ask first, before the story starts.
    asked = any(node.get("type") == "name" for node in (story.get("nodes") or {}).values()) or any(
        isinstance(item, UpsertNode) and item.node.get("type") == "name" for item in operations
    )
    if not asked:
        entries = [item for item in operations if isinstance(item, SetEntry)]
        first = entries[0].id if entries else story["entry"]
        known = set(story.get("nodes") or {}) | {
            item.id for item in operations if isinstance(item, UpsertNode)
        }
        key = next(
            name
            for name in ("ask_name", *(f"ask_name_{number}" for number in range(2, 99)))
            if name not in known
        )
        node = {"type": "name", "text": "What is your name?", "next": first}
        operations = [item for item in operations if not isinstance(item, SetEntry)]
        operations.append(UpsertNode(op="upsert_node", id=key, node=node))
        operations.append(SetEntry(op="set_entry", id=key))
    return proposal.model_copy(update={"operations": operations})


# What a new project holds before anyone has written a word (narrative_projects.py).
_STARTER_TEXTS = {"A new story begins.", "To be continued."}


def _joined_to_the_start(story: dict[str, Any], proposal: Proposal) -> Proposal:
    """A first story written beside the blank starter, which still leads straight to its end:
    the game would never reach a word of it. With one clear place to begin, begin there, and
    let go of the starter's scenes the story does not use. A creator's own words are left alone."""
    starter = story.get("nodes") or {}
    if len(starter) > 2 or any(node.get("text") not in _STARTER_TEXTS for node in starter.values()):
        return proposal
    written = {item.id: item.node for item in proposal.operations if isinstance(item, UpsertNode)}
    added = {key: node for key, node in written.items() if key not in starter}
    if not added:
        return proposal

    def targets(node: dict[str, Any]) -> list[Any]:
        return [
            *(node.get(field) for field in ("next", "if_true", "if_false")),
            *(option.get("target") for option in node.get("options", [])),
        ]

    operations: list[Any] = list(proposal.operations)
    entries = [item for item in operations if isinstance(item, SetEntry)]
    start = entries[0].id if entries else story["entry"]
    if start not in added and len(added) == len(written):
        led_to = {target for node in added.values() for target in targets(node)}
        roots = [key for key in added if key not in led_to]
        if len(roots) != 1:
            return proposal
        start = roots[0]
        operations = [item for item in operations if not isinstance(item, SetEntry)]
        operations.append(SetEntry(op="set_entry", id=start))
    nodes = {**starter, **written}
    if start not in nodes:
        return proposal  # A wrong entry is for validation to report.
    reached: set[Any] = set()
    pending = [start]
    while pending:
        key = pending.pop()
        if key in nodes and key not in reached:
            reached.add(key)
            pending.extend(targets(nodes[key]))
    # Only a story that stands on its own can let go. With a broken link or no ending yet, what is
    # wrong is for validation to say, without a missing ending we would have caused ourselves.
    complete = any(nodes[key].get("type") == "end" for key in reached) and all(
        target in nodes for key in reached for target in targets(nodes[key]) if target is not None
    )
    stray = set(starter) - reached if complete else set()
    operations = [
        item
        for item in operations
        if not (isinstance(item, UpsertNode | DeleteNode) and item.id in stray)
    ]
    operations.extend(DeleteNode(op="delete_node", id=key) for key in sorted(stray))
    return proposal.model_copy(update={"operations": operations})


_TAKES_OFF_STAGE = re.compile(
    r"\b(remove|removes|hide|hides|leave|leaves|leaving|exit|exits|gone|disappear|disappears"
    r"|without|nobody|no one|alone|empty|off (?:the )?(?:stage|screen)|take\b.*\boff)\b",
    re.I,
)


def _keeps_who_is_on_stage(story: dict[str, Any], proposal: Proposal, request: str) -> Proposal:
    """A rewrite replaces the whole step, and models rewriting one for another reason leave out
    who is on it. Asked to bring someone closer, one took them out of the scene altogether."""
    if _TAKES_OFF_STAGE.search(request):
        return proposal
    nodes = story.get("nodes") or {}
    operations = []
    for item in proposal.operations:
        if isinstance(item, UpsertNode) and item.node.get("type") == "stage":
            saved = (nodes.get(item.id) or {}).get("show") or []
            shown = [entry for entry in item.node.get("show") or [] if isinstance(entry, dict)]
            named = {entry.get("character") for entry in shown} | set(item.node.get("hide") or [])
            taken = {entry.get("position") for entry in shown}
            back = [
                entry
                for entry in saved
                if isinstance(entry, dict)
                and entry.get("character") not in named
                and entry.get("position") not in taken
            ]
            if back:
                item = item.model_copy(update={"node": {**item.node, "show": [*back, *shown]}})
        operations.append(item)
    return proposal.model_copy(update={"operations": operations})


def _pictures_first(
    proposal: Proposal, edited: dict[str, Any], missing: Sequence[tuple[str, str]]
) -> tuple[Proposal | None, str]:
    """What survives of a scene for someone with no picture: them, and the card to draw them. Told
    three times, the live model still wrote the scene beside the card, so asking again only ends
    in a proposal nobody can accept. The scene waits, and the reply says what to do next."""
    kept = [
        item
        for item in proposal.operations
        if isinstance(
            item, UpsertCharacter | GenerateCharacterImages | GenerateBackgrounds | SetTitle
        )
    ]
    offered = {item.character for item in kept if isinstance(item, GenerateCharacterImages)}
    wanted = sorted({name for _, name in missing})
    people = [str((edited["characters"].get(name) or {}).get("name") or name) for name in wanted]
    listed = people[0] if len(people) == 1 else ", ".join(people[:-1]) + f" and {people[-1]}"
    if set(wanted) <= offered:
        step = (
            "Press Generate on the card below and approve a picture, then ask me for the scene "
            "again and I'll write it."
        )
    else:
        step = "Ask me to make a picture first, then ask for the scene again and I'll write it."
    reply = f"{listed} needs an approved picture before appearing in a scene. {step}"
    return (proposal.model_copy(update={"operations": kept}) if kept else None), reply


def _with_library_sprites(
    story: dict[str, Any], proposal: Proposal, library: Sequence[LibraryEntry]
) -> Proposal:
    """A character needs a picture attached to be shown at all, and approving one does not attach
    it. A real thread wrote a scene for someone with four approved sprites and showed nobody."""
    if story.get("schema_version") != "2":
        return proposal
    characters = story.get("characters") or {}
    upserted = {item.id: item for item in proposal.operations if isinstance(item, UpsertCharacter)}
    wanted: set[str] = set()
    for item in proposal.operations:
        if isinstance(item, UpsertNode):
            speaker = item.node.get("speaker")
            if isinstance(speaker, str):
                wanted.add(speaker)
            for entry in item.node.get("show") or []:
                if isinstance(entry, dict) and isinstance(entry.get("character"), str):
                    wanted.add(entry["character"])
    operations = list(proposal.operations)
    for character in sorted(wanted):
        chosen = upserted.get(character)
        saved = characters.get(character)
        if (chosen is None and not isinstance(saved, dict)) or (chosen and chosen.sprites):
            continue
        if isinstance(saved, dict) and saved.get("sprites"):
            continue
        # A cut-out stands on the stage properly, so it beats a portrait with a background.
        pictures = [
            entry
            for kind in ("sprite", "character_portrait")
            for entry in library
            if entry.character_id == character and entry.library_kind == kind
        ]
        if not pictures:
            continue
        sprites = {"default": pictures[0].key}
        if chosen is not None:
            at = operations.index(chosen)
            operations[at] = chosen.model_copy(update={"sprites": sprites})
        else:
            assert isinstance(saved, dict)
            operations.append(
                UpsertCharacter(
                    op="upsert_character", id=character, name=saved["name"], sprites=sprites
                )
            )
    return proposal.model_copy(update={"operations": operations})


_POSITIONS = ("center", "left", "right")
_STAGING_ROUNDS = 16


def _targets(node: dict[str, Any]) -> list[str]:
    found = [node.get(field) for field in ("next", "if_true", "if_false")]
    found += [option.get("target") for option in node.get("options") or []]
    return [target for target in found if isinstance(target, str)]


def _on_arrival(nodes: Mapping[str, Any], entry: Any) -> dict[str, dict[str, str]]:
    """Who is on stage arriving at each step, and where. Someone counts only if every route leaves
    them there, and the answer can only shrink as routes are found, so this settles."""
    if entry not in nodes:
        return {}
    reached: dict[str, dict[str, str]] = {entry: {}}
    queue = deque([entry])
    while queue:
        key = queue.popleft()
        node = nodes[key]
        after = dict(reached[key])
        if node.get("type") == "stage":
            for name in node.get("hide") or []:
                after.pop(name, None)
            for shown in node.get("show") or []:
                # A place holds one person, so whoever stood there has gone.
                after = {k: v for k, v in after.items() if v != shown.get("position")}
                after[shown.get("character")] = shown.get("position")
        for target in _targets(node):
            if target not in nodes:
                continue
            known = reached.get(target)
            merged = after if known is None else {k: v for k, v in known.items() if k in after}
            if known is None or merged != known:
                reached[target] = merged
                queue.append(target)
    return reached


def _with_speakers_on_stage(story: dict[str, Any], proposal: Proposal, request: str) -> Proposal:
    """Who speaks a new line, and has a picture to show, is on stage for it. The model forgets, and
    the game then plays their words over an empty stage. Only new lines: rewording a saved one
    says nothing about the stage, and someone hidden or asked to be absent stays that way."""
    if _TAKES_OFF_STAGE.search(request):
        return proposal
    try:
        edited = apply_operations(story, proposal.operations).story
    except PackageError:
        return proposal  # The check reports the operation problem itself.
    saved = story.get("nodes") or {}
    written = {item.id for item in proposal.operations if isinstance(item, UpsertNode)}
    nodes: dict[str, Any] = dict(edited["nodes"])
    entry = edited.get("entry")
    characters = edited.get("characters") or {}
    hidden = {
        name
        for key in written
        if nodes.get(key, {}).get("type") == "stage"
        for name in nodes[key].get("hide") or []
    }
    changed: set[str] = set()
    full: set[str] = set()
    for _ in range(_STAGING_ROUNDS):
        arrival = _on_arrival(nodes, entry)
        found = None
        for key, there in arrival.items():
            node = nodes[key]
            speaker = node.get("speaker") if node.get("type") == "line" else None
            sprites = (characters.get(speaker) or {}).get("sprites") if speaker else None
            if (
                sprites
                and key in written
                and key not in saved
                and speaker not in hidden
                and speaker not in full
                and speaker not in there
            ):
                found = key, str(speaker), sprites
                break
        if found is None:
            break
        key, speaker, sprites = found
        into: dict[str, list[str]] = {}
        for name, node in nodes.items():
            for target in _targets(node):
                into.setdefault(target, []).append(name)
        # The step this proposal wrote for the scene, if a single path leads from it to the line.
        step = None
        at = key
        for _ in range(len(nodes)):
            before = into.get(at) or []
            if len(before) != 1:
                break
            at = before[0]
            if nodes[at].get("type") == "stage":
                step = at if at in written else None
                break
        standing = arrival.get(step, {}) if step else arrival[key]
        shown_there = nodes[step].get("show") or [] if step else []
        taken = set(standing.values()) | {shown.get("position") for shown in shown_there}
        place = next((slot for slot in _POSITIONS if slot not in taken), None)
        if place is None:
            full.add(speaker)  # Who should leave is the creator's choice.
            continue
        wearing = nodes[key].get("expression")
        if wearing not in sprites:
            wearing = _usual_face(sprites)
        arriving = {"character": speaker, "sprite": wearing, "position": place}
        if step is not None:
            nodes[step] = {**nodes[step], "show": [*shown_there, arriving]}
            changed.add(step)
            continue
        added = f"{key}_stage"
        number = 2
        while added in nodes:
            added, number = f"{key}_stage_{number}", number + 1
        for name in into.get(key) or []:
            nodes[name] = _repointed(nodes[name], {key: added})
            changed.add(name)
        nodes[added] = {"type": "stage", "show": [arriving], "next": key}
        changed.add(added)
        if entry == key:
            entry = added
    if not changed and entry == edited.get("entry"):
        return proposal
    operations: list[Any] = [
        item.model_copy(update={"node": nodes[item.id]})
        if isinstance(item, UpsertNode) and item.id in changed
        else item
        for item in proposal.operations
    ]
    operations.extend(
        UpsertNode(op="upsert_node", id=key, node=nodes[key]) for key in sorted(changed - written)
    )
    if entry != edited.get("entry"):
        # An operation names its target once, so one already moving the start is changed instead.
        operations = [item for item in operations if not isinstance(item, SetEntry)]
        operations.append(SetEntry(op="set_entry", id=entry))
    return proposal.model_copy(update={"operations": operations})


def _without_stage_copies(story: dict[str, Any], proposal: Proposal) -> Proposal:
    """A real thread rewrote a step, then added an exact copy that nothing led to. A new step that
    is merely unlinked stays, because the creator asked for it and the warning can say so."""
    saved = story.get("nodes") or {}
    written = {item.id: item.node for item in proposal.operations if isinstance(item, UpsertNode)}
    nodes = {**saved, **written}
    led_to: set[Any] = set()
    for node in nodes.values():
        led_to.update(node.get(field) for field in ("next", "if_true", "if_false"))
        led_to.update(option.get("target") for option in node.get("options", []))
    led_to.update(item.id for item in proposal.operations if isinstance(item, SetEntry))
    led_to.add(story.get("entry"))
    copies = {
        key
        for key, node in written.items()
        if key not in saved
        and node.get("type") == "stage"
        and key not in led_to
        and any(other == node for name, other in nodes.items() if name != key)
    }
    operations = [
        item
        for item in proposal.operations
        if not (isinstance(item, UpsertNode) and item.id in copies)
    ]
    return proposal.model_copy(update={"operations": operations})


def _without_no_ops(story: dict[str, Any], proposal: Proposal) -> Proposal:
    """Writing out a character or scene unchanged is not an edit. Left in, it reads as a change,
    asks to be accepted, and saves a revision identical to the one before."""
    operations = []
    for item in proposal.operations:
        if isinstance(item, UpsertCharacter | UpsertNode | UpsertVariable | SetEntry | SetTitle):
            try:
                if apply_operations(story, [item]).story == story:
                    continue
            except PackageError:
                pass  # For validation to report.
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


_PROMISE = re.compile(
    r"\b(?:i'll|i will|i'm going to|i am going to|let me)\s+(?:\w+\s+)?"
    r"(?:create|write|add|set|make|draft|put|start|get|prepare|build)\b",
    re.I,
)


def _promised_work(reply: str) -> bool:
    """It says what it will do and proposes nothing: the creator is left waiting for work that
    is not coming, and the message has already been paid for."""
    return _PROMISE.search(reply) is not None


_ASKS_LOOKS = re.compile(
    r"\b(look like|looks like|wear|wearing|clothes|outfit|hair|sprite|portrait|visual)\b", re.I
)
# Asking about pictures, or designing someone, is when how they look is a fair question.
_WANTS_LOOKS = re.compile(
    r"\b(picture|pictures|image|images|sprite|sprites|portrait|portraits|draw|art|look|looks"
    r"|character|characters|hair|eyes|outfit|outfits|clothes|wear|wearing)\b",
    re.I,
)


def _wrongly_asks_about_looks(request: str, reply: str) -> bool:
    """The creator asked for writing, and the model asks what people wear instead. Told not to,
    it still does: a small model follows its examples of asking more than this exception."""
    return _ASKS_LOOKS.search(reply) is not None and _WANTS_LOOKS.search(request) is None


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
    story: dict[str, Any],
    proposal: Proposal,
    diagnostics: Sequence[Diagnostic],
    library: Sequence[LibraryEntry] = (),
    capabilities: Sequence[str] = (),
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
        if item.code == PICTURE_CODE:
            reasons[item.location] = (
                "this character has no approved picture yet, so they cannot speak or be on stage. "
                "Write no lines for them. Propose upsert_character with their name and one "
                "generate_character_images action, and say you will write the scene as soon as the "
                "creator approves a picture. Scenes without them may stay."
            )
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
        elif field in ("music", "ambience", "sound"):
            wanted = "audio" if field == "sound" else "music"
            files = [
                key
                for key, asset in (edited.get("assets") or {}).items()
                if isinstance(asset, dict) and asset.get("kind") == wanted
            ] + [entry.key for entry in library if entry.kind == wanted]
            otherwise = (
                "add a generate_music action"
                if wanted == "music" and "music" in capabilities
                else "tell the creator to upload one in Assets"
            )
            reasons[item.location] = (
                f"no file of that kind has this id. Files you can use: {_listed(files)}. "
                f'If none fits, leave out "{field}" and {otherwise}.'
            )
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
        schema = response_schema(child_session=child_session, music="music" in capabilities)
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
                story,
                add_library_assets(story, _with_library_sprites(story, parsed, library), library),
                dropped_for,
            )
            parsed = _keeps_who_is_on_stage(story, _without_stage_copies(story, parsed), request)
            parsed = _with_voice_actions(_with_tidied_nodes(story, parsed, library), capabilities)
            # The question goes before wherever the story begins, so find that first.
            parsed = _with_speakers_on_stage(story, _joined_to_the_start(story, parsed), request)
            parsed = _with_player(story, parsed)
            parsed = _without_no_ops(story, parsed)
            # A provider without a grammar could still write these; they can only be refused.
            refused: tuple[type, ...] = (StartChildSession,) if child_session else ()
            if "music" not in capabilities:
                refused = (*refused, GenerateMusic)
            if refused:
                parsed = parsed.model_copy(
                    update={
                        "operations": [
                            item for item in parsed.operations if not isinstance(item, refused)
                        ]
                    }
                )
            if not parsed.operations:
                parsed = None  # Nothing was left to propose, so the reply stands alone.
        if parsed is not None:
            check = check_proposal(story, parsed.operations)
            if check.diagnostics and attempt == calls:
                # Repairs are spent: keep the story edits if only actions are unusable.
                trimmed = _without_unusable_actions(story, parsed, check.diagnostics)
                if trimmed is not None:
                    parsed, dropped = trimmed[0], (*dropped, *trimmed[1])
                    check = check_proposal(story, parsed.operations)
            missing = without_pictures(story, check.story) if check.story is not None else []
            offered = {
                item.character
                for item in parsed.operations
                if isinstance(item, GenerateCharacterImages)
            }
            if missing and (attempt == calls or {name for _, name in missing} <= offered):
                # With the card already offered there is nothing a repair could add.
                assert check.story is not None
                parsed, reply = _pictures_first(parsed, check.story, missing)
                if parsed is not None:
                    check = check_proposal(story, parsed.operations)
                missing = []
            proposal = parsed
            diagnostics = () if parsed is None else check.diagnostics
            if parsed is not None and check.story is not None and missing:
                diagnostics = (*diagnostics, *picture_diagnostics(story, check.story))
            if parsed is not None:
                reasons = {
                    **reasons,
                    **_problem_reasons(story, parsed, diagnostics, library, capabilities),
                }
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
        if parsed is None and not diagnostics and attempt < calls:
            if _wrongly_asks_about_looks(request, reply):
                diagnostics = (Diagnostic("no_proposal", "proposal"),)
                reasons = {
                    "proposal": "the creator asked for writing, so do not ask how anyone looks or "
                    "what they wear. Write every scene now for characters with an approved "
                    "picture. For anyone without one, propose upsert_character and one "
                    "generate_character_images action, choosing their look yourself and saying "
                    "what you chose, and say their scenes can follow once a picture is approved."
                }
            elif _promised_work(reply):
                diagnostics = (Diagnostic("no_proposal", "proposal"),)
                reasons = {
                    "proposal": "your reply says what you will do, but the proposal is null. "
                    "Write the whole proposal now, or ask your question if you truly cannot."
                }
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
