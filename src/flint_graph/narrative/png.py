"""Validate bounded PNG framing/scanlines before handing bytes to an engine."""

import struct
import zlib

from flint_graph.narrative.values import PackageError


def validate_png(data: bytes, location: str) -> None:
    def reject() -> None:
        raise PackageError("invalid_png", location)

    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        reject()
    offset = 8
    header: bytes | None = None
    compressed = bytearray()
    palette_entries = 0
    transparency: bytes | None = None
    ended = False
    seen_idat = False
    idat_closed = False
    allowed_metadata = {b"sRGB": 1, b"gAMA": 4, b"cHRM": 32, b"pHYs": 9}
    seen: set[bytes] = set()
    while offset < len(data):
        if offset + 12 > len(data):
            reject()
        length, kind = struct.unpack_from(">I4s", data, offset)
        end = offset + 12 + length
        if end > len(data):
            reject()
        payload = data[offset + 8 : end - 4]
        checksum = struct.unpack_from(">I", data, end - 4)[0]
        if zlib.crc32(kind + payload) != checksum or ended:
            reject()
        if header is None and kind != b"IHDR":
            reject()
        if kind == b"IHDR":
            if header is not None or length != 13:
                reject()
            header = payload
        elif kind == b"IDAT":
            if idat_closed:
                reject()
            seen_idat = True
            compressed.extend(payload)
        elif kind == b"IEND":
            if length != 0 or not compressed or end != len(data):
                reject()
            ended = True
        elif kind == b"PLTE":
            if kind in seen or seen_idat or b"tRNS" in seen or not 3 <= length <= 768 or length % 3:
                reject()
            palette_entries = length // 3
        elif kind == b"tRNS":
            if kind in seen or seen_idat or not 1 <= length <= 256:
                reject()
            transparency = payload
        elif kind in allowed_metadata:
            if (
                kind in seen
                or seen_idat
                or length != allowed_metadata[kind]
                or (kind != b"pHYs" and palette_entries)
            ):
                reject()
            if (
                (kind == b"sRGB" and payload[0] > 3)
                or (kind == b"pHYs" and payload[-1] > 1)
                or (kind == b"gAMA" and int.from_bytes(payload, "big") == 0)
            ):
                reject()
        else:
            # Deliberate initial subset: no compressed profiles/text, APNG or unknown chunks.
            reject()
        if seen_idat and kind != b"IDAT":
            idat_closed = True
        seen.add(kind)
        offset = end
    if header is None or not ended:
        reject()
    assert header is not None
    width, height, depth, color, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", header
    )
    depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
    if (
        not 1 <= width <= 4096
        or not 1 <= height <= 4096
        or width * height > 16777216
        or depth not in depths.get(color, ())
        or compression != 0
        or filtering != 0
        or interlace not in (0, 1)
        # Complete indexed palettes avoid accepting out-of-range pixel indexes
        # without adding a second full pixel unfiltering/Adam7 decoder here.
        or (color == 3 and palette_entries != 2**depth)
        or (color in (0, 4) and palette_entries)
    ):
        reject()
    if transparency is not None and (
        (color == 0 and len(transparency) != 2)
        or (color == 2 and len(transparency) != 6)
        or (color == 3 and len(transparency) > palette_entries)
        or color in (4, 6)
    ):
        reject()
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    passes = (
        [(0, 0, 1, 1)]
        if interlace == 0
        else [
            (0, 0, 8, 8),
            (4, 0, 8, 8),
            (0, 4, 4, 8),
            (2, 0, 4, 4),
            (0, 2, 2, 4),
            (1, 0, 2, 2),
            (0, 1, 1, 2),
        ]
    )
    rows: list[tuple[int, int]] = []
    for x, y, dx, dy in passes:
        columns = max(0, (width - x + dx - 1) // dx)
        count = max(0, (height - y + dy - 1) // dy)
        if columns and count:
            rows.append((count, 1 + (columns * channels * depth + 7) // 8))
    expected = sum(count * length for count, length in rows)
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, expected + 1)
    except zlib.error:
        reject()
    if len(raw) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        reject()
    offset = 0
    for count, length in rows:
        for _ in range(count):
            if raw[offset] > 4:
                reject()
            offset += length
