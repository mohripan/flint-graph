"""Trusted parent for the isolated local image child (ADR 0039).

The child runs from its own locked environment with ``python -I``, a minimal
environment and no credentials. Nothing it returns is trusted: output lines are
bounded, events must follow the protocol exactly, the output directory must hold
exactly the expected files, and every PNG passes the strict validator with exact
dimensions before the bytes leave this module.
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

from flint_graph.narrative.png import validate_png
from flint_graph.narrative.values import PackageError

PROTOCOL = 1
MANIFEST = "flintgraph-download.json"
IMAGE_LIMIT = 10 * 1024 * 1024
THUMBNAIL_LIMIT = 1024 * 1024
THUMBNAIL_WIDTH = 256
LINE_LIMIT = 16 * 1024
MAX_LINES = 32
MAX_IMAGES = 4
CHILD_CODES = {"bad_request", "model_invalid", "gpu_unavailable", "gpu_busy", "out_of_memory"}
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
class GenerationRequest:
    prompt: str
    negative_prompt: str
    width: int
    height: int
    steps: int
    guidance: float
    seeds: tuple[int, ...]


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


@dataclass(frozen=True)
class GenerationResult:
    images: tuple[GeneratedImage, ...]
    runtime: dict[str, str]
    prompt_tokens: int
    truncated: bool


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
    return identity


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
        validate_png(data, path.name)
    except PackageError:
        raise ImageGenerationError("invalid_output") from None
    return data


class LocalImageGenerator:
    def __init__(
        self,
        *,
        python: Path,
        script: Path,
        model_dir: Path,
        model: ModelIdentity,
        deadline_seconds: int,
    ) -> None:
        self.python, self.script, self.model_dir = python, script, model_dir
        self.model, self.deadline = model, deadline_seconds

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
        with tempfile.TemporaryDirectory(prefix="flint-imagegen-") as directory:
            work = Path(directory)
            output = work / "out"
            output.mkdir()
            body = json.dumps(
                {
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
                }
            ).encode()
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
                events = await asyncio.wait_for(
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
            return self._collect(output, request, events)

    async def _converse(
        self,
        process: asyncio.subprocess.Process,
        body: bytes,
        request: GenerationRequest,
        on_progress: Progress,
    ) -> dict[str, Any]:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(body)
        with contextlib.suppress(ConnectionError):
            await process.stdin.drain()
        process.stdin.close()
        loaded: dict[str, Any] | None = None
        done = False
        images = 0
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
                ):
                    raise ImageGenerationError("invalid_output")
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
        return loaded

    def _collect(
        self, output: Path, request: GenerationRequest, loaded: dict[str, Any]
    ) -> GenerationResult:
        count = len(request.seeds)
        expected = {f"{i}.png" for i in range(count)} | {f"{i}.thumb.png" for i in range(count)}
        if {path.name for path in output.iterdir()} != expected:
            raise ImageGenerationError("invalid_output")
        images = []
        for index, seed in enumerate(request.seeds):
            data = _read_png(output / f"{index}.png", IMAGE_LIMIT)
            thumbnail = _read_png(output / f"{index}.thumb.png", THUMBNAIL_LIMIT)
            width, height = _dimensions(data)
            thumb_width, thumb_height = _dimensions(thumbnail)
            if (
                (width, height) != (request.width, request.height)
                or thumb_width != THUMBNAIL_WIDTH
                or thumb_height != round(request.height * THUMBNAIL_WIDTH / request.width)
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
                )
            )
        runtime = loaded.get("runtime")
        tokens = loaded.get("prompt_tokens")
        if (
            not isinstance(runtime, dict)
            or set(runtime) != {"torch", "diffusers", "cuda", "device"}
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
