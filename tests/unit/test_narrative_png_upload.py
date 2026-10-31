"""Uploaded PNGs: metadata chunks editors add are dropped losslessly before checks."""

import struct
import zlib

import pytest

from flint_graph.narrative.png import normalize_png, validate_png
from flint_graph.narrative.values import PackageError


def chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload))
    )


IHDR = chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0))
IDAT = chunk(b"IDAT", zlib.compress((b"\x00" + b"\x10\x20\x30\xff" * 2) * 2))
IEND = chunk(b"IEND", b"")
SIGNATURE = b"\x89PNG\r\n\x1a\n"


def test_editor_metadata_is_dropped_and_pixels_are_untouched():
    noisy = (
        SIGNATURE
        + IHDR
        + chunk(b"iCCP", b"profile\x00\x00" + zlib.compress(b"icc"))
        + chunk(b"sRGB", b"\x00")
        + chunk(b"bKGD", b"\x00\x00\x00\x00\x00\x00")
        + chunk(b"tEXt", b"Software\x00GIMP")
        + chunk(b"tIME", b"\x07\xea\x0a\x1f\x0c\x00\x00")
        + IDAT
        + chunk(b"iTXt", b"XML:com.adobe.xmp\x00\x00\x00\x00\x00<x/>")
        + IEND
    )
    with pytest.raises(PackageError):
        validate_png(noisy, "file")
    clean = normalize_png(noisy, "file")
    assert clean == SIGNATURE + IHDR + chunk(b"sRGB", b"\x00") + IDAT + IEND
    validate_png(clean, "file")
    assert normalize_png(clean, "file") == clean, "Already clean files are unchanged"


@pytest.mark.parametrize(
    "data",
    [
        SIGNATURE + IHDR + chunk(b"ABCD", b"x") + IDAT + IEND,
        SIGNATURE + IHDR + IDAT[:-1] + b"\x00" + IEND,
        b"GIF89a" + IHDR,
        SIGNATURE + IHDR + IDAT + IEND + b"trailing",
    ],
    ids=["unknown-critical", "bad-crc", "not-png", "trailing-bytes"],
)
def test_unknown_critical_chunks_and_corruption_are_rejected(data):
    with pytest.raises(PackageError):
        normalize_png(data, "file")
