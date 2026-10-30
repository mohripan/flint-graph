"""Opt-in trusted Docker runner; no database, storage or provider credentials in child.

The activity supplies a fresh execution UUID and an async fence/cancellation check.
Artifacts stay private bytes: this adapter neither publishes nor completes jobs.
"""

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from flint_graph.narrative.build_child import WEB_FILES
from flint_graph.narrative.export import TEMPLATE_FILES, export_godot
from flint_graph.narrative.package import load_text_package
from flint_graph.narrative.release_artifacts import (
    ArtifactError,
    make_artifact_zip,
    read_child_files,
)
from flint_graph.narrative.values import PackageError, StoryPackage

Check = Callable[[], Awaitable[None]]
_SAFE_FAILURES = {
    "input_integrity",
    "engine_failed",
    "engine_timeout",
    "output_inventory",
    "output_size_limit",
    "build_io",
}


class BuildError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


async def _join_owned[T](task: asyncio.Task[T]) -> tuple[T, bool]:
    """Join owned resources despite repeated parent cancellation; caller re-raises."""
    interrupted = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            interrupted = True
    return task.result(), interrupted


def _stop(process: subprocess.Popen[bytes]) -> None:
    try:
        if sys.platform != "win32":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.poll() is None:
            process.kill()
        process.wait(timeout=5)
    finally:
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()


class _PipeReader:
    def __init__(self, fd: int, stop: threading.Event, deadline: float) -> None:
        self.fd, self.stop, self.deadline = fd, stop, deadline

    def read(self, size: int = -1, /) -> bytes:
        if not 0 <= size <= 65536:
            raise BuildError("build_io")
        while True:
            if self.stop.is_set():
                raise BuildError("build_io")
            if time.monotonic() >= self.deadline:
                raise BuildError("build_timeout")
            try:
                return os.read(self.fd, size)
            except BlockingIOError:
                time.sleep(0.005)


@dataclass(frozen=True)
class BuiltArtifacts:
    package_hash: str
    source_zip: bytes
    web_zip: bytes


class DockerNarrativeBuilder:
    def __init__(
        self,
        *,
        image: str,
        toolchain_sha256: str,
        work_root: Path,
        docker_command: tuple[str, ...] = ("docker",),
    ) -> None:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image) or not re.fullmatch(
            r"[0-9a-f]{64}", toolchain_sha256
        ):
            raise ValueError("Invalid narrative builder identity")
        root = work_root.absolute()
        if root.resolve(strict=True) != root or not root.is_dir():
            raise ValueError("Invalid narrative scratch root")
        self.image, self.toolchain, self.root, self.docker = (
            image,
            toolchain_sha256,
            root,
            docker_command,
        )

    def _blocking_command(
        self,
        args: tuple[str, ...],
        stop: threading.Event,
        seconds: float,
        cap: int,
    ) -> tuple[int, bytes]:
        try:
            process = subprocess.Popen(
                [*self.docker, *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                start_new_session=sys.platform != "win32",
            )
        except OSError:
            raise BuildError("build_io") from None
        assert process.stdout is not None and process.stderr is not None
        streams = [process.stdout, process.stderr]
        buffers, limits, ended = [bytearray(), bytearray()], [cap, 16384], [False, False]
        try:
            for stream in streams:
                os.set_blocking(stream.fileno(), False)
            deadline = time.monotonic() + seconds
            while True:
                if stop.is_set():
                    raise BuildError("build_io")
                if time.monotonic() >= deadline:
                    raise BuildError("build_timeout")
                received = False
                for i, stream in enumerate(streams):
                    if ended[i]:
                        continue
                    try:
                        chunk = os.read(stream.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        ended[i] = True
                    else:
                        received = True
                        if len(buffers[i]) + len(chunk) > limits[i]:
                            raise BuildError("build_io")
                        buffers[i].extend(chunk)
                status = process.poll()
                if status is not None and all(ended):
                    return status, bytes(buffers[0])
                if not received:
                    time.sleep(0.005)
        finally:
            _stop(process)

    async def _command(
        self, *args: str, deadline_seconds: float = 15, cap: int = 262144
    ) -> tuple[int, bytes]:
        stop = threading.Event()
        task = asyncio.create_task(
            asyncio.to_thread(
                self._blocking_command,
                args,
                stop,
                deadline_seconds,
                cap,
            )
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            stop.set()
            try:
                await _join_owned(task)
            except BuildError:
                pass
            raise

    async def _inspect(self, *args: str) -> dict[str, Any]:
        status, raw = await self._command(*args)
        if status:
            raise BuildError("runtime_unavailable")
        try:
            result = json.loads(raw)
            if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
                raise ValueError
            return result[0]
        except (ValueError, RecursionError):
            raise BuildError("build_io") from None

    async def _image(self) -> None:
        info = await self._inspect("image", "inspect", self.image)
        config = info.get("Config", {})
        allowed_env = {
            "PATH",
            "LANG",
            "GPG_KEY",
            "PYTHON_VERSION",
            "PYTHON_SHA256",
            "HOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_CACHE_HOME",
            "TMPDIR",
            "PYTHONDONTWRITEBYTECODE",
            "PYTHONUNBUFFERED",
        }
        if (
            info.get("Id") != self.image
            or info.get("Os") != "linux"
            or info.get("Architecture") != "amd64"
            or config.get("User") != "10001:10001"
            or config.get("Entrypoint") != ["python", "/opt/build_child.py"]
            or config.get("Cmd")
            or config.get("Volumes")
            or config.get("Labels", {}).get("io.flintgraph.narrative.toolchain.sha256")
            != self.toolchain
            or any(value.split("=", 1)[0] not in allowed_env for value in config.get("Env", []))
        ):
            raise BuildError("runtime_unavailable")

    async def _remove(self, name: str, execution: str) -> None:
        status, raw = await self._command(
            "container",
            "ls",
            "--all",
            "--no-trunc",
            "--filter",
            "name=^/" + name + "$",
            "--format",
            "{{.ID}}",
        )
        if status:
            raise BuildError("build_io")
        identity = raw.decode("ascii").strip()
        if not identity:
            return
        if not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise BuildError("build_io")
        info = await self._inspect("container", "inspect", identity)
        if (
            info.get("Id") != identity
            or info.get("Config", {}).get("Labels", {}).get("io.flintgraph.narrative.execution")
            != execution
        ):
            raise BuildError("build_io")
        status, _ = await self._command("rm", "--force", identity)
        if status:
            raise BuildError("build_io")

    async def _effective(self, name: str, execution: str) -> None:
        info = await self._inspect("container", "inspect", name)
        config, child = info.get("HostConfig", {}), info.get("Config", {})
        binds = [mount for mount in info.get("Mounts", []) if mount.get("Type") == "bind"]
        if (
            child.get("Labels", {}).get("io.flintgraph.narrative.execution") != execution
            or info.get("Image") != self.image
            or child.get("User") != "10001:10001"
            or config.get("NetworkMode") != "none"
            or not config.get("ReadonlyRootfs")
            or config.get("Memory") != 1073741824
            or config.get("MemorySwap") != 1073741824
            or config.get("NanoCpus") != 2000000000
            or config.get("PidsLimit") != 128
            or config.get("CapDrop") != ["ALL"]
            or config.get("Privileged")
            or config.get("Devices")
            or config.get("DeviceRequests")
            or config.get("SecurityOpt") != ["no-new-privileges"]
            or config.get("Tmpfs") != {"/scratch": "rw,size=268435456,mode=1777"}
            or len(binds) != 1
            or binds[0].get("Destination") != "/input"
            or binds[0].get("RW")
        ):
            raise BuildError("build_io")

    async def _ready(self, name: str, check: Check) -> dict[str, Any]:
        code = (
            "from pathlib import Path; import sys; p=Path('/scratch/status.json'); "
            "sys.exit(3) if not p.exists() else None; "
            "assert p.stat().st_size < 16384; sys.stdout.buffer.write(p.read_bytes())"
        )
        while True:
            await check()
            status, raw = await self._command("exec", name, "python", "-c", code, cap=16384)
            if status == 3:
                await asyncio.sleep(0.25)
                continue
            if status:
                raise BuildError("engine_failed")
            try:
                result = json.loads(raw)
                if result["schema_version"] != "1":
                    raise ValueError
                if result["status"] == "failed":
                    code = result.get("code")
                    raise BuildError(code if code in _SAFE_FAILURES else "engine_failed")
                inventory = result["files"]
                if (
                    set(result) != {"schema_version", "status", "files"}
                    or result["status"] != "ready"
                    or not isinstance(inventory, dict)
                    or set(inventory) != WEB_FILES
                ):
                    raise ValueError
                total = 0
                for entry in inventory.values():
                    if (
                        not isinstance(entry, dict)
                        or set(entry) != {"bytes", "sha256"}
                        or type(entry["bytes"]) is not int
                        or not 1 <= entry["bytes"] <= 52428800
                        or not isinstance(entry["sha256"], str)
                        or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
                    ):
                        raise ValueError
                    total += entry["bytes"]
                if total > 67108864:
                    raise ValueError
                return inventory
            except BuildError:
                raise
            except (ValueError, KeyError, TypeError, RecursionError):
                raise BuildError("output_inventory") from None

    async def _transport(self, name: str, check: Check) -> dict[str, bytes]:
        spawning = asyncio.create_task(
            asyncio.to_thread(
                subprocess.Popen,
                [*self.docker, "exec", name, "python", "/opt/build_child.py", "archive"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                start_new_session=sys.platform != "win32",
            )
        )
        try:
            process = await asyncio.shield(spawning)
        except asyncio.CancelledError:
            process, _ = await _join_owned(spawning)
            await _join_owned(asyncio.create_task(asyncio.to_thread(_stop, process)))
            raise
        assert process.stdout is not None
        os.set_blocking(process.stdout.fileno(), False)
        stop = threading.Event()
        reader = _PipeReader(process.stdout.fileno(), stop, time.monotonic() + 30)
        decoded = asyncio.create_task(
            asyncio.to_thread(
                read_child_files,
                reader,
                expected_names=WEB_FILES,
            )
        )
        try:
            async with asyncio.timeout(30):
                while not decoded.done():
                    await check()
                    await asyncio.wait({decoded}, timeout=0.25)
                files = await decoded
                if await asyncio.to_thread(process.wait, timeout=5):
                    raise BuildError("output_inventory")
                return files
        except ArtifactError:
            raise BuildError("artifact_invalid") from None
        finally:
            stop.set()

            async def close() -> None:
                try:
                    await _join_owned(decoded)
                except (ArtifactError, BuildError, OSError):
                    pass
                finally:
                    await asyncio.to_thread(_stop, process)

            _, interrupted = await _join_owned(asyncio.create_task(close()))
            if interrupted:
                raise asyncio.CancelledError

    async def _finalize(self, folder: Path | None, name: str | None, execution: str) -> None:
        if folder is None:
            return
        try:
            if name is not None:
                await self._remove(name, execution)
        except BuildError:
            # Private, token-marked input is retained if daemon/ownership cannot
            # confirm child cleanup. A later owned sweep can recover this state.
            await asyncio.to_thread(self._scratch_cleanup, folder, execution, True)
            raise
        await asyncio.to_thread(self._scratch_cleanup, folder, execution, False)

    def _scratch_cleanup(self, folder: Path, execution: str, retained: bool) -> None:
        if (
            folder.resolve(strict=True) != folder
            or folder.parent != self.root
            or not folder.name.startswith("build-" + execution.replace("-", "") + "-")
            or folder.is_symlink()
            or (folder / ".owner").is_symlink()
            or (folder / ".owner").read_text(encoding="ascii") != execution
        ):
            raise BuildError("build_io")
        if retained:
            (folder / ".cleanup").write_text("cleanup_unconfirmed", encoding="ascii")
        else:
            shutil.rmtree(folder)

    async def build(
        self, package: StoryPackage, *, execution_id: UUID, check: Check
    ) -> BuiltArtifacts:
        await check()
        try:
            if package.assets:
                raise BuildError("input_integrity")
            validated = load_text_package(package.canonical_story, package.notices)
            if validated.content_hash != package.content_hash:
                raise BuildError("package_integrity")
        except PackageError:
            raise BuildError("input_integrity") from None
        folder: Path | None = None
        created = False
        execution = str(execution_id)
        name = "flint-narrative-build-" + execution_id.hex
        try:
            async with asyncio.timeout(170):
                await self._image()
                folder = Path(
                    tempfile.mkdtemp(prefix="build-" + execution_id.hex + "-", dir=self.root)
                )
                (folder / ".owner").write_text(execution, encoding="ascii")
                source = folder / "input"
                export_godot(validated, source)
                names = (
                    *TEMPLATE_FILES,
                    "content/story.json",
                    "content/NOTICES.txt",
                    "content/package-manifest.json",
                    "build-manifest.json",
                )
                source_files = {relative: (source / relative).read_bytes() for relative in names}
                try:
                    manifest = json.loads(source_files["build-manifest.json"])
                    if (
                        manifest["package_hash"] != validated.content_hash
                        or set(manifest["files"]) != set(names) - {"build-manifest.json"}
                        or source_files["content/story.json"] != validated.canonical_story
                        or source_files["content/NOTICES.txt"] != validated.notices
                        or hashlib.sha256(source_files["content/package-manifest.json"]).hexdigest()
                        != validated.content_hash
                        or any(
                            hashlib.sha256(source_files[relative]).hexdigest() != expected
                            for relative, expected in manifest["files"].items()
                        )
                    ):
                        raise ValueError
                except (ValueError, TypeError, KeyError, RecursionError):
                    raise BuildError("artifact_invalid") from None
                await check()
                created = True  # Also clean up a created child if the CLI reply is lost.
                status, _ = await self._command(
                    "create",
                    "--pull",
                    "never",
                    "--name",
                    name,
                    "--label",
                    "io.flintgraph.narrative.execution=" + execution,
                    "--label",
                    "io.flintgraph.narrative.expires=" + str(int(time.time()) + 180),
                    "--network",
                    "none",
                    "--read-only",
                    "--user",
                    "10001:10001",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--pids-limit",
                    "128",
                    "--cpus",
                    "2",
                    "--memory",
                    "1g",
                    "--memory-swap",
                    "1g",
                    "--tmpfs",
                    "/scratch:rw,size=268435456,mode=1777",
                    "--mount",
                    "type=bind,source=" + str(source) + ",target=/input,readonly",
                    self.image,
                )
                if status:
                    raise BuildError("build_io")
                await self._effective(name, execution)
                await check()
                status, _ = await self._command("start", name)
                if status:
                    raise BuildError("engine_failed")
                inventory = await self._ready(name, check)
                files = await self._transport(name, check)
                for relative, data in files.items():
                    if inventory[relative] != {
                        "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }:
                        raise BuildError("artifact_invalid")
                for target, original in {
                    "LICENSE.runtime.txt": "LICENSE.runtime.txt",
                    "GODOT-NOTICE.txt": "GODOT-NOTICE.txt",
                    "LICENSE-Lora.txt": "fonts/LICENSE-Lora.txt",
                    "font-provenance.json": "fonts/provenance.json",
                    "NOTICES.txt": "content/NOTICES.txt",
                }.items():
                    files[target] = source_files[original]
                source_zip = await asyncio.to_thread(make_artifact_zip, source_files)
                web_zip = await asyncio.to_thread(make_artifact_zip, files)
                await check()
                return BuiltArtifacts(validated.content_hash, source_zip, web_zip)
        except TimeoutError:
            raise BuildError("build_timeout") from None
        finally:
            cleanup = asyncio.create_task(
                self._finalize(folder, name if created else None, execution)
            )
            _, interrupted = await _join_owned(cleanup)
            if interrupted:
                raise asyncio.CancelledError
