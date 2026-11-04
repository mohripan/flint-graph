"""Bounded cancellable child supervision for the trusted offline trainer."""

import asyncio
import hashlib
import json
import math
import os
import sys
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flint_graph.infrastructure.narrative_posegen import stop_child
from flint_graph.narrative.style_weights import MAX_ADAPTER_BYTES, validate_adapter


@dataclass(frozen=True)
class StyleTrainingRequest:
    images: tuple[tuple[bytes, str], ...]
    dataset_hash: str
    recipe_hash: str
    trigger: str
    steps: int
    seed: int
    reference_index: int | None = None


@dataclass(frozen=True)
class StyleTrainingResult:
    weights: bytes
    losses: list[float]
    runtime: dict[str, str]


class LocalStyleTrainer:
    def __init__(
        self, *, python: Path, script: Path, model_dir: Path, model_hash: str, deadline: float
    ) -> None:
        self.python, self.script, self.model_dir = python, script, model_dir
        self.model_hash, self.deadline = model_hash, deadline

    async def train(
        self, request: StyleTrainingRequest, *, on_progress: Callable[[int], Awaitable[None]]
    ) -> StyleTrainingResult:
        if request.reference_index is not None and (
            type(request.reference_index) is not int
            or not 0 <= request.reference_index < len(request.images)
        ):
            raise ValueError("invalid_reference")
        with tempfile.TemporaryDirectory(prefix="flint-style-") as directory:
            work = Path(directory)
            images = []
            for index, (data, caption) in enumerate(request.images):
                (work / f"image-{index}.png").write_bytes(data)
                images.append({"sha256": hashlib.sha256(data).hexdigest(), "caption": caption})
            payload = {
                "schema_version": 2 if request.reference_index is not None else 1,
                **(
                    {"reference_index": request.reference_index}
                    if request.reference_index is not None
                    else {}
                ),
                "model_dir": str(self.model_dir.resolve()),
                "model_manifest_sha256": self.model_hash,
                "dataset_sha256": request.dataset_hash,
                "recipe_sha256": request.recipe_hash,
                "trigger": request.trigger,
                "steps": request.steps,
                "seed": request.seed,
                "images": images,
            }
            env = {
                key: value
                for key, value in os.environ.items()
                if key.upper()
                in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC", "CUDA_PATH"}
            }
            env.update(
                HF_HUB_OFFLINE="1",
                TRANSFORMERS_OFFLINE="1",
                HF_HUB_DISABLE_TELEMETRY="1",
                TORCHINDUCTOR_CACHE_DIR=str(work / "cache"),
                TORCH_COMPILE_DISABLE="1",
                PYTHONIOENCODING="utf-8",
            )
            process = await asyncio.create_subprocess_exec(
                str(self.python),
                "-I",
                str(self.script.resolve()),
                cwd=work,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=sys.platform != "win32",
                limit=65536,
            )
            try:
                async with asyncio.timeout(self.deadline):
                    assert process.stdin and process.stdout
                    process.stdin.write(json.dumps(payload).encode())
                    await process.stdin.drain()
                    process.stdin.close()
                    result: dict[str, Any] | None = None
                    error = None
                    count, last_step = 0, 0
                    while line := await process.stdout.readline():
                        count += 1
                        if count > request.steps + 5 or len(line) > 65536:
                            raise ValueError("invalid_output")
                        value = json.loads(line)
                        if not isinstance(value, dict) or result is not None:
                            raise ValueError("invalid_output")
                        if value.get("event") == "progress":
                            step, loss = value.get("step"), value.get("loss")
                            if (
                                type(step) is not int
                                or not last_step < step <= request.steps
                                or not isinstance(loss, (float, int))
                                or isinstance(loss, bool)
                                or not math.isfinite(float(loss))
                            ):
                                raise ValueError("invalid_output")
                            last_step = step
                            await on_progress(step)
                        elif value.get("event") == "stage":
                            if value.get("stage") not in {"encoding", "caching", "training"}:
                                raise ValueError("invalid_output")
                        elif value.get("event") == "result":
                            result = value
                        elif value.get("event") == "error":
                            code = value.get("code")
                            error = (
                                code
                                if code
                                in {
                                    "gpu_busy",
                                    "host_memory_busy",
                                    "out_of_memory",
                                    "caption_too_long",
                                }
                                else "training_failed"
                            )
                        else:
                            raise ValueError("invalid_output")
                    await process.wait()
                    if error:
                        raise ValueError(error)
                    if process.returncode != 0 or result is None:
                        raise ValueError("training_failed")
                    if set(result) != {"event", "sha256", "losses", "runtime"}:
                        raise ValueError("invalid_output")
                    losses, runtime = result["losses"], result["runtime"]
                    if (
                        not isinstance(losses, list)
                        or len(losses) != request.steps
                        or any(type(n) not in (float, int) or not math.isfinite(n) for n in losses)
                        or not isinstance(runtime, dict)
                        or len(runtime) > 32
                        or any(
                            not isinstance(k, str)
                            or len(k) > 80
                            or not isinstance(v, str)
                            or len(v) > 512
                            for k, v in runtime.items()
                        )
                    ):
                        raise ValueError("invalid_output")
                    if request.reference_index is not None and (
                        runtime.get("conditioning") != "approved_look_image"
                        or runtime.get("loss_tokens") != "target_only"
                        or runtime.get("reference_sha256")
                        != hashlib.sha256(request.images[request.reference_index][0]).hexdigest()
                        or runtime.get("conditioning_sha256")
                        != hashlib.sha256(
                            self.script.with_name("conditioning.py").read_bytes()
                        ).hexdigest()
                    ):
                        raise ValueError("invalid_output")
                    output = work / "out" / "adapter.safetensors"
                    if (
                        output.parent.is_symlink()
                        or output.is_symlink()
                        or not output.is_file()
                        or output.stat().st_size > MAX_ADAPTER_BYTES
                    ):
                        raise ValueError("invalid_output")
                    weights = output.read_bytes()
                    if hashlib.sha256(weights).hexdigest() != result["sha256"]:
                        raise ValueError("invalid_output")
                    validate_adapter(
                        weights,
                        base_hash=self.model_hash,
                        dataset_hash=request.dataset_hash,
                        recipe_hash=request.recipe_hash,
                    )
                    return StyleTrainingResult(weights, losses, runtime)
            finally:
                if process.returncode is None:
                    await stop_child(process)
