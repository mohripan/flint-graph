"""Isolated local image-generation child for FlintGraph narrative assets.

The trusted parent starts this with ``python -I generate.py`` from the locked
runtime environment, writes one JSON request to stdin and reads JSON lines from
stdout. The child loads a pinned local SDXL model from safetensors only, never
downloads or runs remote code, writes PNG files into the parent's private
output directory and exits, which releases all GPU memory.

With a ``cutout`` request it also separates the figure from its plain background
with a pinned anime segmentation model (ONNX, run on the CPU from bytes it hashed
itself) and writes cropped RGBA sprites instead of opaque images.
"""

import hashlib
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
SEGMENTER_LIMIT = 512 * 1024 * 1024
# The anime-seg ISNet takes a 1024x1024 letterboxed image and returns a 0..1 mask.
CUTOUT_SIZE = 1024
# Mask values up to ALPHA_LOW are background and from ALPHA_HIGH figure; the ramp
# between them keeps hair and edges soft without a faint veil of background.
ALPHA_LOW, ALPHA_HIGH = 0.1, 0.9
CROP_MARGIN = 16
BLEED_PIXELS = 8
# A plausible full-body figure covers part of the frame, never none or nearly all.
MIN_COVERAGE, MAX_COVERAGE = 0.005, 0.9


class CutoutError(Exception):
    """The segmenter found no usable figure in an image."""


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
    # ``cutout`` is optional so a parent that predates it keeps working.
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
    if (
        type(request) is not dict
        or set(request) - {"cutout"} != expected
        or request["protocol"] != PROTOCOL
    ):
        fail("bad_request")
    request.setdefault("cutout", None)
    cutout = request["cutout"]
    if cutout is not None and (
        type(cutout) is not dict
        or set(cutout) != {"model", "sha256"}
        or type(cutout["model"]) is not str
        or type(cutout["sha256"]) is not str
        or not Path(cutout["model"]).is_absolute()
        or Path(cutout["model"]).suffix != ".onnx"
        or len(cutout["sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in cutout["sha256"])
    ):
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
    if cutout is not None and not Path(cutout["model"]).is_file():
        fail("model_invalid")
    return request


def load_segmenter(cutout: dict) -> tuple[object, str]:
    """Load the segmenter from the very bytes whose hash matched the parent's pin."""
    path = Path(cutout["model"])
    if path.is_symlink() or not path.is_file() or path.stat().st_size > SEGMENTER_LIMIT:
        fail("model_invalid")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != cutout["sha256"]:
        fail("model_invalid")
    import onnxruntime

    try:
        session = onnxruntime.InferenceSession(data, providers=["CPUExecutionProvider"])
    except Exception:
        fail("model_invalid")
    inputs, outputs = session.get_inputs(), session.get_outputs()
    if (
        len(inputs) != 1
        or len(outputs) != 1
        or list(inputs[0].shape) != [1, 3, CUTOUT_SIZE, CUTOUT_SIZE]
        or list(outputs[0].shape) != [1, 1, CUTOUT_SIZE, CUTOUT_SIZE]
    ):
        fail("model_invalid")
    return session, onnxruntime.__version__


def letterbox(image, size: int = CUTOUT_SIZE):
    """The segmenter's input: the image scaled to fit ``size``, centred on black, 0..1."""
    import numpy as np
    from PIL import Image

    scale = size / max(image.width, image.height)
    width, height = round(image.width * scale), round(image.height * scale)
    left, top = (size - width) // 2, (size - height) // 2
    canvas = np.zeros((size, size, 3), dtype=np.float32)
    scaled = image.convert("RGB").resize((width, height), Image.BILINEAR)
    canvas[top : top + height, left : left + width] = np.asarray(scaled, np.float32) / 255
    return canvas.transpose(2, 0, 1)[np.newaxis], (left, top, width, height)


def unletterbox(output, placement: tuple[int, int, int, int], size: tuple[int, int]):
    """The model's mask cut back out of the letterbox at the image's own size."""
    import numpy as np
    from PIL import Image

    left, top, width, height = placement
    mask = np.clip(output[0, 0, top : top + height, left : left + width], 0, 1)
    resized = Image.fromarray(np.ascontiguousarray(mask, np.float32)).resize(size, Image.BILINEAR)
    return np.clip(np.asarray(resized, np.float32), 0, 1)


def segment(session, image):
    batch, placement = letterbox(image)
    name = session.get_inputs()[0].name
    output = session.run(None, {name: batch})[0]
    if output.shape != (1, 1, CUTOUT_SIZE, CUTOUT_SIZE):
        fail("model_invalid")
    return unletterbox(output, placement, image.size)


def alpha_from_mask(mask):
    """Confident values become fully clear or opaque; a short ramp keeps edges soft."""
    import numpy as np

    ramp = np.clip((mask - ALPHA_LOW) / (ALPHA_HIGH - ALPHA_LOW), 0, 1)
    return np.rint(ramp * 255).astype(np.uint8)


def _neighbour_sum(values):
    import numpy as np

    padded = np.pad(values, [(1, 1), (1, 1)] + [(0, 0)] * (values.ndim - 2))
    return padded[:-2, 1:-1] + padded[2:, 1:-1] + padded[1:-1, :-2] + padded[1:-1, 2:]


def bleed(color, known, pixels: int = BLEED_PIXELS):
    """Spread edge colours into clear pixels so scaled sprites filter without a fringe."""
    import numpy as np

    color = np.where(known[..., None], color, 0).astype(np.float32)
    weight = known.astype(np.float32)
    for _ in range(pixels):
        count = _neighbour_sum(weight)
        grow = (weight == 0) & (count > 0)
        if not grow.any():
            break
        color[grow] = _neighbour_sum(color)[grow] / count[grow][:, None]
        weight[grow] = 1
    if known.any():
        color[weight == 0] = color[known].mean(axis=0)
    return color


def crop_box(alpha, margin: int = CROP_MARGIN, min_width: int = THUMBNAIL_WIDTH):
    """The figure's bounds plus a margin, clamped to the image, at least a thumbnail wide."""
    import numpy as np

    height, width = alpha.shape
    rows, cols = np.flatnonzero(alpha.any(axis=1)), np.flatnonzero(alpha.any(axis=0))
    left, right = max(0, int(cols[0]) - margin), min(width, int(cols[-1]) + 1 + margin)
    top, bottom = max(0, int(rows[0]) - margin), min(height, int(rows[-1]) + 1 + margin)
    target = min(width, min_width)
    if right - left < target:
        left = min(max(0, (left + right - target) // 2), width - target)
        right = left + target
    return left, top, right, bottom


def cut_out(rgb, mask):
    """An RGBA sprite cropped to the figure, from an image and the segmenter's mask.

    Edge pixels blend figure and background, C = mF + (1 - m)B. Solving for F with
    the mask as coverage removes the background tint (the "halo") from them.
    """
    import numpy as np

    mask = np.clip(np.asarray(mask, np.float32), 0, 1)
    alpha = alpha_from_mask(mask)
    coverage = float((alpha > 127).mean())
    if not MIN_COVERAGE <= coverage <= MAX_COVERAGE:
        raise CutoutError
    pixels = np.asarray(rgb, np.float32)[..., :3]
    clear = alpha == 0
    background = np.median(pixels[clear], axis=0) if clear.any() else np.full(3, 255.0)
    blend = np.maximum(mask, ALPHA_LOW)[..., None]
    figure = np.clip((pixels - (1 - blend) * background) / blend, 0, 255)
    color = bleed(figure, ~clear)
    sprite = np.dstack([np.rint(color).astype(np.uint8), alpha])
    left, top, right, bottom = crop_box(alpha)
    return np.ascontiguousarray(sprite[top:bottom, left:right]), (left, top, right, bottom)


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
    # Load the small segmenter first so a bad pin fails before the minutes of SDXL work.
    segmenter, onnxruntime_version = (
        load_segmenter(request["cutout"]) if request["cutout"] else (None, None)
    )
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
        }
        | ({"onnxruntime": onnxruntime_version} if segmenter is not None else {}),
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
        extra: dict[str, object] = {}
        if segmenter is not None:
            import numpy as np

            try:
                sprite, box = cut_out(np.asarray(image.convert("RGB")), segment(segmenter, image))
            except CutoutError:
                fail("cutout_failed")
            image, extra["box"] = Image.fromarray(sprite), list(box)
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
            **extra,
        )
    emit("done", peak_bytes=torch.cuda.max_memory_allocated())


if __name__ == "__main__":
    main()
