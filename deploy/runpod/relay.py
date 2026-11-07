"""Runs one generation child on the remote GPU and yields what it says. Standard library only.

The child is the same `generate.py` a local worker runs, speaking the same protocol, so the
trusted parent keeps checking every event and file exactly as it does locally. Only paths change:
the request names files on the worker, and here they become files in a private folder.
"""

import base64
import json
import os
import queue
import re
import subprocess
import tempfile
import threading
from collections.abc import Generator, Iterator
from pathlib import Path
from typing import Any

# Only what the parent sends, under names this chooses. Nothing else is written.
INPUT_NAME = re.compile(r"(base|reference-\d)\.png\Z")
OUTPUT_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
OUTPUT_KEYS = ("file", "thumbnail")
KEEPALIVE_SECONDS = 15.0


def frame(**fields: object) -> bytes:
    return json.dumps(fields).encode() + b"\n"


def _under(value: object, root: Path) -> bool:
    return isinstance(value, str) and Path(value).resolve().is_relative_to(root)


def prepare(payload: dict[str, Any], work: Path, output: Path, models_root: Path) -> dict[str, Any]:
    """The child's request, with its files here. Raises ValueError for anything unexpected."""
    request = payload["request"]
    files = payload.get("files", {})
    if not isinstance(request, dict) or not isinstance(files, dict):
        raise ValueError("bad payload")
    root = models_root.resolve()
    if not _under(request.get("model_dir"), root):
        raise ValueError("model outside the models folder")
    for name, data in files.items():
        if not INPUT_NAME.match(name):
            raise ValueError("unexpected input")
        (work / name).write_bytes(base64.b64decode(data, validate=True))
    request["output_dir"] = str(output)
    cutout = request.get("cutout")
    if cutout is not None and not _under(cutout.get("model"), root):
        raise ValueError("cutout outside the models folder")
    inpaint = request.get("inpaint")
    if inpaint is not None:
        inpaint["image"] = str(work / "base.png")
    scene = request.get("scene")
    if scene is not None:
        if not _under(scene.get("adapter"), root):
            raise ValueError("adapter outside the models folder")
        for index, reference in enumerate(scene["references"]):
            reference["image"] = str(work / f"reference-{index}.png")
    return request


def _environment(work: Path) -> dict[str, str]:
    private = str(work)
    return {
        **{
            key: os.environ[key]
            for key in ("PATH", "LD_LIBRARY_PATH", "CUDA_VISIBLE_DEVICES", "SYSTEMROOT")
            if key in os.environ
        },
        "TEMP": private,
        "TMP": private,
        "TMPDIR": private,
        "HOME": private,
        "HF_HOME": str(work / "hf"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def run(
    payload: dict[str, Any],
    *,
    python: str,
    script: str,
    models_root: Path,
    keepalive: float = KEEPALIVE_SECONDS,
) -> Generator[bytes, None, None]:
    """Yields frames: `{}` while nothing is happening, `file` with its bytes, `line` for each thing
    the child said, in order, and finally `exit`. A file is sent before the line that names it.
    Closing this kills the child."""
    yield frame()
    with tempfile.TemporaryDirectory(prefix="flint-relay-") as directory:
        work = Path(directory)
        output = work / "out"
        output.mkdir()
        protocol = payload.get("request", {}).get("protocol") if isinstance(payload, dict) else None
        try:
            request = prepare(payload, work, output, models_root)
        except (KeyError, TypeError, ValueError, AttributeError):
            yield frame(
                line=json.dumps({"protocol": protocol, "event": "error", "code": "bad_request"})
            )
            yield frame(exit=1)
            return
        process = subprocess.Popen(
            [python, "-I", script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=work,
            env=_environment(work),
        )
        assert process.stdin is not None and process.stdout is not None
        lines: queue.Queue[bytes | None] = queue.Queue()

        def pump(stream: Any) -> None:
            for raw in stream:
                lines.put(raw)
            lines.put(None)

        threading.Thread(target=pump, args=(process.stdout,), daemon=True).start()
        try:
            process.stdin.write(json.dumps(request).encode())
            process.stdin.close()
            while True:
                try:
                    raw = lines.get(timeout=keepalive)
                except queue.Empty:
                    yield frame()
                    continue
                if raw is None:
                    break
                text = raw.decode("utf-8", "replace").rstrip("\r\n")
                yield from _named_files(text, output)
                yield frame(line=text)
            yield frame(exit=process.wait())
        finally:
            # Also when nobody is collecting any more: the child must not keep a paid GPU busy.
            if process.poll() is None:
                process.kill()
                process.wait()


def _named_files(text: str, output: Path) -> Iterator[bytes]:
    """Only files the child just named, never a folder listing: the next one may be half written."""
    try:
        event = json.loads(text)
    except ValueError:
        return
    if not isinstance(event, dict):
        return
    for key in OUTPUT_KEYS:
        name = event.get(key)
        if isinstance(name, str) and OUTPUT_NAME.match(name) and (output / name).is_file():
            data = base64.b64encode((output / name).read_bytes()).decode()
            yield frame(file=name, data=data)
