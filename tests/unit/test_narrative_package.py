import hashlib
import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from flint_graph.narrative import PackageError, load_package


def minimal_story() -> dict:
    return {
        "schema_version": "1",
        "id": "first_game",
        "title": "A door at dawn",
        "language": "en",
        "entry": "hello",
        "characters": {},
        "variables": {},
        "assets": {},
        "nodes": {
            "hello": {
                "type": "line",
                "text_id": "hello_text",
                "text": "Pagi arrives.",
                "next": "finish",
            },
            "finish": {"type": "end", "text_id": "end_text", "text": "Dawn.", "ending": "dawn"},
        },
    }


def write_package(root: Path, story: dict | None = None) -> None:
    (root / "story.json").write_text(json.dumps(story or minimal_story()), encoding="utf-8")
    (root / "NOTICES.txt").write_text("Original test writing.\n", encoding="utf-8")


def test_creator_can_load_a_minimal_game_without_services(tmp_path: Path) -> None:
    write_package(tmp_path)
    (tmp_path / "NOTICES.txt").write_text("Original test writing.\n", encoding="utf-8")

    package = load_package(tmp_path)

    assert package.story["title"] == "A door at dawn"
    assert package.warnings == ()
    assert package.assets == ()
    copy = package.story
    copy["title"] = "Changed outside the package"
    assert package.story["title"] == "A door at dawn"


@pytest.mark.parametrize(
    "source",
    [
        b'{"id":"one","id":"two"}',
        b'{"title": NaN}',
        b'{"title": Infinity}',
        b'{"title": "\\ud800"}',
        b'{"title": "\\u0000"}',
        b'{"title": "\xff"}',
        b"\xef\xbb\xbf{}",
        b"[" * 65 + b"]" * 65,
        b'{"secret": "provider_key",}',
    ],
)
def test_invalid_json_is_a_safe_controlled_failure(tmp_path: Path, source: bytes) -> None:
    write_package(tmp_path)
    (tmp_path / "story.json").write_bytes(source)

    with pytest.raises(PackageError) as error:
        load_package(tmp_path)

    assert error.value.code in {"invalid_json", "invalid_text", "json_depth_limit"}
    assert "provider_key" not in str(error.value)
    assert str(tmp_path) not in str(error.value)


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        (("schema_version",), "2", "unsupported_schema"),
        (("hidden_command",), "run", "unknown_field"),
        (("id",), "../escape", "invalid_id"),
        (("title",), "", "invalid_text"),
        (("title",), "x" * 16385, "invalid_text"),
        (("entry",), "missing", "unknown_reference"),
        (("nodes", "hello", "next"), "missing", "unknown_reference"),
        (("nodes", "hello", "speaker"), "missing", "unknown_reference"),
        (("nodes", "hello", "background"), "missing", "unknown_reference"),
        (("nodes", "hello", "extra"), True, "unknown_field"),
        (("nodes", "hello", "text_id"), "end_text", "duplicate_id"),
        (("nodes", "hello", "type"), "script", "invalid_node"),
        (("variables", "trust"), {"type": "int", "initial": True}, "invalid_value"),
        (("variables", "trust"), {"type": "int", "initial": 1.0}, "invalid_value"),
        (("variables", "trust"), {"type": "int", "initial": 2147483648}, "invalid_value"),
        (("variables", "trust"), {"type": "bool", "initial": 1}, "invalid_value"),
        (
            ("variables", "trust"),
            {"type": "enum", "values": ["a", "a"], "initial": "a"},
            "invalid_value",
        ),
        (
            ("variables", "trust"),
            {"type": "enum", "values": ["a"], "initial": "b"},
            "invalid_value",
        ),
    ],
)
def test_invalid_game_contract_is_rejected(
    tmp_path: Path,
    path: tuple[str, ...],
    value: object,
    code: str,
) -> None:
    story = minimal_story()
    target = story
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    write_package(tmp_path, story)

    with pytest.raises(PackageError) as error:
        load_package(tmp_path)

    assert error.value.code == code


def test_creator_can_validate_choices_assignments_and_branch_conditions(tmp_path: Path) -> None:
    story = minimal_story()
    story["variables"] = {"trust": {"type": "int", "initial": 0}}
    story["nodes"]["hello"] = {
        "type": "choice",
        "text_id": "choice_text",
        "text": "Help the archivist?",
        "options": [
            {
                "id": "help",
                "text_id": "help_text",
                "text": "Help.",
                "target": "earn",
                "condition": {"op": "eq", "variable": "trust", "value": 0},
            }
        ],
    }
    story["nodes"]["earn"] = {
        "type": "set",
        "operations": [{"op": "increment", "variable": "trust", "value": 1}],
        "next": "check",
    }
    story["nodes"]["check"] = {
        "type": "branch",
        "condition": {"op": "ge", "variable": "trust", "value": 1},
        "if_true": "finish",
        "if_false": "hello",
    }
    write_package(tmp_path, story)

    package = load_package(tmp_path)

    assert package.story["nodes"]["hello"]["options"][0]["id"] == "help"
    assert any(warning.code == "structural_cycle" for warning in package.warnings)


@pytest.mark.parametrize(
    "condition",
    [
        {"op": "eq", "variable": "missing", "value": 0},
        {"op": "eq", "variable": "trust", "value": True},
        {"op": "eval", "variable": "trust", "value": 0},
        {"op": "all", "children": []},
        {"op": "all", "children": [{"op": "eq", "variable": "trust", "value": 0}] * 64},
    ],
)
def test_invalid_branch_conditions_cannot_reach_a_runtime(tmp_path: Path, condition: dict) -> None:
    story = minimal_story()
    story["variables"] = {"trust": {"type": "int", "initial": 0}}
    story["nodes"]["hello"] = {
        "type": "branch",
        "condition": condition,
        "if_true": "finish",
        "if_false": "finish",
    }
    write_package(tmp_path, story)

    with pytest.raises(PackageError):
        load_package(tmp_path)


def png_bytes(width: int = 1, height: int = 1) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    rows = (b"\x00" + b"\x66\x88\xaa\xff" * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def attach_asset(root: Path, data: bytes) -> dict:
    story = minimal_story()
    story["assets"] = {
        "portrait": {"path": "assets/portrait.png", "sha256": hashlib.sha256(data).hexdigest()}
    }
    story["nodes"]["hello"]["portrait"] = "portrait"
    (root / "assets").mkdir(exist_ok=True)
    (root / "assets/portrait.png").write_bytes(data)
    write_package(root, story)
    return story


def test_validated_assets_are_an_immutable_snapshot(tmp_path: Path) -> None:
    data = png_bytes()
    attach_asset(tmp_path, data)

    package = load_package(tmp_path)
    identity = package.content_hash
    (tmp_path / "assets/portrait.png").write_bytes(b"replaced after validation")

    assert package.assets[0].data == data
    assert package.assets[0].path == "assets/portrait.png"
    assert package.content_hash == identity


@pytest.mark.parametrize(
    "path",
    [
        "../private.png",
        "/private.png",
        "C:/private.png",
        "\\\\server/share/file.png",
        "assets/PORTRAIT.png",
    ],
)
def test_asset_paths_are_fixed_and_portable(tmp_path: Path, path: str) -> None:
    story = attach_asset(tmp_path, png_bytes())
    story["assets"]["portrait"]["path"] = path
    write_package(tmp_path, story)

    with pytest.raises(PackageError, match="unsafe_path"):
        load_package(tmp_path)


@pytest.mark.parametrize(
    "data",
    [
        b"not a PNG",
        png_bytes()[:-2],
        png_bytes() + b"trailing",
        png_bytes().replace(b"IDAT", b"IDaT"),
    ],
)
def test_corrupt_png_is_rejected_even_when_its_hash_matches(tmp_path: Path, data: bytes) -> None:
    attach_asset(tmp_path, data)

    with pytest.raises(PackageError, match="invalid_png"):
        load_package(tmp_path)


def test_changed_asset_hash_is_rejected(tmp_path: Path) -> None:
    attach_asset(tmp_path, png_bytes())
    (tmp_path / "assets/portrait.png").write_bytes(png_bytes(2))

    with pytest.raises(PackageError, match="hash_mismatch"):
        load_package(tmp_path)


@pytest.mark.parametrize("filename", ["agent.gd", "other.txt", "assets/private.png"])
def test_undeclared_package_files_are_rejected(tmp_path: Path, filename: str) -> None:
    write_package(tmp_path)
    (tmp_path / "assets").mkdir(exist_ok=True)
    (tmp_path / filename).write_bytes(b"unexpected input")

    with pytest.raises(PackageError, match="unexpected_file"):
        load_package(tmp_path)


def test_missing_package_input_does_not_expose_absolute_paths(tmp_path: Path) -> None:
    with pytest.raises(PackageError) as error:
        load_package(tmp_path)

    assert error.value.code == "missing_file"
    assert str(tmp_path) not in str(error.value)


def test_oversized_story_is_rejected_before_parsing(tmp_path: Path) -> None:
    write_package(tmp_path)
    (tmp_path / "story.json").write_bytes(b" " * (5 * 1024 * 1024 + 1))

    with pytest.raises(PackageError, match="size_limit"):
        load_package(tmp_path)


def test_linked_package_file_is_never_followed(tmp_path: Path) -> None:
    write_package(tmp_path)
    target = tmp_path.parent / (tmp_path.name + "-outside.txt")
    target.write_text("Private outside content", encoding="utf-8")
    (tmp_path / "NOTICES.txt").unlink()
    try:
        (tmp_path / "NOTICES.txt").symlink_to(target)
    except OSError:
        pytest.skip("Host does not permit unprivileged file symlinks")

    with pytest.raises(PackageError, match="unsafe_path"):
        load_package(tmp_path)


def test_original_mystery_has_three_reviewable_routes() -> None:
    root = Path(__file__).parents[1] / "fixtures/narrative/lantern_archive"

    package = load_package(root)

    assert package.story["id"] == "lantern_archive"
    assert {
        node["ending"] for node in package.story["nodes"].values() if node["type"] == "end"
    } == {
        "restored",
        "quiet",
        "hasty",
    }
    assert len(package.assets) == 2
    assert package.warnings == ()
    # Also checked with PowerShell Get-FileHash over the literal package manifest.
    assert package.content_hash == (
        "057e54a191c2a79d35a52a2d3502d749e214058b79214d5e967a9afb894b3850"
    )


def test_canonical_story_bytes_have_an_independent_literal_golden(tmp_path: Path) -> None:
    story = minimal_story()
    story["title"] = "Pagi — 朝"
    write_package(tmp_path, story)
    expected = (
        '{"assets":{},"characters":{},"entry":"hello","id":"first_game","language":"en",'
        '"nodes":{"finish":{"ending":"dawn","text":"Dawn.","text_id":"end_text","type":"end"},'
        '"hello":{"next":"finish","text":"Pagi arrives.","text_id":"hello_text","type":"line"}},'
        '"schema_version":"1","title":"Pagi — 朝","variables":{}}'
    ).encode()

    assert load_package(tmp_path).canonical_story == expected


def framed_png(color: int, depth: int, chunks: list[tuple[bytes, bytes]]) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", 1, 1, depth, color, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + b"".join(chunk(kind, data) for kind, data in chunks)
        + chunk(b"IEND", b"")
    )


@pytest.mark.parametrize(
    ("color", "depth", "chunks"),
    [
        (6, 8, [(b"tRNS", b"\x00"), (b"IDAT", zlib.compress(b"\x00" * 5))]),
        (0, 8, [(b"tRNS", b"\x00"), (b"IDAT", zlib.compress(b"\x00" * 2))]),
        (2, 8, [(b"tRNS", b"\x00" * 2), (b"IDAT", zlib.compress(b"\x00" * 4))]),
        (3, 1, [(b"PLTE", b"\x00" * 9), (b"IDAT", zlib.compress(b"\x00" * 2))]),
        (
            3,
            1,
            [(b"PLTE", b"\x00" * 3), (b"tRNS", b"\x00" * 2), (b"IDAT", zlib.compress(b"\x00" * 2))],
        ),
        (2, 8, [(b"IDAT", b""), (b"PLTE", b"\x00" * 3), (b"IDAT", zlib.compress(b"\x00" * 4))]),
        (6, 8, [(b"sRGB", b"\xff"), (b"IDAT", zlib.compress(b"\x00" * 5))]),
    ],
)
def test_crc_correct_invalid_png_chunk_rules_are_rejected(
    tmp_path: Path,
    color: int,
    depth: int,
    chunks: list[tuple[bytes, bytes]],
) -> None:
    attach_asset(tmp_path, framed_png(color, depth, chunks))

    with pytest.raises(PackageError, match="invalid_png"):
        load_package(tmp_path)


@pytest.mark.parametrize("source", [None, [], 3, "game"])
def test_non_object_json_root_has_a_controlled_error(tmp_path: Path, source: object) -> None:
    write_package(tmp_path)
    (tmp_path / "story.json").write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(PackageError, match="invalid_object"):
        load_package(tmp_path)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("nodes", "hello", "type"), {}),
        (("nodes", "hello", "text"), []),
        (("variables", "trust"), {"type": {}, "initial": 0}),
        (("characters", "mira"), None),
        (("nodes", "hello", "next"), False),
    ],
)
def test_malformed_field_types_never_escape_as_python_errors(
    tmp_path: Path,
    path: tuple[str, ...],
    value: object,
) -> None:
    story = minimal_story()
    target = story
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    write_package(tmp_path, story)

    with pytest.raises(PackageError):
        load_package(tmp_path)


@pytest.mark.parametrize(
    ("depth", "children", "valid"), [(7, 0, True), (8, 0, False), (0, 63, True), (0, 64, False)]
)
def test_condition_limits_accept_the_boundary_and_reject_the_next_value(
    tmp_path: Path,
    depth: int,
    children: int,
    valid: bool,
) -> None:
    story = minimal_story()
    story["variables"] = {"trust": {"type": "int", "initial": 0}}
    comparison = {"op": "eq", "variable": "trust", "value": 0}
    value = {"op": "all", "children": [comparison] * children} if children else comparison
    for _ in range(depth):
        value = {"op": "not", "child": value}
    story["nodes"]["hello"] = {
        "type": "branch",
        "condition": value,
        "if_true": "finish",
        "if_false": "finish",
    }
    write_package(tmp_path, story)

    if valid:
        assert load_package(tmp_path).story["entry"] == "hello"
    else:
        with pytest.raises(PackageError, match="condition_limit"):
            load_package(tmp_path)


@pytest.mark.parametrize(
    "data",
    [
        png_bytes(4097),
        framed_png(6, 8, [(b"IDAT", zlib.compress(b"\x05" + b"\x00" * 4))]),
        framed_png(6, 8, [(b"IDAT", zlib.compress(b"\x00" * 2000000))]),
    ],
)
def test_png_dimensions_filters_and_inflated_length_are_bounded(
    tmp_path: Path, data: bytes
) -> None:
    attach_asset(tmp_path, data)

    with pytest.raises(PackageError, match="invalid_png"):
        load_package(tmp_path)


def test_indexed_png_requires_a_complete_palette_for_the_supported_subset(tmp_path: Path) -> None:
    # A one-entry palette cannot decode this pixel's index 1.
    data = framed_png(3, 1, [(b"PLTE", b"\x00" * 3), (b"IDAT", zlib.compress(b"\x00\x80"))])
    attach_asset(tmp_path, data)
    with pytest.raises(PackageError, match="invalid_png"):
        load_package(tmp_path)

    data = framed_png(3, 1, [(b"PLTE", b"\x00" * 6), (b"IDAT", zlib.compress(b"\x00\x80"))])
    attach_asset(tmp_path, data)
    assert load_package(tmp_path).assets[0].data == data


def test_package_identity_ignores_json_layout_but_includes_notices_and_assets(
    tmp_path: Path,
) -> None:
    story = attach_asset(tmp_path, png_bytes())
    original = load_package(tmp_path).content_hash
    (tmp_path / "story.json").write_text(
        json.dumps(story, indent=4, sort_keys=True), encoding="utf-8"
    )
    assert load_package(tmp_path).content_hash == original

    (tmp_path / "NOTICES.txt").write_text("Revised notices\n", encoding="utf-8")
    assert load_package(tmp_path).content_hash != original
    write_package(tmp_path, story)
    data = png_bytes(2)
    story["assets"]["portrait"]["sha256"] = hashlib.sha256(data).hexdigest()
    (tmp_path / "assets/portrait.png").write_bytes(data)
    write_package(tmp_path, story)
    assert load_package(tmp_path).content_hash != original


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction/reparse boundary")
def test_windows_asset_junction_is_rejected_without_reading_outside(tmp_path: Path) -> None:
    write_package(tmp_path)
    target = tmp_path.parent / (tmp_path.name + "-private")
    target.mkdir()
    (target / "private.png").write_bytes(b"private canary")
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(tmp_path / "assets"), str(target)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("Host does not permit a local directory junction")
    try:
        with pytest.raises(PackageError, match="unsafe_path"):
            load_package(tmp_path)
        assert (target / "private.png").read_bytes() == b"private canary"
    finally:
        # rmdir removes this exact owned junction; it does not traverse the target.
        (tmp_path / "assets").rmdir()
