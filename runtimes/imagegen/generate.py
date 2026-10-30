"""Isolated local image-generation child for FlintGraph narrative assets.

The trusted parent starts this with ``python -I generate.py`` from the locked
runtime environment, writes one JSON request to stdin and reads JSON lines from
stdout. The child loads a pinned local SDXL model from safetensors only, never
downloads or runs remote code, writes PNG files into the parent's private
output directory and exits, which releases all GPU memory.
"""

import json
import os
import sys
import time
from pathlib import Path

PROTOCOL = 1
REQUEST_LIMIT = 64 * 1024
MAX_IMAGES = 4
SIZES = {(832, 1216), (1216, 832), (1024, 1024), (1344, 768), (768, 1344)}
# SDXL fp16 with a tiled VAE peaks near this much dedicated device memory.
MIN_FREE_BYTES = 8 * 1024**3
THUMBNAIL_WIDTH = 256


def dedicated_free_bytes() -> int:
    """Free dedicated VRAM from NVML.

    On Windows (WDDM) ``cudaMemGetInfo`` counts shared system memory, and the
    driver silently spills into it, making generation ~10x slower instead of
    failing. NVML reports the real dedicated free memory.
    """
    import pynvml

    pynvml.nvmlInit()
    try:
        index = int(os.environ.get("CUDA_VISIBLE_DEVICES", "0").split(",")[0] or 0)
        handle = pynvml.nvmlDeviceGetHandleByIndex(index)
        return int(pynvml.nvmlDeviceGetMemoryInfo(handle).free)
    finally:
        pynvml.nvmlShutdown()


def emit(event: str, **fields: object) -> None:
    sys.stdout.write(json.dumps({"protocol": PROTOCOL, "event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str) -> None:
    emit("error", code=code)
    raise SystemExit(2)


def read_request() -> dict:
    raw = sys.stdin.buffer.read(REQUEST_LIMIT + 1)
    if len(raw) > REQUEST_LIMIT:
        fail("bad_request")
    try:
        request = json.loads(raw)
    except ValueError:
        fail("bad_request")
    expected = {
        "protocol",
        "model_dir",
        "output_dir",
        "prompt",
        "negative_prompt",
        "width",
        "height",
        "steps",
        "guidance",
        "seeds",
    }
    if type(request) is not dict or set(request) != expected or request["protocol"] != PROTOCOL:
        fail("bad_request")
    seeds = request["seeds"]
    if (
        not all(
            type(request[key]) is str
            for key in ("model_dir", "output_dir", "prompt", "negative_prompt")
        )
        or (request["width"], request["height"]) not in SIZES
        or type(request["steps"]) is not int
        or not 1 <= request["steps"] <= 50
        or type(request["guidance"]) not in (int, float)
        or not 1 <= request["guidance"] <= 12
        or type(seeds) is not list
        or not 1 <= len(seeds) <= MAX_IMAGES
        or any(type(seed) is not int or not 0 <= seed < 2**32 for seed in seeds)
        or not 1 <= len(request["prompt"]) <= 2000
        or len(request["negative_prompt"]) > 2000
    ):
        fail("bad_request")
    output = Path(request["output_dir"])
    if not output.is_absolute() or not output.is_dir() or any(output.iterdir()):
        fail("bad_request")
    if (
        not Path(request["model_dir"]).is_absolute()
        or not (Path(request["model_dir"]) / "model_index.json").is_file()
    ):
        fail("model_invalid")
    return request


def main() -> None:
    request = read_request()
    # Offline only: no hub lookups, telemetry or remote code.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DISABLE_TELEMETRY"] = "1"
    import diffusers
    import torch
    from diffusers import EulerAncestralDiscreteScheduler, StableDiffusionXLPipeline
    from PIL import Image

    if not torch.cuda.is_available():
        fail("gpu_unavailable")
    try:
        free = dedicated_free_bytes()
    except Exception:
        fail("gpu_unavailable")
    if free < MIN_FREE_BYTES:
        emit("busy", free_bytes=free, required_bytes=MIN_FREE_BYTES)
        fail("gpu_busy")
    started = time.monotonic()
    try:
        pipeline = StableDiffusionXLPipeline.from_pretrained(
            request["model_dir"],
            torch_dtype=torch.float16,
            use_safetensors=True,
            local_files_only=True,
        )
    except (OSError, ValueError):
        fail("model_invalid")
    pipeline.scheduler = EulerAncestralDiscreteScheduler.from_config(pipeline.scheduler.config)
    pipeline.set_progress_bar_config(disable=True)
    pipeline.to("cuda")
    # Decoding 832x1216 latents in tiles keeps the peak within the free-memory floor.
    pipeline.vae.enable_tiling()
    tokens = len(pipeline.tokenizer(request["prompt"]).input_ids)
    limit = pipeline.tokenizer.model_max_length
    emit(
        "loaded",
        seconds=round(time.monotonic() - started, 2),
        prompt_tokens=tokens,
        truncated=tokens > limit,
        runtime={
            "torch": torch.__version__,
            "diffusers": diffusers.__version__,
            "cuda": torch.version.cuda,
            "device": torch.cuda.get_device_name(0),
        },
    )
    output = Path(request["output_dir"])
    for index, seed in enumerate(request["seeds"]):
        began = time.monotonic()
        try:
            image = pipeline(
                prompt=request["prompt"],
                negative_prompt=request["negative_prompt"],
                width=request["width"],
                height=request["height"],
                num_inference_steps=request["steps"],
                guidance_scale=float(request["guidance"]),
                generator=torch.Generator("cuda").manual_seed(seed),
            ).images[0]
        except torch.OutOfMemoryError:
            fail("out_of_memory")
        name, thumbnail = f"{index}.png", f"{index}.thumb.png"
        with (output / name).open("xb") as stream:
            image.save(stream, format="PNG")
        small = image.resize(
            (THUMBNAIL_WIDTH, round(image.height * THUMBNAIL_WIDTH / image.width)), Image.LANCZOS
        )
        with (output / thumbnail).open("xb") as stream:
            small.save(stream, format="PNG")
        emit(
            "image",
            index=index,
            file=name,
            thumbnail=thumbnail,
            seed=seed,
            seconds=round(time.monotonic() - began, 2),
        )
    emit("done", peak_bytes=torch.cuda.max_memory_allocated())


if __name__ == "__main__":
    main()
