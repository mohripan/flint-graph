"""Immutable values at the local story-package boundary."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


NAME_LIMIT = 32
# Invisible, line-breaking or text-reversing characters have no place in a name on screen. The
# joiners U+200C and U+200D stay: some scripts and emoji need them.
_NOT_IN_NAMES = (
    (0x0000, 0x001F),
    (0x007F, 0x009F),
    (0x200B, 0x200B),
    (0x200E, 0x200F),
    (0x2028, 0x202E),
    (0x2060, 0x2069),
    (0xD800, 0xDFFF),
    (0xFEFF, 0xFEFF),
    (0xFFFE, 0xFFFF),
)
_NAME_EDGES = {0x0020, 0x00A0, 0x3000}


def clean_name(raw: str, fallback: str) -> str:
    """What a typed name becomes; the Godot player does exactly the same (ADR 0072)."""
    kept = [
        code
        for code in map(ord, raw)
        if not any(low <= code <= high for low, high in _NOT_IN_NAMES)
    ]
    while kept and kept[0] in _NAME_EDGES:
        kept.pop(0)
    kept = kept[:NAME_LIMIT]
    while kept and kept[-1] in _NAME_EDGES:
        kept.pop()
    return "".join(map(chr, kept)) or fallback


@dataclass(frozen=True)
class Diagnostic:
    code: str
    location: str


class PackageError(ValueError):
    """Safe, structured failure without source text or absolute host paths."""

    def __init__(self, code: str, location: str = "package") -> None:
        self.code = code
        self.location = location
        super().__init__(f"{code}: {location}")


@dataclass(frozen=True)
class Asset:
    id: str
    path: str
    sha256: str
    # ``None`` for a reference whose bytes are resolved later (Studio saves, ADR 0040);
    # anything that writes or ships the asset must load and verify the bytes first.
    data: bytes | None


@dataclass(frozen=True)
class StoryPackage:
    canonical_story: bytes
    notices: bytes
    assets: tuple[Asset, ...] = ()
    warnings: tuple[Diagnostic, ...] = ()

    @property
    def story(self) -> dict[str, Any]:
        # Return a fresh view: callers cannot mutate content behind its hash.
        value: dict[str, Any] = json.loads(self.canonical_story)
        return value

    @property
    def manifest(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "story_sha256": hashlib.sha256(self.canonical_story).hexdigest(),
            "notices_sha256": hashlib.sha256(self.notices).hexdigest(),
            "assets": [
                {"id": asset.id, "path": asset.path, "sha256": asset.sha256}
                for asset in self.assets
            ],
        }

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.manifest)).hexdigest()
