"""Preservation is checked from decoded pixels, independently of child compositing."""

import hashlib
import struct
import zlib

import pytest

from flint_graph.narrative.pose_repairs import verify_preservation


def png(rows, width, channels, filters=False):
    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    raw = bytearray()
    for index, row in enumerate(rows):
        kind = index % 5 if filters else 0
        # The source is constant. These are the independently worked PNG residuals
        # for None/Sub/Up/Average/Paeth; the expected colors are (10,20,30[,128]).
        if kind == 0:
            encoded = row
        elif kind == 1:
            encoded = row[:channels] + bytes(len(row) - channels)
        elif kind in (2, 4):
            encoded = bytes(len(row))
        else:
            encoded = bytes([5, 10, 15] + ([64] if channels == 4 else [])) + bytes(
                len(row) - channels
            )
        raw.extend(bytes([kind]) + encoded)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, len(rows), 8, 6 if channels == 4 else 2, 0, 0, 0),
        )
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.mark.parametrize("channels", [3, 4])
def test_filters_and_alpha_are_decoded_before_checking_the_unchanged_area(channels):
    pixel = bytes([10, 20, 30] + ([128] if channels == 4 else []))
    rows = [bytearray(pixel * 40) for _ in range(48)]
    source = png(rows, 40, channels, filters=True)
    for y in range(16, 32):
        rows[y][16 * channels : 32 * channels] = (
            bytes([90, 80, 70] + ([240] if channels == 4 else [])) * 16
        )
    repaired = png(rows, 40, channels)
    # There are 1664 unchanged pixels, all the literal source color.
    expected = hashlib.sha256(pixel * 1664).hexdigest()
    assert verify_preservation(source, repaired, [16, 16, 32, 32]) == expected
    rows[0][0] = 11
    with pytest.raises(ValueError, match="repair_preservation_failed"):
        verify_preservation(source, png(rows, 40, channels), [16, 16, 32, 32])


def test_output_dimensions_and_channels_cannot_change():
    source = png([bytes([10, 20, 30]) * 40 for _ in range(48)], 40, 3)
    for changed in (
        png([bytes([10, 20, 30]) * 41 for _ in range(48)], 41, 3),
        png([bytes([10, 20, 30, 255]) * 40 for _ in range(48)], 40, 4),
    ):
        with pytest.raises(ValueError, match="repair_preservation_failed"):
            verify_preservation(source, changed, [16, 16, 32, 32])


def test_transparency_chunks_cannot_bypass_the_alpha_preservation_check():
    source = png([bytes([10, 20, 30]) * 40 for _ in range(48)], 40, 3)
    kind, payload = b"tRNS", struct.pack(">HHH", 10, 20, 30)
    transparency = (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload))
    )
    with pytest.raises(ValueError, match="repair_preservation_failed"):
        verify_preservation(source, source[:33] + transparency + source[33:], [16, 16, 32, 32])


def test_an_outside_alpha_change_is_rejected_even_when_rgb_is_identical():
    rows = [bytearray(bytes([10, 20, 30, 128]) * 40) for _ in range(48)]
    source = png(rows, 40, 4)
    rows[0][3] = 129
    with pytest.raises(ValueError, match="repair_preservation_failed"):
        verify_preservation(source, png(rows, 40, 4), [16, 16, 32, 32])
