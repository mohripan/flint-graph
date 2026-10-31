"""Trusted parent for the isolated local Kokoro child (ADR 0043).

The child runs from its own locked CPU environment with ``python -I``, a minimal
environment without credentials and a watchdog. Nothing it returns is trusted:
output lines are bounded, events must follow the protocol in order, the output
directory must hold exactly one WAV per text, and every clip must be canonical
24 kHz mono 16-bit PCM of the announced length before its bytes leave this module.
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

from flint_graph.infrastructure.narrative_imagegen import (
    ModelIdentity,
    _verify_manifest,
)
from flint_graph.narrative.values import PackageError
from flint_graph.narrative.voices import MAX_ITEMS, SPEEDS, VOICE_ID, clean_voice_text
from flint_graph.narrative.wav import AUDIO_LIMIT, validate_wav

PROTOCOL = 1
SAMPLE_RATE = 24000
LINE_LIMIT = 16 * 1024
CHILD_CODES = {"bad_request", "model_invalid", "empty_speech", "too_long"}
RUNTIME_KEYS = {"torch", "kokoro", "misaki", "device"}
# What the interpreter needs; nothing that carries secrets.
_PASSTHROUGH = ("SYSTEMROOT", "WINDIR", "PATH", "USERNAME", "USER", "LOGNAME")


class VoiceGenerationError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class VoiceItem:
    text: str
    mode: str  # "full" or "vocalization"


@dataclass(frozen=True)
class VoiceRequest:
    voice: str
    speed: float
    seed: int
    items: tuple[VoiceItem, ...]


@dataclass(frozen=True)
class GeneratedClip:
    index: int
    data: bytes
    sha256: str
    frames: int

    @property
    def duration_ms(self) -> int:
        return round(self.frames * 1000 / SAMPLE_RATE)


@dataclass(frozen=True)
class VoiceResult:
    clips: tuple[GeneratedClip, ...]
    runtime: dict[str, str]


Progress = Callable[[int], Awaitable[None]]


class VoiceGenerator(Protocol):
    model: ModelIdentity

    async def generate(self, request: VoiceRequest, *, on_progress: Progress) -> VoiceResult: ...


def verify_voice_model(
    model_dir: Path, manifest_sha256: str
) -> tuple[ModelIdentity, tuple[str, ...]]:
    """The Kokoro directory under its pinned manifest, and the voice packs it holds."""
    identity, _, files = _verify_manifest(model_dir, manifest_sha256)
    if "config.json" not in files or "kokoro-v1_0.pth" not in files:
        raise ValueError("The voice manifest lacks the Kokoro weights")
    voices = tuple(
        sorted(
            name.removeprefix("voices/").removesuffix(".pt")
            for name in files
            if name.startswith("voices/") and name.endswith(".pt")
        )
    )
    return identity, voices


def _checked(request: VoiceRequest) -> None:
    try:
        if (
            not VOICE_ID.fullmatch(request.voice)
            or type(request.speed) not in (int, float)
            or not SPEEDS[0] <= request.speed <= SPEEDS[1]
            or type(request.seed) is not int
            or not 0 <= request.seed < 2**32
            or not 1 <= len(request.items) <= MAX_ITEMS
        ):
            raise ValueError
        for item in request.items:
            if clean_voice_text(item.text, item.mode) != item.text:
                raise ValueError
    except ValueError:
        raise VoiceGenerationError("bad_request") from None


class LocalVoiceGenerator:
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

    async def generate(self, request: VoiceRequest, *, on_progress: Progress) -> VoiceResult:
        _checked(request)
        with tempfile.TemporaryDirectory(prefix="flint-voicegen-") as directory:
            work = Path(directory)
            output = work / "out"
            output.mkdir()
            body = json.dumps(
                {
                    "protocol": PROTOCOL,
                    "model_dir": str(self.model_dir),
                    "output_dir": str(output),
                    "voice": request.voice,
                    "speed": request.speed,
                    "seed": request.seed,
                    "items": [{"text": item.text, "mode": item.mode} for item in request.items],
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
                loaded, samples = await asyncio.wait_for(
                    self._converse(process, body, request, on_progress), self.deadline
                )
            except TimeoutError:
                raise VoiceGenerationError("generation_timeout") from None
            finally:
                if process.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        process.kill()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(process.communicate(), 30)
            return self._collect(output, loaded, samples)

    async def _converse(
        self,
        process: asyncio.subprocess.Process,
        body: bytes,
        request: VoiceRequest,
        on_progress: Progress,
    ) -> tuple[dict[str, Any], list[int]]:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(body)
        with contextlib.suppress(ConnectionError):
            await process.stdin.drain()
        process.stdin.close()
        loaded: dict[str, Any] | None = None
        samples: list[int] = []
        done = False
        for _ in range(len(request.items) + 3):
            try:
                raw = await process.stdout.readline()
            except (ValueError, asyncio.LimitOverrunError):
                raise VoiceGenerationError("invalid_output") from None
            if not raw:
                break
            try:
                event = json.loads(raw)
            except ValueError:
                raise VoiceGenerationError("invalid_output") from None
            if not isinstance(event, dict) or event.get("protocol") != PROTOCOL or done:
                raise VoiceGenerationError("invalid_output")
            kind = event.get("event")
            if kind == "error":
                code = event.get("code")
                raise VoiceGenerationError(code if code in CHILD_CODES else "generation_failed")
            if kind == "loaded" and loaded is None:
                loaded = event
            elif kind == "clip" and loaded is not None and len(samples) < len(request.items):
                index, count = event.get("index"), event.get("samples")
                if (
                    index != len(samples)
                    or event.get("file") != f"{index}.wav"
                    or type(count) is not int
                    or not 0 < count <= SAMPLE_RATE * 60
                ):
                    raise VoiceGenerationError("invalid_output")
                samples.append(count)
                await on_progress(len(samples))
            elif kind == "done" and len(samples) == len(request.items):
                done = True
            else:
                raise VoiceGenerationError("invalid_output")
        else:
            raise VoiceGenerationError("invalid_output")
        code = await process.wait()
        if not done or code != 0 or loaded is None:
            raise VoiceGenerationError("generation_failed")
        return loaded, samples

    def _collect(self, output: Path, loaded: dict[str, Any], samples: list[int]) -> VoiceResult:
        if {path.name for path in output.iterdir()} != {f"{i}.wav" for i in range(len(samples))}:
            raise VoiceGenerationError("invalid_output")
        clips = []
        for index, frames in enumerate(samples):
            path = output / f"{index}.wav"
            if path.is_symlink() or not path.is_file() or path.stat().st_size > AUDIO_LIMIT:
                raise VoiceGenerationError("invalid_output")
            data = path.read_bytes()
            try:
                info = validate_wav(data, path.name)
            except PackageError:
                raise VoiceGenerationError("invalid_output") from None
            if (info.channels, info.sample_rate, info.frames) != (1, SAMPLE_RATE, frames):
                raise VoiceGenerationError("invalid_output")
            clips.append(
                GeneratedClip(
                    index=index, data=data, sha256=hashlib.sha256(data).hexdigest(), frames=frames
                )
            )
        runtime = loaded.get("runtime")
        if (
            not isinstance(runtime, dict)
            or set(runtime) != RUNTIME_KEYS
            or not all(isinstance(value, str) and len(value) <= 120 for value in runtime.values())
        ):
            raise VoiceGenerationError("invalid_output")
        return VoiceResult(clips=tuple(clips), runtime={k: str(v) for k, v in runtime.items()})


def voice_runtime_paths(runtime_dir: Path) -> tuple[Path, Path]:
    """The child's interpreter and script inside ``runtimes/voicegen``."""
    from flint_graph.infrastructure.narrative_imagegen import runtime_paths

    return runtime_paths(runtime_dir)
