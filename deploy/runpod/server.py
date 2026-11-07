"""The generation worker's server on Runpod (ADR 0078). Standard library only.

Runpod's load balancer checks the caller's key and forwards here. It ends any request after 5.5
minutes and refuses a body over 30 MB, and a batch of large pictures can exceed both. So a job is
not one request: the caller starts it, then collects what the child said a few frames at a time.
"""

import json
import os
import re
import sys
import threading
import time
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).parent))
import relay

MODELS_ROOT = Path("/models")
ROUTE = re.compile(r"/(images|voices)/jobs/([0-9a-f]{32})\Z")
BODY_BYTES = 30 * 1024 * 1024
# Under Runpod's 30 MB, in frames that are at most a few MB each.
REPLY_BYTES = 20 * 1024 * 1024
# Short enough that no proxy on the way gives up on a request that has said nothing.
WAIT_SECONDS = 20.0
# Nobody collecting means the worker that asked is gone. The GPU is billed until the child stops.
ABANDONED_SECONDS = 120.0


class Job:
    def __init__(self) -> None:
        self.changed = threading.Condition()
        self.frames: list[bytes] = []
        self.first = 0
        self.seen = time.monotonic()
        self.finished = False

    def feed(self, stream: Generator[bytes, None, None], abandoned: float) -> None:
        nothing = relay.frame()
        try:
            for data in stream:
                if time.monotonic() - self.seen > abandoned:
                    stream.close()
                    return
                if data != nothing:
                    with self.changed:
                        self.frames.append(data)
                        self.changed.notify_all()
        except Exception:
            # For example a runtime that will not start. The parent reports a failed generation.
            with self.changed:
                self.frames.append(relay.frame(exit=1))
        finally:
            with self.changed:
                self.finished = True
                self.changed.notify_all()

    def collect(self, after: int, wait: float) -> list[bytes]:
        """Frames from `after`. Asking for `after` confirms the ones before it, which frees them;
        until then they are kept, so a reply lost on the way can be asked for again."""
        with self.changed:
            if after > self.first:
                del self.frames[: after - self.first]
                self.first = after
            self.seen = time.monotonic()
            self.changed.wait_for(lambda: self.frames or self.finished, wait)
            self.seen = time.monotonic()
            reply: list[bytes] = []
            size = 0
            for data in self.frames:
                if reply and size + len(data) > REPLY_BYTES:
                    break
                reply.append(data)
                size += len(data)
            return reply


class Jobs:
    def __init__(
        self,
        runtimes: dict[str, tuple[str, str]],
        models_root: Path,
        *,
        abandoned: float = ABANDONED_SECONDS,
        keepalive: float = relay.KEEPALIVE_SECONDS,
    ) -> None:
        self.runtimes, self.models_root = runtimes, models_root
        self.abandoned, self.keepalive = abandoned, keepalive
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def start(self, kind: str, identity: str, payload: dict[str, Any]) -> bool:
        """Starts the job once, because a caller repeats this if the reply does not reach it."""
        with self.lock:
            now = time.monotonic()
            for key in [
                key
                for key, job in self.jobs.items()
                if job.finished and now - job.seen > self.abandoned
            ]:
                del self.jobs[key]
            if identity in self.jobs or kind not in self.runtimes:
                return kind in self.runtimes
            job = self.jobs[identity] = Job()
        python, script = self.runtimes[kind]
        stream = relay.run(
            payload,
            python=python,
            script=script,
            models_root=self.models_root,
            keepalive=self.keepalive,
        )
        threading.Thread(target=job.feed, args=(stream, self.abandoned), daemon=True).start()
        return True

    def collect(self, identity: str, after: int, wait: float) -> list[bytes] | None:
        job = self.jobs.get(identity)
        return None if job is None else job.collect(after, wait)


def handler_for(jobs: Jobs, *, wait: float = WAIT_SECONDS) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: object) -> None:
            pass

        def _reply(self, status: int, body: bytes = b"{}") -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            if parts.path == "/ping":
                self._reply(200)
                return
            route = ROUTE.match(parts.path)
            after = parse_qs(parts.query).get("after", ["0"])[0]
            if route is None or not after.isdecimal():
                self._reply(404)
                return
            frames = jobs.collect(route[2], int(after), wait)
            if frames is None:
                # A new worker knows nothing of the job. The caller must not wait for it.
                self._reply(404)
                return
            self._reply(200, b"".join(frames))

        def do_POST(self) -> None:
            self.close_connection = True
            route = ROUTE.match(self.path)
            length = self.headers.get("Content-Length", "0")
            if route is None or not length.isdecimal() or not 0 < int(length) <= BODY_BYTES:
                self._reply(400)
                return
            try:
                payload = json.loads(self.rfile.read(int(length)))
            except ValueError:
                self._reply(400)
                return
            self._reply(200 if jobs.start(route[1], route[2], payload) else 404)

    return Handler


def main() -> None:
    runtimes = {
        kind: (f"/app/runtimes/{name}/.venv/bin/python", f"/app/runtimes/{name}/generate.py")
        for kind, name in (("images", "imagegen"), ("voices", "voicegen"))
    }
    server = ThreadingHTTPServer(
        ("0.0.0.0", int(os.environ.get("PORT", "80"))),
        handler_for(Jobs(runtimes, MODELS_ROOT)),
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
