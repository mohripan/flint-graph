"""Scripted stand-in for a protocol 2 voice child (runtimes/voicegen-*) in offline tests.

The behaviour is chosen by the first item's text. The fake checks what a real child
relies on: the reference sample sits in its private working folder with the hash the
parent named, and each item carries only the controls of its engine.
"""

import hashlib
import json
import struct
import sys
import time
from pathlib import Path


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"protocol": 2, "event": event, **fields}), flush=True)


def wav(frames: int, level: int, rate: int, channels: int = 1) -> bytes:
    samples = struct.pack("<h", level) * frames * channels
    header = struct.pack("<HHIIHH", 1, channels, rate, rate * channels * 2, channels * 2, 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + header
    body += b"data" + struct.pack("<I", len(samples)) + samples
    return b"RIFF" + struct.pack("<I", len(body)) + body


request = json.loads(sys.stdin.read())
mode = request["items"][0]["text"].split(" ")[0]
output = Path(request["output_dir"])
reference = request["reference"]
if reference is not None:
    path = Path(reference["path"])
    if path.parent != Path.cwd() or not path.is_file():
        emit("error", code="bad_request")
        raise SystemExit(2)
    expected = request["items"][0]["text"].split(" ")[-1]
    if len(expected) == 64 and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        emit("error", code="bad_request")
        raise SystemExit(2)
if mode == "hang":
    time.sleep(60)
if mode == "busy":
    emit("error", code="gpu_busy")
    raise SystemExit(2)
rate = {"chatterbox": 24000, "qwen3": 24000, "indextts": 22050}[request["engine"]]
emit("loaded", runtime={"torch": "2.8.0+cu128", "engine": request["engine"], "device": "fake"})
for index, item in enumerate(request["items"]):
    frames = rate // 10 * (index + 1)
    data = wav(frames, 100 + index, 16000 if mode == "rate" else rate)
    (output / f"{index}.wav").write_bytes(data)
    emit(
        "clip",
        index=index,
        file=f"{index}.wav",
        samples=frames,
        sample_rate=16000 if mode == "rate" else rate,
        device="cuda" if request["device"] == "auto" else "cpu",
    )
    if mode == "controls":
        print(json.dumps(item["controls"]), file=sys.stderr)
emit("done")
