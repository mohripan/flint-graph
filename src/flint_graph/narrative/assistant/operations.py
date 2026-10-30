"""Bounded story edit operations applied to a copy of a saved revision's story.

A proposal never regenerates the whole story: each operation replaces or removes
one record, so large projects stay reviewable and untouched text is preserved.
Results are checked with the same rules as a manual save before any review.
"""

import copy
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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


Operation = Annotated[
    UpsertNode
    | DeleteNode
    | UpsertCharacter
    | DeleteCharacter
    | UpsertVariable
    | DeleteVariable
    | SetEntry
    | SetTitle,
    Field(discriminator="op"),
]


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


def _target(operation: Operation) -> str:
    if isinstance(operation, UpsertNode | DeleteNode):
        return "nodes." + operation.id
    if isinstance(operation, UpsertCharacter | DeleteCharacter):
        return "characters." + operation.id
    if isinstance(operation, UpsertVariable | DeleteVariable):
        return "variables." + operation.id
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
        target = _target(operation)
        if target in touched:
            raise PackageError("duplicate_target", location)
        touched.add(target)
        if isinstance(operation, UpsertNode):
            node = copy.deepcopy(operation.node)
            _inherit_text_ids(node, result["nodes"].get(operation.id))
            result["nodes"][operation.id] = node
            written.append((operation.id, node))
        elif isinstance(operation, UpsertCharacter):
            result["characters"][operation.id] = {"name": operation.name}
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
    if diagnostics:
        return ProposalCheck(None, diagnostics, (), edit.touched)
    return ProposalCheck(edit.story, (), warnings, edit.touched)


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
