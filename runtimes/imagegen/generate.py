"""Isolated local image-generation child for FlintGraph narrative assets.

The trusted parent starts this with ``python -I generate.py`` from the locked
runtime environment, writes one JSON request to stdin and reads JSON lines from
stdout. The child loads a pinned local SDXL model from safetensors only, never
downloads or runs remote code, writes PNG files into the parent's private
output directory and exits, which releases all GPU memory.

With a ``cutout`` request it also separates the figure from its plain background
with a pinned anime segmentation model (ONNX, run on the CPU from bytes it hashed
itself) and writes cropped RGBA sprites instead of opaque images. A render with
no usable figure is reported as ``skipped`` and the others are kept; the job fails
with ``cutout_failed`` only when no render survives.

With an ``inpaint`` request (ADR 0041) it repaints only the face of a base image,
one prompt per seed: a square around the face box is upscaled, inpainted under a
feathered ellipse, scaled back and pasted, and the base alpha is restored. Size,
silhouette and everything outside the face stay exactly as they were.

With a ``hires`` request each render is upscaled (Lanczos) and lightly repainted
at the larger size by the same weights (img2img, same prompt and seed), so large
stage sprites gain real detail; the cutout then runs on the final image.
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
HIRES_SCALES = {1.5, 2.0}
HIRES_STRENGTH = (0.2, 0.6)
# The repaint at the upscaled size needs more; measured peaks on a 12 GB RTX 5070 Ti
# were 8.3 GiB (standard), 8.4 GiB (1.5x) and 9.5 GiB (2x) of dedicated memory.
HIRES_MIN_FREE_BYTES = {1.5: int(8.5 * 1024**3), 2.0: int(9.5 * 1024**3)}
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
# Face inpainting: the face is redrawn at this size with this much context around it.
INPAINT_SIZE = 1024
FACE_CONTEXT = 2.4
BASE_LIMIT = 16 * 1024 * 1024
MIN_BASE, MAX_BASE = 64, 2560  # covers 2x high-resolution sprites (1664 x 2432)
MIN_FACE = 16
# The mask reaches a little past the box sideways and down (cheeks, chin) but barely
# up, so little hair is repainted; feathering hides the seam.
MASK_GROW, MASK_GROW_UP, MASK_FEATHER = 0.12, 0.06, 20


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


def hires_size(width: int, height: int, scale: float) -> tuple[int, int]:
    return round(width * scale), round(height * scale)


def upscale(image, scale: float):
    from PIL import Image

    return image.resize(hires_size(image.width, image.height, scale), Image.LANCZOS)


def required_free_bytes(hires: dict | None) -> int:
    return MIN_FREE_BYTES if hires is None else HIRES_MIN_FREE_BYTES[hires["scale"]]


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
    # ``cutout`` and ``hires`` are optional so a parent that predates them keeps working.
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
        or set(request) - {"cutout", "inpaint", "hires"} != expected
        or request["protocol"] != PROTOCOL
    ):
        fail("bad_request")
    request.setdefault("cutout", None)
    request.setdefault("inpaint", None)
    request.setdefault("hires", None)
    hires = request["hires"]
    if hires is not None and (
        type(hires) is not dict
        or set(hires) != {"scale", "strength"}
        or type(hires["scale"]) not in (int, float)
        or hires["scale"] not in HIRES_SCALES
        or type(hires["strength"]) not in (int, float)
        or not HIRES_STRENGTH[0] <= hires["strength"] <= HIRES_STRENGTH[1]
        or request["inpaint"] is not None
    ):
        fail("bad_request")
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
    inpaint = request["inpaint"]
    if inpaint is not None and (cutout is not None or not valid_inpaint(inpaint, request)):
        fail("bad_request")
    if (
        not all(
            type(request[key]) is str
            for key in ("model_dir", "output_dir", "prompt", "negative_prompt")
        )
        or (inpaint is None and (request["width"], request["height"]) not in SIZES)
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


def png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def valid_inpaint(inpaint: object, request: dict) -> bool:
    """The base image is the parent's verified copy; check it again before any model."""
    if (
        type(inpaint) is not dict
        or set(inpaint) != {"image", "sha256", "box", "strength", "prompts"}
        or type(inpaint["image"]) is not str
        or not Path(inpaint["image"]).is_absolute()
        or type(inpaint["sha256"]) is not str
        or type(inpaint["strength"]) not in (int, float)
        or not 0.3 <= inpaint["strength"] <= 1
        or type(inpaint["prompts"]) is not list
        or type(request["seeds"]) is not list
        or len(inpaint["prompts"]) != len(request["seeds"])
        or any(
            type(prompt) is not str or not 1 <= len(prompt) <= 2000
            for prompt in inpaint["prompts"]
        )
        or type(inpaint["box"]) is not list
        or len(inpaint["box"]) != 4
        or any(type(value) is not int for value in inpaint["box"])
    ):
        return False
    path = Path(inpaint["image"])
    if not path.is_file() or path.stat().st_size > BASE_LIMIT:
        return False
    data = path.read_bytes()
    size = png_size(data)
    if hashlib.sha256(data).hexdigest() != inpaint["sha256"] or size is None:
        return False
    width, height = size
    left, top, right, bottom = inpaint["box"]
    return (
        (request["width"], request["height"]) == size
        and MIN_BASE <= width <= MAX_BASE
        and MIN_BASE <= height <= MAX_BASE
        and 0 <= left < right <= width
        and 0 <= top < bottom <= height
        and right - left >= MIN_FACE
        and bottom - top >= MIN_FACE
    )


def face_context(image, box):
    """The face with context around it: a white-padded square upscaled for inpainting."""
    from PIL import Image

    left, top, right, bottom = box
    side = round(max(right - left, bottom - top) * FACE_CONTEXT)
    cx, cy = (left + right) / 2, (top + bottom) / 2
    crop = (round(cx - side / 2), round(cy - side / 2))
    crop = (*crop, crop[0] + side, crop[1] + side)
    flat = Image.new("RGBA", image.size, (255, 255, 255, 255))
    flat.alpha_composite(image.convert("RGBA"))
    padded = Image.new("RGB", (side, side), (255, 255, 255))
    padded.paste(flat.convert("RGB"), (-crop[0], -crop[1]))
    return padded.resize((INPAINT_SIZE, INPAINT_SIZE), Image.LANCZOS), crop


def face_mask(box, crop):
    """A feathered ellipse over the face, in the coordinates of the upscaled context."""
    from PIL import Image, ImageDraw, ImageFilter

    scale = INPAINT_SIZE / (crop[2] - crop[0])
    left, top, right, bottom = (
        (box[0] - crop[0]) * scale,
        (box[1] - crop[1]) * scale,
        (box[2] - crop[0]) * scale,
        (box[3] - crop[1]) * scale,
    )
    grow = MASK_GROW * (right - left)
    mask = Image.new("L", (INPAINT_SIZE, INPAINT_SIZE), 0)
    ImageDraw.Draw(mask).ellipse(
        (left - grow, top - MASK_GROW_UP * (bottom - top), right + grow, bottom + grow), fill=255
    )
    return mask.filter(ImageFilter.GaussianBlur(MASK_FEATHER))


def paste_face(base, painted, crop, mask):
    """Blend the repainted face into the base; only opaque pixels change, alpha never."""
    import numpy as np
    from PIL import Image

    side = crop[2] - crop[0]
    patch = painted.convert("RGB").resize((side, side), Image.LANCZOS)
    weight = np.zeros((base.height, base.width), dtype=np.float32)
    small = np.asarray(mask.resize((side, side), Image.LANCZOS), dtype=np.float32) / 255
    layer = np.zeros((base.height, base.width, 3), dtype=np.float32)
    # Where the square lies inside the base image.
    x0, y0 = max(crop[0], 0), max(crop[1], 0)
    x1, y1 = min(crop[2], base.width), min(crop[3], base.height)
    if x1 > x0 and y1 > y0:
        source = np.asarray(patch, dtype=np.float32)
        layer[y0:y1, x0:x1] = source[y0 - crop[1] : y1 - crop[1], x0 - crop[0] : x1 - crop[0]]
        weight[y0:y1, x0:x1] = small[y0 - crop[1] : y1 - crop[1], x0 - crop[0] : x1 - crop[0]]
    pixels = np.asarray(base.convert("RGBA") if base.mode == "RGBA" else base.convert("RGB"))
    if base.mode == "RGBA":
        # Soft edges keep their colour: repainting them would mix in the white backdrop.
        weight *= pixels[..., 3] == 255
    rgb = pixels[..., :3].astype(np.float32)
    blended = np.rint(weight[..., None] * layer + (1 - weight[..., None]) * rgb).astype(np.uint8)
    if base.mode == "RGBA":
        return Image.fromarray(np.dstack([blended, pixels[..., 3]]), "RGBA")
    return Image.fromarray(blended, "RGB")


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
    from diffusers import (
        EulerAncestralDiscreteScheduler,
        StableDiffusionXLImg2ImgPipeline,
        StableDiffusionXLInpaintPipeline,
        StableDiffusionXLPipeline,
    )
    from PIL import Image

    inpaint = request["inpaint"]

    if not torch.cuda.is_available():
        fail("gpu_unavailable")
    try:
        free = dedicated_free_bytes()
    except Exception:
        fail("gpu_unavailable")
    required = required_free_bytes(request["hires"])
    if free < required:
        emit("busy", free_bytes=free, required_bytes=required)
        fail("gpu_busy")
    started = time.monotonic()
    # Load the small segmenter first so a bad pin fails before the minutes of SDXL work.
    segmenter, onnxruntime_version = (
        load_segmenter(request["cutout"]) if request["cutout"] else (None, None)
    )
    # Face inpainting runs the same weights as masked img2img (a 4-channel UNet).
    kind = StableDiffusionXLInpaintPipeline if inpaint else StableDiffusionXLPipeline
    try:
        pipeline = kind.from_pretrained(
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
    hires = request["hires"]
    # The repaint shares every module (and the tiled VAE) with the base pipeline. Without
    # an explicit dtype, from_pipe casts the shared modules to float32 in place, which
    # doubles their memory and spills past a 12 GB card.
    refine = (
        StableDiffusionXLImg2ImgPipeline.from_pipe(pipeline, torch_dtype=torch.float16)
        if hires
        else None
    )
    if refine is not None:
        refine.set_progress_bar_config(disable=True)
    prompts = inpaint["prompts"] if inpaint else [request["prompt"]] * len(request["seeds"])
    tokens = max(len(pipeline.tokenizer(prompt).input_ids) for prompt in prompts)
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
    if inpaint:
        base = Image.open(inpaint["image"])
        base.load()
        base = base.convert("RGBA" if "A" in base.getbands() else "RGB")
        box = tuple(inpaint["box"])
        context, crop = face_context(base, box)
        mask = face_mask(box, crop)
    kept = 0
    for index, seed in enumerate(request["seeds"]):
        began = time.monotonic()
        try:
            if inpaint:
                painted = pipeline(
                    prompt=prompts[index],
                    negative_prompt=request["negative_prompt"],
                    image=context,
                    mask_image=mask,
                    width=INPAINT_SIZE,
                    height=INPAINT_SIZE,
                    strength=float(inpaint["strength"]),
                    num_inference_steps=request["steps"],
                    guidance_scale=float(request["guidance"]),
                    generator=torch.Generator("cuda").manual_seed(seed),
                ).images[0]
                image = paste_face(base, painted, crop, mask)
            else:
                image = pipeline(
                    prompt=request["prompt"],
                    negative_prompt=request["negative_prompt"],
                    width=request["width"],
                    height=request["height"],
                    num_inference_steps=request["steps"],
                    guidance_scale=float(request["guidance"]),
                    generator=torch.Generator("cuda").manual_seed(seed),
                ).images[0]
                if refine is not None:
                    image = refine(
                        prompt=request["prompt"],
                        negative_prompt=request["negative_prompt"],
                        image=upscale(image, hires["scale"]),
                        strength=float(hires["strength"]),
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
                # One render with no usable figure is skipped; the job keeps the others.
                emit("skipped", index=index, seed=seed, code="cutout_failed")
                continue
            image, extra["box"] = Image.fromarray(sprite), list(box)
        kept += 1
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
    if not kept:
        fail("cutout_failed")
    emit("done", peak_bytes=torch.cuda.max_memory_allocated())


if __name__ == "__main__":
    main()
