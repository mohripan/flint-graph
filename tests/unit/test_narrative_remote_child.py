"""A remote GPU must look exactly like a local child to the trusted parent (ADR 0078).

These run the real parent, the real stand-in and the real relay over real HTTP. Only the child
is fake.
"""

import base64
import hashlib
import importlib.util
import io
import itertools
import json
import sys
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from flint_graph.infrastructure import narrative_assistant, narrative_remote_child
from flint_graph.infrastructure.narrative_assistant import ollama_client
from flint_graph.infrastructure.narrative_imagegen import (
    GenerationRequest,
    ImageGenerationError,
    InpaintRequest,
    LocalImageGenerator,
    ModelIdentity,
    verify_cutout_model,
    verify_ip_adapter_model,
    verify_model,
)
from flint_graph.infrastructure.narrative_remote_child import (
    TOKEN,
    URL,
    child_environment,
    script_path,
)
from flint_graph.infrastructure.narrative_voicegen import verify_voice_model

pytestmark = pytest.mark.anyio

ROOT = Path(__file__).parents[2]
FAKE = ROOT / "tests/fixtures/narrative/fake_imagegen.py"
MODEL = ModelIdentity(repo="fixture/model", revision="a" * 40, license="openrail++")
GOOD_TOKEN = "correct-token"


def _load(name: str):
    specification = importlib.util.spec_from_file_location(
        f"runpod_{name}", ROOT / f"deploy/runpod/{name}.py"
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


relay = _load("relay")
worker = _load("server")


class Remote:
    """The real worker server, behind what Runpod's edge does for it."""

    def __init__(self, models_root: Path, script: Path = FAKE, *, starting: int = 0) -> None:
        self.seen: list[dict] = []
        self.starting = starting
        outer = self

        class Recording(worker.Jobs):
            def start(self, kind: str, identity: str, payload: dict) -> bool:
                outer.seen.append(json.loads(json.dumps(payload)))
                return super().start(kind, identity, payload)

        self.jobs = Recording({"images": (sys.executable, str(script))}, models_root)

        class Handler(worker.handler_for(self.jobs, wait=0.05)):
            def _at_the_edge(self) -> bool:
                if self.headers.get("Authorization") != f"Bearer {GOOD_TOKEN}":
                    self.close_connection = True
                    self._reply(401)
                    return False
                if outer.starting:
                    outer.starting -= 1
                    self.close_connection = True
                    self._reply(400, b'{"error":"timed out waiting for worker"}')
                    return False
                return True

            def do_GET(self) -> None:
                if self._at_the_edge():
                    super().do_GET()

            def do_POST(self) -> None:
                if self._at_the_edge():
                    super().do_POST()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/images"

    def __enter__(self) -> "Remote":
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *args: object) -> None:
        self.server.shutdown()
        self.server.server_close()


def generator(url: str, token: str = GOOD_TOKEN, model_dir: Path = Path(__file__).parent):
    return LocalImageGenerator(
        python=Path(sys.executable),
        script=script_path(),
        model_dir=model_dir,
        model=MODEL,
        deadline_seconds=30,
        child_env=child_environment(url, token),
    )


def request(mode: str = "ok", seeds: tuple[int, ...] = (11, 22), inpaint=None) -> GenerationRequest:
    return GenerationRequest(
        prompt=f"{mode}, solo",
        negative_prompt="lowres",
        width=832,
        height=1216,
        steps=28,
        guidance=5.0,
        seeds=seeds,
        inpaint=inpaint,
    )


async def nothing(_: int) -> None:
    pass


async def test_a_job_on_the_remote_side_returns_what_a_local_one_would():
    progress: list[int] = []

    async def note(count: int) -> None:
        progress.append(count)

    with Remote(Path(__file__).parent) as remote:
        result = await generator(remote.url).generate(request(), on_progress=note)
    assert [image.seed for image in result.images] == [11, 22]
    for image in result.images:
        assert hashlib.sha256(image.data).hexdigest() == image.sha256
        assert (image.width, image.height) == (832, 1216)
    assert progress == [1, 2]


def child_request(root: Path, mode: str = "ok") -> dict:
    return {
        "protocol": 1,
        "model_dir": str(root),
        "output_dir": "unused",
        "prompt": f"{mode}, solo",
        "negative_prompt": "lowres",
        "width": 832,
        "height": 1216,
        "steps": 28,
        "guidance": 5.0,
        "seeds": [11],
        "cutout": None,
    }


def test_a_worker_still_starting_is_waited_for_and_the_job_runs_once(monkeypatch):
    monkeypatch.setattr(narrative_remote_child, "RETRY_SECONDS", 0.0)
    root = Path(__file__).parent
    with Remote(root, starting=2) as remote:
        received = list(
            itertools.takewhile(
                lambda frame: "exit" not in frame,
                narrative_remote_child.frames(child_request(root), remote.url, GOOD_TOKEN),
            )
        )
    assert any("file" in frame for frame in received)
    assert len(remote.jobs.jobs) == len(remote.seen) == 1


def test_a_repeated_start_does_not_run_the_job_again():
    root = Path(__file__).parent
    jobs = worker.Jobs({"images": (sys.executable, str(FAKE))}, root)
    payload = {"request": child_request(root)}
    identity = "a" * 32
    assert jobs.start("images", identity, payload)
    first = jobs.jobs[identity]
    assert jobs.start("images", identity, payload)
    assert jobs.jobs[identity] is first
    assert not jobs.start("music", "b" * 32, payload)


def test_a_reply_lost_on_the_way_can_be_asked_for_again_until_it_is_confirmed():
    job = worker.Job()
    job.frames = [b"one\n", b"two\n"]
    assert job.collect(0, 0) == [b"one\n", b"two\n"]
    assert job.collect(0, 0) == [b"one\n", b"two\n"]
    assert job.collect(1, 0) == [b"two\n"]
    assert job.frames == [b"two\n"]


def test_a_large_batch_arrives_over_several_replies(monkeypatch):
    # Runpod refuses a body over 30 MB. A single frame always goes, whatever its size.
    monkeypatch.setattr(worker, "REPLY_BYTES", 10)
    job = worker.Job()
    job.frames = [b"x" * 8, b"y" * 8, b"z" * 20]
    assert job.collect(0, 0) == [b"x" * 8]
    assert job.collect(1, 0) == [b"y" * 8]
    assert job.collect(2, 0) == [b"z" * 20]


def test_a_new_worker_that_knows_nothing_of_the_job_fails_it_at_once():
    with Remote(Path(__file__).parent) as remote:
        with pytest.raises(urllib.error.HTTPError) as caught:
            narrative_remote_child._patiently(600, f"{remote.url}/jobs/{'c' * 32}", GOOD_TOKEN)
    assert caught.value.code == 404


def test_a_job_nobody_is_collecting_stops_using_the_gpu():
    root = Path(__file__).parent
    jobs = worker.Jobs({"images": (sys.executable, str(FAKE))}, root, abandoned=0.2, keepalive=0.05)
    assert jobs.start("images", "d" * 32, {"request": child_request(root, "hang")})
    job = jobs.jobs["d" * 32]
    deadline = time.monotonic() + 20
    while not job.finished and time.monotonic() < deadline:
        time.sleep(0.05)
    assert job.finished


def test_a_runtime_that_will_not_start_ends_the_job_instead_of_leaving_it_waiting():
    root = Path(__file__).parent
    jobs = worker.Jobs({"images": (str(root / "no-such-python"), str(FAKE))}, root)
    assert jobs.start("images", "e" * 32, {"request": child_request(root)})
    job = jobs.jobs["e" * 32]
    deadline = time.monotonic() + 20
    while not job.finished and time.monotonic() < deadline:
        time.sleep(0.05)
    assert json.loads(job.frames[-1]) == {"exit": 1}


async def test_the_parent_still_checks_what_comes_back():
    # A remote child that returns the wrong size is refused exactly as a local one would be.
    with Remote(Path(__file__).parent) as remote:
        with pytest.raises(ImageGenerationError) as caught:
            await generator(remote.url).generate(request("wrongsize"), on_progress=nothing)
    assert caught.value.code == "invalid_output"


async def test_a_childs_own_error_reaches_the_parent():
    with Remote(Path(__file__).parent) as remote:
        with pytest.raises(ImageGenerationError) as caught:
            await generator(remote.url).generate(request("busy"), on_progress=nothing)
    assert caught.value.code == "gpu_busy"


async def test_a_wrong_token_is_a_failed_job_and_reveals_nothing():
    with Remote(Path(__file__).parent) as remote:
        with pytest.raises(ImageGenerationError) as caught:
            await generator(remote.url, token="wrong").generate(request(), on_progress=nothing)
    assert caught.value.code == "generation_failed"
    assert GOOD_TOKEN not in str(caught.value) and "wrong" not in str(caught.value)


def test_a_remote_that_never_answers_ends_in_a_failure_that_reveals_nothing(monkeypatch, capsys):
    # Unreachable is what a cold start looks like, so it is waited for first, and then given up on.
    monkeypatch.setattr(narrative_remote_child, "START_SECONDS", 0)
    body = json.dumps({"protocol": 1, "output_dir": "unused"}).encode()
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(body)))
    monkeypatch.setenv(URL, "http://127.0.0.1:9/images")
    monkeypatch.setenv(TOKEN, "secret-token")
    assert narrative_remote_child.main() == 1
    said = capsys.readouterr().out
    assert json.loads(said)["code"] == "remote_failed"
    assert "secret-token" not in said and "127.0.0.1" not in said


async def test_a_base_image_travels_with_the_job_and_gets_a_private_path(tmp_path):
    base = (ROOT / "tests/fixtures/narrative").glob("*.png")
    image = next(base, None)
    data = image.read_bytes() if image else b"not checked by the relay"
    inpaint = InpaintRequest(
        image=data, box=(0, 0, 64, 64), strength=0.5, prompts=("smile", "smile")
    )
    with Remote(Path(__file__).parent) as remote:
        try:
            await generator(remote.url).generate(request(inpaint=inpaint), on_progress=nothing)
        except ImageGenerationError:
            pass
    payload = remote.seen[0]
    assert base64.b64decode(payload["files"]["base.png"]) == data


def test_a_request_cannot_reach_outside_the_models_folder(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    payload = {"request": {"protocol": 1, "model_dir": str(tmp_path / "secrets")}}
    frames = [
        json.loads(line)
        for line in relay.run(payload, python="unused", script="unused", models_root=models)
    ]
    event = json.loads(next(frame["line"] for frame in frames if "line" in frame))
    assert event["code"] == "bad_request"
    assert frames[-1] == {"exit": 1}


def test_a_request_cannot_write_a_file_of_its_choosing(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    payload = {
        "request": {"protocol": 1, "model_dir": str(models)},
        "files": {"../../evil.png": base64.b64encode(b"x").decode()},
    }
    frames = [
        json.loads(line)
        for line in relay.run(payload, python="unused", script="unused", models_root=models)
    ]
    assert frames[-1] == {"exit": 1}
    assert not (tmp_path / "evil.png").exists()


def test_a_slow_start_still_sends_something_at_once(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    stream = relay.run(
        {"request": {"model_dir": str(models)}},
        python="unused",
        script="unused",
        models_root=models,
    )
    # A proxy gives up on a connection with no first byte, however long a cold start takes.
    assert json.loads(next(stream)) == {}
    stream.close()


def test_the_assistants_model_gets_the_token_only_when_there_is_one():
    remote = SimpleNamespace(
        ollama_base_url="https://gpu.example.com", narrative_remote_gpu_token="secret"
    )
    assert ollama_client(remote).headers["authorization"] == "Bearer secret"
    local = SimpleNamespace(
        ollama_base_url="http://localhost:11434", narrative_remote_gpu_token=None
    )
    assert "authorization" not in ollama_client(local).headers


class Gateway:
    """Answers each request with the next status, as Runpod's edge does around a cold start."""

    def __init__(self, *statuses: int) -> None:
        self.statuses = list(statuses)
        self.bodies: list[bytes] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                pass

            def do_POST(self) -> None:
                outer.bodies.append(self.rfile.read(int(self.headers["Content-Length"])))
                body = b'{"ok":true}'
                self.send_response(outer.statuses.pop(0))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def client(self):
        return ollama_client(
            SimpleNamespace(
                ollama_base_url=f"http://127.0.0.1:{self.server.server_port}",
                narrative_remote_gpu_token="secret",
            )
        )


async def test_the_assistant_waits_for_a_worker_to_start(monkeypatch):
    monkeypatch.setattr(narrative_assistant, "WORKER_RETRY_SECONDS", 0.0)
    gateway = Gateway(400, 524, 200)
    async with gateway.client() as client:
        response = await client.post("/api/chat", json={"model": "m"})
    gateway.server.shutdown()
    assert response.status_code == 200
    # The same request every time, because nothing took it.
    assert len(gateway.bodies) == 3 and len(set(gateway.bodies)) == 1


async def test_the_assistant_does_not_wait_on_a_wrong_key(monkeypatch):
    monkeypatch.setattr(narrative_assistant, "WORKER_RETRY_SECONDS", 0.0)
    gateway = Gateway(401, 200)
    async with gateway.client() as client:
        response = await client.post("/api/chat", json={"model": "m"})
    gateway.server.shutdown()
    assert response.status_code == 401
    assert len(gateway.bodies) == 1


async def test_the_assistant_gives_up_on_a_worker_that_never_starts(monkeypatch):
    monkeypatch.setattr(narrative_assistant, "WORKER_RETRY_SECONDS", 0.0)
    monkeypatch.setattr(narrative_assistant, "WORKER_START_SECONDS", 0.0)
    gateway = Gateway(400, 200)
    async with gateway.client() as client:
        response = await client.post("/api/chat", json={"model": "m"})
    gateway.server.shutdown()
    assert response.status_code == 400


def test_the_stand_in_keeps_its_address_and_token_out_of_the_arguments():
    environment = child_environment("https://gpu.example.com/", "secret")
    assert environment[URL] == "https://gpu.example.com"
    assert environment[TOKEN] == "secret"


def _manifest(tmp_path: Path, files: dict[str, dict]) -> tuple[Path, str]:
    folder = tmp_path / "manifest-only"
    folder.mkdir()
    data = json.dumps(
        {"repo": "fixture/model", "revision": "a" * 40, "license": "apache-2.0", "files": files}
    ).encode()
    (folder / "flintgraph-download.json").write_bytes(data)
    return folder, hashlib.sha256(data).hexdigest()


ENTRY = {"size": 1, "sha256": "0" * 64}


def test_a_remote_model_is_named_by_its_pinned_manifest_alone(tmp_path):
    folder, pin = _manifest(tmp_path, {"weights.safetensors": ENTRY})
    assert verify_model(folder, pin, weights_here=False).repo == "fixture/model"
    # On a machine that should hold the weights, their absence is still refused.
    with pytest.raises(ValueError):
        verify_model(folder, pin)


def test_the_manifest_is_still_held_to_its_pin(tmp_path):
    folder, _ = _manifest(tmp_path, {"weights.safetensors": ENTRY})
    with pytest.raises(ValueError):
        verify_model(folder, "1" * 64, weights_here=False)


def test_every_kind_of_model_can_be_named_remotely(tmp_path):
    cutout, pin = _manifest(tmp_path, {"isnet.onnx": ENTRY})
    assert verify_cutout_model(cutout, pin, weights_here=False).path.name == "isnet.onnx"
    (cutout / "flintgraph-download.json").unlink()
    cutout.rmdir()
    adapter, pin = _manifest(
        tmp_path,
        {
            "sdxl_models/ip-adapter.safetensors": ENTRY,
            "models/image_encoder/config.json": ENTRY,
            "models/image_encoder/model.safetensors": ENTRY,
        },
    )
    assert verify_ip_adapter_model(adapter, pin, weights_here=False).weight.startswith(
        "sdxl_models/"
    )
    (adapter / "flintgraph-download.json").unlink()
    adapter.rmdir()
    voice, pin = _manifest(
        tmp_path, {"config.json": ENTRY, "kokoro-v1_0.pth": ENTRY, "voices/af_bella.pt": ENTRY}
    )
    identity, voices = verify_voice_model(voice, pin, weights_here=False)
    assert identity.repo == "fixture/model"
    assert voices == ("af_bella",)
