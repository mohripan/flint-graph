"""Scripted stand-in for runtimes/imagegen/generate.py used by offline tests.

The behaviour is chosen by the first word of the prompt, so tests exercise the
real parent: process start, stdin/stdout protocol, watchdog and file checks.
"""

import json
import struct
import sys
import time
import zlib
from pathlib import Path


def png(width: int, height: int, shade: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    row = b"\x00" + bytes([shade, 64, 128]) * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height, 9))
        + chunk(b"IEND", b"")
    )


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"protocol": 1, "event": event, **fields}), flush=True)


request = json.loads(sys.stdin.read())
mode = request["prompt"].split(",")[0]
output = Path(request["output_dir"])
width, height = request["width"], request["height"]
if mode == "busy":
    emit("busy", free_bytes=1, required_bytes=2)
    emit("error", code="gpu_busy")
    raise SystemExit(2)
if mode == "hang":
    time.sleep(60)
if mode == "noisy":
    for _ in range(500):
        print("x" * 100, flush=True)
if mode == "crash":
    raise SystemExit(9)
emit(
    "loaded",
    seconds=0.1,
    prompt_tokens=81 if mode == "long" else 12,
    truncated=mode == "long",
    runtime={"torch": "fake", "diffusers": "fake", "cuda": "0", "device": "Fake GPU"},
)
for index, seed in enumerate(request["seeds"]):
    image = png(width + (1 if mode == "wrongsize" else 0), height, index * 40)
    if mode == "badpng":
        image = image[:-5]
    (output / f"{index}.png").write_bytes(image)
    (output / f"{index}.thumb.png").write_bytes(png(256, round(height * 256 / width), index * 40))
    emit(
        "image",
        index=index,
        file=f"{index}.png",
        thumbnail=f"{index}.thumb.png",
        seed=seed + (1 if mode == "wrongseed" else 0),
        seconds=0.1,
    )
if mode == "extra":
    (output / "notes.txt").write_text("unexpected")
emit("done", peak_bytes=1)
