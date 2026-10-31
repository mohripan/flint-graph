"""Scripted stand-in for runtimes/voicegen/generate.py used by offline tests.

The behaviour is chosen by the first item's text, so tests exercise the real
parent: process start, stdin/stdout protocol, watchdog and file checks.
"""

import json
import struct
import sys
import time
from pathlib import Path


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"protocol": 1, "event": event, **fields}), flush=True)


def wav(frames: int, level: int, rate: int = 24000, channels: int = 1) -> bytes:
    samples = struct.pack("<h", level) * frames * channels
    header = struct.pack("<HHIIHH", 1, channels, rate, rate * channels * 2, channels * 2, 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + header
    body += b"data" + struct.pack("<I", len(samples)) + samples
    return b"RIFF" + struct.pack("<I", len(body)) + body


request = json.loads(sys.stdin.read())
mode = request["items"][0]["text"].split(" ")[0]
output = Path(request["output_dir"])
if mode == "hang":
    time.sleep(60)
if mode == "crash":
    raise SystemExit(3)
if mode == "empty":
    emit("error", code="empty_speech")
    raise SystemExit(2)
RUNTIME = {"torch": "2.11.0+cpu", "kokoro": "0.9.4", "misaki": "0.9.4", "device": "cpu"}
emit("loaded", runtime=RUNTIME)
for index in range(len(request["items"])):
    frames = 2400 * (index + 1)
    data = wav(frames, 100 + index)
    if mode == "stereo":
        data = wav(frames, 1, channels=2)
    if mode == "rate":
        data = wav(frames, 1, rate=22050)
    if mode == "badwav":
        data = data[:-2]
    (output / f"{index}.wav").write_bytes(data)
    if mode == "extra":
        (output / "notes.txt").write_text("x")
    device = {"gpu": "cuda", "baddevice": "tpu"}.get(mode, "cpu")
    if request["device"] == "cpu" and device == "cuda":
        device = "cpu"
    emit(
        "clip",
        index=index + (mode == "wrongindex"),
        file=f"{index}.wav",
        samples=frames + (mode == "wrongsamples"),
        device=device,
    )
    if mode == "noisy":
        print("debug output", flush=True)
emit("done")
