"""Isolated local Chatterbox voice child for FlintGraph narrative assets (ADR 0044).

The trusted parent starts this with ``python -I generate.py`` from the locked runtime,
inside a private temporary folder, writes one JSON request to stdin and reads JSON
lines from stdout. The child loads one pinned Chatterbox model (English,
Turbo or Multilingual V3) from local files, clones the voice of the reference sample
the parent placed in that folder, speaks each text with the controls the parent
mapped from its delivery, and writes one canonical mono 16-bit WAV per text. Every
clip carries Resemble AI's PerTh watermark, which the model adds itself. Nothing is
downloaded. Library output goes to stderr so stdout carries only the protocol.

It uses the GPU when the request allows it and NVML reports enough free dedicated
memory, otherwise (or when the card fills up mid-job) the CPU.
"""

import json
import math
import os
import re
import sys
import wave
from pathlib import Path

PROTOCOL = 2
REQUEST_LIMIT = 64 * 1024
MAX_ITEMS = 24
TEXT_LIMIT = 600
VOCALIZATION_LIMIT = 40
MAX_SECONDS = 60
MODELS = {"chatterbox", "chatterbox-turbo", "chatterbox-multilingual"}
LANGUAGES = {"en", "ja", "zh", "ko", "de", "fr", "es", "it", "pt", "ru"}
PREFIX = re.compile(r"(\[[a-z ]{3,20}\]( \[[a-z ]{3,20}\])?)?\Z")
MULTILINGUAL_T3 = "t3_mtl23ls_v3.safetensors"
# The protocol stream: the real stdout, kept before library output is sent to stderr.
_OUT = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
os.dup2(2, 1)
sys.stdout = sys.stderr


class ChildError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def emit(event: str, **fields: object) -> None:
    _OUT.write(json.dumps({"protocol": PROTOCOL, "event": event, **fields}) + "\n")
    _OUT.flush()


def _number(value: object, low: float, high: float) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def _controls(model: str, controls: object) -> bool:
    if not isinstance(controls, dict):
        return False
    if model == "chatterbox-turbo":
        return (
            set(controls) == {"prefix"}
            and isinstance(controls["prefix"], str)
            and bool(PREFIX.fullmatch(controls["prefix"]))
        )
    return (
        set(controls) == {"exaggeration", "cfg_weight"}
        and _number(controls["exaggeration"], 0.0, 2.0)
        and _number(controls["cfg_weight"], 0.0, 1.0)
    )


def read_request() -> dict:
    raw = sys.stdin.buffer.read(REQUEST_LIMIT + 1)
    if len(raw) > REQUEST_LIMIT:
        raise ChildError("bad_request")
    try:
        request = json.loads(raw)
    except ValueError:
        raise ChildError("bad_request") from None
    keys = {
        "protocol",
        "engine",
        "model",
        "model_dir",
        "output_dir",
        "voice",
        "reference",
        "language",
        "seed",
        "device",
        "min_free_bytes",
        "cpu_fallback",
        "items",
    }
    if not isinstance(request, dict) or set(request) != keys or request["protocol"] != PROTOCOL:
        raise ChildError("bad_request")
    reference = request["reference"]
    items = request["items"]
    if (
        request["engine"] != "chatterbox"
        or request["model"] not in MODELS
        or request["voice"] is not None
        or not isinstance(reference, dict)
        or set(reference) != {"path", "transcript"}
        or not isinstance(reference["path"], str)
        or request["language"] not in LANGUAGES
        or (request["model"] != "chatterbox-multilingual" and request["language"] != "en")
        or request["device"] not in ("auto", "cpu")
        or type(request["seed"]) is not int
        or not 0 <= request["seed"] < 2**32
        or type(request["min_free_bytes"]) is not int
        or type(request["cpu_fallback"]) is not bool
        or not isinstance(items, list)
        or not 1 <= len(items) <= MAX_ITEMS
    ):
        raise ChildError("bad_request")
    for item in items:
        if (
            not isinstance(item, dict)
            or set(item) != {"text", "mode", "controls"}
            or item["mode"] not in ("full", "vocalization")
            or not isinstance(item["text"], str)
            or not item["text"].strip()
            or len(item["text"])
            > (VOCALIZATION_LIMIT if item["mode"] == "vocalization" else TEXT_LIMIT)
            or not _controls(request["model"], item["controls"])
        ):
            raise ChildError("bad_request")
    return request


def dedicated_free_bytes() -> int:
    """Free dedicated VRAM from NVML (``cudaMemGetInfo`` counts shared memory on WDDM)."""
    import pynvml

    pynvml.nvmlInit()
    try:
        index = int(os.environ.get("CUDA_VISIBLE_DEVICES", "0").split(",")[0] or 0)
        handle = pynvml.nvmlDeviceGetHandleByIndex(index)
        return int(pynvml.nvmlDeviceGetMemoryInfo(handle).free)
    finally:
        pynvml.nvmlShutdown()


def choose_device(request: dict) -> str:
    import torch

    if request["device"] != "auto" or not torch.cuda.is_available():
        if request["cpu_fallback"]:
            return "cpu"
        raise ChildError("gpu_busy")
    try:
        free = dedicated_free_bytes()
    except Exception:
        free = 0
    if free >= request["min_free_bytes"]:
        return "cuda"
    if request["cpu_fallback"]:
        return "cpu"
    raise ChildError("gpu_busy")


def write_wav(path: Path, rate: int, samples: bytes) -> None:
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(samples)


def load(model: str, model_dir: Path, device: str):
    if model == "chatterbox-turbo":
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        return ChatterboxTurboTTS.from_local(model_dir, device)
    if model == "chatterbox-multilingual":
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        return ChatterboxMultilingualTTS.from_local(model_dir, device, t3_model=MULTILINGUAL_T3)
    from chatterbox.tts import ChatterboxTTS

    return ChatterboxTTS.from_local(model_dir, device)


def main() -> int:
    try:
        request = read_request()
        model_dir = Path(request["model_dir"])
        output = Path(request["output_dir"])
        reference = Path(request["reference"]["path"])
        if not output.is_dir() or any(output.iterdir()):
            raise ChildError("bad_request")
        if reference.is_symlink() or not reference.is_file() or reference.parent != Path.cwd():
            raise ChildError("bad_request")
        if not model_dir.is_dir():
            raise ChildError("model_invalid")
        import random
        from importlib import metadata

        import numpy
        import torch

        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
        device = choose_device(request)
        try:
            tts = load(request["model"], model_dir, device)
        except torch.cuda.OutOfMemoryError:
            if not request["cpu_fallback"]:
                raise ChildError("gpu_busy") from None
            torch.cuda.empty_cache()
            device, tts = "cpu", load(request["model"], model_dir, "cpu")
        except Exception:
            raise ChildError("model_invalid") from None
        turbo = request["model"] == "chatterbox-turbo"
        try:
            if turbo:
                tts.prepare_conditionals(str(reference), norm_loudness=True)
            else:
                tts.prepare_conditionals(str(reference), exaggeration=0.5)
        except Exception:
            raise ChildError("reference_invalid") from None
        name = torch.cuda.get_device_name(0) if device == "cuda" else "cpu"
        emit(
            "loaded",
            runtime={
                "torch": torch.__version__,
                "engine": f"chatterbox-tts {metadata.version('chatterbox-tts')}",
                "device": name[:120],
            },
        )

        def speak(item: dict):
            controls = item["controls"]
            with torch.inference_mode():
                if turbo:
                    text = f"{controls['prefix']} {item['text']}".strip()
                    return tts.generate(text)
                options = {
                    "exaggeration": float(controls["exaggeration"]),
                    "cfg_weight": float(controls["cfg_weight"]),
                }
                if request["model"] == "chatterbox-multilingual":
                    return tts.generate(item["text"], language_id=request["language"], **options)
                return tts.generate(item["text"], **options)

        for index, item in enumerate(request["items"]):
            seed = request["seed"] + index
            random.seed(seed)
            numpy.random.seed(seed)
            torch.manual_seed(seed)
            try:
                wav = speak(item)
            except torch.cuda.OutOfMemoryError:
                if not request["cpu_fallback"]:
                    raise ChildError("gpu_busy") from None
                # The shared GPU filled up mid-job: finish this job on the CPU.
                torch.cuda.empty_cache()
                device = "cpu"
                tts = load(request["model"], model_dir, "cpu")
                tts.prepare_conditionals(str(reference), **({} if turbo else {"exaggeration": 0.5}))
                torch.manual_seed(seed)
                wav = speak(item)
            audio = wav.detach().float().cpu().numpy().reshape(-1)
            if not len(audio) or not numpy.isfinite(audio).all():
                raise ChildError("empty_speech")
            rate = int(tts.sr)
            if len(audio) > rate * MAX_SECONDS:
                raise ChildError("too_long")
            pcm = (numpy.clip(audio, -1.0, 1.0) * 32767.0).round().astype("<i2").tobytes()
            name = f"{index}.wav"
            write_wav(output / name, rate, pcm)
            emit(
                "clip", index=index, file=name, samples=len(audio), sample_rate=rate, device=device
            )
        # This child's own peak of reserved GPU memory (other processes not counted).
        peak = torch.cuda.max_memory_reserved() // 2**20 if torch.cuda.is_available() else 0
        emit("done", peak_vram_mib=int(peak))
        return 0
    except ChildError as error:
        emit("error", code=error.code)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
