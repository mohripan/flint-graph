"""FLUX.2 klein editing pilot with separate text-encoding and rendering phases.

No quantization or offload of a simultaneously resident full pipeline: free the
text encoder before loading the transformer, as a measured 12 GB experiment.
"""

import argparse
import gc
import json
import os
import time
from pathlib import Path

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")

import psutil
import pynvml
import torch
from diffusers import Flux2KleinPipeline
from edit_prompt import edit_prompt
from generate import canonical, digest, image, verify
from settings import gpu_floor_gib


def run(args):
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    if args.out.exists() or not 1 <= len(dataset["cases"]) <= 256:
        raise ValueError("new output and bounded cases required")
    verify(args.models, args.manifest_sha256)
    manifest = json.loads((args.models / "flintgraph-download.json").read_text())
    if (
        manifest["repo"] != "black-forest-labs/FLUX.2-klein-4B"
        or manifest["revision"] != "e7b7dc27f91deacad38e78976d1f2b499d76a294"
    ):
        raise ValueError("wrong editing checkpoint")
    pair = bool(dataset["cases"][0].get("participants"))
    if any(bool(case.get("participants")) != pair for case in dataset["cases"]):
        raise ValueError("mixed single and pair cases")
    if args.background_context and not pair:
        raise ValueError("background context is a pair-pilot ablation")
    refs = {key: image(args.dataset.parent, entry) for key, entry in dataset["references"].items()}
    background = (
        image(args.dataset.parent, dataset["background"]) if args.background_context else None
    )
    pynvml.nvmlInit()
    gpu = pynvml.nvmlDeviceGetHandleByIndex(0)
    if pynvml.nvmlDeviceGetMemoryInfo(gpu).free < gpu_floor_gib("klein", False) * 2**30:
        raise RuntimeError("gpu_busy")
    if psutil.virtual_memory().available < 9 * 2**30:
        raise RuntimeError("host_memory_busy")
    started = time.monotonic()
    options = dict(
        torch_dtype=torch.bfloat16, use_safetensors=True, local_files_only=True, is_distilled=True
    )
    # Phase 1: only the Qwen3 encoder and tokenizer, never the transformer.
    encoder = Flux2KleinPipeline.from_pretrained(args.models, transformer=None, vae=None, **options)
    encoder.to("cuda")
    embeddings = {}
    prompts = {
        case["id"]: edit_prompt(case, background_context=args.background_context)
        for case in dataset["cases"]
    }
    torch.cuda.reset_peak_memory_stats()
    with torch.no_grad():
        for prompt in dict.fromkeys(prompts.values()):
            embeddings[prompt] = encoder.encode_prompt(prompt, device="cuda")[0].cpu()
    encoding_peak = torch.cuda.max_memory_allocated()
    encoding_seconds = time.monotonic() - started
    del encoder
    gc.collect()
    torch.cuda.empty_cache()
    # Phase 2: precomputed embeddings, local transformer and VAE only.
    pipe = Flux2KleinPipeline.from_pretrained(
        args.models, text_encoder=None, tokenizer=None, **options
    )
    pipe.to("cuda")
    pipe.vae.enable_tiling()
    pipe.set_progress_bar_config(disable=True)
    args.out.mkdir(parents=True)
    metadata = {
        "schema": 1,
        "method": ("klein-pair-context" if args.background_context else "klein-pair")
        if pair
        else "klein",
        "dataset_sha256": canonical(dataset),
        "model_manifests": {"flux2-klein-4b": args.manifest_sha256},
        "generator_source_sha256": digest(Path(__file__)),
        "edit_prompt_source_sha256": digest(Path(__file__).with_name("edit_prompt.py")),
        "parameters": {
            "steps": 4,
            "guidance": 1.0,
            "dtype": "bfloat16",
            "quantized": False,
            "text_encoder_released_before_transformer": True,
            "max_sequence_length": 512,
            "background_context": args.background_context,
        },
        "versions": {
            "torch": torch.__version__,
            "diffusers": "0.42.1",
            "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0),
        },
        "encoding_seconds": encoding_seconds,
        "encoding_peak_bytes": encoding_peak,
        "load_seconds": time.monotonic() - started,
        "images": [],
    }
    physical = {}
    for index, case in enumerate(dataset["cases"]):
        began = time.monotonic()
        torch.cuda.reset_peak_memory_stats()
        prompt = prompts[case["id"]]
        people = case.get("participants", [case["character"]])
        key = (case["seed"], prompt, tuple(people), case["width"], case["height"])
        if key in physical:
            entry = physical[key] | {"id": case["id"], "reuse_of": physical[key]["id"]}
            if "box" in case:
                entry["box"] = case["box"]
            metadata["images"].append(entry)
            continue
        sources = [refs[person] for person in people]
        if background is not None:
            sources.append(background)
        result = pipe(
            image=sources if pair else sources[0],
            prompt_embeds=embeddings[prompt].to("cuda"),
            width=case["width"],
            height=case["height"],
            num_inference_steps=4,
            guidance_scale=1,
            generator=torch.Generator("cuda").manual_seed(case["seed"]),
        ).images[0]
        name = f"{index:03d}.png"
        result.save(args.out / name)
        entry = {
            "id": case["id"],
            "image": name,
            "sha256": digest(args.out / name),
            "prompt": prompt,
            "seconds": time.monotonic() - began,
            "torch_peak_bytes": torch.cuda.max_memory_allocated(),
            "device_used_bytes_after": pynvml.nvmlDeviceGetMemoryInfo(gpu).used,
            "host_rss_bytes": psutil.Process().memory_info().rss,
        }
        physical[key] = entry.copy()
        if "box" in case:
            entry["box"] = case["box"]
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
    metadata["physical_image_count"] = len(physical)
    (args.out / "run.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (args.out / "run.partial.json").unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--background-context", action="store_true")
    try:
        run(parser.parse_args())
    except torch.OutOfMemoryError:
        print("out_of_memory: editing configuration is unqualified", flush=True)
        raise SystemExit(75) from None
