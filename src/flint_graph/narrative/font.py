"""Bounded structural checks for uploaded TrueType/OpenType fonts (ADR 0040).

Godot parses font bytes with its own font engine. Before any bytes are stored or
shipped, the sfnt header and table directory must be well formed. Every table must
lie inside the file without overlapping another, and the tables a renderer needs
must be present. Collections and WOFF/WOFF2 are not accepted.
"""

import struct
from itertools import pairwise

from flint_graph.narrative.values import PackageError

FONT_LIMIT = 8 * 1024 * 1024
MAX_TABLES = 64
_TRUETYPE = (b"\x00\x01\x00\x00", b"true")
_REQUIRED = {b"head", b"name", b"cmap"}
# Colour, bitmap, SVG, Graphite and AAT tables are not needed for story text and
# reach rarely exercised parsers. Uploaded fonts ship inside games on other people's
# devices, so these are refused outright.
_REFUSED = {
    b"SVG ",
    b"COLR",
    b"CPAL",
    b"sbix",
    b"CBDT",
    b"CBLC",
    b"EBDT",
    b"EBLC",
    b"EBSC",
    b"Silf",
    b"Glat",
    b"Gloc",
    b"Feat",
    b"Sill",
    b"morx",
    b"mort",
    b"kerx",
    b"ankr",
}
# Variation tables drive the most complex (and historically exploited) glyph code.
# Static instances are always available (Google Fonts ships them in `static/`).
_VARIABLE = {b"fvar", b"gvar", b"avar", b"cvar", b"HVAR", b"VVAR", b"MVAR", b"CFF2"}
_RESTRICTED_EMBEDDING = 0x0002


def validate_font(data: bytes, location: str) -> str:
    """Return ``"ttf"`` or ``"otf"`` for an acceptable font, else raise."""

    def reject() -> None:
        raise PackageError("invalid_font", location)

    if not isinstance(data, bytes) or not 12 <= len(data) <= FONT_LIMIT:
        reject()
    version = data[:4]
    if version not in (*_TRUETYPE, b"OTTO"):
        reject()
    count = struct.unpack_from(">H", data, 4)[0]
    if not 1 <= count <= MAX_TABLES or 12 + 16 * count > len(data):
        reject()
    tags: list[bytes] = []
    spans: list[tuple[int, int]] = []
    for index in range(count):
        tag, _checksum, offset, length = struct.unpack_from(">4sIII", data, 12 + 16 * index)
        if (
            not all(0x20 <= byte <= 0x7E for byte in tag)
            or (tags and tag <= tags[-1])
            or offset < 12 + 16 * count
            or length == 0
            or offset + length > len(data)
        ):
            reject()
        tags.append(tag)
        spans.append((offset, offset + length))
    spans.sort()
    if any(start < previous_end for (_, previous_end), (start, _) in pairwise(spans)):
        reject()
    present = set(tags)
    outlines = {b"glyf", b"loca"} <= present if version in _TRUETYPE else b"CFF " in present
    if not _REQUIRED <= present or not outlines or present & _REFUSED:
        reject()
    if present & _VARIABLE:
        raise PackageError("font_variable", location)
    if b"OS/2" in present:
        offset, end = _span(data, count, b"OS/2")
        if end - offset < 10:
            reject()
        # A restricted-licence font may not be embedded, and a game embeds its fonts.
        if struct.unpack_from(">H", data, offset + 8)[0] & 0x000F == _RESTRICTED_EMBEDDING:
            raise PackageError("font_embedding_restricted", location)
    return "otf" if version == b"OTTO" else "ttf"


def _span(data: bytes, count: int, wanted: bytes) -> tuple[int, int]:
    for index in range(count):
        tag, _checksum, offset, length = struct.unpack_from(">4sIII", data, 12 + 16 * index)
        if tag == wanted:
            return offset, offset + length
    raise PackageError("invalid_font", "font")
