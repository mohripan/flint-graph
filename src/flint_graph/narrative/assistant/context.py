"""Bounded, focus-first story context for one assistant turn.

The model sees one saved revision of the current project only: a compact outline
of every scene that fits the budget (nearest the focus scene first), full JSON for
the focus scene and its neighbors, and a few earlier turns of the same thread.
Story text is data: it is delimited and escaped so it cannot close the delimiter.
"""

import json
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from flint_graph.narrative.assistant.assets import LibraryEntry, LibraryRow
from flint_graph.narrative.assistant.prompts import system_prompt
from flint_graph.narrative.voices import VOICES
from flint_graph.prompts.source import render

HISTORY_TURNS = 8
HISTORY_CHARS = 2000
REQUEST_CHARS = 8000
SNIPPET_CHARS = 80
NEIGHBORS = 8
_OMISSION_RESERVE = 80


@dataclass(frozen=True)
class HistoryTurn:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class ContextStats:
    """Counts shown to the creator while a turn reads the story; IDs only, no text."""

    scenes: int
    outlined: int
    focus: str | None
    history: int


def build_messages(
    story: dict[str, Any],
    request: str,
    *,
    focus: str | None = None,
    history: Sequence[HistoryTurn] = (),
    budget: int = 32000,
) -> list[dict[str, str]]:
    return build_turn_messages(story, request, focus=focus, history=history, budget=budget)[0]


def build_turn_messages(
    story: dict[str, Any],
    request: str,
    *,
    focus: str | None = None,
    history: Sequence[HistoryTurn] = (),
    budget: int = 32000,
    library: Sequence[LibraryEntry] = (),
    profiles: Mapping[str, str] | None = None,
    earlier: Sequence[str] = (),
    voices: Mapping[str, str] | None = None,
    capabilities: Sequence[str] = (),
    attached: Sequence[str] = (),
) -> tuple[list[dict[str, str]], ContextStats]:
    messages = [{"role": "system", "content": system_prompt()}]
    recent = list(history)[-HISTORY_TURNS:]
    for turn in recent:
        messages.append({"role": turn.role, "content": turn.content[:HISTORY_CHARS]})
    context, outlined, shown = _render(
        story, focus, budget, library, profiles or {}, earlier, voices or {}, capabilities, attached
    )
    messages.append(
        {
            "role": "user",
            "content": render(
                "narrative.assistant.context", story=context, request=request[:REQUEST_CHARS]
            ),
        }
    )
    return messages, ContextStats(len(story["nodes"]), outlined, shown, len(recent))


def _safe(text: str) -> str:
    return text.replace("</", "<\\/")


def _quote(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _snippet(text: Any) -> str:
    value = str(text)
    return _quote(value if len(value) <= SNIPPET_CHARS else value[: SNIPPET_CHARS - 1] + "…")


def _condition(condition: Any) -> str:
    if type(condition) is not dict:
        return "?"
    op = condition.get("op")
    if op in ("all", "any"):
        joiner = " and " if op == "all" else " or "
        return "(" + joiner.join(_condition(child) for child in condition.get("children", [])) + ")"
    if op == "not":
        return "not (" + _condition(condition.get("child")) + ")"
    return f"{condition.get('variable')} {op} {_quote(condition.get('value'))}"


def _outline(key: str, node: dict[str, Any]) -> str:
    kind = node.get("type")
    if kind == "line":
        expression = f" ({node['expression']})" if "expression" in node else ""
        voice = node.get("voice")
        if isinstance(voice, dict):
            # Voices are set in the Studio (ADR 0043); rewording a line keeps its voice.
            sound = f" {_quote(voice.get('text'))}" if voice.get("mode") == "vocalization" else ""
            expression += f" [voice: {voice.get('mode')}{sound}]"
        speaker = f" {node['speaker']}{expression} |" if "speaker" in node else ""
        return f"{key} | line |{speaker} {_snippet(node.get('text'))} -> {node.get('next')}"
    if kind == "stage":
        parts = []
        if "background" in node:
            parts.append(f"background {node['background'] or 'none'}")
        if node.get("hide"):
            parts.append("hide " + ", ".join(str(item) for item in node["hide"]))
        if node.get("show"):
            shown = ", ".join(
                f"{entry.get('character')} {entry.get('sprite')} {entry.get('position')}"
                for entry in node["show"]
            )
            parts.append("show " + shown)
        return f"{key} | stage | {'; '.join(parts)} -> {node.get('next')}"
    if kind == "choice":
        options = "; ".join(
            f"{option.get('id')} -> {option.get('target')}"
            + (f" if {_condition(option['condition'])}" if "condition" in option else "")
            for option in node.get("options", [])
        )
        return f"{key} | choice | {_snippet(node.get('text'))} | {options}"
    if kind == "set":
        changes = ", ".join(
            f"{item.get('variable')} {item.get('op')} {_quote(item.get('value'))}"
            for item in node.get("operations", [])
        )
        return f"{key} | set | {changes} -> {node.get('next')}"
    if kind == "branch":
        return (
            f"{key} | branch | if {_condition(node.get('condition'))} "
            f"-> {node.get('if_true')} else {node.get('if_false')}"
        )
    return f"{key} | end {node.get('ending')} | {_snippet(node.get('text'))}"


def _targets(node: dict[str, Any]) -> list[str]:
    targets = [node.get(field) for field in ("next", "if_true", "if_false")]
    targets += [option.get("target") for option in node.get("options", [])]
    return [target for target in targets if type(target) is str]


def render_story(story: dict[str, Any], focus: str | None, budget: int) -> str:
    return _render(story, focus, budget)[0]


def _stock_voices() -> str:
    by_gender = {
        gender: " ".join(voice.id for voice in VOICES if voice.gender == gender)
        for gender in ("female", "male")
    }
    return f"stock voices: female {by_gender['female']}; male {by_gender['male']}"


def _character(key: str, item: dict[str, Any], looks: str | None, voice: str | None) -> str:
    details = []
    if item.get("sprites"):
        details.append(
            "expressions: "
            + ", ".join(f"{name}={asset}" for name, asset in item["sprites"].items())
        )
    if item.get("color"):
        details.append(f"color {item['color']}")
    if item.get("stage"):
        details.append("framing " + json.dumps(item["stage"], separators=(",", ":")))
    if looks:
        details.append("looks: " + _quote(looks[:200]))
    if voice:
        details.append(f"voice {voice}")
    return f"  {key}: {_quote(item.get('name'))}" + (f" ({'; '.join(details)})" if details else "")


def attached_lines(
    story: dict[str, Any],
    attachments: Sequence[Mapping[str, Any]],
    *,
    files: Mapping[str, LibraryRow],
    library: Sequence[LibraryEntry],
    profiles: Mapping[str, str],
    voices: Mapping[str, str],
) -> tuple[str, ...]:
    """What the creator attached, in detail, under the IDs the model must use.

    Anything removed or no longer approved since it was attached is left out.
    """
    in_story = {
        item.get("sha256"): key
        for key, item in (story.get("assets") or {}).items()
        if type(item) is dict
    }
    offered = {entry.sha256: entry.key for entry in library}
    lines: list[str] = []
    for item in attachments:
        if item["kind"] == "character":
            character = story["characters"].get(item["id"])
            if character is not None:
                described = _character(
                    item["id"], character, profiles.get(item["id"]), voices.get(item["id"])
                )
                lines.append("  character " + described.strip())
            continue
        row = files.get(item["id"])
        if row is None:
            continue
        key = in_story.get(row.sha256) or offered.get(row.sha256) or item["id"]
        owner = f" of {row.character_id}" if row.character_id else ""
        lines.append(f"  {key}: {row.kind} {_quote(row.name[:60])}{owner}")
    return tuple(lines)


def _render(
    story: dict[str, Any],
    focus: str | None,
    budget: int,
    library: Sequence[LibraryEntry] = (),
    profiles: Mapping[str, str] | None = None,
    earlier: Sequence[str] = (),
    voices: Mapping[str, str] | None = None,
    capabilities: Sequence[str] = (),
    attached: Sequence[str] = (),
) -> tuple[str, int, str | None]:
    """Return the context text, the number of outlined scenes and the shown focus scene."""
    nodes: dict[str, Any] = story["nodes"]
    staged = story.get("schema_version") == "2"
    looks = profiles or {}
    spoken = voices or {}
    header = [
        f"title: {_quote(story['title'])}",
        f"language: {story['language']}",
        f"format: {story.get('schema_version')}"
        + (" (stage, expressions, sprites and theme)" if staged else " (text only)"),
        f"entry: {story['entry']}",
        *(
            [
                "attached by the creator for this request "
                '(when they say "this", "here", "her" or "that", they mean these):',
                *attached,
            ]
            if attached
            else []
        ),
        "characters:",
        *(
            _character(key, item, looks.get(key), spoken.get(key))
            for key, item in story["characters"].items()
        ),
        "variables:",
    ]
    for key, declaration in story["variables"].items():
        kind = declaration.get("type")
        values = f" [{', '.join(declaration.get('values', []))}]" if kind == "enum" else ""
        header.append(f"  {key}: {kind}{values} = {_quote(declaration.get('initial'))}")
    if staged:
        header.append("story assets:")
        header += [f"  {key}: {item.get('kind', 'image')}" for key, item in story["assets"].items()]
        if library:
            header.append("library (approved files; use an ID and it is added to the story):")
            header += [
                f"  {entry.key}: {entry.library_kind} {_quote(entry.name[:40])}"
                + (f" of {entry.character_id}" if entry.character_id else "")
                for entry in library
            ]
        if story.get("theme"):
            header.append(
                "theme: " + json.dumps(story["theme"], ensure_ascii=False, separators=(",", ":"))
            )
    if capabilities:
        header.append("generation available: " + ", ".join(capabilities))
        if "voices" in capabilities:
            header.append(_stock_voices())
    if earlier:
        # Older turns of this thread, folded from its log; escaped like any other data.
        header += ["earlier in this conversation (oldest first):", *earlier]
    head = _safe("\n".join(header)) + "\nscenes (id | type | text -> next):"

    adjacent: dict[str, set[str]] = {key: set() for key in nodes}
    for key, node in nodes.items():
        for target in _targets(node):
            if target in adjacent:
                adjacent[key].add(target)
                adjacent[target].add(key)
    start = focus if focus in nodes else story["entry"]
    distance = {start: 0} if start in nodes else {}
    pending = deque(distance)
    while pending:
        current = pending.popleft()
        for neighbor in sorted(adjacent[current]):
            if neighbor not in distance:
                distance[neighbor] = distance[current] + 1
                pending.append(neighbor)
    order = {key: index for index, key in enumerate(nodes)}

    focus_block = ""
    if focus in nodes:
        near = sorted(adjacent[focus], key=order.__getitem__)[:NEIGHBORS]
        while True:
            selected = {key: nodes[key] for key in [focus, *near]}
            focus_block = f"FOCUS {focus}\n" + _safe(
                json.dumps(selected, ensure_ascii=False, separators=(",", ":"))
            )
            if len(head) + len(focus_block) + _OMISSION_RESERVE <= budget // 2 or not near:
                break
            near.pop()
        if len(head) + len(focus_block) + _OMISSION_RESERVE > budget:
            focus_block = ""

    remaining = budget - len(head) - len(focus_block) - _OMISSION_RESERVE - 2
    chosen: set[str] = set()
    for key in sorted(nodes, key=lambda item: (distance.get(item, len(nodes)), order[item])):
        line = _safe(_outline(key, nodes[key]))
        if len(line) + 1 > remaining:
            break
        remaining -= len(line) + 1
        chosen.add(key)
    lines = [head, *(_safe(_outline(key, nodes[key])) for key in nodes if key in chosen)]
    if len(chosen) < len(nodes):
        lines.append(f"({len(nodes) - len(chosen)} scenes omitted, farthest from the focus first)")
    if focus_block:
        lines.append(focus_block)
    return "\n".join(lines), len(chosen), focus if focus_block else None
