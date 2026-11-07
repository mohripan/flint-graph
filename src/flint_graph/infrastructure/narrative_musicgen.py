"""The parent side of local music generation (ADR 0067): an isolated child and its result.

The child is ``runtimes/musicgen/generate.py``, started with ``python -I`` from its own locked
environment. Its output is never trusted: the file must be one bounded Ogg Vorbis stream of about
the length that was asked for.
"""

import asyncio
import contextlib
import hashlib
import json
import os
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from flint_graph.infrastructure.narrative_imagegen import ModelIdentity, _verify_manifest
from flint_graph.narrative.ogg import MUSIC_LIMIT, validate_ogg
from flint_graph.narrative.values import PackageError

PROTOCOL = 1
LINE_LIMIT = 64 * 1024
# Upstream's quality setting; 27 is its fast one and sounds rougher by its own account.
STEPS = 60
MIN_SECONDS, MAX_SECONDS = 15, 180
DESCRIPTION_LIMIT = 500
RUNTIME_KEYS = frozenset({"torch", "cuda", "device"})
CHILD_CODES = frozenset({"bad_request", "gpu_busy", "gpu_unavailable", "generation_failed"})
_PASSTHROUGH = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LD_LIBRARY_PATH")
Progress = Callable[[int], Awaitable[None]]
# The child trims the overlap it uses to join the end of a track to its start.
_LENGTH_SLACK_MS = 4000


class MusicGenerationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class MusicRequest:
    description: str
    seconds: int
    seed: int


@dataclass(frozen=True)
class GeneratedTrack:
    data: bytes
    sha256: str
    duration_ms: int
    channels: int
    rate: int


@dataclass(frozen=True)
class MusicResult:
    track: GeneratedTrack
    runtime: dict[str, str]


class MusicGenerator(Protocol):
    model: ModelIdentity

    async def generate(self, request: MusicRequest, *, on_progress: Progress) -> MusicResult: ...


def verify_music_model(model_dir: Path, manifest_sha256: str) -> ModelIdentity:
    """The ACE-Step directory under its pinned manifest, file by file."""
    identity, _, files = _verify_manifest(model_dir, manifest_sha256)
    needed = {
        "ace_step_transformer/config.json",
        "music_dcae_f8c8/config.json",
        "music_vocoder/config.json",
        "umt5-base/config.json",
    }
    if not needed <= set(files):
        raise ValueError("The music manifest lacks the ACE-Step parts")
    return identity


def checked_request(request: MusicRequest) -> None:
    if not 0 < len(request.description.strip()) <= DESCRIPTION_LIMIT:
        raise MusicGenerationError("bad_request")
    if not MIN_SECONDS <= request.seconds <= MAX_SECONDS or request.seed < 0:
        raise MusicGenerationError("bad_request")


class LocalMusicGenerator:
    def __init__(
        self,
        *,
        python: Path,
        script: Path,
        model_dir: Path,
        model: ModelIdentity,
        deadline_seconds: int,
        cuda_cache: Path | None = None,
    ) -> None:
        self.python, self.script, self.model_dir = python, script, model_dir
        self.model, self.deadline, self.cuda_cache = model, deadline_seconds, cuda_cache

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
                # Importing this torch asks who is running it, and fails without an answer.
                "USERNAME": "musicgen",
                "HF_HOME": str(work / "hf"),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_TELEMETRY": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONIOENCODING": "utf-8",
            }
        )
        if self.cuda_cache is not None:
            environment["CUDA_CACHE_PATH"] = str(self.cuda_cache)
            environment["CUDA_CACHE_MAXSIZE"] = str(4 * 1024**3)
        return environment

    async def generate(self, request: MusicRequest, *, on_progress: Progress) -> MusicResult:
        checked_request(request)
        with tempfile.TemporaryDirectory(prefix="flint-musicgen-", ignore_cleanup_errors=True) as d:
            work = Path(d)
            output = work / "out"
            output.mkdir()
            body = json.dumps(
                {
                    "protocol": PROTOCOL,
                    "model_dir": str(self.model_dir),
                    "output_dir": str(output),
                    "description": request.description,
                    "seconds": request.seconds,
                    "seed": request.seed,
                    "steps": STEPS,
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
                loaded = await asyncio.wait_for(
                    self._converse(process, body, on_progress), self.deadline
                )
            except TimeoutError:
                raise MusicGenerationError("generation_timeout") from None
            finally:
                if process.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        process.kill()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(process.communicate(), 30)
            return collect(output, loaded, request)

    async def _converse(
        self, process: asyncio.subprocess.Process, body: bytes, on_progress: Progress
    ) -> dict[str, Any]:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(body)
        with contextlib.suppress(ConnectionError):
            await process.stdin.drain()
        process.stdin.close()
        loaded: dict[str, Any] | None = None
        made = done = False
        for _ in range(4):
            try:
                raw = await process.stdout.readline()
            except (ValueError, asyncio.LimitOverrunError):
                raise MusicGenerationError("invalid_output") from None
            if not raw:
                break
            try:
                event = json.loads(raw)
            except ValueError:
                raise MusicGenerationError("invalid_output") from None
            if not isinstance(event, dict) or event.get("protocol") != PROTOCOL or done:
                raise MusicGenerationError("invalid_output")
            kind = event.get("event")
            if kind == "error":
                code = event.get("code")
                raise MusicGenerationError(code if code in CHILD_CODES else "generation_failed")
            if kind == "loaded" and loaded is None:
                loaded = event
            elif kind == "track" and loaded is not None and not made:
                if event.get("file") != "0.ogg":
                    raise MusicGenerationError("invalid_output")
                made = True
                await on_progress(1)
            elif kind == "done" and made:
                done = True
            else:
                raise MusicGenerationError("invalid_output")
        code = await process.wait()
        if not done or code != 0 or loaded is None:
            raise MusicGenerationError("generation_failed")
        return loaded


def collect(output: Path, loaded: dict[str, Any], request: MusicRequest) -> MusicResult:
    """Accept exactly one bounded Vorbis file of about the requested length."""
    if {path.name for path in output.iterdir()} != {"0.ogg"}:
        raise MusicGenerationError("invalid_output")
    path = output / "0.ogg"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MUSIC_LIMIT:
        raise MusicGenerationError("invalid_output")
    data = path.read_bytes()
    try:
        info = validate_ogg(data, path.name)
    except PackageError:
        raise MusicGenerationError("invalid_output") from None
    if abs(info.duration_ms - request.seconds * 1000) > _LENGTH_SLACK_MS:
        raise MusicGenerationError("invalid_output")
    runtime = loaded.get("runtime")
    if (
        not isinstance(runtime, dict)
        or set(runtime) != RUNTIME_KEYS
        or not all(isinstance(value, str) and len(value) <= 120 for value in runtime.values())
    ):
        raise MusicGenerationError("invalid_output")
    track = GeneratedTrack(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        duration_ms=info.duration_ms,
        channels=info.channels,
        rate=info.rate,
    )
    return MusicResult(track=track, runtime={key: str(value) for key, value in runtime.items()})
