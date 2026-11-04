"""Offline rank-4 project-style training; no downloads, remote logging or pickle."""

import contextlib
import gc
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contract import LIMIT, bucket_size, parse_request, reference_size

OUT = sys.stdout


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}, allow_nan=False), file=OUT, flush=True)


def pose_contract():
    path = Path(__file__).resolve().parents[1] / "posegen/contract.py"
    spec = importlib.util.spec_from_file_location("verified_pose_model", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(request):
    began = time.monotonic()
    pins = pose_contract()
    root = Path(request["model_dir"])
    pins.verify_model(root, request["model_manifest_sha256"])
    paths = [Path(f"image-{i}.png") for i in range(len(request["images"]))]
    for path, image in zip(paths, request["images"], strict=True):
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > 8 * 1024**2
            or pins.digest(path) != image["sha256"]
        ):
            raise ValueError("input_integrity")
    os.environ.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        DISABLE_TELEMETRY="1",
    )
    import psutil
    import pynvml

    pynvml.nvmlInit()
    gpu = pynvml.nvmlDeviceGetHandleByIndex(0)
    if pynvml.nvmlDeviceGetMemoryInfo(gpu).free < 11 * 2**30:
        raise ValueError("gpu_busy")
    if psutil.virtual_memory().available < 6 * 2**30:
        raise ValueError("host_memory_busy")
    import bitsandbytes
    import diffusers
    import peft
    import torch
    from diffusers import (
        AutoencoderKLFlux2,
        FlowMatchEulerDiscreteScheduler,
        Flux2KleinPipeline,
        Flux2Transformer2DModel,
    )
    from peft import LoraConfig
    from peft.utils import get_peft_model_state_dict
    from PIL import Image
    from safetensors.torch import save_file

    if (
        not torch.cuda.is_available()
        or torch.cuda.device_count() != 1
        or not torch.cuda.is_bf16_supported()
    ):
        raise ValueError("unsupported_device")
    torch.manual_seed(request["seed"])
    torch.cuda.manual_seed_all(request["seed"])
    emit("stage", stage="encoding")
    options = dict(torch_dtype=torch.bfloat16, local_files_only=True, use_safetensors=True)
    encoder = Flux2KleinPipeline.from_pretrained(
        root, transformer=None, vae=None, device_map="cuda", is_distilled=True, **options
    )
    contexts = []
    torch.cuda.reset_peak_memory_stats()
    for image in request["images"]:
        caption = request["trigger"] + ", " + image["caption"]
        chat = encoder.tokenizer.apply_chat_template(
            [{"role": "user", "content": caption}],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        if len(encoder.tokenizer(chat, truncation=False)["input_ids"]) > 512:
            raise ValueError("caption_too_long")
        with torch.no_grad():
            embeddings, ids = encoder.encode_prompt(caption, device="cuda", max_sequence_length=512)
            contexts.append((embeddings.cpu(), ids.cpu()))
    peak = torch.cuda.max_memory_allocated()
    del encoder
    gc.collect()
    torch.cuda.empty_cache()
    emit("stage", stage="caching")
    vae = AutoencoderKLFlux2.from_pretrained(root, subfolder="vae", device_map="cuda", **options)
    vae.requires_grad_(False)
    vae.enable_tiling()
    mean = vae.bn.running_mean.view(1, -1, 1, 1).to("cuda")
    std = (vae.bn.running_var.view(1, -1, 1, 1) + vae.config.batch_norm_eps).sqrt().to("cuda")
    latents = []
    sizes = []
    for path in paths:
        with Image.open(path) as source:
            if source.format != "PNG":
                raise ValueError("invalid_image")
            size = bucket_size(*source.size)
            sizes.append(size)
            rgba = source.convert("RGBA")
            image = (
                Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba)
                .convert("RGB")
                .resize(size, Image.Resampling.LANCZOS)
            )
            import numpy as np

            pixels = (
                torch.from_numpy(np.array(image))
                .permute(2, 0, 1)
                .unsqueeze(0)
                .to(device="cuda", dtype=torch.bfloat16)
                / 127.5
                - 1
            )
        with torch.no_grad():
            raw = vae.encode(pixels).latent_dist.mode()
            latents.append(((Flux2KleinPipeline._patchify_latents(raw) - mean) / std).cpu())
    reference = None
    reference_shape = None
    if request["schema_version"] == 2:
        with Image.open(paths[request["reference_index"]]) as source:
            reference_shape = reference_size(*source.size)
            rgba = source.convert("RGBA")
            image = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba).convert(
                "RGB"
            )
            image.thumbnail((512, 512), Image.Resampling.LANCZOS)
            image = image.resize(reference_shape, Image.Resampling.LANCZOS)
            pixels = (
                torch.from_numpy(np.array(image))
                .permute(2, 0, 1)
                .unsqueeze(0)
                .to(device="cuda", dtype=torch.bfloat16)
                / 127.5
                - 1
            )
        with torch.no_grad():
            raw = vae.encode(pixels).latent_dist.mode()
            reference = ((Flux2KleinPipeline._patchify_latents(raw) - mean) / std).cpu()
    peak = max(peak, torch.cuda.max_memory_allocated())
    del vae, mean, std, pixels, raw
    gc.collect()
    torch.cuda.empty_cache()
    emit("stage", stage="training")
    transformer = Flux2Transformer2DModel.from_pretrained(
        root, subfolder="transformer", device_map="cuda", **options
    )
    transformer.requires_grad_(False)
    modules = ["to_q", "to_k", "to_v", "to_out.0", "to_qkv_mlp_proj"] + [
        f"single_transformer_blocks.{i}.attn.to_out"
        for i in range(len(transformer.single_transformer_blocks))
    ]
    transformer.add_adapter(
        LoraConfig(r=4, lora_alpha=4, init_lora_weights="gaussian", target_modules=modules)
    )
    params = [p for p in transformer.parameters() if p.requires_grad]
    for p in params:
        p.data = p.data.float()
    transformer.enable_gradient_checkpointing()
    transformer.train()
    optimizer = bitsandbytes.optim.AdamW8bit(params, lr=1e-4, weight_decay=1e-2)
    scheduler = FlowMatchEulerDiscreteScheduler.from_pretrained(
        root, subfolder="scheduler", local_files_only=True
    )
    losses = []
    torch.cuda.reset_peak_memory_stats()
    for step in range(request["steps"]):
        idx = step % len(latents)
        latent = latents[idx].to("cuda")
        context, text_ids = (item.to("cuda") for item in contexts[idx])
        index = torch.randint(0, len(scheduler.timesteps), (1,))
        sigma = scheduler.sigmas[index].to("cuda").reshape(1, 1, 1, 1)
        timestep = scheduler.timesteps[index].to("cuda") / 1000
        noise = torch.randn_like(latent)
        noisy = (1 - sigma) * latent + sigma * noise
        image_ids = Flux2KleinPipeline._prepare_latent_ids(latent).to("cuda")
        model_input = Flux2KleinPipeline._pack_latents(noisy)
        if reference is not None:
            from conditioning import training_inputs

            model_input, image_ids = training_inputs(noisy, reference.to("cuda"))
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            prediction = transformer(
                hidden_states=model_input,
                timestep=timestep,
                guidance=None,
                encoder_hidden_states=context,
                txt_ids=text_ids,
                img_ids=image_ids,
                return_dict=False,
            )[0]
            if reference is not None:
                from conditioning import target_prediction

                prediction = target_prediction(prediction, latent)
            else:
                prediction = Flux2KleinPipeline._unpack_latents_with_ids(prediction, image_ids)
            loss = torch.nn.functional.mse_loss(prediction.float(), (noise - latent).float())
        if not torch.isfinite(loss):
            raise ValueError("nonfinite_training")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(params, 1.0, error_if_nonfinite=True)
        optimizer.step()
        losses.append(float(loss.detach()))
        emit("progress", step=step + 1, loss=losses[-1])
    torch.cuda.synchronize()
    peak = max(peak, torch.cuda.max_memory_allocated())
    weights = {
        "transformer." + key: value.detach().float().contiguous().cpu()
        for key, value in get_peft_model_state_dict(transformer).items()
    }
    if not any(torch.count_nonzero(value) for key, value in weights.items() if ".lora_B." in key):
        raise ValueError("unchanged_adapter")
    Path("out").mkdir()
    save_file(
        weights,
        "out/adapter.safetensors",
        metadata={
            "format": "pt",
            "model_manifest_sha256": request["model_manifest_sha256"],
            "dataset_sha256": request["dataset_sha256"],
            "recipe_sha256": request["recipe_sha256"],
        },
    )
    runtime = dict(
        torch=torch.__version__,
        diffusers=diffusers.__version__,
        peft=peft.__version__,
        bitsandbytes=bitsandbytes.__version__,
        gpu=torch.cuda.get_device_name(0),
        peak_allocated_bytes=str(peak),
        dedicated_used_bytes_after=str(pynvml.nvmlDeviceGetMemoryInfo(gpu).used),
        host_rss_bytes=str(psutil.Process().memory_info().rss),
        seconds=str(round(time.monotonic() - began, 3)),
        child_sha256=pins.digest(Path(__file__)),
        protocol_sha256=pins.digest(Path(__file__).with_name("contract.py")),
        lock_sha256=pins.digest(Path(__file__).with_name("uv.lock")),
        bucket_sizes=json.dumps(sizes),
    )
    if reference is not None:
        runtime.update(
            conditioning="approved_look_image",
            reference_sha256=request["images"][request["reference_index"]]["sha256"],
            reference_size=json.dumps(reference_shape),
            loss_tokens="target_only",
            conditioning_sha256=pins.digest(Path(__file__).with_name("conditioning.py")),
        )
    emit(
        "result",
        sha256=pins.digest(Path("out/adapter.safetensors")),
        losses=losses,
        runtime=runtime,
    )


if __name__ == "__main__":
    try:
        request = parse_request(sys.stdin.buffer.read(LIMIT + 1))
        with contextlib.redirect_stdout(sys.stderr):
            run(request)
    except BaseException as error:
        import traceback

        traceback.print_exc(file=sys.stderr)
        code = (
            str(error)
            if isinstance(error, ValueError)
            else "out_of_memory"
            if type(error).__name__ == "OutOfMemoryError"
            else "training_failed"
        )
        if code not in {
            "gpu_busy",
            "host_memory_busy",
            "input_integrity",
            "model_invalid",
            "caption_too_long",
            "nonfinite_training",
            "unchanged_adapter",
            "unsupported_device",
            "invalid_request",
            "invalid_image",
            "out_of_memory",
        }:
            code = "training_failed"
        emit("error", code=code)
        sys.exit(75 if code in {"gpu_busy", "host_memory_busy", "out_of_memory"} else 2)
