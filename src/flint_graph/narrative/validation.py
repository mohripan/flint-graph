"""Strict, bounded v1 story semantics, independent of any execution engine."""

import re
from collections import deque
from typing import Any

from flint_graph.narrative.values import Diagnostic, PackageError

ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
INT_MIN = -(2**31)
INT_MAX = 2**31 - 1


def fields(value: Any, required: set[str], optional: set[str], location: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise PackageError("invalid_object", location)
    if set(value) - required - optional:
        raise PackageError("unknown_field", location)
    if required - set(value):
        raise PackageError("missing_field", location)
    return value


def identifier(value: Any, location: str) -> str:
    if type(value) is not str or not ID.fullmatch(value):
        raise PackageError("invalid_id", location)
    return value


def text(value: Any, location: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > 16384:
        raise PackageError("invalid_text", location)
    return value


def mapping(value: Any, limit: int, location: str) -> dict[str, Any]:
    if type(value) is not dict or len(value) > limit:
        raise PackageError("collection_limit", location)
    for key in value:
        identifier(key, location)
    return value


def sequence(value: Any, limit: int, location: str) -> list[Any]:
    if type(value) is not list or not 1 <= len(value) <= limit:
        raise PackageError("collection_limit", location)
    return value


def typed_value(value: Any, declaration: dict[str, Any], location: str) -> None:
    kind = declaration["type"]
    valid = (
        (kind == "bool" and type(value) is bool)
        or (kind == "int" and type(value) is int and INT_MIN <= value <= INT_MAX)
        or (kind == "enum" and type(value) is str and value in declaration["values"])
    )
    if not valid:
        raise PackageError("invalid_value", location)


def reference(value: Any, targets: dict[str, Any], location: str) -> str:
    key = identifier(value, location)
    if key not in targets:
        raise PackageError("unknown_reference", location)
    return key


def condition(value: Any, variables: dict[str, Any], location: str) -> None:
    count = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal count
        count += 1
        if depth > 8 or count > 64:
            raise PackageError("condition_limit", location)
        if type(item) is not dict:
            raise PackageError("invalid_condition", location)
        op = item.get("op")
        if op in ("all", "any"):
            fields(item, {"op", "children"}, set(), location)
            for child in sequence(item["children"], 64, location):
                visit(child, depth + 1)
        elif op == "not":
            fields(item, {"op", "child"}, set(), location)
            visit(item["child"], depth + 1)
        elif op in ("eq", "ne", "lt", "le", "gt", "ge"):
            fields(item, {"op", "variable", "value"}, set(), location)
            variable = reference(item["variable"], variables, location)
            declaration = variables[variable]
            typed_value(item["value"], declaration, location)
            if op not in ("eq", "ne") and declaration["type"] != "int":
                raise PackageError("invalid_condition", location)
        else:
            raise PackageError("invalid_condition", location)

    visit(value, 1)


def _variables(value: Any) -> dict[str, Any]:
    declarations = mapping(value, 256, "variables")
    for key, declaration in declarations.items():
        location = f"variables.{key}"
        fields(declaration, {"type", "initial"}, {"values"}, location)
        kind = declaration["type"]
        if kind == "enum":
            values = sequence(declaration.get("values"), 256, location)
            for item in values:
                text(item, location)
            if len(set(values)) != len(values):
                raise PackageError("invalid_value", location)
        elif kind not in ("bool", "int") or "values" in declaration:
            raise PackageError("invalid_value", location)
        typed_value(declaration["initial"], declaration, location)
    return declarations


def validate_story(story: Any) -> tuple[Diagnostic, ...]:
    fields(
        story,
        {
            "schema_version",
            "id",
            "title",
            "language",
            "entry",
            "characters",
            "variables",
            "nodes",
            "assets",
        },
        set(),
        "story",
    )
    if story["schema_version"] != "1":
        raise PackageError("unsupported_schema", "schema_version")
    identifier(story["id"], "id")
    text(story["title"], "title")
    if type(story["language"]) is not str or not re.fullmatch(
        r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", story["language"]
    ):
        raise PackageError("invalid_value", "language")
    characters = mapping(story["characters"], 256, "characters")
    for key, character in characters.items():
        fields(character, {"name"}, set(), f"characters.{key}")
        text(character["name"], f"characters.{key}.name")
    variables = _variables(story["variables"])
    assets = mapping(story["assets"], 256, "assets")
    for key, asset in assets.items():
        location = f"assets.{key}"
        if key in {
            "con",
            "prn",
            "aux",
            "nul",
            *(f"com{i}" for i in range(1, 10)),
            *(f"lpt{i}" for i in range(1, 10)),
        }:
            raise PackageError("unsafe_path", location)
        fields(asset, {"path", "sha256"}, set(), location)
        if asset["path"] != f"assets/{key}.png":
            raise PackageError("unsafe_path", location)
        if type(asset["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"]):
            raise PackageError("invalid_hash", location)
    nodes = mapping(story["nodes"], 10000, "nodes")
    reference(story["entry"], nodes, "entry")
    text_ids: set[str] = set()
    endings: set[str] = set()
    graph: dict[str, list[str]] = {}

    def display(item: dict[str, Any], location: str) -> None:
        key = identifier(item["text_id"], location + ".text_id")
        if key in text_ids:
            raise PackageError("duplicate_id", location + ".text_id")
        text_ids.add(key)
        text(item["text"], location + ".text")

    for key, node in nodes.items():
        location = f"nodes.{key}"
        if type(node) is not dict:
            raise PackageError("invalid_node", location)
        kind = node.get("type")
        targets: list[str] = []
        if kind == "line":
            fields(
                node,
                {"type", "text_id", "text", "next"},
                {"speaker", "background", "portrait"},
                location,
            )
            display(node, location)
            if "speaker" in node:
                reference(node["speaker"], characters, location + ".speaker")
            for slot in ("background", "portrait"):
                if slot in node:
                    reference(node[slot], assets, location + "." + slot)
            targets.append(reference(node["next"], nodes, location + ".next"))
        elif kind == "choice":
            fields(node, {"type", "text_id", "text", "options"}, set(), location)
            display(node, location)
            option_ids: set[str] = set()
            for option in sequence(node["options"], 32, location + ".options"):
                fields(option, {"id", "text_id", "text", "target"}, {"condition"}, location)
                option_id = identifier(option["id"], location + ".options")
                if option_id in option_ids:
                    raise PackageError("duplicate_id", location + ".options")
                option_ids.add(option_id)
                display(option, location + ".options." + option_id)
                if "condition" in option:
                    condition(option["condition"], variables, location + ".condition")
                targets.append(reference(option["target"], nodes, location + ".target"))
        elif kind == "set":
            fields(node, {"type", "operations", "next"}, set(), location)
            for operation in sequence(node["operations"], 256, location + ".operations"):
                fields(operation, {"op", "variable", "value"}, set(), location)
                variable = reference(operation["variable"], variables, location + ".variable")
                declaration = variables[variable]
                typed_value(operation["value"], declaration, location + ".value")
                if operation["op"] not in ("set", "increment") or (
                    operation["op"] == "increment" and declaration["type"] != "int"
                ):
                    raise PackageError("invalid_operation", location)
            targets.append(reference(node["next"], nodes, location + ".next"))
        elif kind == "branch":
            fields(node, {"type", "condition", "if_true", "if_false"}, set(), location)
            condition(node["condition"], variables, location + ".condition")
            targets.extend(
                reference(node[field], nodes, location + "." + field)
                for field in ("if_true", "if_false")
            )
        elif kind == "end":
            fields(node, {"type", "text_id", "text", "ending"}, set(), location)
            display(node, location)
            ending = identifier(node["ending"], location + ".ending")
            if ending in endings:
                raise PackageError("duplicate_id", location + ".ending")
            endings.add(ending)
        else:
            raise PackageError("invalid_node", location)
        graph[key] = targets
    if not endings:
        raise PackageError("missing_ending", "nodes")
    return _graph_warnings(graph, story["entry"])


def _graph_warnings(graph: dict[str, list[str]], entry: str) -> tuple[Diagnostic, ...]:
    reached: set[str] = set()
    pending = deque([entry])
    while pending:
        node = pending.popleft()
        if node not in reached:
            reached.add(node)
            pending.extend(graph[node])
    warnings = [
        Diagnostic("structural_unreachable", f"nodes.{node}")
        for node in sorted(set(graph) - reached)
    ]
    # Kahn's algorithm detects cycles without recursive traversal of a 10k-node graph.
    incoming = dict.fromkeys(graph, 0)
    for targets in graph.values():
        for target in targets:
            incoming[target] += 1
    ready = deque(key for key, count in incoming.items() if count == 0)
    visited = 0
    while ready:
        visited += 1
        for target in graph[ready.popleft()]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    if visited != len(graph):
        warnings.append(Diagnostic("structural_cycle", "nodes"))
    return tuple(warnings)
