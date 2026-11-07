"""Calls the deployed Runpod endpoints as the workers do and times each part. Costs a few cents.

    GPU_TOKEN=... uv run python deploy/runpod/smoke.py <generation> images --seeds 2 --hires --out D
    GPU_TOKEN=... uv run python deploy/runpod/smoke.py <generation> voices --out DIR
    GPU_TOKEN=... uv run python deploy/runpod/smoke.py <assistant> assistant
    GPU_TOKEN=... uv run python deploy/runpod/smoke.py <assistant> vision --picture FILE

<generation> and <assistant> are the endpoint IDs.

Run it twice within a minute to see a warm call beside the cold one. The trusted checks on what
comes back are the parent's, and `tests/unit/test_narrative_remote_child.py` covers those.
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = ROOT / "deploy/k8s/base/model-manifests"
# An original adult fixture character, as in the other qualification reports.
PROMPT = (
    "1woman, adult, solo, short silver hair, green eyes, navy blazer, white shirt, "
    "full body, standing, plain background"
)
NEGATIVE = "lowres, bad anatomy, bad hands, worst quality, low quality"
LINE = "The harbour lights came on one by one, and nobody on the pier looked up."


def _config(name: str) -> str:
    for line in (ROOT / "deploy/k8s/base/config.env").read_text("utf-8").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1]
    raise SystemExit(f"{name} is not in config.env")


def _post(url: str, token: str, body: dict[str, Any]) -> Iterator[bytes]:
    call = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(call, timeout=900) as response:
        yield from response


def _relay(url: str, token: str, request: dict[str, Any], out: Path | None) -> None:
    from flint_graph.infrastructure.narrative_remote_child import frames

    started = time.monotonic()

    def say(what: str) -> None:
        print(f"{time.monotonic() - started:7.1f}s  {what}", flush=True)

    for frame in frames(request, url, token):
        if "file" in frame:
            data = base64.b64decode(frame["data"])
            say(f"file {frame['file']} ({len(data)} bytes)")
            if out is not None:
                out.mkdir(parents=True, exist_ok=True)
                (out / frame["file"]).write_bytes(data)
        elif "line" in frame:
            event = json.loads(frame["line"])
            detail = {key: event[key] for key in ("code", "device", "index") if key in event}
            say(f"{event.get('event')} {detail if detail else ''}")
        elif "exit" in frame:
            say(f"exit {frame['exit']}")
            if frame["exit"] != 0:
                raise SystemExit(1)
            return


def images(url: str, token: str, args: argparse.Namespace) -> None:
    from flint_graph.infrastructure.narrative_imagegen import PROTOCOL

    cutout = json.loads((MANIFESTS / "anime-seg.json").read_text("utf-8"))["files"]
    onnx = next(name for name in cutout if name.endswith(".onnx"))
    request: dict[str, Any] = {
        "protocol": PROTOCOL,
        "model_dir": "/models/animagine-xl-4.0",
        "output_dir": "/unused",
        "prompt": PROMPT,
        "negative_prompt": NEGATIVE,
        "width": 832,
        "height": 1216,
        "steps": 28,
        "guidance": 5.0,
        "seeds": list(range(11, 11 + args.seeds)),
        "cutout": {"model": f"/models/anime-seg/{onnx}", "sha256": cutout[onnx]["sha256"]},
    }
    if args.hires:
        request["hires"] = {"scale": 2.0, "strength": 0.3}
    _relay(url, token, request, args.out)


def voices(url: str, token: str, args: argparse.Namespace) -> None:
    from flint_graph.infrastructure.narrative_voicegen import PROTOCOL

    request = {
        "protocol": PROTOCOL,
        "model_dir": "/models/kokoro-82m",
        "output_dir": "/unused",
        "voice": "af_heart",
        "speed": 1.0,
        "seed": 1,
        "items": [{"text": LINE, "mode": "full"}],
        "device": "cpu",
    }
    _relay(url, token, request, args.out)


def assistant(url: str, token: str, args: argparse.Namespace) -> None:
    model = _config("FLINT_GRAPH_NARRATIVE_ASSISTANT_OLLAMA_MODEL")
    started = time.monotonic()
    for _ in _post(url + "/api/show", token, {"model": model}):
        pass
    print(f"{time.monotonic() - started:7.1f}s  the container answered", flush=True)
    started = time.monotonic()
    first = None
    final: dict[str, Any] = {}
    body = {
        "model": model,
        "stream": True,
        "messages": [{"role": "user", "content": "Write two sentences about a lighthouse."}],
        "options": {"num_predict": args.tokens},
    }
    for raw in _post(url + "/api/chat", token, body):
        if not raw.strip():
            continue
        final = json.loads(raw)
        if first is None:
            first = time.monotonic() - started
            print(f"{first:7.1f}s  first words (model loaded)", flush=True)
    print(f"{time.monotonic() - started:7.1f}s  done", flush=True)
    produced, spent = final.get("eval_count", 0), final.get("eval_duration", 0) / 1e9
    print(f"{produced} tokens in {spent:.1f}s of generation")


def vision(url: str, token: str, args: argparse.Namespace) -> None:
    started = time.monotonic()
    body = {
        "model": _config("FLINT_GRAPH_NARRATIVE_ASSISTANT_VISION_MODEL"),
        "stream": False,
        "keep_alive": 0,
        "messages": [
            {
                "role": "user",
                "content": "Describe this picture in one sentence.",
                "images": [base64.b64encode(args.picture.read_bytes()).decode()],
            }
        ],
    }
    reply = json.loads(b"".join(_post(url + "/api/chat", token, body)))
    print(f"{time.monotonic() - started:7.1f}s  {reply['message']['content'][:160]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("endpoint", help="the Runpod endpoint ID")
    parser.add_argument("kind", choices=["images", "voices", "assistant", "vision"])
    parser.add_argument("--seeds", type=int, default=1)
    parser.add_argument("--hires", action="store_true")
    parser.add_argument("--tokens", type=int, default=80)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--picture", type=Path)
    args = parser.parse_args()
    base = f"https://{args.endpoint}.api.runpod.ai"
    url = f"{base}/{args.kind}" if args.kind in ("images", "voices") else base
    run = {"images": images, "voices": voices, "assistant": assistant, "vision": vision}[args.kind]
    run(url, os.environ["GPU_TOKEN"], args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
