"""Strict, bounded story semantics (v1 and v2), independent of any execution engine."""

import re
from collections import deque
from collections.abc import Callable
from functools import partial
from typing import Any, TypeVar

from flint_graph.narrative.values import Diagnostic, PackageError

ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
COLOR = re.compile(r"#[0-9a-f]{6}(?:[0-9a-f]{2})?\Z")
OPAQUE_COLOR = re.compile(r"#[0-9a-f]{6}\Z")
POSITIONS = ("left", "center", "right")
INT_MIN = -(2**31)
INT_MAX = 2**31 - 1
_T = TypeVar("_T")
_STORY_FIELDS = {
    "schema_version",
    "id",
    "title",
    "language",
    "entry",
    "characters",
    "variables",
    "nodes",
    "assets",
}
_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


class _Full(Exception):
    pass


class _Errors:
    """Raise the first error (manual saves) or collect a bounded list (proposal repair)."""

    def __init__(self, limit: int | None) -> None:
        self.limit = limit
        self.found: list[Diagnostic] = []

    def check(self, step: Callable[[], _T]) -> _T | None:
        if self.limit is None:
            return step()
        try:
            return step()
        except PackageError as error:
            self.found.append(Diagnostic(error.code, error.location))
            if len(self.found) >= self.limit:
                raise _Full from None
            return None


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
    """Raise the first error a manual save would report; return structural warnings."""
    return _validate(story, _Errors(None))


def collect_story_diagnostics(
    story: Any, limit: int = 50
) -> tuple[tuple[Diagnostic, ...], tuple[Diagnostic, ...]]:
    """Return up to ``limit`` errors (first equals ``validate_story``'s) and warnings.

    Each header section and each node reports at most its first error, so a model
    repairing a proposal sees every independent problem in one pass.
    """
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Invalid diagnostic limit")
    errors = _Errors(limit)
    try:
        warnings = _validate(story, errors)
    except _Full:
        warnings = ()
    found = tuple(errors.found)
    return found, () if found else warnings


def _schema(value: Any) -> None:
    if value not in ("1", "2"):
        raise PackageError("unsupported_schema", "schema_version")


def _language(value: Any) -> None:
    if type(value) is not str or not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", value):
        raise PackageError("invalid_value", "language")


def _characters(value: Any) -> dict[str, Any]:
    characters = mapping(value, 256, "characters")
    for key, character in characters.items():
        fields(character, {"name"}, set(), f"characters.{key}")
        text(character["name"], f"characters.{key}.name")
    return characters


def _assets(value: Any) -> dict[str, Any]:
    assets = mapping(value, 256, "assets")
    for key, asset in assets.items():
        location = f"assets.{key}"
        if key in _RESERVED:
            raise PackageError("unsafe_path", location)
        fields(asset, {"path", "sha256"}, set(), location)
        if asset["path"] != f"assets/{key}.png":
            raise PackageError("unsafe_path", location)
        if type(asset["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"]):
            raise PackageError("invalid_hash", location)
    return assets


def _assets_v2(value: Any) -> dict[str, Any]:
    assets = mapping(value, 256, "assets")
    for key, asset in assets.items():
        location = f"assets.{key}"
        if key in _RESERVED:
            raise PackageError("unsafe_path", location)
        fields(asset, {"kind", "path", "sha256"}, set(), location)
        if asset["kind"] == "image":
            paths = {f"assets/{key}.png"}
        elif asset["kind"] == "font":
            paths = {f"assets/{key}.ttf", f"assets/{key}.otf"}
        else:
            raise PackageError("invalid_value", location + ".kind")
        if asset["path"] not in paths:
            raise PackageError("unsafe_path", location)
        if type(asset["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"]):
            raise PackageError("invalid_hash", location)
    return assets


def asset_of(value: Any, assets: dict[str, Any], kind: str, location: str) -> str:
    key = reference(value, assets, location)
    if assets[key]["kind"] != kind:
        raise PackageError("invalid_asset_kind", location)
    return key


def _color(value: Any, location: str, *, alpha: bool = True) -> None:
    if type(value) is not str or not (COLOR if alpha else OPAQUE_COLOR).fullmatch(value):
        raise PackageError("invalid_value", location)


def _bounded(value: Any, low: int, high: int, location: str) -> None:
    if type(value) is not int or not low <= value <= high:
        raise PackageError("invalid_value", location)


def _characters_v2(value: Any, assets: dict[str, Any]) -> dict[str, Any]:
    characters = mapping(value, 256, "characters")
    for key, character in characters.items():
        location = f"characters.{key}"
        fields(character, {"name"}, {"color", "sprites"}, location)
        text(character["name"], location + ".name")
        if "color" in character:
            _color(character["color"], location + ".color", alpha=False)
        if "sprites" in character:
            sprites = mapping(character["sprites"], 32, location + ".sprites")
            for expression, asset in sprites.items():
                asset_of(asset, assets, "image", f"{location}.sprites.{expression}")
    return characters


def _theme(value: Any, assets: dict[str, Any]) -> None:
    """A closed presentation theme; every part is optional (defaults: ADR 0040 design)."""
    theme = fields(value, set(), {"textbox", "name", "choices", "font"}, "theme")
    if "textbox" in theme:
        location = "theme.textbox"
        box = fields(
            theme["textbox"],
            set(),
            {"position", "width", "background", "text", "border", "radius"},
            location,
        )
        if "position" in box and box["position"] not in ("bottom", "middle", "top"):
            raise PackageError("invalid_value", location + ".position")
        if "width" in box:
            _bounded(box["width"], 40, 100, location + ".width")
        if "radius" in box:
            _bounded(box["radius"], 0, 48, location + ".radius")
        for part in ("background", "text", "border"):
            if part in box:
                _color(box[part], f"{location}.{part}")
    if "name" in theme:
        name = fields(theme["name"], set(), {"show", "background", "text"}, "theme.name")
        if "show" in name and type(name["show"]) is not bool:
            raise PackageError("invalid_value", "theme.name.show")
        for part in ("background", "text"):
            if part in name:
                _color(name[part], f"theme.name.{part}")
    if "choices" in theme:
        choices = fields(theme["choices"], set(), {"background", "text", "border"}, "theme.choices")
        for part, color in choices.items():
            _color(color, f"theme.choices.{part}")
    if "font" in theme:
        font = fields(theme["font"], set(), {"asset", "size"}, "theme.font")
        if font.get("asset") is not None:
            asset_of(font["asset"], assets, "font", "theme.font.asset")
        if "size" in font:
            _bounded(font["size"], 14, 48, "theme.font.size")


def _missing_ending() -> None:
    raise PackageError("missing_ending", "nodes")


def _validate(story: Any, errors: _Errors) -> tuple[Diagnostic, ...]:
    # Check order defines which error a manual save reports first; keep it stable.
    # v2 (ADR 0040) adds an optional theme and checks assets before the characters
    # whose sprites reference them; v1 order and fields are unchanged.
    v2 = type(story) is dict and story.get("schema_version") == "2"
    if (
        errors.check(lambda: fields(story, _STORY_FIELDS, {"theme"} if v2 else set(), "story"))
        is None
    ):
        return ()
    errors.check(lambda: _schema(story["schema_version"]))
    errors.check(lambda: identifier(story["id"], "id"))
    errors.check(lambda: text(story["title"], "title"))
    errors.check(lambda: _language(story["language"]))
    if v2:
        assets = errors.check(lambda: _assets_v2(story["assets"]))
        known: dict[str, Any] = assets or {}
        characters = (
            errors.check(lambda: _characters_v2(story["characters"], known))
            if assets is not None
            else None
        )
        variables = errors.check(lambda: _variables(story["variables"]))
        if assets is not None and "theme" in story:
            errors.check(lambda: _theme(story["theme"], known))
    else:
        characters = errors.check(lambda: _characters(story["characters"]))
        variables = errors.check(lambda: _variables(story["variables"]))
        assets = errors.check(lambda: _assets(story["assets"]))
    nodes = errors.check(lambda: mapping(story["nodes"], 10000, "nodes"))
    if characters is None or variables is None or assets is None or nodes is None:
        return ()
    errors.check(lambda: reference(story["entry"], nodes, "entry"))
    scenes = _Nodes(characters, variables, assets, nodes, v2=v2)
    for key, node in nodes.items():
        errors.check(partial(scenes.check, key, node))
    if not scenes.endings:
        errors.check(_missing_ending)
    if errors.found:
        return ()
    warnings = _graph_warnings(scenes.graph, story["entry"])
    if v2:
        warnings += _stage_warnings(scenes.graph, nodes, story["entry"])
    return warnings


class _Nodes:
    def __init__(
        self,
        characters: dict[str, Any],
        variables: dict[str, Any],
        assets: dict[str, Any],
        nodes: dict[str, Any],
        *,
        v2: bool = False,
    ) -> None:
        self.characters, self.variables, self.assets, self.nodes = (
            characters,
            variables,
            assets,
            nodes,
        )
        self.v2 = v2
        self.text_ids: set[str] = set()
        self.endings: set[str] = set()
        self.graph: dict[str, list[str]] = {}

    def display(self, item: dict[str, Any], location: str) -> None:
        key = identifier(item["text_id"], location + ".text_id")
        if key in self.text_ids:
            raise PackageError("duplicate_id", location + ".text_id")
        self.text_ids.add(key)
        text(item["text"], location + ".text")

    def check(self, key: str, node: Any) -> None:
        characters, variables, assets, nodes = (
            self.characters,
            self.variables,
            self.assets,
            self.nodes,
        )
        display = self.display
        location = f"nodes.{key}"
        if type(node) is not dict:
            raise PackageError("invalid_node", location)
        kind = node.get("type")
        targets: list[str] = []
        if kind == "line" and self.v2:
            fields(node, {"type", "text_id", "text", "next"}, {"speaker", "expression"}, location)
            display(node, location)
            if "speaker" in node:
                speaker = reference(node["speaker"], characters, location + ".speaker")
            if "expression" in node:
                if "speaker" not in node:
                    raise PackageError("invalid_expression", location + ".expression")
                sprites = characters[speaker].get("sprites", {})
                reference(node["expression"], sprites, location + ".expression")
            targets.append(reference(node["next"], nodes, location + ".next"))
        elif kind == "line":
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
        elif kind == "stage" and self.v2:
            fields(node, {"type", "next"}, {"background", "show", "hide"}, location)
            effect = False
            if "background" in node:
                effect = True
                if node["background"] is not None:
                    asset_of(node["background"], assets, "image", location + ".background")
            hidden: set[str] = set()
            if "hide" in node:
                effect = True
                for item in sequence(node["hide"], 8, location + ".hide"):
                    character = reference(item, characters, location + ".hide")
                    if character in hidden:
                        raise PackageError("invalid_stage", location + ".hide")
                    hidden.add(character)
            if "show" in node:
                effect = True
                shown: set[str] = set()
                taken: set[str] = set()
                for entry in sequence(node["show"], 8, location + ".show"):
                    fields(entry, {"character", "sprite", "position"}, set(), location + ".show")
                    character = reference(entry["character"], characters, location + ".show")
                    sprites = characters[character].get("sprites", {})
                    reference(entry["sprite"], sprites, location + ".show")
                    if entry["position"] not in POSITIONS:
                        raise PackageError("invalid_value", location + ".show")
                    if character in shown or character in hidden or entry["position"] in taken:
                        raise PackageError("invalid_stage", location + ".show")
                    shown.add(character)
                    taken.add(entry["position"])
            if not effect:
                raise PackageError("invalid_stage", location)
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
            if ending in self.endings:
                raise PackageError("duplicate_id", location + ".ending")
            self.endings.add(ending)
        else:
            raise PackageError("invalid_node", location)
        self.graph[key] = targets


def _stage_warnings(
    graph: dict[str, list[str]], nodes: dict[str, Any], entry: str
) -> tuple[Diagnostic, ...]:
    """Warn where a line's expression targets a speaker who is off stage on every path.

    A forward analysis tracks each character as off (absent from the map), at a
    position, or "?" when paths disagree. Only definite absence warns.
    """
    states: dict[str, dict[str, str]] = {entry: {}}
    pending = deque([entry])
    while pending:
        key = pending.popleft()
        state, node = states[key], nodes[key]
        after = _after_stage(state, node) if node["type"] == "stage" else state
        for target in graph[key]:
            previous = states.get(target)
            joined = after if previous is None else _join(previous, after)
            if joined != previous:
                states[target] = joined
                pending.append(target)
    warnings = []
    for key in sorted(states):
        node = nodes[key]
        if node["type"] == "line" and "expression" in node and node["speaker"] not in states[key]:
            warnings.append(Diagnostic("expression_off_stage", f"nodes.{key}"))
    return tuple(warnings)


def _after_stage(state: dict[str, str], node: dict[str, Any]) -> dict[str, str]:
    result = {key: value for key, value in state.items() if key not in node.get("hide", [])}
    for entry in node.get("show", []):
        for other, where in list(result.items()):
            if where == entry["position"] and other != entry["character"]:
                del result[other]
        result[entry["character"]] = entry["position"]
    return result


def _join(left: dict[str, str], right: dict[str, str]) -> dict[str, str]:
    return {
        key: left.get(key, "") if left.get(key) == right.get(key) else "?"
        for key in left.keys() | right.keys()
    }


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
