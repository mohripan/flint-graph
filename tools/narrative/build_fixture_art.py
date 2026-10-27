"""Reproduce original fixture PNGs with no external imaging dependency."""

import hashlib
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "tests/fixtures/narrative/lantern_archive/assets"


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def image(width: int, height: int, portrait: bool) -> bytes:
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            if portrait:
                inside = (x - width // 2) ** 2 + (y - height // 3) ** 2 < (width // 5) ** 2
                coat = abs(x - width // 2) < width // 3 and y > height // 2
                color = (
                    (234, 190, 145, 255)
                    if inside
                    else ((82, 108, 137, 255) if coat else (0, 0, 0, 0))
                )
            else:
                shelf = y % 20 > 15 or x % 32 < 3
                color = (48, 39, 48, 255) if shelf else (39 + x // 8, 46, 67 + y // 8, 255)
            rows.extend(color)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows), level=9))
        + chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, width, height, portrait in [
        ("archive", 320, 180, False),
        ("archivist", 96, 128, True),
    ]:
        data = image(width, height, portrait)
        (ROOT / (name + ".png")).write_bytes(data)
        print(name, hashlib.sha256(data).hexdigest())
