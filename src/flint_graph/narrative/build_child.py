"""Standalone stdlib-only trusted image entrypoint, never creator-supplied code.

The image pins trusted runtime hashes. Host-provided text cannot replace scripts.
No credentials, network, writable host tree or raw-log response is needed here.
"""

import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tarfile
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

WEB_FILES = frozenset(
    {
        "index.html",
        "index.js",
        "index.wasm",
        "index.pck",
        "index.png",
        "index.audio.worklet.js",
        "index.audio.position.worklet.js",
    }
)
RUNTIME_FILES = frozenset(
    {
        "project.godot",
        "main.tscn",
        "runtime/bootstrap.gd",
        "runtime/strict_json.gd",
        "runtime/player.gd",
        "runtime/game_view.gd",
        "runtime/save_store.gd",
        "fonts/Lora.ttf",
        "fonts/LICENSE-Lora.txt",
        "fonts/provenance.json",
        "export_presets.cfg",
        "LICENSE.runtime.txt",
        "GODOT-NOTICE.txt",
        "README.txt",
        "toolchain.json",
    }
)
CONTENT_FILES = frozenset(
    {"content/story.json", "content/NOTICES.txt", "content/package-manifest.json"}
)


def _read(path: Path, cap: int) -> bytes:
    # Known relative paths only; reject links on every traversed component too.
    if any(parent.is_symlink() for parent in path.parents) or path.is_symlink():
        raise ValueError("input_integrity")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > cap:
        raise ValueError("input_integrity")
    with path.open("rb") as stream:
        data = stream.read(cap + 1)
    if len(data) > cap:
        raise ValueError("input_integrity")
    return data


def _inputs(source: Path, trusted: Mapping[str, str]) -> dict[str, bytes]:
    if set(trusted) != RUNTIME_FILES:
        raise ValueError("input_integrity")
    manifest_bytes = _read(source / "build-manifest.json", 65536)

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError("input_integrity")
        return result

    manifest = json.loads(manifest_bytes, object_pairs_hook=unique)
    if set(manifest) != {
        "schema_version",
        "package_hash",
        "compiler_version",
        "runtime_version",
        "godot_version",
        "files",
    }:
        raise ValueError("input_integrity")
    if (
        manifest["schema_version"] != "1"
        or manifest["compiler_version"] != "0.1.0"
        or manifest["runtime_version"] != "0.2.0"
        or manifest["godot_version"] != "4.7.2.stable"
        or not isinstance(manifest["package_hash"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", manifest["package_hash"])
    ):
        raise ValueError("input_integrity")
    hashes = manifest["files"]
    if set(hashes) != RUNTIME_FILES | CONTENT_FILES:
        raise ValueError("input_integrity")
    result = {}
    for name in sorted(hashes):
        cap = 5 * 1024 * 1024 if name == "content/story.json" else 1024 * 1024
        data = _read(source / name, cap)
        actual = hashlib.sha256(data).hexdigest()
        if actual != hashes[name] or (name in trusted and actual != trusted[name]):
            raise ValueError("input_integrity")
        result[name] = data
    result["build-manifest.json"] = manifest_bytes
    if (
        hashlib.sha256(result["content/package-manifest.json"]).hexdigest()
        != manifest["package_hash"]
    ):
        raise ValueError("input_integrity")
    return result


def _engine(command: tuple[str, ...], project: Path, args: list[str], timeout: float) -> bool:
    process = subprocess.Popen(
        [*command, "--headless", "--path", str(project), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        start_new_session=sys.platform != "win32",
    )
    previous, invalid, eof = b"", False, False
    assert process.stdout is not None
    try:
        os.set_blocking(process.stdout.fileno(), False)
        deadline = time.monotonic() + timeout
        while True:
            try:
                chunk = os.read(process.stdout.fileno(), 65536)
            except BlockingIOError:
                chunk = None
            if chunk:
                combined = previous + chunk
                invalid |= b"SCRIPT ERROR" in combined or b"Parse Error" in combined
                previous = combined[-64:]
            elif chunk == b"":
                eof = True
            result = process.poll()
            if eof and result is not None:
                return result == 0 and not invalid
            if time.monotonic() >= deadline:
                raise TimeoutError
            if not chunk:
                time.sleep(0.01)
    finally:
        if sys.platform != "win32":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        process.stdout.close()


def run_build(
    source: Path,
    scratch: Path,
    trusted: Mapping[str, str],
    *,
    engine_command: tuple[str, ...] = ("/opt/godot",),
    templates: Path = Path("/opt/templates"),
    stage_timeout: float = 90,
) -> dict[str, Any]:
    """Run fixed import/export stages; paths/command are image-owned, not API inputs."""

    def failed(code: str) -> dict[str, Any]:
        return {"schema_version": "1", "status": "failed", "code": code}

    try:
        payloads = _inputs(source, trusted)
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return failed("input_integrity")
    try:
        for name in ["home", "tmp", "web", "project"]:
            (scratch / name).mkdir()
        project = scratch / "project"
        for name, data in payloads.items():
            path = project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        presets = project / "export_presets.cfg"
        text = presets.read_text(encoding="utf-8")
        for mode in ["debug", "release"]:
            text = text.replace(
                f'custom_template/{mode}=""',
                f'custom_template/{mode}="{templates}/web_nothreads_{mode}.zip"',
            )
        presets.write_text(text, encoding="utf-8", newline="\n")
        for args in [
            ["--editor", "--import"],
            ["--export-release", "Web", str(scratch / "web/index.html")],
        ]:
            if not _engine(engine_command, project, args, stage_timeout):
                return failed("engine_failed")
        web = scratch / "web"
        if {p.name for p in web.iterdir()} != WEB_FILES:
            return failed("output_inventory")
        inventory = {}
        total = 0
        for name in sorted(WEB_FILES):
            data = _read(web / name, 50 * 1024 * 1024)
            total += len(data)
            if total > 64 * 1024 * 1024:
                return failed("output_size_limit")
            inventory[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        return {"schema_version": "1", "status": "ready", "files": inventory}
    except TimeoutError:
        return failed("engine_timeout")
    except (OSError, ValueError):
        return failed("build_io")


def main() -> None:
    if sys.argv[1:] == ["archive"]:
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|", format=tarfile.USTAR_FORMAT) as t:
            root = Path("/scratch/web")
            for name in sorted(WEB_FILES):
                path = root / name
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_size > 50 * 1024 * 1024:
                    raise ValueError("output_inventory")
                entry = tarfile.TarInfo("web/" + name)
                entry.size = info.st_size
                with path.open("rb") as stream:
                    t.addfile(entry, stream)
        return
    if sys.argv[1:]:
        raise SystemExit(2)
    watchdog = threading.Timer(180, lambda: os._exit(124))
    watchdog.daemon = True
    watchdog.start()
    trusted = json.loads(Path("/opt/runtime-files.json").read_bytes())
    outcome = run_build(Path("/input"), Path("/scratch"), trusted)
    temporary = Path("/scratch/status.tmp")
    temporary.write_text(json.dumps(outcome, separators=(",", ":")), encoding="utf-8")
    temporary.replace("/scratch/status.json")
    # Keep bounded tmpfs available for the host's fixed archiver until cleanup.
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
