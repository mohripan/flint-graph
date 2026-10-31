"""The local Studio launcher: config parsing, per-service plans and preflight checks."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def launcher():
    spec = importlib.util.spec_from_file_location("studio", ROOT / "tools/narrative/studio.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["studio"] = module
    spec.loader.exec_module(module)
    return module


studio = launcher()

BASE = {
    "FLINT_GRAPH_DATABASE_URL": "postgresql+asyncpg://user:secret@127.0.0.1:55433/narrative",
    "FLINT_GRAPH_OBJECT_STORE_ENDPOINT_URL": "http://127.0.0.1:59000",
    "FLINT_GRAPH_OBJECT_STORE_SECRET_ACCESS_KEY": "store-secret",
    "FLINT_GRAPH_TEMPORAL_ADDRESS": "127.0.0.1:57233",
    "FLINT_GRAPH_OLLAMA_BASE_URL": "http://127.0.0.1:11434",
    "FLINT_GRAPH_NARRATIVE_BUILD_WORK_ROOT": "notes/build-root",
    "STUDIO_PREVIEW_BUILD": "notes/preview",
}


def config(**changes):
    return studio.StudioConfig.from_values({**BASE, **changes}, ROOT)


def test_the_env_file_is_simple_key_value_lines(tmp_path):
    path = tmp_path / "studio.local.env"
    path.write_text(
        "# comment\n\nFLINT_GRAPH_DATABASE_URL=postgresql://a:b@h:1/d?x=1\n"
        'STUDIO_API_PORT = 8101\nFLINT_GRAPH_NARRATIVE_ASSISTANT_OLLAMA_MODEL="gemma:latest"\n',
        encoding="utf-8",
    )
    assert studio.parse_env(path) == {
        "FLINT_GRAPH_DATABASE_URL": "postgresql://a:b@h:1/d?x=1",
        "STUDIO_API_PORT": "8101",
        "FLINT_GRAPH_NARRATIVE_ASSISTANT_OLLAMA_MODEL": "gemma:latest",
    }
    for bad in ("no equals sign\n", "lower=1\n", "A=1\nA=2\n"):
        path.write_text(bad, encoding="utf-8")
        with pytest.raises(studio.StudioError, match="line"):
            studio.parse_env(path)


def test_config_defaults_and_validation():
    plain = config()
    assert (plain.api_port, plain.preview_port, plain.frontend_port) == (8101, 5192, 5173)
    assert plain.services == studio.SERVICES
    assert plain.preview_build == ROOT / "notes/preview"
    assert "STUDIO_PREVIEW_BUILD" not in plain.settings, "Only FLINT_GRAPH_* reaches the app"
    picked = config(STUDIO_SERVICES="api, frontend", STUDIO_CONTAINERS="pg, store")
    assert picked.services == ("api", "frontend") and picked.containers == ("pg", "store")
    for changes, message in (
        ({"STUDIO_SERVICES": "api,web"}, "web"),
        ({"STUDIO_API_PORT": "80x"}, "STUDIO_API_PORT"),
        ({"STUDIO_FRONTEND_PORT": "5192"}, "different ports"),
        ({"STUDIO_TYPO": "1"}, "STUDIO_TYPO"),
        ({"FLINT_GRAPH_DATABASE_URL": ""}, "FLINT_GRAPH_DATABASE_URL"),
        ({"FLINT_GRAPH_TEMPORAL_ADDRESS": ""}, "FLINT_GRAPH_TEMPORAL_ADDRESS"),
        ({"STUDIO_PREVIEW_BUILD": ""}, "STUDIO_PREVIEW_BUILD"),
    ):
        with pytest.raises(studio.StudioError, match=message):
            config(**changes)
    # Temporal and a preview build are only needed by the services that use them.
    assert config(FLINT_GRAPH_TEMPORAL_ADDRESS="", STUDIO_SERVICES="api,frontend").services
    assert config(STUDIO_PREVIEW_BUILD="", STUDIO_SERVICES="api").services


def test_each_service_gets_only_its_own_role():
    plan = studio.plan(config())
    flags = {
        "worker": "FLINT_GRAPH_NARRATIVE_WORKER_ENABLED",
        "relay": "FLINT_GRAPH_NARRATIVE_RELAY_ENABLED",
        "assistant": "FLINT_GRAPH_NARRATIVE_ASSISTANT_WORKER_ENABLED",
        "image": "FLINT_GRAPH_NARRATIVE_IMAGE_WORKER_ENABLED",
        "voice": "FLINT_GRAPH_NARRATIVE_VOICE_WORKER_ENABLED",
    }
    for name in ("api", *flags):
        env = plan[name].env
        assert env["FLINT_GRAPH_DATABASE_URL"] == BASE["FLINT_GRAPH_DATABASE_URL"]
        assert {flag: env[flag] for flag in flags.values()} == {
            flag: str(role == name).lower() for role, flag in flags.items()
        }
    # The browser-facing processes never see the database or store credentials.
    for name in ("preview", "frontend"):
        assert not any(key.startswith("FLINT_GRAPH_") and "SECRET" in key for key in plan[name].env)
        assert "FLINT_GRAPH_DATABASE_URL" not in plan[name].env
    front = plan["frontend"].env
    assert front["FLINT_GRAPH_API_TARGET"] == "http://127.0.0.1:8101"
    assert front["VITE_FLINT_GRAPH_PREVIEW_ORIGIN"] == "http://127.0.0.1:5192"


def test_commands_ports_and_readiness():
    plan = studio.plan(config(STUDIO_API_PORT="8201", STUDIO_FRONTEND_PORT="5273"))
    assert plan["api"].argv[1:] == [
        "-m",
        "uvicorn",
        "flint_graph.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8201",
        "--log-level",
        "warning",
    ]
    assert plan["api"].ready == "http://127.0.0.1:8201/health/live"
    assert plan["worker"].argv[1:] == ["-m", "flint_graph.processes.narrative_worker"]
    assert plan["image"].argv[1:] == ["-m", "flint_graph.processes.narrative_image_worker"]
    assert plan["voice"].argv[1:] == ["-m", "flint_graph.processes.narrative_voice_worker"]
    assert plan["preview"].argv[2:] == [
        "--build",
        str(ROOT / "notes/preview"),
        "--port",
        "5192",
    ]
    assert plan["frontend"].argv[-4:] == ["--", "--port", "5273", "--strictPort"]
    assert plan["frontend"].cwd == ROOT / "frontend"
    assert plan["frontend"].ready == "http://localhost:5273/"
    assert plan["worker"].ready is None, "Workers are ready when they stay up"
    assert list(studio.plan(config(STUDIO_SERVICES="frontend,api"))) == ["api", "frontend"]


def test_endpoints_are_checked_only_for_the_services_that_need_them():
    assert studio.endpoints(config()) == [
        ("PostgreSQL", "127.0.0.1", 55433),
        ("object store", "127.0.0.1", 59000),
        ("Temporal", "127.0.0.1", 57233),
        ("Ollama", "127.0.0.1", 11434),
    ]
    assert studio.endpoints(config(STUDIO_SERVICES="api,frontend")) == [
        ("PostgreSQL", "127.0.0.1", 55433),
        ("object store", "127.0.0.1", 59000),
    ]


def test_preview_builds_must_match_the_frontend_and_the_runtime(tmp_path):
    runtime = json.loads((ROOT / "runtimes/godot/toolchain.json").read_text())["runtime_version"]
    assert "build_preview.py" in studio.preview_problem(tmp_path / "missing", 5173, runtime)
    (tmp_path / "preview-build.json").write_text(
        json.dumps({"parent_origin": "http://localhost:5173", "runtime": runtime}), "utf-8"
    )
    assert studio.preview_problem(tmp_path, 5173, runtime) is None
    assert "http://localhost:5273" in studio.preview_problem(tmp_path, 5273, runtime)
    assert "0.0.1" in studio.preview_problem(tmp_path, 5173, "0.0.1")


def test_output_a_console_cannot_encode_is_replaced_not_fatal(monkeypatch):
    import io

    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", console)
    studio.say("[frontend] ➜  Local: http://localhost:5173/")
    console.flush()
    assert raw.getvalue().startswith(b"[frontend] ?  Local: http://localhost:5173/")


def test_the_frontend_starts_after_everything_else_answers():
    assert studio.waves(list(studio.plan(config()))) == [
        ["api", "worker", "relay", "assistant", "image", "voice", "preview"],
        ["frontend"],
    ]
    assert studio.waves(["frontend"]) == [["frontend"]]
    assert studio.waves(["api", "worker"]) == [["api", "worker"]]
