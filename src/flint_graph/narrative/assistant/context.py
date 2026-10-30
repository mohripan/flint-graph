"""Bounded, focus-first story context for one assistant turn.

The model sees one saved revision of the current project only: a compact outline
of every scene that fits the budget (nearest the focus scene first), full JSON for
the focus scene and its neighbors, and a few earlier turns of the same thread.
Story text is data: it is delimited and escaped so it cannot close the delimiter.
"""

import json
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from flint_graph.narrative.assistant.prompts import SYSTEM_PROMPT

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
) -> tuple[list[dict[str, str]], ContextStats]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    recent = list(history)[-HISTORY_TURNS:]
    for turn in recent:
        messages.append({"role": turn.role, "content": turn.content[:HISTORY_CHARS]})
    context, outlined, shown = _render(story, focus, budget)
    messages.append(
        {
            "role": "user",
            "content": f"<story>\n{context}\n</story>\n\nRequest:\n{request[:REQUEST_CHARS]}",
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
        speaker = f" {node['speaker']} |" if "speaker" in node else ""
        return f"{key} | line |{speaker} {_snippet(node.get('text'))} -> {node.get('next')}"
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


def _render(story: dict[str, Any], focus: str | None, budget: int) -> tuple[str, int, str | None]:
    """Return the context text, the number of outlined scenes and the shown focus scene."""
    nodes: dict[str, Any] = story["nodes"]
    header = [
        f"title: {_quote(story['title'])}",
        f"language: {story['language']}",
        f"entry: {story['entry']}",
        "characters:",
        *(f"  {key}: {_quote(item.get('name'))}" for key, item in story["characters"].items()),
        "variables:",
    ]
    for key, declaration in story["variables"].items():
        kind = declaration.get("type")
        values = f" [{', '.join(declaration.get('values', []))}]" if kind == "enum" else ""
        header.append(f"  {key}: {kind}{values} = {_quote(declaration.get('initial'))}")
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
