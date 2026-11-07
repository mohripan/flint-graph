"""The assistant's server on Runpod starts every reply at once (ADR 0078)."""

import http.client
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).parents[2]

specification = importlib.util.spec_from_file_location(
    "runpod_assistant", ROOT / "deploy/runpod/assistant.py"
)
assert specification is not None and specification.loader is not None
assistant = importlib.util.module_from_spec(specification)
specification.loader.exec_module(assistant)

pytestmark = pytest.mark.anyio


class Ollama:
    """Stands in for Ollama, and holds its reply until told to answer."""

    def __init__(self, reply: list[bytes], status: int = 200) -> None:
        self.go = threading.Event()
        self.seen: list[bytes] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                pass

            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self) -> None:
                outer.seen.append(self.rfile.read(int(self.headers["Content-Length"])))
                outer.go.wait(10)
                self.send_response(status)
                self.end_headers()
                for data in reply:
                    self.wfile.write(data)
                    self.wfile.flush()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


class Proxy:
    def __init__(self, port: int, keepalive: float = 15.0) -> None:
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), assistant.handler_for(port, keepalive=keepalive)
        )
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def test_the_reply_starts_before_ollama_has_said_anything():
    ollama = Ollama([b'{"done":true}\n'])
    proxy = Proxy(ollama.port, keepalive=0.05)
    connection = http.client.HTTPConnection("127.0.0.1", proxy.port, timeout=5)
    connection.request("POST", "/api/chat", b'{"model":"m"}')
    response = connection.getresponse()
    assert response.status == 200
    # Blank lines arrive while Ollama is still loading its model.
    assert response.readline().strip() == b""
    assert response.readline().strip() == b""
    ollama.go.set()
    rest = [line for line in response.read().splitlines() if line.strip()]
    assert rest == [b'{"done":true}']
    assert ollama.seen == [b'{"model":"m"}']


async def test_a_streamed_reply_reads_line_by_line_as_the_assistant_reads_it():
    ollama = Ollama([b'{"message":{"content":"a"}}\n', b'{"done":true}\n'])
    ollama.go.set()
    proxy = Proxy(ollama.port)
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{proxy.port}") as client:
        async with client.stream("POST", "/api/chat", json={"model": "m"}) as response:
            lines = [line async for line in response.aiter_lines() if line.strip()]
    assert [json.loads(line) for line in lines] == [
        {"message": {"content": "a"}},
        {"done": True},
    ]


async def test_a_whole_reply_is_still_valid_json_after_the_blank_line():
    # The screenshot describer and the capabilities check read one document, not a stream.
    ollama = Ollama([b'{"message":{"content":"a"}}'])
    ollama.go.set()
    proxy = Proxy(ollama.port)
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{proxy.port}") as client:
        response = await client.post("/api/chat", json={"model": "m"})
    assert response.json() == {"message": {"content": "a"}}


async def test_an_upstream_error_arrives_as_a_body_that_is_not_an_answer():
    ollama = Ollama([b'{"error":"model not found"}'], status=404)
    ollama.go.set()
    proxy = Proxy(ollama.port)
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{proxy.port}") as client:
        response = await client.post("/api/chat", json={"model": "m"})
    assert response.json() == {"error": "model not found"}


async def test_no_ollama_is_a_body_that_is_not_an_answer():
    proxy = Proxy(9)
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{proxy.port}") as client:
        response = await client.post("/api/chat", json={"model": "m"})
    assert "error" in response.json()


def test_a_worker_is_not_ready_until_ollama_is():
    ollama = Ollama([])
    for port, expected in ((ollama.port, 200), (9, 204)):
        proxy = Proxy(port)
        connection = http.client.HTTPConnection("127.0.0.1", proxy.port, timeout=5)
        connection.request("GET", "/ping")
        assert connection.getresponse().status == expected


def test_only_ollamas_api_is_forwarded():
    ollama = Ollama([])
    proxy = Proxy(ollama.port)
    connection = http.client.HTTPConnection("127.0.0.1", proxy.port, timeout=5)
    connection.request("POST", "/anything", b"{}")
    assert connection.getresponse().status == 404
    assert ollama.seen == []
