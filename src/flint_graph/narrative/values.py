"""Immutable values at the local story-package boundary."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


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
