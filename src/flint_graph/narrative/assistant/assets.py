"""Library assets the assistant can use in story format 2 (ADR 0040).

The model sees approved library files under story-ready IDs and simply refers to
those IDs in stage steps, sprites and the theme font. Before checking, every such ID
the story does not have yet becomes an explicit ``add_asset`` operation with the
file's kind, path and SHA-256, so a stored proposal is complete on its own and the
save path binds it to the same approved file.
"""

import re
import unicodedata
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from flint_graph.narrative.assistant.operations import AddAsset, Proposal, apply_operations
from flint_graph.narrative.values import PackageError

_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_EXTENSIONS = {"image/png": "png", "font/ttf": "ttf", "font/otf": "otf", "audio/wav": "wav"}
_STORY_KINDS = {"png": "image", "ttf": "font", "otf": "font", "wav": "audio"}
LIBRARY_LIMIT = 120


@dataclass(frozen=True)
class LibraryRow:
    """An approved library asset as the database lists it."""

    name: str
    kind: str  # background, sprite, image, character_portrait, font or voice
    media_type: str
    sha256: str
    character_id: str | None = None


@dataclass(frozen=True)
class LibraryEntry:
    key: str
    kind: str  # story asset kind: image, font or audio
    library_kind: str
    name: str
    path: str
    sha256: str
    character_id: str | None = None


def slug(name: str) -> str:
    """The same story asset IDs the Studio derives from file names."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")[:56].rstrip("_")
    if not re.match(r"[a-z]", text):
        text = f"asset_{text}".rstrip("_")
    return f"asset_{text}" if text in _RESERVED else text


def library_entries(
    story: dict[str, Any], rows: Iterable[LibraryRow], *, attached: Collection[str] = ()
) -> tuple[LibraryEntry, ...]:
    """Approved files the story does not use yet, each under one unused ID.

    Files the creator attached (by SHA-256) come first, so the limit never drops them.
    """
    known = {item.get("sha256") for item in story["assets"].values() if type(item) is dict}
    used = set(story["assets"])
    entries: list[LibraryEntry] = []
    # Pictures first: a project with many voice clips must not crowd out its art.
    for row in sorted(rows, key=lambda r: (r.sha256 not in attached, r.media_type == "audio/wav")):
        extension = _EXTENSIONS.get(row.media_type)
        if extension is None or row.sha256 in known:
            continue
        base = slug(row.name) or _STORY_KINDS[extension]
        key, number = base, 2
        while key in used:
            key, number = f"{base}_{number}", number + 1
        used.add(key)
        known.add(row.sha256)
        entries.append(
            LibraryEntry(
                key,
                _STORY_KINDS[extension],
                row.kind,
                row.name,
                f"assets/{key}.{extension}",
                row.sha256,
                row.character_id,
            )
        )
        if len(entries) >= LIBRARY_LIMIT:
            break
    return tuple(entries)


def _referenced(story: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for node in story["nodes"].values():
        if type(node) is not dict:
            continue
        if node.get("type") == "stage":
            keys.update(
                node[field] for field in ("background", "cg") if type(node.get(field)) is str
            )
        voice = node.get("voice") if node.get("type") == "line" else None
        if type(voice) is dict and type(voice.get("audio")) is str:
            keys.add(voice["audio"])
    for character in story["characters"].values():
        sprites = character.get("sprites") if type(character) is dict else None
        if type(sprites) is dict:
            keys.update(value for value in sprites.values() if type(value) is str)
    theme = story.get("theme")
    font = theme.get("font") if type(theme) is dict else None
    if type(font) is dict and type(font.get("asset")) is str:
        keys.add(font["asset"])
    return keys


def add_library_assets(
    story: dict[str, Any], proposal: Proposal, library: Sequence[LibraryEntry]
) -> Proposal:
    """Append ``add_asset`` for library IDs the edited story uses but does not have."""
    if not library:
        return proposal
    try:
        edited = apply_operations(story, proposal.operations).story
    except PackageError:
        return proposal  # The check reports the operation problem itself.
    by_key = {entry.key: entry for entry in library}
    missing = sorted(key for key in _referenced(edited) - set(edited["assets"]) if key in by_key)
    if not missing:
        return proposal
    additions = [
        AddAsset(
            op="add_asset",
            id=key,
            asset={
                "kind": by_key[key].kind,
                "path": by_key[key].path,
                "sha256": by_key[key].sha256,
            },
        )
        for key in missing
    ]
    return proposal.model_copy(update={"operations": [*proposal.operations, *additions]})
