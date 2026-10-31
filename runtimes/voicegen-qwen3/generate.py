"""Isolated local Qwen3-TTS voice child for FlintGraph narrative assets (ADR 0044).

The trusted parent starts this with ``python -I generate.py`` from the locked runtime,
inside a private temporary folder, writes one JSON request to stdin and reads JSON
lines from stdout. The child loads one pinned Qwen3-TTS 1.7B model from local files:
the Base model clones the voice of the reference sample the parent placed in that
folder (with its transcript when there is one), the CustomVoice model speaks one of
its nine stock voices with an instruction from the parent's fixed delivery table. It
writes one canonical mono 16-bit WAV per text. Nothing is downloaded; references are
passed as samples, never as paths or URLs. Library output goes to stderr so stdout
carries only the protocol.
"""

import json
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
TRANSCRIPT_LIMIT = 600
MAX_SECONDS = 60
MODELS = {"qwen3-tts-clone", "qwen3-tts-voices"}
SPEAKERS = {"Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric", "Ryan", "Aiden", "Ono_Anna", "Sohee"}
LANGUAGES = {
    "en": "English",
    "ja": "Japanese",
    "zh": "Chinese",
    "ko": "Korean",
    "de": "German",
    "fr": "French",
    "ru": "Russian",
    "pt": "Portuguese",
    "es": "Spanish",
    "it": "Italian",
}
# Instructions are fixed sentences from the parent's table, never a creator's text.
INSTRUCTION = re.compile(r"(|(Speak in a|Whisper|Shout) [a-z ,]{1,60}\.)\Z")
_OUT = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
os.dup2(2, 1)
sys.stdout = sys.stderr


class ChildError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def emit(event: str, **fields: object) -> None:
    _OUT.write(json.dumps({"protocol": PROTOCOL, "event": event, **fields}) + "\n")
    _OUT.flush()


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
    cloning = request["model"] == "qwen3-tts-clone"
    reference, items = request["reference"], request["items"]
    if (
        request["engine"] != "qwen3"
        or request["model"] not in MODELS
        or (cloning and request["voice"] is not None)
        or (not cloning and request["voice"] not in SPEAKERS)
        or (cloning != isinstance(reference, dict))
        or (not cloning and reference is not None)
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
    if cloning and (
        set(reference) != {"path", "transcript"}
        or not isinstance(reference["path"], str)
        or not (
            reference["transcript"] is None
            or (
                isinstance(reference["transcript"], str)
                and len(reference["transcript"]) <= TRANSCRIPT_LIMIT
            )
        )
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
            or set(controls) != {"instruct"}
            or not isinstance(controls["instruct"], str)
            or not INSTRUCTION.fullmatch(controls["instruct"])
            or (cloning and controls["instruct"])
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


def read_reference(path: Path) -> tuple:
    """The reference as a mono float sample array (the parent wrote canonical WAV)."""
    import numpy

    with wave.open(str(path), "rb") as stream:
        channels, rate = stream.getnchannels(), stream.getframerate()
        frames = stream.readframes(stream.getnframes())
    samples = numpy.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0
    if channels == 2:
        samples = samples.reshape(-1, 2).mean(axis=1)
    return samples, rate


def write_wav(path: Path, rate: int, samples: bytes) -> None:
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(samples)


def load(model_dir: Path, device: str):
    import torch
    from qwen_tts import Qwen3TTSModel

    return Qwen3TTSModel.from_pretrained(
        str(model_dir),
        device_map="cuda:0" if device == "cuda" else "cpu",
        dtype=torch.bfloat16 if device == "cuda" else torch.float32,
        attn_implementation="sdpa",
        local_files_only=True,
    )


def main() -> int:
    try:
        request = read_request()
        model_dir = Path(request["model_dir"])
        output = Path(request["output_dir"])
        cloning = request["model"] == "qwen3-tts-clone"
        if not output.is_dir() or any(output.iterdir()):
            raise ChildError("bad_request")
        reference = Path(request["reference"]["path"]) if cloning else None
        if reference is not None and (
            reference.is_symlink() or not reference.is_file() or reference.parent != Path.cwd()
        ):
            raise ChildError("bad_request")
        if not (model_dir / "config.json").is_file():
            raise ChildError("model_invalid")
        import random
        from importlib import metadata

        import numpy
        import torch

        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
        device = choose_device(request)
        try:
            tts = load(model_dir, device)
        except torch.cuda.OutOfMemoryError:
            if not request["cpu_fallback"]:
                raise ChildError("gpu_busy") from None
            torch.cuda.empty_cache()
            device, tts = "cpu", load(model_dir, "cpu")
        except Exception:
            raise ChildError("model_invalid") from None
        language = LANGUAGES[request["language"]]
        prompt = None
        if cloning:
            transcript = request["reference"]["transcript"]
            try:
                prompt = tts.create_voice_clone_prompt(
                    ref_audio=read_reference(reference),
                    ref_text=transcript,
                    x_vector_only_mode=not transcript,
                )
            except Exception:
                raise ChildError("reference_invalid") from None
        name = torch.cuda.get_device_name(0) if device == "cuda" else "cpu"
        emit(
            "loaded",
            runtime={
                "torch": torch.__version__,
                "engine": f"qwen-tts {metadata.version('qwen-tts')}",
                "device": name[:120],
            },
        )
        for index, item in enumerate(request["items"]):
            seed = request["seed"] + index
            random.seed(seed)
            numpy.random.seed(seed)
            torch.manual_seed(seed)
            with torch.inference_mode():
                if cloning:
                    wavs, rate = tts.generate_voice_clone(
                        text=item["text"], language=language, voice_clone_prompt=prompt
                    )
                else:
                    instruct = item["controls"]["instruct"]
                    wavs, rate = tts.generate_custom_voice(
                        text=item["text"],
                        language=language,
                        speaker=request["voice"],
                        **({"instruct": instruct} if instruct else {}),
                    )
            audio = numpy.asarray(wavs[0], dtype="float32").reshape(-1)
            if not len(audio) or not numpy.isfinite(audio).all():
                raise ChildError("empty_speech")
            if len(audio) > int(rate) * MAX_SECONDS:
                raise ChildError("too_long")
            pcm = (numpy.clip(audio, -1.0, 1.0) * 32767.0).round().astype("<i2").tobytes()
            file = f"{index}.wav"
            write_wav(output / file, int(rate), pcm)
            emit(
                "clip",
                index=index,
                file=file,
                samples=len(audio),
                sample_rate=int(rate),
                device=device,
            )
        emit("done")
        return 0
    except ChildError as error:
        emit("error", code=error.code)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
