"""Trusted parent for the isolated local image child (ADR 0039).

The child runs from its own locked environment with ``python -I``, a minimal
environment and no credentials. Nothing it returns is trusted: output lines are
bounded, events must follow the protocol exactly, the output directory must hold
exactly the expected files, and every PNG is normalized and passes the strict
validator with exact dimensions before the bytes leave this module. Cutout sprites
must be 8-bit RGBA crops that match the box the child reports.
"""

import asyncio
import contextlib
import hashlib
import json
import os
import struct
import sys
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from flint_graph.narrative.png import normalize_png, validate_png
from flint_graph.narrative.values import PackageError

PROTOCOL = 1
MANIFEST = "flintgraph-download.json"
IMAGE_LIMIT = 10 * 1024 * 1024
THUMBNAIL_LIMIT = 1024 * 1024
THUMBNAIL_WIDTH = 256
LINE_LIMIT = 16 * 1024
MAX_LINES = 32
MAX_IMAGES = 4
CHILD_CODES = {
    "bad_request",
    "model_invalid",
    "gpu_unavailable",
    "gpu_busy",
    "out_of_memory",
    "cutout_failed",
}
RUNTIME_KEYS = {"torch", "diffusers", "cuda", "device"}
# Variables the interpreter and the CUDA runtime need; nothing that carries secrets.
# PyTorch names its caches with getpass.getuser(), which on Windows reads USERNAME
# and otherwise fails importing diffusers with an unrelated-looking error.
_PASSTHROUGH = (
    "SYSTEMROOT",
    "WINDIR",
    "PATH",
    "CUDA_VISIBLE_DEVICES",
    "LD_LIBRARY_PATH",
    "USERNAME",
    "USER",
    "LOGNAME",
)


class ImageGenerationError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ModelIdentity:
    repo: str
    revision: str
    license: str


@dataclass(frozen=True)
class CutoutModel:
    """The verified segmenter: one ONNX file listed in its pinned manifest."""

    path: Path
    sha256: str
    identity: ModelIdentity


@dataclass(frozen=True)
class InpaintRequest:
    """Repaint the face of a base image (ADR 0041); bytes already hash-verified."""

    image: bytes
    box: tuple[int, int, int, int]
    strength: float
    prompts: tuple[str, ...]


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    negative_prompt: str
    width: int
    height: int
    steps: int
    guidance: float
    seeds: tuple[int, ...]
    # Cut the figure out of its background into a cropped RGBA sprite.
    cutout: bool = False
    # Repaint only the face of a base image, one prompt per seed; the size is the base's.
    inpaint: InpaintRequest | None = None


@dataclass(frozen=True)
class GeneratedImage:
    index: int
    seed: int
    data: bytes
    sha256: str
    width: int
    height: int
    thumbnail: bytes
    thumbnail_sha256: str
    thumbnail_width: int
    thumbnail_height: int
    # Where a cutout sprite was cropped from the full render: left, top, right, bottom.
    box: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class GenerationResult:
    images: tuple[GeneratedImage, ...]
    runtime: dict[str, str]
    prompt_tokens: int
    truncated: bool
    # The segmenter that cut these images out, when the request asked for it.
    cutout: CutoutModel | None = None


Progress = Callable[[int], Awaitable[None]]


class ImageGenerator(Protocol):
    model: ModelIdentity

    async def generate(
        self, request: GenerationRequest, *, on_progress: Progress
    ) -> GenerationResult: ...


class GpuReleaser(Protocol):
    async def release(self) -> None: ...


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model(model_dir: Path, manifest_sha256: str) -> ModelIdentity:
    """Check the model directory against its pinned download manifest.

    The manifest's own SHA-256 is the operator pin; every listed file must match
    size and hash and nothing else may be present (no extra weights or code).
    """
    return _verify_manifest(model_dir, manifest_sha256)[0]


def verify_cutout_model(model_dir: Path, manifest_sha256: str) -> CutoutModel:
    """The segmenter directory under the same pin, holding exactly one ONNX model."""
    identity, root, files = _verify_manifest(model_dir, manifest_sha256)
    models = [name for name in files if name.endswith(".onnx")]
    if len(models) != 1:
        raise ValueError("The cutout manifest must list exactly one ONNX model")
    return CutoutModel(
        path=root / models[0], sha256=str(files[models[0]]["sha256"]), identity=identity
    )


def _verify_manifest(
    model_dir: Path, manifest_sha256: str
) -> tuple[ModelIdentity, Path, dict[str, Any]]:
    root = model_dir.resolve(strict=True)
    manifest_path = root / MANIFEST
    data = manifest_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest_sha256:
        raise ValueError("Model manifest does not match the pinned hash")
    manifest = json.loads(data)
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Model manifest lists no files")
    present = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if present != set(files) | {MANIFEST}:
        raise ValueError("Model directory does not match its manifest")
    for name, expected in files.items():
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Model files must be regular files")
        if path.stat().st_size != expected["size"] or _sha256_file(path) != expected["sha256"]:
            raise ValueError("Model file does not match its manifest")
    identity = ModelIdentity(
        repo=str(manifest["repo"]),
        revision=str(manifest["revision"]),
        license=str(manifest["license"]),
    )
    if not identity.repo or len(identity.revision) != 40:
        raise ValueError("Model manifest identity is incomplete")
    return identity, root, files


def _dimensions(data: bytes) -> tuple[int, int]:
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def _read_png(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ImageGenerationError("invalid_output")
    data = path.read_bytes()
    if len(data) > limit:
        raise ImageGenerationError("invalid_output")
    try:
        # The same lossless path as uploads: metadata chunks go, pixels and alpha stay.
        data = normalize_png(data, path.name)
        validate_png(data, path.name)
    except PackageError:
        raise ImageGenerationError("invalid_output") from None
    return data


def _rgba(data: bytes) -> bool:
    # IHDR bit depth and colour type: 8-bit truecolour with alpha.
    return data[24:26] == bytes([8, 6])


def _box(value: object, request: GenerationRequest) -> tuple[int, int, int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(type(item) is not int for item in value)
    ):
        raise ImageGenerationError("invalid_output")
    left, top, right, bottom = value
    if not (0 <= left < right <= request.width and 0 <= top < bottom <= request.height):
        raise ImageGenerationError("invalid_output")
    return left, top, right, bottom


class LocalImageGenerator:
    def __init__(
        self,
        *,
        python: Path,
        script: Path,
        model_dir: Path,
        model: ModelIdentity,
        deadline_seconds: int,
        cutout: CutoutModel | None = None,
    ) -> None:
        self.python, self.script, self.model_dir = python, script, model_dir
        self.model, self.deadline, self.cutout = model, deadline_seconds, cutout

    def _environment(self, work: Path) -> dict[str, str]:
        environment = {key: os.environ[key] for key in _PASSTHROUGH if key in os.environ}
        private = str(work)
        environment.update(
            {
                "TEMP": private,
                "TMP": private,
                "TMPDIR": private,
                "HOME": private,
                "USERPROFILE": private,
                "HF_HOME": str(work / "hf"),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_TELEMETRY": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        return environment

    async def generate(
        self, request: GenerationRequest, *, on_progress: Progress
    ) -> GenerationResult:
        if not 1 <= len(request.seeds) <= MAX_IMAGES:
            raise ImageGenerationError("bad_request")
        inpaint = request.inpaint
        if inpaint is not None and (
            request.cutout or len(inpaint.prompts) != len(request.seeds)
        ):
            raise ImageGenerationError("bad_request")
        if request.cutout and self.cutout is None:
            raise ImageGenerationError("cutout_unavailable")
        cutout = (
            {"model": str(self.cutout.path), "sha256": self.cutout.sha256}
            if request.cutout and self.cutout is not None
            else None
        )
        with tempfile.TemporaryDirectory(prefix="flint-imagegen-") as directory:
            work = Path(directory)
            output = work / "out"
            output.mkdir()
            fields: dict[str, Any] = {
                "protocol": PROTOCOL,
                "model_dir": str(self.model_dir),
                "output_dir": str(output),
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt,
                "width": request.width,
                "height": request.height,
                "steps": request.steps,
                "guidance": request.guidance,
                "seeds": list(request.seeds),
                "cutout": cutout,
            }
            if inpaint is not None:
                # The child reads its own copy from the private work folder and hashes it.
                base = work / "base.png"
                base.write_bytes(inpaint.image)
                fields["inpaint"] = {
                    "image": str(base),
                    "sha256": hashlib.sha256(inpaint.image).hexdigest(),
                    "box": list(inpaint.box),
                    "strength": inpaint.strength,
                    "prompts": list(inpaint.prompts),
                }
            body = json.dumps(fields).encode()
            process = await asyncio.create_subprocess_exec(
                str(self.python),
                "-I",
                str(self.script),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(work),
                env=self._environment(work),
                limit=LINE_LIMIT,
            )
            try:
                loaded, boxes = await asyncio.wait_for(
                    self._converse(process, body, request, on_progress), self.deadline
                )
            except TimeoutError:
                raise ImageGenerationError("generation_timeout") from None
            finally:
                if process.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        process.kill()
                # wait() only returns once every pipe reaches EOF, and a paused
                # reader never does; drain what the killed child left in the pipe.
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(process.communicate(), 30)
            return self._collect(output, request, loaded, boxes)

    async def _converse(
        self,
        process: asyncio.subprocess.Process,
        body: bytes,
        request: GenerationRequest,
        on_progress: Progress,
    ) -> tuple[dict[str, Any], list[tuple[int, int, int, int] | None]]:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(body)
        with contextlib.suppress(ConnectionError):
            await process.stdin.drain()
        process.stdin.close()
        loaded: dict[str, Any] | None = None
        done = False
        images = 0
        boxes: list[tuple[int, int, int, int] | None] = []
        for _ in range(MAX_LINES):
            try:
                raw = await process.stdout.readline()
            except (ValueError, asyncio.LimitOverrunError):
                raise ImageGenerationError("invalid_output") from None
            if not raw:
                break
            try:
                event = json.loads(raw)
            except ValueError:
                raise ImageGenerationError("invalid_output") from None
            if not isinstance(event, dict) or event.get("protocol") != PROTOCOL or done:
                raise ImageGenerationError("invalid_output")
            kind = event.get("event")
            if kind == "error":
                code = event.get("code")
                raise ImageGenerationError(code if code in CHILD_CODES else "generation_failed")
            if kind == "busy":
                continue
            if kind == "loaded" and loaded is None:
                loaded = event
            elif kind == "image" and loaded is not None and images < len(request.seeds):
                if (
                    event.get("index") != images
                    or event.get("seed") != request.seeds[images]
                    or event.get("file") != f"{images}.png"
                    or event.get("thumbnail") != f"{images}.thumb.png"
                    or ("box" in event) != request.cutout
                ):
                    raise ImageGenerationError("invalid_output")
                boxes.append(_box(event["box"], request) if request.cutout else None)
                images += 1
                await on_progress(images)
            elif kind == "done" and images == len(request.seeds):
                done = True
            else:
                raise ImageGenerationError("invalid_output")
        else:
            raise ImageGenerationError("invalid_output")
        code = await process.wait()
        if not done or code != 0 or loaded is None:
            raise ImageGenerationError("generation_failed")
        return loaded, boxes

    def _collect(
        self,
        output: Path,
        request: GenerationRequest,
        loaded: dict[str, Any],
        boxes: list[tuple[int, int, int, int] | None],
    ) -> GenerationResult:
        count = len(request.seeds)
        expected = {f"{i}.png" for i in range(count)} | {f"{i}.thumb.png" for i in range(count)}
        if {path.name for path in output.iterdir()} != expected:
            raise ImageGenerationError("invalid_output")
        images = []
        # A repainted face keeps the base's transparency exactly: a sprite stays a sprite.
        base_alpha = request.inpaint is not None and _rgba(request.inpaint.image)
        for index, seed in enumerate(request.seeds):
            data = _read_png(output / f"{index}.png", IMAGE_LIMIT)
            thumbnail = _read_png(output / f"{index}.thumb.png", THUMBNAIL_LIMIT)
            width, height = _dimensions(data)
            thumb_width, thumb_height = _dimensions(thumbnail)
            box = boxes[index]
            expected_size = (
                (request.width, request.height)
                if box is None
                else (box[2] - box[0], box[3] - box[1])
            )
            if (
                (width, height) != expected_size
                or thumb_width != THUMBNAIL_WIDTH
                or thumb_height != round(height * THUMBNAIL_WIDTH / width)
                or (box is not None and not (_rgba(data) and _rgba(thumbnail)))
                or (
                    request.inpaint is not None
                    and not (_rgba(data) == _rgba(thumbnail) == base_alpha)
                )
            ):
                raise ImageGenerationError("invalid_output")
            images.append(
                GeneratedImage(
                    index=index,
                    seed=seed,
                    data=data,
                    sha256=hashlib.sha256(data).hexdigest(),
                    width=width,
                    height=height,
                    thumbnail=thumbnail,
                    thumbnail_sha256=hashlib.sha256(thumbnail).hexdigest(),
                    thumbnail_width=thumb_width,
                    thumbnail_height=thumb_height,
                    box=box,
                )
            )
        runtime = loaded.get("runtime")
        tokens = loaded.get("prompt_tokens")
        if (
            not isinstance(runtime, dict)
            or set(runtime) != RUNTIME_KEYS | ({"onnxruntime"} if request.cutout else set())
            or not all(isinstance(value, str) and len(value) <= 120 for value in runtime.values())
            or type(tokens) is not int
            or type(loaded.get("truncated")) is not bool
        ):
            raise ImageGenerationError("invalid_output")
        return GenerationResult(
            images=tuple(images),
            runtime={key: str(value) for key, value in runtime.items()},
            prompt_tokens=tokens,
            truncated=bool(loaded["truncated"]),
            cutout=self.cutout if request.cutout else None,
        )


class OllamaGpuReleaser:
    """Ask the local Ollama server to unload one configured model (operator opt-in)."""

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url, self.model = base_url.rstrip("/"), model

    async def release(self) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self.base_url + "/api/generate", json={"model": self.model, "keep_alive": 0}
            )
            response.raise_for_status()
        # Ollama reports the unload before the driver has reclaimed the memory.
        await asyncio.sleep(3)


def runtime_paths(runtime_dir: Path) -> tuple[Path, Path]:
    """The child's interpreter and script inside ``runtimes/imagegen``."""
    venv = runtime_dir / ".venv"
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    return python, runtime_dir / "generate.py"
