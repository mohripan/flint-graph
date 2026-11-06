"""A first guess at where a sprite's face is, for expressions the assistant starts.

The Studio's expression tool makes this guess in the browser and lets the creator
adjust it. The assistant has no such step, so the server makes the same guess: this
mirrors ``faceBoxFromAlpha`` in ``frontend/src/narrative/expressionModel.ts``. It reads
only the alpha channel: PNG filters work per channel, so the other channels can be
skipped. Pure Python, so pass a thumbnail when one exists.
"""

import struct
import zlib

Box = tuple[int, int, int, int]

MIN_FACE = 16
MAX_PIXELS = 2560 * 2560
_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}
_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _clamp(box: tuple[float, float, float, float], width: int, height: int) -> Box:
    left, top, right, bottom = box

    def side(value: float, limit: int) -> int:
        return round(min(max(value, MIN_FACE), limit))

    w, h = side(right - left, width), side(bottom - top, height)
    x = round(min(max(left, 0), width - w))
    y = round(min(max(top, 0), height - h))
    return (x, y, x + w, y + h)


def _alpha_rows(data: bytes) -> tuple[int, int, list[bytes] | None]:
    """Width, height and alpha rows; rows are ``None`` for an image with no alpha channel."""
    if data[:8] != _SIGNATURE or len(data) < 45 or data[12:16] != b"IHDR":
        raise ValueError("Not a PNG")
    width, height, depth, color, _, _, interlace = struct.unpack_from(">IIBBBBB", data, 16)
    if not width or not height or width * height > MAX_PIXELS or depth != 8 or interlace:
        raise ValueError("Unsupported PNG")
    if color not in _CHANNELS:
        raise ValueError("Unsupported PNG")
    if color in (0, 2):
        return width, height, None
    compressed = bytearray()
    offset = 8
    while offset + 8 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        if data[offset + 4 : offset + 8] == b"IDAT":
            compressed.extend(data[offset + 8 : offset + 8 + length])
        offset += length + 12
    channels = _CHANNELS[color]
    stride = width * channels
    size = (stride + 1) * height
    decoder = zlib.decompressobj()
    encoded = decoder.decompress(bytes(compressed), size + 1)
    if len(encoded) != size:
        raise ValueError("Truncated PNG")
    rows: list[bytes] = []
    previous = bytes(width)
    for y in range(height):
        start = y * (stride + 1)
        kind = encoded[start]
        # Alpha is the last byte of each pixel, and each channel unfilters on its own.
        filtered = encoded[start + channels :: channels][:width]
        row = bytearray(filtered)
        if kind == 1:
            for x in range(1, width):
                row[x] = (filtered[x] + row[x - 1]) & 255
        elif kind == 2:
            row = bytearray((a + b) & 255 for a, b in zip(filtered, previous, strict=True))
        elif kind == 3:
            for x in range(width):
                left = row[x - 1] if x else 0
                row[x] = (filtered[x] + (left + previous[x]) // 2) & 255
        elif kind == 4:
            for x in range(width):
                left = row[x - 1] if x else 0
                corner = previous[x - 1] if x else 0
                up = previous[x]
                estimate = left + up - corner
                a, b, c = abs(estimate - left), abs(estimate - up), abs(estimate - corner)
                predictor = left if a <= b and a <= c else up if b <= c else corner
                row[x] = (filtered[x] + predictor) & 255
        elif kind != 0:
            raise ValueError("Unsupported PNG")
        rows.append(bytes(row))
        previous = rows[-1]
    return width, height, rows


def face_box_from_png(data: bytes, size: tuple[int, int]) -> Box:
    """The face box for an image of ``size``, measured on ``data`` (itself or its thumbnail)."""
    try:
        width, height, rows = _alpha_rows(data)
    except (struct.error, zlib.error, IndexError) as error:
        raise ValueError("Unreadable PNG") from error
    full_width, full_height = size
    scale_x, scale_y = full_width / width, full_height / height
    top, bottom = -1, -1
    transparent = rows is None
    if rows is not None:
        transparent = False
        for y, row in enumerate(rows):
            filled = max(row) > 128
            if min(row) <= 128:
                transparent = True
            if filled:
                if top < 0:
                    top = y
                bottom = y
    if rows is None or not transparent or top < 0:
        # No cut-out to measure: a portrait-style guess, like the Studio's.
        face = round(min(full_width, full_height) * 0.3)
        centre_x, centre_y = full_width / 2, full_height * 0.2
        half = face / 2
        return _clamp(
            (centre_x - half, centre_y - half, centre_x + half, centre_y + half),
            full_width,
            full_height,
        )
    figure = bottom - top + 1
    total = count = 0
    for y in range(top, min(height, top + max(1, round(figure * 0.12)))):
        for x, value in enumerate(rows[y]):
            if value > 128:
                total += x
                count += 1
    centre_x = (total / count if count else width / 2) + 0.5
    centre_y = top + figure * 0.075
    # Sizes are measured in the full image, so a thumbnail gives the same box.
    half = max(MIN_FACE, round(figure * scale_y * 0.11)) / 2
    return _clamp(
        (
            centre_x * scale_x - half,
            centre_y * scale_y - half,
            centre_x * scale_x + half,
            centre_y * scale_y + half,
        ),
        full_width,
        full_height,
    )
