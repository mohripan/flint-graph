"""Stands in for a generation child, and runs the real one on a remote GPU (ADR 0078).

The trusted parent starts this exactly as it starts `generate.py`, with one JSON request on
stdin, and reads JSON lines from stdout and files from the output folder. So the parent's checks
on every event and file stay the same, wherever the work ran. Standard library only, because it
runs under `python -I`.
"""

import base64
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

URL = "FLINT_GRAPH_REMOTE_CHILD_URL"
TOKEN = "FLINT_GRAPH_REMOTE_CHILD_TOKEN"
# A cold worker may first have to pull its image onto a machine that has never run it.
START_SECONDS = 600
# Enough for a brief network failure. The worker keeps what has not been collected.
COLLECT_SECONDS = 120
# Runpod holds a request for up to two minutes while a worker starts.
REQUEST_SECONDS = 130
RETRY_SECONDS = 5.0
# Waiting will not change these: a wrong key, or a worker that knows nothing of this job.
FINAL_STATUSES = (401, 403, 404)
OUTPUT_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")


def child_environment(url: str, token: str) -> dict[str, str]:
    return {URL: url.rstrip("/"), TOKEN: token}


def script_path() -> Path:
    return Path(__file__).resolve()


def inputs(request: dict[str, Any]) -> dict[str, str]:
    """The images a request names by local path, which the remote side cannot read."""

    def encoded(path: str) -> str:
        return base64.b64encode(Path(path).read_bytes()).decode()

    files = {}
    if request.get("inpaint"):
        files["base.png"] = encoded(request["inpaint"]["image"])
    if request.get("scene"):
        for index, reference in enumerate(request["scene"]["references"]):
            files[f"reference-{index}.png"] = encoded(reference["image"])
    return files


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _patiently(seconds: float, url: str, token: str, body: bytes | None = None) -> bytes:
    deadline = time.monotonic() + seconds
    call = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    while True:
        try:
            with urllib.request.urlopen(call, timeout=REQUEST_SECONDS) as response:
                return bytes(response.read())
        except (OSError, http.client.HTTPException) as error:
            final = isinstance(error, urllib.error.HTTPError) and error.code in FINAL_STATUSES
            if final or time.monotonic() >= deadline:
                raise
        time.sleep(RETRY_SECONDS)


def frames(request: dict[str, Any], url: str, token: str) -> Iterator[dict[str, Any]]:
    """Starts the job, then yields what it says until the caller stops asking. Repeating a start
    is safe, because the identity is chosen here."""
    job = f"{url}/jobs/{uuid.uuid4().hex}"
    body = json.dumps({"request": request, "files": inputs(request)}).encode()
    _patiently(START_SECONDS, job, token, body)
    after = 0
    while True:
        for raw in _patiently(COLLECT_SECONDS, f"{job}?after={after}", token).splitlines():
            after += 1
            yield json.loads(raw)


def relay(request: dict[str, Any], url: str, token: str) -> int:
    output = Path(request["output_dir"])
    for frame in frames(request, url, token):
        if "file" in frame:
            if not OUTPUT_NAME.match(frame["file"]):
                return 1
            (output / frame["file"]).write_bytes(base64.b64decode(frame["data"]))
        elif "line" in frame:
            _say(frame["line"])
        elif "exit" in frame:
            return int(frame["exit"])
    return 1


def main() -> int:
    request = json.loads(sys.stdin.buffer.read())
    try:
        return relay(request, os.environ[URL], os.environ[TOKEN])
    except (OSError, KeyError, ValueError, http.client.HTTPException):
        # No detail: a URL or a token must not reach a log. The parent reports a failed generation.
        _say(
            json.dumps(
                {"protocol": request.get("protocol"), "event": "error", "code": "remote_failed"}
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
