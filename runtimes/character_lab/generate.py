"""Bounded offline pose pilot. Run separately from the Studio image worker.

This is an experimental CLI, not a worker protocol or a production pose feature.
Each invocation creates one immutable method run; all cases share dataset seeds.
"""

import argparse
import gc
import hashlib
import json
import os
import sys
import time
from pathlib import Path

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")

import pynvml
import torch
from diffusers import (
    ControlNetModel,
    EulerAncestralDiscreteScheduler,
    StableDiffusionXLControlNetPipeline,
    StableDiffusionXLImg2ImgPipeline,
    StableDiffusionXLPipeline,
)
from PIL import Image
from reference import reference_image
from settings import gpu_floor_gib, img2img_strength
from transformers import CLIPVisionModelWithProjection

PINS = {
    "animagine-xl-4.0": "9c2308313c36fd1479e178b34eb0b4f861257177d222b87dfbbab07e2feac900",
    "ip-adapter": "760958414c3111196983fee599755d99c5146bd2b8d62e9526d7d245a20823ee",
    "controlnet-openpose-sdxl": "f2392eedba8043bc2f40640d38bbdc244a7bc1af1cbece596b0567349f4cc677",
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def verify(folder, expected):
    manifest = folder / "flintgraph-download.json"
    if digest(manifest) != expected:
        raise ValueError("unreviewed model manifest")
    for name, entry in json.loads(manifest.read_text())["files"].items():
        path = folder / name
        if not path.resolve().is_relative_to(folder.resolve()) or digest(path) != entry["sha256"]:
            raise ValueError("model hash mismatch")


def image(root, entry):
    path = root / entry["image"]
    if not path.resolve().is_relative_to(root.resolve()) or digest(path) != entry["sha256"]:
        raise ValueError("fixture hash mismatch")
    with Image.open(path) as source:
        flat = Image.new("RGBA", source.size, "white")
        flat.alpha_composite(source.convert("RGBA"))
    return flat.convert("RGB")


def run(args):
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    if not 1 <= len(dataset["cases"]) <= 256 or args.out.exists():
        raise ValueError("bounded cases and new output required")
    if args.cache_text_embeddings and args.method != "control":
        raise ValueError("text-cache resource ablation is defined for control only")
    # Never evict another process or stop a service to make room.
    pynvml.nvmlInit()
    gpu = pynvml.nvmlDeviceGetHandleByIndex(0)
    free = pynvml.nvmlDeviceGetMemoryInfo(gpu).free
    if free < gpu_floor_gib(args.method, args.cache_text_embeddings) * 2**30:
        raise RuntimeError("gpu_busy: leave work queued; do not interrupt another owner")
    for name in ("animagine-xl-4.0", "ip-adapter"):
        verify(args.models / name, PINS[name])
    if args.method == "control":
        verify(args.models / "controlnet-openpose-sdxl", PINS["controlnet-openpose-sdxl"])
    if args.method == "face":
        if not args.face_models:
            raise ValueError("explicit face adapter directory required")
        verify(args.face_models, "3d0e766cd0f9893ccd6f506d713e61d4642bebf3bc49c1ecfd071dabcb766fb7")
    refs = {key: image(args.dataset.parent, ref) for key, ref in dataset["references"].items()}
    started = time.monotonic()
    options = dict(torch_dtype=torch.float16, use_safetensors=True, local_files_only=True)
    if args.method == "control":
        control = ControlNetModel.from_pretrained(
            args.models / "controlnet-openpose-sdxl", **options
        )
        pipe = StableDiffusionXLControlNetPipeline.from_pretrained(
            args.models / "animagine-xl-4.0", controlnet=control, **options
        )
    else:
        pipe = StableDiffusionXLPipeline.from_pretrained(
            args.models / "animagine-xl-4.0", **options
        )
    pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)
    pipe.set_progress_bar_config(disable=True)
    embeddings = {}
    if args.method != "text":
        if args.method == "face":
            encoder = CLIPVisionModelWithProjection.from_pretrained(
                args.models / "ip-adapter/models/image_encoder", **options
            )
            pipe.register_modules(image_encoder=encoder)
        pipe.load_ip_adapter(
            str(args.face_models if args.method == "face" else args.models / "ip-adapter"),
            subfolder="sdxl_models",
            weight_name=(
                "ip-adapter-plus-face_sdxl_vit-h.safetensors"
                if args.method == "face"
                else "ip-adapter-plus_sdxl_vit-h.safetensors"
            ),
            image_encoder_folder=None if args.method == "face" else "models/image_encoder",
            local_files_only=True,
        )
        pipe.image_encoder.to("cuda")
        with torch.no_grad():
            for key, ref in refs.items():
                # Same approved source, two scales: no new unreviewed look is introduced.
                # This is NOT two independently approved views or a character sheet.
                inputs = [ref, ref.crop((ref.width // 4, 0, ref.width * 3 // 4, ref.height // 3))]
                inputs = (
                    [reference_image(item) for item in inputs]
                    if args.method == "multi"
                    else reference_image(ref)
                )
                if args.method == "face":
                    inputs = reference_image(
                        ref.crop((ref.width // 4, 0, ref.width * 3 // 4, ref.height // 3))
                    )
                embeddings[key] = pipe.prepare_ip_adapter_image_embeds(
                    [inputs], None, "cuda", 1, True
                )
        encoder = pipe.image_encoder
        pipe.register_modules(image_encoder=None)
        del encoder
        torch.cuda.empty_cache()
        pipe.set_ip_adapter_scale(0.5)
    text_cache = {}
    if args.cache_text_embeddings:
        pipe.text_encoder.to("cuda")
        pipe.text_encoder_2.to("cuda")
        with torch.no_grad():
            for case in dataset["cases"]:
                key = (case["prompt"], case["negative_prompt"])
                if key not in text_cache:
                    encoded = pipe.encode_prompt(
                        prompt=key[0],
                        negative_prompt=key[1],
                        device="cuda",
                        num_images_per_prompt=1,
                        do_classifier_free_guidance=True,
                    )
                    text_cache[key] = tuple(value.cpu() for value in encoded)
                    del encoded
        pipe.register_modules(text_encoder=None, text_encoder_2=None)
        gc.collect()
        torch.cuda.empty_cache()
    pipe.to("cuda")
    pipe.vae.enable_tiling()
    if args.method == "img2img":
        pipe = StableDiffusionXLImg2ImgPipeline.from_pipe(pipe, torch_dtype=torch.float16)
        pipe.set_progress_bar_config(disable=True)
    args.out.mkdir(parents=True)
    metadata = {
        "schema": 1,
        "method": (
            f"img2img-{round(args.img2img_strength * 1000)}"
            if args.method == "img2img" and args.img2img_strength != 0.7
            else args.method + ("-cached" if args.cache_text_embeddings else "")
        ),
        "generator_source_sha256": digest(Path(__file__)),
        "reference_preparation_sha256": digest(Path(__file__).with_name("reference.py")),
        "face_manifest_sha256": (
            "3d0e766cd0f9893ccd6f506d713e61d4642bebf3bc49c1ecfd071dabcb766fb7"
            if args.method == "face"
            else None
        ),
        "dataset_sha256": canonical(dataset),
        "model_manifests": {
            k: v
            for k, v in PINS.items()
            if k != "controlnet-openpose-sdxl" or args.method == "control"
        },
        "parameters": {
            "ip_scale": 0.5 if embeddings else None,
            "img2img_strength": args.img2img_strength,
            "control_scale": 0.8,
            "scheduler": "EulerAncestralDiscreteScheduler",
            "text_encoders_released": args.cache_text_embeddings,
            "text_cache_entries": len(text_cache),
        },
        "versions": {
            "torch": torch.__version__,
            "diffusers": "0.42.1",
            "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0),
        },
        "load_seconds": time.monotonic() - started,
        "images": [],
    }
    for index, case in enumerate(dataset["cases"]):
        began = time.monotonic()
        torch.cuda.reset_peak_memory_stats()
        kwargs = dict(
            prompt=case["short_prompt"] if args.method == "ip" else case["prompt"],
            negative_prompt=case["negative_prompt"],
            width=case["width"],
            height=case["height"],
            num_inference_steps=case["steps"],
            guidance_scale=case["guidance"],
            generator=torch.Generator("cuda").manual_seed(case["seed"]),
        )
        if text_cache:
            encoded = text_cache[(case["prompt"], case["negative_prompt"])]
            kwargs.pop("prompt")
            kwargs.pop("negative_prompt")
            kwargs.update(
                zip(
                    (
                        "prompt_embeds",
                        "negative_prompt_embeds",
                        "pooled_prompt_embeds",
                        "negative_pooled_prompt_embeds",
                    ),
                    (value.to("cuda") for value in encoded),
                    strict=True,
                )
            )
        if embeddings:
            kwargs["ip_adapter_image_embeds"] = embeddings[case["character"]]
        if args.method == "img2img":
            kwargs.update(image=refs[case["character"]], strength=args.img2img_strength)
        elif args.method == "control":
            kwargs.update(
                image=image(args.dataset.parent, case["control"]), controlnet_conditioning_scale=0.8
            )
        result = pipe(**kwargs).images[0]
        name = f"{index:03d}.png"
        result.save(args.out / name)
        entry = {
            "id": case["id"],
            "image": name,
            "sha256": digest(args.out / name),
            "seconds": time.monotonic() - began,
            "torch_peak_bytes": torch.cuda.max_memory_allocated(),
            "device_used_bytes_after": pynvml.nvmlDeviceGetMemoryInfo(gpu).used,
        }
        metadata["images"].append(entry)
        (args.out / "run.partial.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "id": case["id"],
                    "seconds": entry["seconds"],
                    "peak_mib": entry["torch_peak_bytes"] / 2**20,
                }
            ),
            flush=True,
        )
    (args.out / "run.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (args.out / "run.partial.json").unlink()
    print(json.dumps({"done": len(metadata["images"]), "seconds": time.monotonic() - started}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument(
        "--method",
        choices=("text", "ip", "locked", "multi", "control", "img2img", "face"),
        required=True,
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--face-models", type=Path)
    parser.add_argument("--img2img-strength", type=img2img_strength, default=0.7)
    parser.add_argument("--cache-text-embeddings", action="store_true")
    options = parser.parse_args()
    try:
        run(options)
    except torch.OutOfMemoryError:
        print("out_of_memory: incomplete run retained, never rank as successful", file=sys.stderr)
        raise SystemExit(75) from None
