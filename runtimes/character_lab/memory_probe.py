"""Synthetic LoRA backward-pass resource probe; NO images, useful weights or quality claim.

This intentionally does not train a character or a style. #184 requires a
creator-selected approved dataset before any such training run.
"""

import argparse
import json
import os
import time
from pathlib import Path

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")

import bitsandbytes as bnb
import pynvml
import torch
from diffusers import UNet2DConditionModel
from generate import PINS, verify
from peft import LoraConfig


def probe(args):
    if args.out.exists() or not 1 <= args.steps <= 20 or args.resolution not in (512, 768, 1024):
        raise ValueError("new output and bounded probe required")
    pynvml.nvmlInit()
    gpu = pynvml.nvmlDeviceGetHandleByIndex(0)
    free = pynvml.nvmlDeviceGetMemoryInfo(gpu).free
    if free < 10 * 2**30:
        raise RuntimeError("gpu_busy")
    verify(args.models / "animagine-xl-4.0", PINS["animagine-xl-4.0"])
    torch.manual_seed(20261101)
    began = time.monotonic()
    unet = UNet2DConditionModel.from_pretrained(
        args.models / "animagine-xl-4.0",
        subfolder="unet",
        local_files_only=True,
        use_safetensors=True,
        torch_dtype=torch.float16,
    )
    unet.requires_grad_(False)
    unet.add_adapter(
        LoraConfig(
            r=4,
            lora_alpha=4,
            init_lora_weights="gaussian",
            target_modules=["to_k", "to_q", "to_v", "to_out.0"],
        )
    )
    trainable = [parameter for parameter in unet.parameters() if parameter.requires_grad]
    for parameter in trainable:
        parameter.data = parameter.data.float()
    unet.enable_gradient_checkpointing()
    unet.to("cuda").train()
    optimizer = bnb.optim.AdamW8bit(trainable, lr=1e-4)
    scaler = torch.amp.GradScaler("cuda")
    side = args.resolution // 8
    latent = torch.randn((1, 4, side, side), device="cuda", dtype=torch.float16)
    noise = torch.randn_like(latent)
    context = torch.randn((1, 77, 2048), device="cuda", dtype=torch.float16)
    pooled = torch.randn((1, 1280), device="cuda", dtype=torch.float16)
    time_ids = torch.tensor(
        [[args.resolution, args.resolution, 0, 0, args.resolution, args.resolution]],
        device="cuda",
        dtype=torch.float16,
    )
    times, losses = [], []
    torch.cuda.reset_peak_memory_stats()
    for _ in range(args.steps):
        step = time.monotonic()
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast("cuda", dtype=torch.float16):
            predicted = unet(
                latent,
                torch.tensor([500], device="cuda"),
                context,
                added_cond_kwargs={"text_embeds": pooled, "time_ids": time_ids},
            ).sample
            loss = torch.nn.functional.mse_loss(predicted.float(), noise.float())
        scaler.scale(loss).backward()
        scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(trainable, 1)
        scaler.step(optimizer)
        scaler.update()
        torch.cuda.synchronize()
        times.append(time.monotonic() - step)
        losses.append(float(loss.detach()))
        print(
            json.dumps({"step": len(times), "seconds": times[-1], "loss": losses[-1]}), flush=True
        )
    result = {
        "schema": 1,
        "synthetic_only": True,
        "approved_training_images": 0,
        "saved_weights": False,
        "quality_measured": False,
        "model_manifest_sha256": PINS["animagine-xl-4.0"],
        "rank": 4,
        "batch": 1,
        "resolution": args.resolution,
        "gradient_checkpointing": True,
        "optimizer": "bitsandbytes.AdamW8bit",
        "cached_conditioning": True,
        "trainable_parameters": sum(p.numel() for p in trainable),
        "step_seconds": times,
        "losses": losses,
        "seconds_including_load": time.monotonic() - began,
        "torch_peak_bytes": torch.cuda.max_memory_allocated(),
        "device_used_bytes_after": pynvml.nvmlDeviceGetMemoryInfo(gpu).used,
        "torch": torch.__version__,
        "gpu": torch.cuda.get_device_name(0),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resolution", type=int, default=768)
    parser.add_argument("--steps", type=int, default=6)
    options = parser.parse_args()
    try:
        probe(options)
    except torch.OutOfMemoryError:
        print(
            "out_of_memory: feasibility failed at this configuration; no weights saved", flush=True
        )
        raise SystemExit(75) from None
