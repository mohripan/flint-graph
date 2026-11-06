"""Bounded story edit operations applied to a copy of a saved revision's story.

A proposal never regenerates the whole story: each operation replaces or removes
one record, so large projects stay reviewable and untouched text is preserved.
Results are checked with the same rules as a manual save before any review.
"""

import copy
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, model_validator

from flint_graph.narrative.package import STORY_LIMIT
from flint_graph.narrative.validation import ID, collect_story_diagnostics
from flint_graph.narrative.values import Diagnostic, PackageError, canonical_json

MAX_OPERATIONS = 64
_DISPLAY = {"line", "choice", "end"}
_Key = Annotated[str, Field(min_length=1, max_length=64)]
_Text = Annotated[str, Field(min_length=1, max_length=16384)]


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UpsertNode(_Operation):
    op: Literal["upsert_node"]
    id: _Key
    node: dict[str, Any]


class DeleteNode(_Operation):
    op: Literal["delete_node"]
    id: _Key


class UpsertCharacter(_Operation):
    op: Literal["upsert_character"]
    id: _Key
    name: _Text
    # Story format 2 (ADR 0040): optional; fields left out keep their saved values.
    color: str | None = None
    sprites: dict[str, str] | None = None
    stage: dict[str, int] | None = None


class DeleteCharacter(_Operation):
    op: Literal["delete_character"]
    id: _Key


class UpsertVariable(_Operation):
    op: Literal["upsert_variable"]
    id: _Key
    declaration: dict[str, Any]


class DeleteVariable(_Operation):
    op: Literal["delete_variable"]
    id: _Key


class SetEntry(_Operation):
    op: Literal["set_entry"]
    id: _Key


class SetTitle(_Operation):
    op: Literal["set_title"]
    title: _Text


class SetTheme(_Operation):
    """Replace the whole theme (story format 2); ``None`` removes it."""

    op: Literal["set_theme"]
    theme: dict[str, Any] | None


class AddAsset(_Operation):
    """A library file's story entry (kind, path, SHA-256); normally added by the worker."""

    op: Literal["add_asset"]
    id: _Key
    asset: dict[str, str]


_Appearance = Annotated[str, Field(min_length=1, max_length=600)]


def _renamed(data: Any, used: str, expected: str) -> Any:
    """Accept the other image action's field name when only that one was given.

    Local models sometimes write a character's look under the background action's
    ``description``, or a place under ``appearance``; the meaning is unambiguous.
    """
    if isinstance(data, dict) and expected not in data and isinstance(data.get(used), str):
        return {**{key: value for key, value in data.items() if key != used}, expected: data[used]}
    return data


class GenerateCharacterImages(_Operation):
    """An action, not an edit: the Studio offers it as a one-click portrait job."""

    op: Literal["generate_character_images"]
    character: _Key
    appearance: _Appearance
    character_type: Literal["girl", "boy", "woman", "man", "other"]
    framing: Literal["portrait", "full_body"] = "full_body"
    transparent: bool = False
    hires: bool = False

    @model_validator(mode="before")
    @classmethod
    def _cutout_is_full_body(cls, data: Any) -> Any:
        data = _renamed(data, "description", "appearance")
        # A transparent cut-out is a stage sprite, and those are always full-body.
        if isinstance(data, dict) and data.get("transparent") is True:
            return {**data, "framing": "full_body", "hires": data.get("hires", True)}
        return data


class GenerateBackgrounds(_Operation):
    """An action, not an edit: the Studio offers it as a one-click background job."""

    op: Literal["generate_backgrounds"]
    description: _Appearance

    @model_validator(mode="before")
    @classmethod
    def _place_is_a_description(cls, data: Any) -> Any:
        return _renamed(data, "appearance", "description")


_Expression = Annotated[str, Field(min_length=1, max_length=40)]


class GenerateExpressions(_Operation):
    """An action: repaint only the face of the character's approved picture (ADR 0041)."""

    op: Literal["generate_expressions"]
    character: _Key
    expressions: Annotated[list[_Expression], Field(min_length=1, max_length=4)]


class GenerateCg(_Operation):
    """An action: draw an event illustration from each character's approved picture."""

    op: Literal["generate_cg"]
    characters: Annotated[list[_Key], Field(min_length=1, max_length=2)]
    description: _Appearance

    @model_validator(mode="before")
    @classmethod
    def _scene_is_a_description(cls, data: Any) -> Any:
        return _renamed(data, "scene", "description")


class GenerateVoice(_Operation):
    """An action: speak saved lines of one character, one job and one clip per line."""

    op: Literal["generate_voice"]
    character: _Key
    lines: Annotated[list[_Key], Field(min_length=1, max_length=24)]
    # A stock voice for a character who has none yet; a chosen voice is never replaced.
    voice: str | None = None


ACTIONS = (
    GenerateCharacterImages,
    GenerateBackgrounds,
    GenerateExpressions,
    GenerateCg,
    GenerateVoice,
)

Operation = Annotated[
    UpsertNode
    | DeleteNode
    | UpsertCharacter
    | DeleteCharacter
    | UpsertVariable
    | DeleteVariable
    | SetEntry
    | SetTitle
    | SetTheme
    | AddAsset
    | GenerateCharacterImages
    | GenerateBackgrounds
    | GenerateExpressions
    | GenerateCg
    | GenerateVoice,
    Field(discriminator="op"),
]


def action_label(action: Any) -> str:
    """A short, plain description of an action for the thread log and the model."""
    if isinstance(action, GenerateBackgrounds):
        return f"backgrounds of {action.description[:80]}"
    if isinstance(action, GenerateExpressions):
        return f"{', '.join(action.expressions)} expressions of {action.character}"
    if isinstance(action, GenerateCg):
        return f"CGs of {' and '.join(action.characters)}: {action.description[:80]}"
    if isinstance(action, GenerateVoice):
        lines = len(action.lines)
        return f"voice for {lines} line{'' if lines == 1 else 's'} of {action.character}"
    if isinstance(action, GenerateCharacterImages):
        kind = "sprites" if action.transparent else "portraits"
        return f"{kind} of {action.character}"
    return "generation"


def action_needs_accept(story: dict[str, Any], operations: Sequence[Any], action: Any) -> bool:
    """Whether an action depends on what its own proposal adds to ``story``.

    Generating before acceptance is safe: results are only candidates. Generating for a
    character or line the story does not have yet is not possible, and a line the proposal
    rewrites must be spoken with its new words.
    """
    characters = story.get("characters") or {}
    if isinstance(action, GenerateCg):
        return any(character not in characters for character in action.characters)
    if isinstance(action, GenerateCharacterImages | GenerateExpressions):
        return action.character not in characters
    if isinstance(action, GenerateVoice):
        rewritten = {item.id for item in operations if isinstance(item, UpsertNode)}
        return action.character not in characters or bool(rewritten.intersection(action.lines))
    return False


def field_choices(op: str, field: str) -> tuple[str, ...]:
    """The allowed values of an operation field with a fixed set of choices, if any."""
    for kind in _Operation.__subclasses__():
        if get_args(kind.model_fields["op"].annotation) == (op,):
            info = kind.model_fields.get(field)
            if info is not None and get_origin(info.annotation) is Literal:
                return tuple(str(value) for value in get_args(info.annotation))
    return ()


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=400)
    operations: list[Operation] = Field(max_length=MAX_OPERATIONS)


@dataclass(frozen=True)
class StoryEdit:
    story: dict[str, Any]
    touched: tuple[str, ...]


@dataclass(frozen=True)
class ProposalCheck:
    """``story`` is set only when the edited story would pass a manual save."""

    story: dict[str, Any] | None
    diagnostics: tuple[Diagnostic, ...]
    warnings: tuple[Diagnostic, ...]
    touched: tuple[str, ...]


def _target(operation: Operation, index: int) -> str:
    if isinstance(operation, UpsertNode | DeleteNode):
        return "nodes." + operation.id
    if isinstance(operation, UpsertCharacter | DeleteCharacter):
        return "characters." + operation.id
    if isinstance(operation, UpsertVariable | DeleteVariable):
        return "variables." + operation.id
    if isinstance(operation, AddAsset):
        return "assets." + operation.id
    if isinstance(operation, GenerateCharacterImages):
        return f"actions.images.{operation.character}.{index}"
    if isinstance(operation, GenerateBackgrounds):
        return f"actions.backgrounds.{index}"
    if isinstance(operation, GenerateExpressions):
        return f"actions.expressions.{operation.character}.{index}"
    if isinstance(operation, GenerateCg):
        return f"actions.cg.{index}"
    if isinstance(operation, GenerateVoice):
        return f"actions.voice.{operation.character}.{index}"
    if isinstance(operation, SetTheme):
        return "theme"
    return "entry" if isinstance(operation, SetEntry) else "title"


def apply_operations(story: dict[str, Any], operations: Sequence[Operation]) -> StoryEdit:
    """Apply operations in order; each record may be targeted at most once."""
    if len(operations) > MAX_OPERATIONS:
        raise PackageError("operation_limit", "operations")
    if type(story) is not dict or any(
        type(story.get(key)) is not dict for key in ("nodes", "characters", "variables")
    ):
        raise PackageError("invalid_object", "story")
    result = copy.deepcopy(story)
    touched: set[str] = set()
    written: list[tuple[str, dict[str, Any]]] = []
    for index, operation in enumerate(operations):
        location = f"operations.{index}"
        target = _target(operation, index)
        if target in touched:
            raise PackageError("duplicate_target", location)
        touched.add(target)
        if isinstance(operation, ACTIONS):
            continue  # Image jobs start only when the creator chooses to.
        if isinstance(operation, UpsertNode):
            node = copy.deepcopy(operation.node)
            _inherit_text_ids(node, result["nodes"].get(operation.id))
            _keep_voice(node, result["nodes"].get(operation.id))
            result["nodes"][operation.id] = node
            written.append((operation.id, node))
        elif isinstance(operation, UpsertCharacter):
            # Fields left out keep their saved values (v2 sprites, colour and framing).
            existing = result["characters"].get(operation.id)
            kept = dict(existing) if isinstance(existing, dict) else {}
            changed = {
                field: copy.deepcopy(value)
                for field in ("color", "sprites", "stage")
                if (value := getattr(operation, field)) is not None
            }
            result["characters"][operation.id] = {**kept, "name": operation.name, **changed}
        elif isinstance(operation, SetTheme):
            if operation.theme is None:
                result.pop("theme", None)
            else:
                result["theme"] = copy.deepcopy(operation.theme)
        elif isinstance(operation, AddAsset):
            result.setdefault("assets", {})[operation.id] = dict(operation.asset)
        elif isinstance(operation, UpsertVariable):
            result["variables"][operation.id] = copy.deepcopy(operation.declaration)
        elif isinstance(operation, SetEntry):
            result["entry"] = operation.id
        elif isinstance(operation, SetTitle):
            result["title"] = operation.title
        else:
            collection = target.split(".", 1)[0]
            if operation.id not in result[collection]:
                raise PackageError("unknown_target", location)
            del result[collection][operation.id]
    _derive_text_ids(result, written)
    return StoryEdit(result, tuple(sorted(touched)))


def check_proposal(
    story: dict[str, Any], operations: Sequence[Operation], *, limit: int = 50
) -> ProposalCheck:
    """Apply and validate without raising, for review and bounded model repair."""
    try:
        edit = apply_operations(story, operations)
    except PackageError as error:
        return ProposalCheck(None, (Diagnostic(error.code, error.location),), (), ())
    diagnostics, warnings = collect_story_diagnostics(edit.story, limit=limit)
    if not diagnostics and len(canonical_json(edit.story)) > STORY_LIMIT:
        diagnostics = (Diagnostic("size_limit", "story.json"),)
    diagnostics = (*diagnostics, *_action_problems(edit.story, operations))
    if diagnostics:
        return ProposalCheck(None, diagnostics, (), edit.touched)
    return ProposalCheck(edit.story, (), warnings, edit.touched)


def _action_problems(story: dict[str, Any], operations: Sequence[Operation]) -> list[Diagnostic]:
    """Actions must name what the edited story has, so the model can fix them now."""
    problems: list[Diagnostic] = []
    characters, nodes = story["characters"], story["nodes"]
    for index, operation in enumerate(operations):
        location = f"operations.{index}"
        if isinstance(operation, GenerateCharacterImages | GenerateExpressions | GenerateVoice):
            if operation.character not in characters:
                problems.append(Diagnostic("unknown_reference", f"{location}.character"))
                continue
        if isinstance(operation, GenerateCg) and any(
            character not in characters for character in operation.characters
        ):
            problems.append(Diagnostic("unknown_reference", f"{location}.characters"))
        if isinstance(operation, GenerateVoice) and any(
            type(nodes.get(line)) is not dict
            or nodes[line].get("type") != "line"
            or nodes[line].get("speaker") != operation.character
            for line in operation.lines
        ):
            problems.append(Diagnostic("invalid_voice_line", f"{location}.lines"))
    return problems


def _keep_voice(node: Any, previous: Any) -> None:
    """Rewriting a voiced line keeps its voice (ADR 0043). A line rewritten for the same speaker
    without ``voice`` keeps the old one, and an unchanged line keeps its clip."""
    if (
        not isinstance(node, dict)
        or not isinstance(previous, dict)
        or node.get("type") != previous.get("type")
        or node.get("type") != "line"
        or "voice" not in previous
        or node.get("speaker") != previous.get("speaker")
    ):
        return
    if "voice" not in node:
        node["voice"] = copy.deepcopy(previous["voice"])
        return
    voice, earlier = node["voice"], previous["voice"]
    if (
        isinstance(voice, dict)
        and isinstance(earlier, dict)
        and "audio" not in voice
        and "audio" in earlier
        and voice.get("mode") == earlier.get("mode")
        and voice.get("text") == earlier.get("text")
        and node.get("text") == previous.get("text")
    ):
        voice["audio"] = earlier["audio"]


def _inherit_text_ids(node: dict[str, Any], previous: Any) -> None:
    # Stable text IDs keep saves and future translations attached to replaced text.
    if type(previous) is not dict:
        return
    if node.get("type") in _DISPLAY and "text_id" not in node and "text_id" in previous:
        node["text_id"] = previous["text_id"]
    options, earlier = node.get("options"), previous.get("options")
    if node.get("type") != "choice" or type(options) is not list or type(earlier) is not list:
        return
    known = {
        option.get("id"): option["text_id"]
        for option in earlier
        if type(option) is dict and "text_id" in option
    }
    for option in options:
        if type(option) is dict and "text_id" not in option and option.get("id") in known:
            option["text_id"] = known[option["id"]]


def _derive_text_ids(story: dict[str, Any], written: list[tuple[str, dict[str, Any]]]) -> None:
    used: set[str] = set()
    for node in story["nodes"].values():
        if type(node) is not dict:
            continue
        if type(node.get("text_id")) is str:
            used.add(node["text_id"])
        for option in node.get("options") or ():
            if type(option) is dict and type(option.get("text_id")) is str:
                used.add(option["text_id"])

    def fresh(preferred: str, seed: str) -> str:
        candidate = preferred if ID.fullmatch(preferred) and preferred not in used else ""
        attempt = 0
        while not candidate or candidate in used:
            candidate = "t" + hashlib.sha256(f"{seed}:{attempt}".encode()).hexdigest()[:24]
            attempt += 1
        used.add(candidate)
        return candidate

    for node_id, node in written:
        if node.get("type") in _DISPLAY and "text_id" not in node:
            node["text_id"] = fresh(f"{node_id}_text", node_id)
        options = node.get("options")
        if node.get("type") == "choice" and type(options) is list:
            for option in options:
                if type(option) is dict and "text_id" not in option:
                    option_id = str(option.get("id"))
                    option["text_id"] = fresh(
                        f"{node_id}_{option_id}_option", f"{node_id}:{option_id}"
                    )
