"""Isolated local voice-generation child for FlintGraph narrative assets (ADR 0043).

The trusted parent starts this with ``python -I generate.py`` from the locked
runtime environment, writes one JSON request to stdin and reads JSON lines from
stdout. The child loads the pinned local Kokoro-82M weights and one voice pack
(``torch.load`` with ``weights_only``), speaks each text on the CPU with Misaki
(spaCy model from the lock, eSpeak NG fallback for unknown words such as "fufu"),
writes one canonical 24 kHz mono 16-bit WAV per text into the parent's private
output directory and exits. It never downloads anything.
"""

import json
import os
import re
import sys
import wave
from pathlib import Path

PROTOCOL = 1
REQUEST_LIMIT = 64 * 1024
MAX_ITEMS = 24
TEXT_LIMIT = 600
VOCALIZATION_LIMIT = 40
SPEED = (0.7, 1.3)
SAMPLE_RATE = 24000
MAX_SECONDS = 60
VOICE = re.compile(r"[ab][fm]_[a-z]{2,20}\Z")
REPO = "hexgrad/Kokoro-82M"


class ChildError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def emit(event: str, **fields: object) -> None:
    sys.stdout.write(json.dumps({"protocol": PROTOCOL, "event": event, **fields}) + "\n")
    sys.stdout.flush()


def read_request() -> dict:
    raw = sys.stdin.buffer.read(REQUEST_LIMIT + 1)
    if len(raw) > REQUEST_LIMIT:
        raise ChildError("bad_request")
    try:
        request = json.loads(raw)
    except ValueError:
        raise ChildError("bad_request") from None
    keys = {"protocol", "model_dir", "output_dir", "voice", "speed", "seed", "items"}
    if not isinstance(request, dict) or set(request) != keys or request["protocol"] != PROTOCOL:
        raise ChildError("bad_request")
    items = request["items"]
    if (
        not isinstance(request["voice"], str)
        or not VOICE.fullmatch(request["voice"])
        or type(request["speed"]) not in (int, float)
        or not SPEED[0] <= request["speed"] <= SPEED[1]
        or type(request["seed"]) is not int
        or not 0 <= request["seed"] < 2**32
        or not isinstance(items, list)
        or not 1 <= len(items) <= MAX_ITEMS
    ):
        raise ChildError("bad_request")
    for item in items:
        if (
            not isinstance(item, dict)
            or set(item) != {"text", "mode"}
            or item["mode"] not in ("full", "vocalization")
            or not isinstance(item["text"], str)
            or not item["text"].strip()
            or len(item["text"])
            > (VOCALIZATION_LIMIT if item["mode"] == "vocalization" else TEXT_LIMIT)
        ):
            raise ChildError("bad_request")
    return request


def write_wav(path: Path, samples: bytes) -> None:
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes(samples)


def main() -> int:
    try:
        request = read_request()
        model_dir = Path(request["model_dir"])
        output = Path(request["output_dir"])
        voice_path = model_dir / "voices" / f"{request['voice']}.pt"
        if not output.is_dir() or any(output.iterdir()):
            raise ChildError("bad_request")
        if not (model_dir / "config.json").is_file() or not voice_path.is_file():
            raise ChildError("model_invalid")
        import kokoro
        import misaki
        import numpy
        import torch
        from kokoro import KModel, KPipeline

        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
        try:
            model = KModel(
                repo_id=REPO,
                config=str(model_dir / "config.json"),
                model=str(model_dir / "kokoro-v1_0.pth"),
            ).eval()
            pipeline = KPipeline(lang_code=request["voice"][0], repo_id=REPO, model=model)
            pack = pipeline.load_voice(str(voice_path))
        except Exception:
            raise ChildError("model_invalid") from None
        emit(
            "loaded",
            runtime={
                "torch": torch.__version__,
                "kokoro": getattr(kokoro, "__version__", "unknown"),
                "misaki": getattr(misaki, "__version__", "unknown"),
                "device": "cpu",
            },
        )
        for index, item in enumerate(request["items"]):
            torch.manual_seed(request["seed"] + index)
            parts = []
            with torch.inference_mode():
                for result in pipeline(item["text"], voice=pack, speed=request["speed"]):
                    if result.audio is not None:
                        parts.append(result.audio.detach().cpu().numpy())
            if not parts:
                raise ChildError("empty_speech")
            audio = numpy.concatenate(parts)
            if not len(audio) or not numpy.isfinite(audio).all():
                raise ChildError("empty_speech")
            if len(audio) > SAMPLE_RATE * MAX_SECONDS:
                raise ChildError("too_long")
            pcm = (numpy.clip(audio, -1.0, 1.0) * 32767.0).round().astype("<i2").tobytes()
            name = f"{index}.wav"
            write_wav(output / name, pcm)
            emit("clip", index=index, file=name, samples=len(audio))
        emit("done")
        return 0
    except ChildError as error:
        emit("error", code=error.code)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
