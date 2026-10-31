"""Isolated local IndexTTS-2.5 voice child for FlintGraph narrative assets (ADR 0044).

The trusted parent starts this with ``python -I generate.py`` from the locked runtime,
inside a private temporary folder, writes one JSON request to stdin and reads JSON
lines from stdout. The child loads the pinned IndexTTS-2.5 weights and their MIT and
Apache-2.0 auxiliaries (w2v-BERT 2.0, CAM++, BigVGAN) from the model directory, never
the non-commercial MaskGCT codec that IndexTTS2 needs. It clones the voice of the
reference sample the parent placed in that folder and steers each line's emotion with
an emotion vector from the parent's fixed delivery table, separately from the voice.
It writes one canonical mono 16-bit 22.05 kHz WAV per text. Nothing is downloaded.
Library output goes to stderr so stdout carries only the protocol.

IndexTTS-2.5 needs several gigabytes of GPU memory and is far too slow on the CPU, so
a job refuses with ``gpu_busy`` when the shared card has too little free memory.
"""

import json
import math
import os
import sys
import wave
from pathlib import Path

PROTOCOL = 2
REQUEST_LIMIT = 64 * 1024
MAX_ITEMS = 24
TEXT_LIMIT = 600
VOCALIZATION_LIMIT = 40
MAX_SECONDS = 60
SAMPLE_RATE = 22050
LANGUAGES = {"en", "zh", "ja"}
AUXILIARIES = ("hf_cache/w2v-bert-2.0/model.safetensors", "hf_cache/campplus_cn_common.bin")
_OUT = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
os.dup2(2, 1)
sys.stdout = sys.stderr


class ChildError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def emit(event: str, **fields: object) -> None:
    _OUT.write(json.dumps({"protocol": PROTOCOL, "event": event, **fields}) + "\n")
    _OUT.flush()


def _vector(value: object) -> bool:
    if value is None:
        return True
    return (
        isinstance(value, list)
        and len(value) == 8
        and all(
            type(item) in (int, float) and math.isfinite(item) and 0 <= item <= 1 for item in value
        )
        and sum(value) <= 1.0
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
    reference, items = request["reference"], request["items"]
    if (
        request["engine"] != "indextts"
        or request["model"] != "indextts-2.5"
        or request["voice"] is not None
        or not isinstance(reference, dict)
        or set(reference) != {"path", "transcript"}
        or not isinstance(reference["path"], str)
        or request["language"] not in LANGUAGES
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
        controls = item.get("controls") if isinstance(item, dict) else None
        if (
            not isinstance(item, dict)
            or set(item) != {"text", "mode", "controls"}
            or item["mode"] not in ("full", "vocalization")
            or not isinstance(item["text"], str)
            or not item["text"].strip()
            or len(item["text"])
            > (VOCALIZATION_LIMIT if item["mode"] == "vocalization" else TEXT_LIMIT)
            or not isinstance(controls, dict)
            or set(controls) != {"emo_vector"}
            or not _vector(controls["emo_vector"])
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

    if request["device"] == "auto" and torch.cuda.is_available():
        try:
            free = dedicated_free_bytes()
        except Exception:
            free = 0
        if free >= request["min_free_bytes"]:
            return "cuda"
    if request["cpu_fallback"]:
        return "cpu"
    raise ChildError("gpu_busy")


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
        reference = Path(request["reference"]["path"])
        if not output.is_dir() or any(output.iterdir()):
            raise ChildError("bad_request")
        if reference.is_symlink() or not reference.is_file() or reference.parent != Path.cwd():
            raise ChildError("bad_request")
        if not (model_dir / "config.yaml").is_file() or not all(
            (model_dir / name).is_file() for name in AUXILIARIES
        ):
            raise ChildError("model_invalid")
        import random

        import numpy
        import torch

        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
        device = choose_device(request)
        try:
            from indextts.infer_v2_5 import IndexTTS2

            tts = IndexTTS2(
                cfg_path=str(model_dir / "config.yaml"),
                model_dir=str(model_dir),
                use_bf16=device == "cuda",
                device="cuda:0" if device == "cuda" else "cpu",
                use_cuda_kernel=False,
                use_deepspeed=False,
                use_accel=False,
                use_torch_compile=False,
                use_qwen_emo=False,
            )
        except torch.cuda.OutOfMemoryError:
            raise ChildError("gpu_busy") from None
        except Exception:
            raise ChildError("model_invalid") from None
        name = torch.cuda.get_device_name(0) if device == "cuda" else "cpu"
        emit(
            "loaded",
            runtime={"torch": torch.__version__, "engine": "indextts 2.5", "device": name[:120]},
        )
        for index, item in enumerate(request["items"]):
            seed = request["seed"] + index
            random.seed(seed)
            numpy.random.seed(seed)
            torch.manual_seed(seed)
            vector = item["controls"]["emo_vector"]
            try:
                with torch.inference_mode():
                    result = tts.infer(
                        spk_audio_prompt=str(reference),
                        text=item["text"],
                        output_path=None,
                        lang=request["language"],
                        emo_vector=vector,
                        emo_alpha=1.0,
                        use_random=False,
                        verbose=False,
                    )
            except torch.cuda.OutOfMemoryError:
                raise ChildError("gpu_busy") from None
            if not isinstance(result, tuple) or len(result) != 2 or result[0] != SAMPLE_RATE:
                raise ChildError("empty_speech")
            audio = numpy.asarray(result[1]).reshape(-1)
            if not len(audio):
                raise ChildError("empty_speech")
            if len(audio) > SAMPLE_RATE * MAX_SECONDS:
                raise ChildError("too_long")
            pcm = numpy.clip(audio, -32768, 32767).astype("<i2").tobytes()
            file = f"{index}.wav"
            write_wav(output / file, pcm)
            emit(
                "clip",
                index=index,
                file=file,
                samples=len(audio),
                sample_rate=SAMPLE_RATE,
                device=device,
            )
        emit("done")
        return 0
    except ChildError as error:
        emit("error", code=error.code)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
