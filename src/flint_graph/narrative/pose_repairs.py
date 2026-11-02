"""Bounded regions and independent pixel preservation for local pose repairs."""

import hashlib
import struct
import zlib

from flint_graph.narrative.png import validate_png


def validate_region(box: list[int] | tuple[int, ...], width: int, height: int) -> None:
    if len(box) != 4 or any(type(value) is not int for value in box):
        raise ValueError("invalid_repair_region")

    left, top, right, bottom = box
    if not (
        0 <= left < right <= width
        and 0 <= top < bottom <= height
        and right - left >= 16
        and bottom - top >= 16
        and (right - left) * (bottom - top) * 4 <= width * height
    ):
        raise ValueError("invalid_repair_region")


def _pixels(data: bytes) -> tuple[int, int, int, bytes]:
    if len(data) > 16 * 1024**2 or len(data) < 45:
        raise ValueError("repair_preservation_failed")
    width, height, depth, color, compression, filtering, interlace = struct.unpack_from(
        ">IIBBBBB", data, 16
    )
    if not (
        32 <= width <= 768
        and 32 <= height <= 1152
        and depth == 8
        and color in (2, 6)
        and compression == filtering == interlace == 0
    ):
        raise ValueError("repair_preservation_failed")
    validate_png(data, "repair")
    channels = 3 if color == 2 else 4
    compressed = bytearray()
    offset = 8
    while offset < len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        if data[offset + 4 : offset + 8] == b"tRNS":
            # Pose images encode alpha as RGBA, never as a color-key chunk.
            raise ValueError("repair_preservation_failed")
        if data[offset + 4 : offset + 8] == b"IDAT":
            compressed.extend(data[offset + 8 : offset + 8 + length])
        offset += length + 12
    stride = width * channels
    decoder = zlib.decompressobj()
    encoded = decoder.decompress(compressed, (stride + 1) * height + 1)
    if (
        len(encoded) != (stride + 1) * height
        or not decoder.eof
        or decoder.unconsumed_tail
        or decoder.unused_data
    ):
        raise ValueError("repair_preservation_failed")
    pixels = bytearray(stride * height)
    for y in range(height):
        row_offset = y * (stride + 1)
        kind = encoded[row_offset]
        for x in range(stride):
            left = pixels[y * stride + x - channels] if x >= channels else 0
            up = pixels[(y - 1) * stride + x] if y else 0
            corner = pixels[(y - 1) * stride + x - channels] if y and x >= channels else 0
            if kind == 0:
                predictor = 0
            elif kind == 1:
                predictor = left
            elif kind == 2:
                predictor = up
            elif kind == 3:
                predictor = (left + up) // 2
            else:
                p = left + up - corner
                a, b, c = abs(p - left), abs(p - up), abs(p - corner)
                predictor = left if a <= b and a <= c else up if b <= c else corner
            pixels[y * stride + x] = (encoded[row_offset + 1 + x] + predictor) & 255
    return width, height, channels, bytes(pixels)


def verify_preservation(source: bytes, result: bytes, box: list[int] | tuple[int, ...]) -> str:
    """Return an outside-pixel digest only after exact decoded-byte comparisons."""
    try:
        width, height, channels, original = _pixels(source)
        rw, rh, rc, repaired = _pixels(result)
        if (rw, rh, rc) != (width, height, channels):
            raise ValueError
        validate_region(box, width, height)
        left, top, right, bottom = box
        digest = hashlib.sha256()
        for y in range(height):
            segments = ((0, width),) if y < top or y >= bottom else ((0, left), (right, width))
            for start, end in segments:
                a, b = (y * width + start) * channels, (y * width + end) * channels
                if original[a:b] != repaired[a:b]:
                    raise ValueError
                digest.update(original[a:b])
        return digest.hexdigest()
    except (ValueError, struct.error, zlib.error):
        raise ValueError("repair_preservation_failed") from None
