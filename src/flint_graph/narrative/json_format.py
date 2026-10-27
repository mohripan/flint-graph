"""Bounded strict JSON shared by package and player-save boundaries."""

import json
from typing import Any, NoReturn

from flint_graph.narrative.values import PackageError


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PackageError("invalid_json")
        result[key] = value
    return result


def _constant(value: str) -> NoReturn:
    raise PackageError("invalid_json")


def parse_json(data: bytes, *, limit: int = 5 * 1024 * 1024) -> Any:
    if len(data) > limit:
        raise PackageError("size_limit", "story.json")
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        raise PackageError("invalid_text") from None
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 64:
                raise PackageError("json_depth_limit")
        elif char in "]}":
            depth -= 1
    try:
        result = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, RecursionError):
        raise PackageError("invalid_json") from None
    pending = [result]
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            if "\x00" in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
                raise PackageError("invalid_text")
        elif isinstance(value, dict):
            pending.extend(value)
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return result
