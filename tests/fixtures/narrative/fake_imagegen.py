"""Scripted stand-in for runtimes/imagegen/generate.py used by offline tests.

The behaviour is chosen by the first word of the prompt, so tests exercise the
real parent: process start, stdin/stdout protocol, watchdog and file checks.
"""

import hashlib
import json
import struct
import sys
import time
import zlib
from pathlib import Path


def chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload))
    )


def png(width: int, height: int, shade: int, alpha: bool = False) -> bytes:
    row = b"\x00" + bytes([shade, 64, 128, 255][: 4 if alpha else 3]) * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height, 9))
        + chunk(b"IEND", b"")
    )


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"protocol": 1, "event": event, **fields}), flush=True)


request = json.loads(sys.stdin.read())
mode = request["prompt"].split(",")[0]
output = Path(request["output_dir"])
width, height = request["width"], request["height"]
cutout = request.get("cutout")
inpaint = request.get("inpaint")
# A high-resolution request is upscaled after the base render; boxes scale with it.
hires = request.get("hires")
factor = hires["scale"] if hires else 1
width, height = round(width * factor), round(height * factor)
if mode == "hireslow":
    width, height = request["width"], request["height"]
if mode == "hiresonly":
    width, height = width * 2, height * 2
# The real child hashes the segmenter bytes it loads; so does this stand-in.
if cutout and hashlib.sha256(Path(cutout["model"]).read_bytes()).hexdigest() != cutout["sha256"]:
    emit("error", code="model_invalid")
    raise SystemExit(2)
base_alpha = False
if inpaint:
    base = Path(inpaint["image"]).read_bytes()
    if mode == "basehash" or hashlib.sha256(base).hexdigest() != inpaint["sha256"]:
        emit("error", code="model_invalid")
        raise SystemExit(2)
    base_alpha = base[25] == 6
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
    runtime={"torch": "fake", "diffusers": "fake", "cuda": "0", "device": "Fake GPU"}
    | ({"onnxruntime": "fake"} if cutout and mode != "nocutruntime" else {}),
)
for index, seed in enumerate(request["seeds"]):
    extra: dict[str, object] = {}
    # A render with no usable figure is skipped; the others are kept.
    skip = {"cutskip": index == 1, "skipwrong": index == 1, "skipplain": index == 1}
    if skip.get(mode) or mode == "cutskipall":
        emit("skipped", index=index + (mode == "skipwrong"), seed=seed, code="cutout_failed")
        continue
    if cutout:
        if mode == "cutfail":
            emit("error", code="cutout_failed")
            raise SystemExit(2)
        box = [round(value * factor) for value in (100, 40, 612, 1176)]
        if mode == "outsidebox":
            box = [round(value * factor) for value in (400, 40, 912, 1176)]
        crop_width, crop_height = box[2] - box[0], box[3] - box[1]
        image = png(
            crop_width + (1 if mode == "badbox" else 0),
            crop_height,
            index * 40,
            mode != "opaquecut",
        )
        thumbnail = png(256, round(crop_height * 256 / crop_width), index * 40, True)
        if mode != "nobox":
            extra["box"] = box
    elif inpaint:
        alpha = base_alpha and mode != "flatexpr"
        image = png(width + (1 if mode == "wrongsize" else 0), height, index * 40, alpha)
        thumbnail = png(256, round(height * 256 / width), index * 40, alpha)
    else:
        image = png(width + (1 if mode == "wrongsize" else 0), height, index * 40)
        thumbnail = png(256, round(height * 256 / width), index * 40)
    if mode == "badpng":
        image = image[:-5]
    if mode == "metadata":
        # Editors and encoders may add text; the parent drops it like an upload's.
        image = image[:33] + chunk(b"tEXt", b"Software\x00fake") + image[33:]
    (output / f"{index}.png").write_bytes(image)
    (output / f"{index}.thumb.png").write_bytes(thumbnail)
    emit(
        "image",
        index=index,
        file=f"{index}.png",
        thumbnail=f"{index}.thumb.png",
        seed=seed + (1 if mode == "wrongseed" else 0),
        seconds=0.1,
        **extra,
    )
if mode == "extra":
    (output / "notes.txt").write_text("unexpected")
if mode == "cutskipall":
    emit("error", code="cutout_failed")
    raise SystemExit(2)
emit("done", peak_bytes=1)
