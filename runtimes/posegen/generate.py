"""Offline production pose editor: staged FLUX.2 klein plus optional sprite cutout."""

import contextlib
import gc
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contract import HEIGHT, REQUEST_LIMIT, WIDTH, digest, parse_request, verify_model

PROTOCOL_OUTPUT = sys.stdout


class PoseFailure(Exception):
    pass


def emit(event, **values):
    print(json.dumps({"event": event, **values}, allow_nan=False), file=PROTOCOL_OUTPUT, flush=True)


def cutout_module():
    path = Path(__file__).resolve().parents[1] / "imagegen/generate.py"
    spec = importlib.util.spec_from_file_location("flint_pose_cutout", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def run(request):
    began = time.monotonic()
    os.environ.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        DISABLE_TELEMETRY="1",
    )
    try:
        verify_model(Path(request["model_dir"]), request["model_manifest_sha256"])
    except ValueError:
        raise PoseFailure("model_invalid") from None
    hashes = (
        [request["reference_sha256"]]
        if request["schema_version"] == 1
        else request["reference_sha256s"]
    )
    reference_paths = (
        [Path("reference.png")]
        if len(hashes) == 1
        else [Path(f"reference-{i}.png") for i in range(2)]
    )
    for reference, expected in zip(reference_paths, hashes, strict=True):
        if (
            reference.is_symlink()
            or not reference.is_file()
            or reference.stat().st_size > 16 * 1024 * 1024
            or digest(reference) != expected
        ):
            raise PoseFailure("reference_unavailable")
    import psutil
    import pynvml

    pynvml.nvmlInit()
    gpu = pynvml.nvmlDeviceGetHandleByIndex(0)
    if pynvml.nvmlDeviceGetMemoryInfo(gpu).free < 11 * 2**30:
        raise PoseFailure("gpu_busy")
    if psutil.virtual_memory().available < 6 * 2**30:
        raise PoseFailure("host_memory_busy")
    host_available_at_start = psutil.virtual_memory().available
    import diffusers
    import torch
    from diffusers import Flux2KleinPipeline
    from PIL import Image

    if (
        not torch.cuda.is_available()
        or torch.cuda.device_count() != 1
        or not torch.cuda.is_bf16_supported()
    ):
        raise PoseFailure("unsupported_device")
    sources = []
    for index, reference in enumerate(reference_paths):
        with Image.open(reference) as original:
            if (
                original.format != "PNG"
                or not 64 <= min(original.size)
                or max(original.size) > 2560
            ):
                raise PoseFailure("reference_unavailable")
            rgba = original.convert("RGBA")
            source = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba).convert(
                "RGB"
            )
            if index:
                source.thumbnail((512, 512), Image.Resampling.LANCZOS)
            sources.append(source)
    segmenter, helper, helper_path = None, None, None
    if request["cutout"]:
        helper, helper_path = cutout_module()
        with contextlib.redirect_stdout(sys.stderr):
            segmenter, onnx_version = helper.load_segmenter(request["cutout"])
    options = dict(
        torch_dtype=torch.bfloat16,
        use_safetensors=True,
        local_files_only=True,
        is_distilled=True,
        device_map="cuda",
        low_cpu_mem_usage=True,
    )
    emit("stage", stage="encoding")
    encoder = Flux2KleinPipeline.from_pretrained(
        request["model_dir"], transformer=None, vae=None, **options
    )
    chat = encoder.tokenizer.apply_chat_template(
        [{"role": "user", "content": request["prompt"]}],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    tokens = len(encoder.tokenizer(chat, truncation=False)["input_ids"])
    if tokens > 512:
        raise PoseFailure("prompt_too_long")
    encoder.to("cuda")
    torch.cuda.reset_peak_memory_stats()
    with torch.no_grad():
        embeddings = encoder.encode_prompt(
            request["prompt"], device="cuda", max_sequence_length=512
        )[0].cpu()
    encoding_peak = torch.cuda.max_memory_allocated()
    del encoder
    gc.collect()
    torch.cuda.empty_cache()
    emit("stage", stage="rendering")
    pipe = Flux2KleinPipeline.from_pretrained(
        request["model_dir"], text_encoder=None, tokenizer=None, **options
    )
    pipe.to("cuda")
    pipe.vae.enable_tiling()
    pipe.set_progress_bar_config(disable=True)
    out = Path("out")
    out.mkdir()
    images, peak = [], encoding_peak
    for index, seed in enumerate(request["seeds"]):
        torch.cuda.reset_peak_memory_stats()
        image = pipe(
            image=sources[0] if len(sources) == 1 else sources,
            prompt_embeds=embeddings.to("cuda"),
            width=WIDTH,
            height=HEIGHT,
            num_inference_steps=4,
            guidance_scale=1,
            generator=torch.Generator("cuda").manual_seed(seed),
        ).images[0]
        peak = max(peak, torch.cuda.max_memory_allocated())
        box = None
        if segmenter is not None:
            import numpy as np

            try:
                with contextlib.redirect_stdout(sys.stderr):
                    sprite, box = helper.cut_out(
                        np.asarray(image.convert("RGB")), helper.segment(segmenter, image)
                    )
                image = Image.fromarray(sprite)
            except helper.CutoutError:
                emit("progress", done=index + 1)
                continue
        image.save(out / f"{index}.png")
        thumbnail = image.copy()
        thumbnail.thumbnail((256, 256), Image.Resampling.LANCZOS)
        thumbnail.save(out / f"thumb-{index}.png")
        images.append({"index": index, "seed": seed, "box": list(box) if box else None})
        emit("progress", done=index + 1)
    if not images:
        raise PoseFailure("cutout_failed")
    runtime = {
        "operation": "pose",
        "torch": torch.__version__,
        "diffusers": diffusers.__version__,
        "cuda": str(torch.version.cuda),
        "gpu": torch.cuda.get_device_name(0),
        "model_manifest_sha256": request["model_manifest_sha256"],
        "source_sha256": hashes[0],
        "reference_sha256s": json.dumps(hashes, separators=(",", ":")),
        "reference_count": str(len(hashes)),
        "additional_reference_preprocessing": "fit-512-lanczos-v1",
        "reference_sizes": json.dumps(
            [list(image.size) for image in sources], separators=(",", ":")
        ),
        "pose_child_sha256": digest(Path(__file__)),
        "protocol_sha256": digest(Path(__file__).with_name("contract.py")),
        "text_encoder_released_before_transformer": "true",
        "peak_allocated_bytes": str(peak),
        "dedicated_used_bytes_after": str(pynvml.nvmlDeviceGetMemoryInfo(gpu).used),
        "host_available_at_start_bytes": str(host_available_at_start),
        "direct_cuda_loading": "true",
        "host_rss_bytes": str(psutil.Process().memory_info().rss),
        "seconds": str(round(time.monotonic() - began, 3)),
    }
    if helper_path:
        runtime.update(cutout_code_sha256=digest(helper_path), onnxruntime=onnx_version)
    emit("result", images=images, prompt_tokens=tokens, runtime=runtime)


if __name__ == "__main__":
    try:
        try:
            request = parse_request(sys.stdin.buffer.read(REQUEST_LIMIT + 1))
        except ValueError:
            raise PoseFailure("invalid_request") from None
        with contextlib.redirect_stdout(sys.stderr):
            run(request)
    except PoseFailure as error:
        emit("error", code=str(error))
        sys.exit(75 if str(error) in {"gpu_busy", "host_memory_busy"} else 2)
    except BaseException as error:
        import traceback

        traceback.print_exc(file=sys.stderr)
        code = (
            "out_of_memory" if type(error).__name__ == "OutOfMemoryError" else "generation_failed"
        )
        emit("error", code=code)
        sys.exit(75 if code == "out_of_memory" else 2)
