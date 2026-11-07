"""Isolated local music-generation child for FlintGraph narrative assets (ADR 0067).

The trusted parent starts this with ``python -I generate.py`` from the locked runtime
environment, writes one JSON request to stdin and reads JSON lines from stdout. The child loads
the pinned local ACE-Step v1 3.5B weights, makes one instrumental track, joins its end to its start
so it loops without a jump, writes it as Ogg Vorbis into the parent's private output directory and
exits, which returns all GPU memory. It never downloads anything.

The model needs the GPU: it reports ``gpu_busy`` when too little memory is free, so the parent can
ask Ollama to unload and try again. There is no CPU fallback, because a track would take hours.
"""

import json
import os
import re
import sys
from pathlib import Path

PROTOCOL = 1
REQUEST_LIMIT = 16 * 1024
DESCRIPTION_LIMIT = 500
SECONDS = (15, 180)
STEPS = (10, 100)
# Measured: 6.8 GiB reserved at its peak for 30 and 90 second tracks on a 12 GB card.
MIN_FREE_BYTES = 7 * 1024**3
LOOP_SECONDS = 2.0
# libsndfile can crash when handed a long Vorbis stream in one call.
ENCODE_FRAMES = 8192
SEED = re.compile(r"\d{1,19}\Z")
_output = None


class ChildError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def emit(event: str, **fields: object) -> None:
    _output.write(json.dumps({"protocol": PROTOCOL, "event": event, **fields}) + "\n")
    _output.flush()


def read_request() -> dict:
    raw = sys.stdin.buffer.read(REQUEST_LIMIT + 1)
    if len(raw) > REQUEST_LIMIT:
        raise ChildError("bad_request")
    try:
        request = json.loads(raw)
    except ValueError:
        raise ChildError("bad_request") from None
    keys = {"protocol", "model_dir", "output_dir", "description", "seconds", "seed", "steps"}
    if not isinstance(request, dict) or set(request) != keys or request["protocol"] != PROTOCOL:
        raise ChildError("bad_request")
    description, seconds = request["description"], request["seconds"]
    if not isinstance(description, str) or not 0 < len(description.strip()) <= DESCRIPTION_LIMIT:
        raise ChildError("bad_request")
    if type(seconds) is not int or not SECONDS[0] <= seconds <= SECONDS[1]:
        raise ChildError("bad_request")
    steps, seed = request["steps"], request["seed"]
    if type(steps) is not int or not STEPS[0] <= steps <= STEPS[1]:
        raise ChildError("bad_request")
    if type(seed) is not int or seed < 0 or not SEED.match(str(seed)):
        raise ChildError("bad_request")
    return request


def seamless_loop(data, rate: int, seconds: float = LOOP_SECONDS):
    """Fade the end into the start, so the track's last sample leads into its first.

    The result is shorter by the overlap. Too short a track is returned unchanged.
    """
    import numpy as np

    overlap = int(rate * seconds)
    if len(data) <= overlap * 2:
        return data
    position = np.linspace(0.0, 1.0, overlap)[:, None]
    # Equal power, so the level does not dip in the middle of the join.
    joined = data[-overlap:] * np.sqrt(1.0 - position) + data[:overlap] * np.sqrt(position)
    return np.concatenate([joined, data[overlap:-overlap]])


def require_gpu() -> None:
    import pynvml

    try:
        pynvml.nvmlInit()
        free = pynvml.nvmlDeviceGetMemoryInfo(pynvml.nvmlDeviceGetHandleByIndex(0)).free
    except pynvml.NVMLError:
        raise ChildError("gpu_unavailable") from None
    finally:
        try:
            pynvml.nvmlShutdown()
        except pynvml.NVMLError:
            pass
    if free < MIN_FREE_BYTES:
        raise ChildError("gpu_busy")


def generate(request: dict) -> None:
    require_gpu()
    import soundfile
    import torch
    import torchaudio

    if not torch.cuda.is_available():
        raise ChildError("gpu_unavailable")

    def save(path, tensor, sample_rate, **_):
        # torchaudio's own saver needs another native package; this one is already here.
        samples = tensor.detach().cpu().float().numpy().T
        soundfile.write(str(path), samples, sample_rate, format="WAV", subtype="PCM_16")

    torchaudio.save = save
    from acestep.pipeline_ace_step import ACEStepPipeline

    pipeline = ACEStepPipeline(
        checkpoint_dir=request["model_dir"],
        dtype="bfloat16",
        torch_compile=False,
        cpu_offload=True,
        overlapped_decode=True,
    )
    emit(
        "loaded",
        runtime={
            "torch": torch.__version__[:40],
            "cuda": str(torch.version.cuda)[:40],
            "device": torch.cuda.get_device_name(0)[:100],
        },
    )
    output = Path(request["output_dir"])
    raw = output.parent / "raw.wav"
    try:
        pipeline(
            format="wav",
            audio_duration=float(request["seconds"]),
            prompt=request["description"].strip() + ", instrumental, no vocals",
            lyrics="[inst]",
            infer_step=request["steps"],
            guidance_scale=15.0,
            scheduler_type="euler",
            cfg_type="apg",
            omega_scale=10.0,
            manual_seeds=[request["seed"]],
            guidance_interval=0.5,
            guidance_interval_decay=0.0,
            min_guidance_scale=3.0,
            use_erg_tag=True,
            use_erg_lyric=False,
            use_erg_diffusion=True,
            oss_steps=[],
            guidance_scale_text=0.0,
            guidance_scale_lyric=0.0,
            save_path=str(raw),
            batch_size=1,
        )
    except torch.cuda.OutOfMemoryError:
        raise ChildError("gpu_busy") from None
    data, rate = soundfile.read(str(raw), always_2d=True, dtype="float32")
    data = seamless_loop(data, rate)
    with soundfile.SoundFile(
        str(output / "0.ogg"),
        "w",
        samplerate=rate,
        channels=data.shape[1],
        format="OGG",
        subtype="VORBIS",
    ) as encoded:
        for start in range(0, len(data), ENCODE_FRAMES):
            encoded.write(data[start : start + ENCODE_FRAMES])
    emit("track", file="0.ogg", frames=len(data), rate=rate, device="gpu")
    emit("done")


def main() -> int:
    global _output
    # Libraries print to stdout; only this protocol may reach the parent.
    _output = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    try:
        generate(read_request())
    except ChildError as error:
        emit("error", code=error.code)
        return 1
    except Exception:
        emit("error", code="generation_failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
