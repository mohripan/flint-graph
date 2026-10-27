"""Read a portable story package into an immutable content snapshot."""

import hashlib
import os
import stat
from pathlib import Path

from flint_graph.narrative.json_format import parse_json
from flint_graph.narrative.png import validate_png
from flint_graph.narrative.validation import validate_story
from flint_graph.narrative.values import Asset, PackageError, StoryPackage, canonical_json

STORY_LIMIT = 5 * 1024 * 1024
ASSET_LIMIT = 10 * 1024 * 1024
PACKAGE_LIMIT = 100 * 1024 * 1024
NOTICES_LIMIT = 1024 * 1024


def load_text_package(story_json: bytes, notices: bytes = b"") -> StoryPackage:
    """Validate an in-memory text-only snapshot without filesystem or asset access."""
    story = parse_json(story_json, limit=STORY_LIMIT)
    warnings = validate_story(story)
    if story["assets"]:
        raise PackageError("assets_not_supported", "assets")
    if len(notices) > NOTICES_LIMIT:
        raise PackageError("size_limit", "NOTICES.txt")
    try:
        notice_text = notices.decode("utf-8")
    except UnicodeError:
        raise PackageError("invalid_text", "NOTICES.txt") from None
    if "\x00" in notice_text:
        raise PackageError("invalid_text", "NOTICES.txt")
    canonical = canonical_json(story)
    if len(canonical) > STORY_LIMIT:
        raise PackageError("size_limit", "story.json")
    return StoryPackage(canonical, notices, warnings=warnings)


def _regular(path: Path, *, directory: bool = False) -> os.stat_result:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise PackageError("unsafe_path")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise PackageError("unsafe_path")
    return info


def _read(path: Path, limit: int) -> bytes:
    info = _regular(path)
    if info.st_size > limit:
        raise PackageError("size_limit")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            info.st_dev,
            info.st_ino,
        ):
            raise PackageError("unsafe_path")
        data = stream.read(limit + 1)
        after = _regular(path)
        if (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
            raise PackageError("unsafe_path")
    if len(data) > limit:
        raise PackageError("size_limit")
    return data


def _inventory(root: Path, expected: set[str]) -> None:
    actual: set[str] = set()
    total = 0
    with os.scandir(root) as entries:
        for entry in entries:
            if entry.name == "assets":
                _regular(Path(entry.path), directory=True)
                with os.scandir(entry.path) as assets:
                    for item in assets:
                        name = "assets/" + item.name
                        if name not in expected:
                            raise PackageError("unexpected_file")
                        total += _regular(Path(item.path)).st_size
                        actual.add(name)
            else:
                if entry.name not in expected:
                    raise PackageError("unexpected_file")
                total += _regular(Path(entry.path)).st_size
                actual.add(entry.name)
            if total > PACKAGE_LIMIT:
                raise PackageError("size_limit")
    if actual != expected:
        raise PackageError("missing_file")


def load_package(root: Path) -> StoryPackage:
    try:
        _regular(root, directory=True)
        story = parse_json(_read(root / "story.json", STORY_LIMIT))
        warnings = validate_story(story)
        expected = {"story.json", "NOTICES.txt"}
        expected.update(item["path"] for item in story["assets"].values())
        _inventory(root, expected)
        notices = _read(root / "NOTICES.txt", NOTICES_LIMIT)
        notice_text = notices.decode("utf-8")
        if "\x00" in notice_text:
            raise PackageError("invalid_text", "NOTICES.txt")
        assets: list[Asset] = []
        total = len(canonical_json(story)) + len(notices)
        for key, item in sorted(story["assets"].items()):
            _regular(root / "assets", directory=True)
            data = _read(root / item["path"], ASSET_LIMIT)
            total += len(data)
            if total > PACKAGE_LIMIT:
                raise PackageError("size_limit")
            digest = hashlib.sha256(data).hexdigest()
            if digest != item["sha256"]:
                raise PackageError("hash_mismatch", f"assets.{key}")
            validate_png(data, f"assets.{key}")
            assets.append(Asset(key, item["path"], digest, data))
        return StoryPackage(canonical_json(story), notices, tuple(assets), warnings)
    except PackageError:
        raise
    except FileNotFoundError:
        raise PackageError("missing_file") from None
    except UnicodeError:
        raise PackageError("invalid_text", "NOTICES.txt") from None
    except OSError:
        raise PackageError("file_access") from None
