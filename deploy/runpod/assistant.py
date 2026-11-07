"""Ollama behind the assistant worker's server on Runpod (ADR 0078). Standard library only.

    python3 assistant.py                 # serve
    python3 assistant.py --pull A B      # download models onto the Network Volume, once

Runpod's edge checks the caller's key. A request that says nothing for about 100 seconds can be
dropped on the way, and loading a model takes about that long. So every reply starts at once, with
blank lines until Ollama has something to say. Whoever reads the reply skips blank lines, and JSON
allows them before a document. An upstream error therefore arrives as a body, not as a status.
"""

import http.client
import os
import queue
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OLLAMA_PORT = 11434
KEEPALIVE_SECONDS = 15.0
ERROR_LINE = b'{"error":"the model server did not answer"}\n'


def ready(port: int = OLLAMA_PORT) -> bool:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", "/api/version")
        return connection.getresponse().status == 200
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def handler_for(
    port: int = OLLAMA_PORT, *, keepalive: float = KEEPALIVE_SECONDS
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: object) -> None:
            pass

        def _empty(self, status: int) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            if self.path != "/ping":
                self._empty(404)
                return
            self._empty(200 if ready(port) else 204)

        def _chunk(self, data: bytes) -> None:
            self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
            self.wfile.flush()

        def do_POST(self) -> None:
            self.close_connection = True
            length = self.headers.get("Content-Length", "0")
            if not self.path.startswith("/api/") or not length.isdecimal():
                self._empty(404)
                return
            body = self.rfile.read(int(length))
            chunks: queue.Queue[bytes | None] = queue.Queue()
            upstream = http.client.HTTPConnection("127.0.0.1", port)

            def pump() -> None:
                try:
                    upstream.request("POST", self.path, body, {"Content-Type": "application/json"})
                    response = upstream.getresponse()
                    while data := response.read1(65536):
                        chunks.put(data)
                except (OSError, http.client.HTTPException, ValueError):
                    chunks.put(ERROR_LINE)
                finally:
                    chunks.put(None)

            threading.Thread(target=pump, daemon=True).start()
            self.send_response(200)
            # The one type every proxy on the way passes on as it comes.
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                self._chunk(b"\n")
                while True:
                    try:
                        data = chunks.get(timeout=keepalive)
                    except queue.Empty:
                        self._chunk(b"\n")
                        continue
                    if data is None:
                        break
                    self._chunk(data)
                self.wfile.write(b"0\r\n\r\n")
            except OSError:
                pass  # The caller left.
            finally:
                # Ollama stops generating when its connection closes.
                upstream.close()

    return Handler


def start_ollama() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        ["/bin/ollama", "serve"],
        env={
            **os.environ,
            "OLLAMA_HOST": f"127.0.0.1:{OLLAMA_PORT}",
            "OLLAMA_MODELS": "/runpod-volume/ollama",
            "OLLAMA_KEEP_ALIVE": "-1",
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def pull(models: list[str]) -> None:
    server = start_ollama()
    try:
        while not ready():
            time.sleep(0.5)
        environment = {**os.environ, "OLLAMA_HOST": f"127.0.0.1:{OLLAMA_PORT}"}
        for model in models:
            subprocess.run(["/bin/ollama", "pull", model], env=environment, check=True)
        print("PULLED", flush=True)
    finally:
        server.terminate()


def main() -> None:
    if sys.argv[1:2] == ["--pull"]:
        pull(sys.argv[2:])
        return
    start_ollama()
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "80"))), handler_for())
    server.serve_forever()


if __name__ == "__main__":
    main()
