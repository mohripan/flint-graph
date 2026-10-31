"""Start the whole local narrative Studio with one command.

    uv run python tools/narrative/studio.py           # start everything, Ctrl+C stops it
    uv run python tools/narrative/studio.py check     # preflight only

Configuration is a git-ignored ``studio.local.env`` at the repository root (copy
``tools/narrative/studio.env.example``). ``FLINT_GRAPH_*`` lines are the app's own
settings and go to the API and workers; ``STUDIO_*`` lines configure this launcher.

Before starting anything it starts the listed Docker containers, waits for
PostgreSQL, the object store, Temporal and Ollama, checks that the ports are free and
that the playtest build matches the frontend and the Godot runtime, and applies the
database migrations. It then runs the API, the build, relay, assistant and image
workers, the playtest server and the frontend, prefixes their output, and stops all
of them on Ctrl+C or when one fails to start. Settings values are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "studio.local.env"
SERVICES = ("api", "worker", "relay", "assistant", "image", "preview", "frontend")
WORKERS = {
    "worker": ("FLINT_GRAPH_NARRATIVE_WORKER_ENABLED", "narrative_worker"),
    "relay": ("FLINT_GRAPH_NARRATIVE_RELAY_ENABLED", "narrative_relay"),
    "assistant": ("FLINT_GRAPH_NARRATIVE_ASSISTANT_WORKER_ENABLED", "narrative_assistant_worker"),
    "image": ("FLINT_GRAPH_NARRATIVE_IMAGE_WORKER_ENABLED", "narrative_image_worker"),
}
LAUNCHER_KEYS = {
    "STUDIO_API_PORT",
    "STUDIO_PREVIEW_PORT",
    "STUDIO_FRONTEND_PORT",
    "STUDIO_PREVIEW_BUILD",
    "STUDIO_CONTAINERS",
    "STUDIO_SERVICES",
}
_KEY = re.compile(r"[A-Z][A-Z0-9_]*\Z")
READY_SECONDS = 90
WORKER_GRACE_SECONDS = 4


class StudioError(Exception):
    """A configuration or preflight problem, explained for the person starting it."""


def parse_env(path: Path) -> dict[str, str]:
    """``KEY=value`` lines; ``#`` comments and blank lines are skipped."""
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not _KEY.match(key):
            raise StudioError(f"{path.name} line {number}: expected KEY=value")
        if key in values:
            raise StudioError(f"{path.name} line {number}: {key} is set twice")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def _port(values: dict[str, str], key: str, default: int) -> int:
    text = values.get(key, str(default))
    if not text.isdigit() or not 1 <= int(text) <= 65535:
        raise StudioError(f"{key} must be a port number")
    return int(text)


def _names(text: str) -> tuple[str, ...]:
    return tuple(name.strip() for name in text.split(",") if name.strip())


@dataclass(frozen=True)
class StudioConfig:
    settings: dict[str, str]
    services: tuple[str, ...]
    containers: tuple[str, ...]
    api_port: int
    preview_port: int
    frontend_port: int
    preview_build: Path | None

    @classmethod
    def from_values(cls, values: dict[str, str], root: Path = ROOT) -> StudioConfig:
        unknown = sorted(
            key for key in values if not key.startswith("FLINT_GRAPH_") and key not in LAUNCHER_KEYS
        )
        if unknown:
            raise StudioError("Unknown settings: " + ", ".join(unknown))
        chosen = _names(values.get("STUDIO_SERVICES", ",".join(SERVICES)))
        if wrong := [name for name in chosen if name not in SERVICES]:
            raise StudioError(
                f"Unknown services: {', '.join(wrong)} (choose from {', '.join(SERVICES)})"
            )
        services = tuple(name for name in SERVICES if name in chosen)
        ports = (
            _port(values, "STUDIO_API_PORT", 8101),
            _port(values, "STUDIO_PREVIEW_PORT", 5192),
            _port(values, "STUDIO_FRONTEND_PORT", 5173),
        )
        if len(set(ports)) != len(ports):
            raise StudioError("The API, playtest and frontend need different ports")
        settings = {key: value for key, value in values.items() if key.startswith("FLINT_GRAPH_")}
        backend = {"api", *WORKERS}.intersection(services)
        required = ["FLINT_GRAPH_DATABASE_URL"] if backend else []
        if set(WORKERS).intersection(services):
            required.append("FLINT_GRAPH_TEMPORAL_ADDRESS")
        if "preview" in services:
            required.append("STUDIO_PREVIEW_BUILD")
        if missing := [key for key in required if not values.get(key)]:
            raise StudioError("Set " + ", ".join(missing) + " in studio.local.env")
        build = values.get("STUDIO_PREVIEW_BUILD")
        return cls(
            settings=settings,
            services=services,
            containers=_names(values.get("STUDIO_CONTAINERS", "")),
            api_port=ports[0],
            preview_port=ports[1],
            frontend_port=ports[2],
            preview_build=(root / build).resolve() if build else None,
        )


@dataclass(frozen=True)
class Service:
    name: str
    argv: list[str]
    cwd: Path
    env: dict[str, str]
    # An HTTP URL that answers once the service is up; None means "still running".
    ready: str | None


def _base_env() -> dict[str, str]:
    # The parent environment minus any app settings, so only the config file counts.
    env = {key: value for key, value in os.environ.items() if not key.startswith("FLINT_GRAPH_")}
    env["NO_PROXY"] = "localhost,127.0.0.1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def plan(config: StudioConfig) -> dict[str, Service]:
    """What to run for each chosen service, in start order."""
    python = sys.executable
    backend = {
        **_base_env(),
        **config.settings,
        **{flag: "false" for flag, _ in WORKERS.values()},
    }
    services: dict[str, Service] = {}
    for name in config.services:
        if name == "api":
            argv = [python, "-m", "uvicorn", "flint_graph.main:app", "--host", "127.0.0.1"]
            argv += ["--port", str(config.api_port), "--log-level", "warning"]
            ready = f"http://127.0.0.1:{config.api_port}/health/live"
            services[name] = Service(name, argv, ROOT, backend, ready)
        elif name in WORKERS:
            flag, module = WORKERS[name]
            argv = [python, "-m", f"flint_graph.processes.{module}"]
            services[name] = Service(name, argv, ROOT, {**backend, flag: "true"}, None)
        elif name == "preview":
            assert config.preview_build is not None
            argv = [python, str(ROOT / "tools/narrative/serve_preview.py")]
            argv += ["--build", str(config.preview_build), "--port", str(config.preview_port)]
            ready = f"http://127.0.0.1:{config.preview_port}/index.html"
            services[name] = Service(name, argv, ROOT, _base_env(), ready)
        else:
            npm = shutil.which("npm") or "npm"
            argv = [npm, "run", "dev", "--", "--port", str(config.frontend_port), "--strictPort"]
            env = {
                **_base_env(),
                "FLINT_GRAPH_API_TARGET": f"http://127.0.0.1:{config.api_port}",
                "VITE_FLINT_GRAPH_PREVIEW_ORIGIN": f"http://127.0.0.1:{config.preview_port}",
            }
            ready = f"http://localhost:{config.frontend_port}/"
            services[name] = Service(name, argv, ROOT / "frontend", env, ready)
    return services


def _host_port(url: str, default: int) -> tuple[str, int]:
    parts = urlsplit(url if "//" in url else "//" + url)
    return parts.hostname or "127.0.0.1", parts.port or default


def endpoints(config: StudioConfig) -> list[tuple[str, str, int]]:
    """Dependencies to wait for, given the chosen services."""
    chosen = set(config.services)
    settings = config.settings
    found: list[tuple[str, str, int]] = []
    if chosen & {"api", *WORKERS}:
        found.append(("PostgreSQL", *_host_port(settings["FLINT_GRAPH_DATABASE_URL"], 5432)))
        if store := settings.get("FLINT_GRAPH_OBJECT_STORE_ENDPOINT_URL"):
            found.append(("object store", *_host_port(store, 9000)))
    if chosen & set(WORKERS):
        found.append(("Temporal", *_host_port(settings["FLINT_GRAPH_TEMPORAL_ADDRESS"], 7233)))
    if chosen & {"assistant", "image"}:
        ollama = settings.get("FLINT_GRAPH_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        found.append(("Ollama", *_host_port(ollama, 11434)))
    return found


def preview_problem(build: Path, frontend_port: int, runtime: str) -> str | None:
    """Why the playtest build cannot serve this Studio, or None."""
    rebuild = (
        "build one with tools/narrative/build_preview.py "
        f"--parent-origin http://localhost:{frontend_port} (see docs/runbooks/narrative-studio.md)"
    )
    try:
        report = json.loads((build / "preview-build.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"No playtest build at {build}; {rebuild}"
    if report.get("parent_origin") != f"http://localhost:{frontend_port}":
        return f"The playtest build is for {report.get('parent_origin')}; {rebuild}"
    if report.get("runtime") != runtime:
        return (
            f"The playtest build has runtime {report.get('runtime')} but the Godot runtime "
            f"is now {runtime}; {rebuild}"
        )
    return None


def _reachable(host: str, port: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            if time.monotonic() > deadline:
                return False
            time.sleep(0.5)


def _port_free(port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) != 0


def _start_containers(names: Sequence[str]) -> None:
    if not names:
        return
    if not shutil.which("docker"):
        raise StudioError("Docker is not on PATH; start Docker Desktop first")
    info = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=60)
    if info.returncode != 0:
        raise StudioError("Docker is not running; start Docker Desktop first")
    for name in names:
        state = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if state.returncode != 0:
            raise StudioError(f"Docker container {name} does not exist")
        if state.stdout.strip() != "true":
            print(f"[studio] starting container {name}", flush=True)
            started = subprocess.run(["docker", "start", name], capture_output=True, timeout=120)
            if started.returncode != 0:
                raise StudioError(f"Docker could not start {name}")


def preflight(config: StudioConfig) -> None:
    _start_containers(config.containers)
    for label, host, port in endpoints(config):
        if not _reachable(host, port, 30):
            hint = " (is the Ollama app running?)" if label == "Ollama" else ""
            raise StudioError(f"{label} is not reachable at {host}:{port}{hint}")
        print(f"[studio] {label} is up", flush=True)
    ports = {
        "api": config.api_port,
        "preview": config.preview_port,
        "frontend": config.frontend_port,
    }
    for name, port in ports.items():
        if name in config.services and not _port_free(port):
            raise StudioError(f"Port {port} for {name} is in use; is the Studio already running?")
    if "preview" in config.services:
        assert config.preview_build is not None
        toolchain = json.loads((ROOT / "runtimes/godot/toolchain.json").read_text("utf-8"))
        problem = preview_problem(
            config.preview_build, config.frontend_port, toolchain["runtime_version"]
        )
        if problem:
            raise StudioError(problem)
    if "frontend" in config.services and not (ROOT / "frontend/node_modules").is_dir():
        raise StudioError("Frontend packages are missing; run npm ci in frontend first")
    if "worker" in config.services:
        root = config.settings.get("FLINT_GRAPH_NARRATIVE_BUILD_WORK_ROOT")
        if root:
            (ROOT / root).mkdir(parents=True, exist_ok=True)


def migrate(config: StudioConfig) -> None:
    env = {**_base_env(), **config.settings}
    print("[studio] applying database migrations", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        # Alembic's own output can include the connection URL; show only its last line.
        last = (result.stderr or result.stdout).strip().splitlines()[-1:]
        raise StudioError("Migrations failed: " + (last[0] if last else "no output"))


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        # npm and Vite run as a tree; end all of it.
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, timeout=30
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()


def say(text: str) -> None:
    """Print, replacing what this console cannot encode (Vite prints arrows and colours)."""
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(encoding, "replace").decode(encoding), flush=True)


def _relay(name: str, process: subprocess.Popen[bytes]) -> None:
    # Keep reading even if printing fails, or a full pipe would stall the child.
    assert process.stdout is not None
    for raw in process.stdout:
        line = raw.decode("utf-8", "replace").rstrip()
        if line:
            try:
                say(f"[{name}] {line}")
            except (OSError, ValueError):
                pass


def _answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            status: int = response.status
            return 200 <= status < 500
    except urllib.error.HTTPError as error:
        return error.code < 500
    except OSError:
        return False


def _wait_ready(name: str, service: Service, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + (READY_SECONDS if service.ready else WORKER_GRACE_SECONDS)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise StudioError(f"{name} exited while starting; see its output above")
        if service.ready and _answers(service.ready):
            return
        time.sleep(0.5)
    if service.ready:
        raise StudioError(f"{name} did not answer at {service.ready}")


def waves(names: Sequence[str]) -> list[list[str]]:
    """Start order: the frontend last, once the API answers, so an open tab finds it."""
    backend = [name for name in names if name != "frontend"]
    return [wave for wave in (backend, [n for n in names if n == "frontend"]) if wave]


def run(config: StudioConfig) -> int:
    services = plan(config)
    running: dict[str, subprocess.Popen[bytes]] = {}
    # On Windows a separate group keeps Ctrl+C from reaching the children before we stop them.
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        for wave in waves(list(services)):
            for name in wave:
                service = services[name]
                print(f"[studio] starting {name}", flush=True)
                process = subprocess.Popen(
                    service.argv,
                    cwd=service.cwd,
                    env=service.env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    creationflags=flags,
                    start_new_session=os.name != "nt",
                )
                running[name] = process
                threading.Thread(target=_relay, args=(name, process), daemon=True).start()
            for name in wave:
                _wait_ready(name, services[name], running[name])
        print("[studio] ready", flush=True)
        if "frontend" in services:
            print(f"[studio] open http://localhost:{config.frontend_port}", flush=True)
        print("[studio] press Ctrl+C to stop everything", flush=True)
        reported: set[str] = set()
        while True:
            for name, process in running.items():
                if process.poll() is not None and name not in reported:
                    reported.add(name)
                    print(f"[studio] {name} stopped (exit {process.returncode})", flush=True)
            if len(reported) == len(running):
                return 1
            time.sleep(1)
    except KeyboardInterrupt:
        print("[studio] stopping", flush=True)
        return 0
    finally:
        for process in reversed(list(running.values())):
            _stop(process)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the local narrative Studio.")
    parser.add_argument("command", nargs="?", choices=("up", "check"), default="up")
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--no-migrate", action="store_true", help="skip alembic upgrade head")
    args = parser.parse_args(argv)
    try:
        if not args.config.is_file():
            raise StudioError(
                f"No {args.config.name}; copy tools/narrative/studio.env.example to "
                f"{args.config} and fill it in"
            )
        config = StudioConfig.from_values(parse_env(args.config))
        preflight(config)
        if args.command == "check":
            print("[studio] everything is ready to start", flush=True)
            return 0
        if not args.no_migrate and {"api", *WORKERS} & set(config.services):
            migrate(config)
        return run(config)
    except StudioError as error:
        print(f"[studio] {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
