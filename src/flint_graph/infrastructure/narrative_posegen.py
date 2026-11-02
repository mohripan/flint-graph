"""The isolated pose model's adapter and explicit reference-image request."""

import asyncio
import hashlib
import importlib.util
import json
import os
import signal
import struct
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flint_graph.infrastructure.narrative_imagegen import (
    IMAGE_LIMIT,
    THUMBNAIL_LIMIT,
    CutoutModel,
    GeneratedImage,
    GenerationRequest,
    GenerationResult,
    ImageGenerationError,
    ModelIdentity,
    Progress,
)
from flint_graph.narrative.png import normalize_png, validate_png
from flint_graph.narrative.pose_repairs import validate_region, verify_preservation
from flint_graph.narrative.poses import MODEL_REPO, MODEL_REVISION, POSE_HEIGHT, POSE_WIDTH


@dataclass(frozen=True)
class PoseStyleAdapter:
    weights: bytes
    dataset_hash: str
    recipe_hash: str
    strength: float


@dataclass(frozen=True, kw_only=True)
class PoseGenerationRequest(GenerationRequest):
    reference: bytes
    additional_references: tuple[bytes, ...] = ()
    style_adapter: PoseStyleAdapter | None = None
    character_adapter: PoseStyleAdapter | None = None
    repair: "PoseRepairRegion | None" = None


@dataclass(frozen=True)
class PoseRepairRegion:
    box: tuple[int, ...]
    source_box: tuple[int, ...] | None
    width: int
    height: int


def verify_pose_model(root: Path, manifest: str, runtime: Path) -> ModelIdentity:
    """Verify with the installed trusted protocol module, without loading ML libraries."""
    spec = importlib.util.spec_from_file_location("flint_pose_contract", runtime / "contract.py")
    if spec is None or spec.loader is None:
        raise ValueError("model_invalid")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.MODEL_REPO != MODEL_REPO or module.MODEL_REVISION != MODEL_REVISION:
        raise ValueError("model_invalid")
    module.verify_model(root.resolve(), manifest)
    return ModelIdentity(MODEL_REPO, MODEL_REVISION, "apache-2.0")


async def stop_child(process: asyncio.subprocess.Process) -> None:
    """Stop only this model process and its descendants, including Windows venv shims."""
    if sys.platform == "win32" and process.returncode is None:
        taskkill = Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "System32/taskkill.exe"
        killer = await asyncio.create_subprocess_exec(
            str(taskkill),
            "/PID",
            str(process.pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(killer.wait(), timeout=15)
    elif sys.platform != "win32":
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    if process.returncode is None:
        with suppress(ProcessLookupError):
            process.kill()
    await process.wait()


class LocalPoseGenerator:
    def __init__(
        self,
        *,
        python: Path,
        script: Path,
        model_dir: Path,
        model: ModelIdentity,
        model_manifest_sha256: str,
        cutout_manifest_sha256: str | None,
        deadline_seconds: float,
        cutout: CutoutModel | None = None,
    ) -> None:
        self.python, self.script, self.model_dir = python, script, model_dir
        self.model, self.model_manifest_sha256 = model, model_manifest_sha256
        self.cutout, self.cutout_manifest_sha256 = cutout, cutout_manifest_sha256
        self.deadline = deadline_seconds

    @staticmethod
    def _png(path: Path, limit: int) -> tuple[bytes, int, int]:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
            raise ValueError("invalid_output")
        data = normalize_png(path.read_bytes(), "pose")
        validate_png(data, "pose")
        width, height = struct.unpack_from(">II", data, 16)
        return data, width, height

    def _result(
        self, value: dict[str, Any], work: Path, request: PoseGenerationRequest
    ) -> GenerationResult:
        if set(value) != {"event", "images", "prompt_tokens", "runtime"}:
            raise ValueError("invalid_output")
        tokens, runtime = value["prompt_tokens"], value["runtime"]
        if type(tokens) is not int or not 1 <= tokens <= 512 or not isinstance(runtime, dict):
            raise ValueError("invalid_output")
        if len(runtime) > 64 or any(
            not isinstance(key, str)
            or not isinstance(item, str)
            or len(key) > 80
            or len(item) > 512
            for key, item in runtime.items()
        ):
            raise ValueError("invalid_output")
        outputs = value["images"]
        if not isinstance(outputs, list) or not 1 <= len(outputs) <= len(request.seeds):
            raise ValueError("invalid_output")
        if (work / "out").is_symlink():
            raise ValueError("invalid_output")
        images, seen = [], set()
        for output in outputs:
            if not isinstance(output, dict) or set(output) != {"index", "seed", "box"}:
                raise ValueError("invalid_output")
            index, seed, box = output["index"], output["seed"], output["box"]
            if type(index) is not int or not 0 <= index < len(request.seeds) or index in seen:
                raise ValueError("invalid_output")
            seen.add(index)
            if type(seed) is not int or seed != request.seeds[index]:
                raise ValueError("invalid_output")
            data, width, height = self._png(work / "out" / f"{index}.png", IMAGE_LIMIT)
            thumb, tw, th = self._png(work / "out" / f"thumb-{index}.png", THUMBNAIL_LIMIT)
            if not 1 <= min(tw, th) or max(tw, th) > 256 or tw > width or th > height:
                raise ValueError("invalid_output")
            if request.cutout:
                if (
                    not isinstance(box, list)
                    or len(box) != 4
                    or any(type(n) is not int for n in box)
                ):
                    raise ValueError("invalid_output")
                left, top, right, bottom = box
                if not (
                    0 <= left < right <= POSE_WIDTH
                    and 0 <= top < bottom <= POSE_HEIGHT
                    and (width, height) == (right - left, bottom - top)
                    and data[25] == 6
                ):
                    raise ValueError("invalid_output")
            elif box is not None or (width, height) != (POSE_WIDTH, POSE_HEIGHT):
                raise ValueError("invalid_output")
            if request.repair:
                expected_box = (
                    list(request.repair.source_box) if request.repair.source_box else None
                )
                if box != expected_box:
                    raise ImageGenerationError("repair_preservation_failed")
                try:
                    preserved = verify_preservation(request.reference, data, request.repair.box)
                except ValueError:
                    raise ImageGenerationError("repair_preservation_failed") from None
                runtime = {
                    **runtime,
                    "repair_preserved_sha256": preserved,
                    "repair_preservation": "decoded-pixels-v1",
                }
            images.append(
                GeneratedImage(
                    index=index,
                    seed=seed,
                    data=data,
                    sha256=hashlib.sha256(data).hexdigest(),
                    width=width,
                    height=height,
                    thumbnail=thumb,
                    thumbnail_sha256=hashlib.sha256(thumb).hexdigest(),
                    thumbnail_width=tw,
                    thumbnail_height=th,
                    box=tuple(box) if box else None,
                )
            )
        return GenerationResult(
            images=tuple(images),
            runtime=runtime,
            prompt_tokens=tokens,
            truncated=False,
            cutout=self.cutout if request.cutout else None,
        )

    async def generate(
        self, request: GenerationRequest, *, on_progress: Progress
    ) -> GenerationResult:
        if not isinstance(request, PoseGenerationRequest) or (
            not 1 <= len(request.seeds) <= 4
            or (request.width, request.height) != (POSE_WIDTH, POSE_HEIGHT)
            or request.steps != 4
            or request.guidance != 1
            or request.negative_prompt
            or request.inpaint is not None
            or request.scene is not None
            or request.hires is not None
        ):
            raise ImageGenerationError("bad_request")
        if request.cutout and self.cutout is None:
            raise ImageGenerationError("cutout_unavailable")
        if len(request.additional_references) > 1:
            raise ImageGenerationError("bad_request")
        references = (request.reference, *request.additional_references)
        if any(len(item) > IMAGE_LIMIT for item in references):
            raise ImageGenerationError("reference_unavailable")
        try:
            for item in references:
                validate_png(item, "reference")
        except ValueError:
            raise ImageGenerationError("reference_unavailable") from None
        if request.repair:
            repair = request.repair
            try:
                validate_region(repair.box, repair.width, repair.height)
                if len(references) != 2 or struct.unpack_from(">II", request.reference, 16) != (
                    repair.width,
                    repair.height,
                ):
                    raise ValueError
                if repair.source_box:
                    left, top, right, bottom = repair.source_box
                    if not request.cutout or not (
                        0 <= left < right <= 768
                        and 0 <= top < bottom <= 1152
                        and (right - left, bottom - top) == (repair.width, repair.height)
                    ):
                        raise ValueError
                elif request.cutout or (repair.width, repair.height) != (768, 1152):
                    raise ValueError
            except (ValueError, struct.error):
                raise ImageGenerationError("bad_request") from None
        with tempfile.TemporaryDirectory(prefix="flint-pose-") as directory:
            work = Path(directory)
            for index, data in enumerate(references):
                name = "reference.png" if len(references) == 1 else f"reference-{index}.png"
                (work / name).write_bytes(data)
            payload: dict[str, Any] = {
                "schema_version": 1,
                "model_dir": str(self.model_dir.resolve()),
                "model_manifest_sha256": self.model_manifest_sha256,
                "reference_sha256": hashlib.sha256(request.reference).hexdigest(),
                "prompt": request.prompt,
                "seeds": list(request.seeds),
                "cutout": {"model": str(self.cutout.path.resolve()), "sha256": self.cutout.sha256}
                if request.cutout and self.cutout
                else None,
            }
            if len(references) == 2:
                payload["schema_version"] = 2
                payload.pop("reference_sha256")
                payload["reference_sha256s"] = [
                    hashlib.sha256(item).hexdigest() for item in references
                ]
            selected = [
                (role, item)
                for role, item in (
                    ("character", request.character_adapter),
                    ("style", request.style_adapter),
                )
                if item is not None
            ]
            adapters: list[dict[str, Any]] = []
            if selected:
                from flint_graph.narrative.style_weights import validate_adapter

                if sum(item.strength for _, item in selected) > 1 + 1e-9:
                    raise ImageGenerationError("bad_request")
                for role, adapter in selected:
                    validate_adapter(
                        adapter.weights,
                        base_hash=self.model_manifest_sha256,
                        dataset_hash=adapter.dataset_hash,
                        recipe_hash=adapter.recipe_hash,
                    )
                    if (
                        type(adapter.strength) not in (float, int)
                        or not 0.1 <= adapter.strength <= 1
                    ):
                        raise ImageGenerationError("bad_request")
                    (work / (role + ".safetensors")).write_bytes(adapter.weights)
                    adapters.append(
                        {
                            "role": role,
                            "sha256": hashlib.sha256(adapter.weights).hexdigest(),
                            "dataset_sha256": adapter.dataset_hash,
                            "recipe_sha256": adapter.recipe_hash,
                            "strength": adapter.strength,
                        }
                    )
                if len({item["sha256"] for item in adapters}) != len(adapters):
                    raise ImageGenerationError("bad_request")
                payload["schema_version"] = 4 if request.character_adapter else 3
                payload.pop("reference_sha256", None)
                payload["reference_sha256s"] = [
                    hashlib.sha256(item).hexdigest() for item in references
                ]
                if request.character_adapter:
                    payload["adapters"] = adapters
                else:
                    payload["style"] = {
                        key: value for key, value in adapters[0].items() if key != "role"
                    }
            if request.repair:
                repair = request.repair
                payload["schema_version"] = 5
                payload.pop("reference_sha256", None)
                payload.pop("style", None)
                payload["reference_sha256s"] = [
                    hashlib.sha256(item).hexdigest() for item in references
                ]
                payload["adapters"] = adapters
                payload["repair"] = {
                    "box": list(repair.box),
                    "width": repair.width,
                    "height": repair.height,
                    "source_box": list(repair.source_box) if repair.source_box else None,
                    "feather": 8,
                }
            env = {
                key: value
                for key, value in os.environ.items()
                if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "PATHEXT", "CUDA_PATH"}
            }
            env.update(
                TEMP=directory,
                TMP=directory,
                TMPDIR=directory,
                HOME=directory,
                USERPROFILE=directory,
                HF_HOME=str(work / "hf"),
                TORCHINDUCTOR_CACHE_DIR=str(work / "torch-cache"),
                HF_HUB_OFFLINE="1",
                TRANSFORMERS_OFFLINE="1",
                PYTHONDONTWRITEBYTECODE="1",
            )
            try:
                with (work / "error.txt").open("wb") as errors:
                    process = await asyncio.create_subprocess_exec(
                        str(self.python),
                        "-I",
                        str(self.script.resolve()),
                        start_new_session=sys.platform != "win32",
                        cwd=work,
                        env=env,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=errors,
                        limit=32768,
                    )
                    try:
                        async with asyncio.timeout(self.deadline):
                            assert process.stdin and process.stdout
                            process.stdin.write(json.dumps(payload).encode())
                            await process.stdin.drain()
                            process.stdin.close()
                            result, done = None, 0
                            while True:
                                try:
                                    line = await asyncio.wait_for(
                                        process.stdout.readline(), timeout=2
                                    )
                                except TimeoutError:
                                    await on_progress(done)
                                    continue
                                if not line:
                                    break
                                value = json.loads(line)
                                if not isinstance(value, dict):
                                    raise ValueError("invalid_output")
                                event = value.get("event")
                                if event == "error":
                                    code = value.get("code")
                                    known = {
                                        "gpu_busy",
                                        "host_memory_busy",
                                        "out_of_memory",
                                        "model_invalid",
                                        "reference_unavailable",
                                        "unsupported_device",
                                        "prompt_too_long",
                                        "cutout_failed",
                                    }
                                    raise ImageGenerationError(
                                        code if code in known else "generation_failed"
                                    )
                                if result is not None:
                                    raise ValueError("invalid_output")
                                if event == "result":
                                    result = value
                                elif event == "progress":
                                    next_done = value.get("done")
                                    if type(next_done) is not int or not done <= next_done <= len(
                                        request.seeds
                                    ):
                                        raise ValueError("invalid_output")
                                    done = next_done
                                    await on_progress(done)
                                elif event != "stage" or value.get("stage") not in {
                                    "encoding",
                                    "rendering",
                                }:
                                    raise ValueError("invalid_output")
                            if await process.wait() or result is None:
                                raise ValueError("invalid_output")
                            return self._result(result, work, request)
                    finally:
                        if process.returncode is None:
                            await stop_child(process)
                        else:
                            await process.wait()
            except TimeoutError:
                raise ImageGenerationError("generation_timeout") from None
            except (OSError, ValueError, KeyError, TypeError):
                raise ImageGenerationError("invalid_output") from None
