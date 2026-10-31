"""Uploaded fonts: bounded sfnt structure checks before Godot ever parses the bytes."""

import struct
from pathlib import Path

import pytest

from flint_graph.narrative.font import FONT_LIMIT, validate_font
from flint_graph.narrative.values import PackageError

LORA = (Path(__file__).parents[2] / "runtimes/godot/fonts/Lora.ttf").read_bytes()


def sfnt(version: bytes, tables: dict[bytes, bytes]) -> bytes:
    count = len(tables)
    header = version + struct.pack(">HHHH", count, 16, 4, 0)
    offset = 12 + 16 * count
    directory, body = b"", b""
    for tag in sorted(tables):
        data = tables[tag]
        directory += tag + struct.pack(">III", 0, offset + len(body), len(data))
        body += data + b"\0" * (-len(data) % 4)
    return header + directory + body


TRUETYPE = {tag: b"x" * 8 for tag in (b"cmap", b"glyf", b"head", b"loca", b"name")}


def test_minimal_static_fonts_are_accepted_with_their_format():
    assert validate_font(sfnt(b"\x00\x01\x00\x00", TRUETYPE), "font") == "ttf"
    assert validate_font(sfnt(b"true", TRUETYPE), "font") == "ttf"
    cff = {tag: b"y" * 4 for tag in (b"CFF ", b"cmap", b"head", b"name")}
    assert validate_font(sfnt(b"OTTO", cff), "font") == "otf"


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"wOFF" + LORA[4:],
        b"wOF2" + LORA[4:],
        b"ttcf" + LORA[4:],
        LORA[:200],
        sfnt(b"\x00\x01\x00\x00", {k: v for k, v in TRUETYPE.items() if k != b"cmap"}),
        sfnt(b"OTTO", {tag: b"y" * 4 for tag in (b"cmap", b"head", b"name")}),
        b"\x00\x01\x00\x00" + struct.pack(">HHHH", 0, 0, 0, 0),
        b"\x00" * (FONT_LIMIT + 1),
    ],
    ids=[
        "empty",
        "woff",
        "woff2",
        "collection",
        "truncated",
        "no-cmap",
        "otf-without-cff",
        "no-tables",
        "too-large",
    ],
)
def test_malformed_or_unsupported_fonts_are_rejected(data):
    with pytest.raises(PackageError):
        validate_font(data, "font")


@pytest.mark.parametrize(
    "table", [b"SVG ", b"COLR", b"CPAL", b"sbix", b"CBDT", b"EBDT", b"Silf", b"morx"]
)
def test_color_bitmap_svg_and_shaping_engine_tables_are_rejected(table):
    # Text fonts need none of these; they reach rarely used, complex parsers.
    with pytest.raises(PackageError):
        validate_font(sfnt(b"\x00\x01\x00\x00", {**TRUETYPE, table: b"z" * 8}), "font")


def test_variable_fonts_and_restricted_embedding_are_refused_with_their_own_codes():
    with pytest.raises(PackageError, match="font_variable"):
        validate_font(LORA, "font")  # The bundled Lora is a variable font.
    variable = {**TRUETYPE, b"fvar": b"v" * 8, b"gvar": b"v" * 8}
    with pytest.raises(PackageError, match="font_variable"):
        validate_font(sfnt(b"\x00\x01\x00\x00", variable), "font")
    static_with_stat = {**TRUETYPE, b"STAT": b"v" * 8}
    assert validate_font(sfnt(b"\x00\x01\x00\x00", static_with_stat), "font") == "ttf"
    restricted = b"\x00" * 8 + struct.pack(">H", 0x0002) + b"\x00" * 6
    with pytest.raises(PackageError, match="font_embedding_restricted"):
        validate_font(sfnt(b"\x00\x01\x00\x00", {**TRUETYPE, b"OS/2": restricted}), "font")
    editable = b"\x00" * 8 + struct.pack(">H", 0x0008) + b"\x00" * 6
    assert (
        validate_font(sfnt(b"\x00\x01\x00\x00", {**TRUETYPE, b"OS/2": editable}), "font") == "ttf"
    )


def test_overlapping_or_out_of_bounds_tables_are_rejected():
    good = sfnt(b"\x00\x01\x00\x00", TRUETYPE)
    # Point the second table into the first table's bytes.
    first_offset = struct.unpack_from(">I", good, 12 + 8)[0]
    overlapping = bytearray(good)
    struct.pack_into(">I", overlapping, 12 + 16 + 8, first_offset)
    with pytest.raises(PackageError):
        validate_font(bytes(overlapping), "font")
    beyond = bytearray(good)
    struct.pack_into(">I", beyond, 12 + 12, 10_000_000)
    with pytest.raises(PackageError):
        validate_font(bytes(beyond), "font")
    unsorted = bytearray(good)
    unsorted[12:16], unsorted[28:32] = good[28:32], good[12:16]
    with pytest.raises(PackageError):
        validate_font(bytes(unsorted), "font")
