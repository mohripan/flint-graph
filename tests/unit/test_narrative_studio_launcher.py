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


def test_pose_service_is_explicitly_selected_and_isolated():
    assert "pose" not in studio.plan(config())
    chosen = studio.plan(config(STUDIO_SERVICES="api,image,pose"))
    assert chosen["pose"].argv[1:] == ["-m", "flint_graph.processes.narrative_pose_worker"]
    flag = "FLINT_GRAPH_NARRATIVE_POSE_WORKER_ENABLED"
    assert chosen["pose"].env[flag] == "true"
    assert chosen["image"].env[flag] == chosen["api"].env[flag] == "false"


def checkout(tmp_path, runtime="0.8.0"):
    """A checkout that has the Godot toolchain, the way this machine does."""
    (tmp_path / "runtimes/godot").mkdir(parents=True)
    (tmp_path / "runtimes/godot/toolchain.json").write_text(
        json.dumps({"runtime_version": runtime})
    )
    godot = tmp_path / studio.GODOT_DIR
    (godot / "engine").mkdir(parents=True)
    (godot / "engine/Godot_v4.7.2-stable_win64.exe").write_bytes(b"engine")
    (godot / "linux").mkdir()
    (godot / "linux/Godot_v4.7.2-stable_linux.x86_64").write_bytes(b"engine")
    (godot / "templates").mkdir()
    return tmp_path


def preview_report(folder, port=5173, runtime="0.8.0"):
    folder.mkdir(parents=True)
    report = {"parent_origin": f"http://localhost:{port}", "runtime": runtime}
    (folder / "preview-build.json").write_text(json.dumps(report))


def finished(code=0, out="", err=""):
    return studio.subprocess.CompletedProcess([], code, out, err)


def test_a_current_playtest_build_is_left_alone(tmp_path):
    root = checkout(tmp_path)
    preview_report(root / "notes/preview")
    current = studio.StudioConfig.from_values(BASE, root)

    def forbidden(*_, **__):
        raise AssertionError("nothing should be built")

    assert studio.refreshed_preview(current, root, forbidden) is current


def test_a_stale_playtest_is_rebuilt_once_and_then_reused(tmp_path):
    root = checkout(tmp_path)
    preview_report(root / "notes/preview", runtime="0.7.0")
    stale = studio.StudioConfig.from_values(BASE, root)
    calls = []

    def build(argv, **_):
        calls.append(argv)
        preview_report(Path(argv[argv.index("--output") + 1]))
        return finished()

    first = studio.refreshed_preview(stale, root, build)
    assert first.preview_build != stale.preview_build
    assert first.preview_build.parent == root / studio.BUILDS_DIR
    assert calls[0][calls[0].index("--parent-origin") + 1] == "http://localhost:5173"
    # Nothing rewrites the person's settings file: the next start finds the same build.
    assert studio.refreshed_preview(stale, root, build).preview_build == first.preview_build
    assert len(calls) == 1


def test_a_stale_playtest_without_a_toolchain_explains_itself(tmp_path):
    root = tmp_path
    (root / "runtimes/godot").mkdir(parents=True)
    (root / "runtimes/godot/toolchain.json").write_text(json.dumps({"runtime_version": "0.8.0"}))
    preview_report(root / "notes/preview", runtime="0.7.0")
    stale = studio.StudioConfig.from_values(BASE, root)
    with pytest.raises(studio.StudioError, match=r"build_preview.py"):
        studio.refreshed_preview(stale, root, lambda *_, **__: finished())


def test_a_failed_playtest_build_says_why(tmp_path):
    root = checkout(tmp_path)
    preview_report(root / "notes/preview", runtime="0.7.0")
    stale = studio.StudioConfig.from_values(BASE, root)
    with pytest.raises(studio.StudioError, match="Unqualified toolchain"):
        studio.refreshed_preview(
            stale, root, lambda *_, **__: finished(1, err="Unqualified toolchain: x")
        )


PINS = {
    "FLINT_GRAPH_NARRATIVE_RELEASE_TOOLCHAIN_SHA256": "a" * 64,
    "FLINT_GRAPH_NARRATIVE_RELEASE_BUILDER_IMAGE_DIGEST": "sha256:" + "1" * 64,
}


def test_a_current_builder_is_left_alone(tmp_path):
    root = checkout(tmp_path)
    current = studio.StudioConfig.from_values({**BASE, **PINS}, root)
    calls = []

    def ask(argv, **_):
        calls.append(argv)
        return finished(out="a" * 64 + "\n")

    assert studio.refreshed_builder(current, root, ask) is current
    assert len(calls) == 1 and "--expected-toolchain" in calls[0]


def test_a_stale_builder_is_rebuilt_once_and_pinned_for_this_run(tmp_path):
    root = checkout(tmp_path)
    stale = studio.StudioConfig.from_values({**BASE, **PINS}, root)
    calls = []

    def fake(argv, **_):
        calls.append(argv)
        if "--expected-toolchain" in argv:
            return finished(out="b" * 64)
        if argv[0] == "docker":
            return finished()
        output = Path(argv[argv.index("--output") + 1])
        output.mkdir(parents=True)
        receipt = {"toolchain_sha256": "b" * 64, "image": "sha256:" + "2" * 64}
        (output / "toolchain.json").write_text(json.dumps(receipt))
        return finished()

    fresh = studio.refreshed_builder(stale, root, fake)
    pins = fresh.settings
    assert pins["FLINT_GRAPH_NARRATIVE_RELEASE_TOOLCHAIN_SHA256"] == "b" * 64
    assert pins["FLINT_GRAPH_NARRATIVE_RELEASE_BUILDER_IMAGE_DIGEST"] == "sha256:" + "2" * 64
    assert "--build" in calls[1]
    # The next start reuses that image instead of building another.
    again = studio.refreshed_builder(stale, root, fake)
    assert again.settings == pins
    assert sum("--build" in call for call in calls) == 1


def test_a_failed_builder_warns_and_leaves_the_studio_running(tmp_path, capsys):
    root = checkout(tmp_path)
    stale = studio.StudioConfig.from_values({**BASE, **PINS}, root)

    def fake(argv, **_):
        if "--expected-toolchain" in argv:
            return finished(out="b" * 64)
        return finished(1, err="Image preparation failed; context retained")

    assert studio.refreshed_builder(stale, root, fake) is stale
    assert "releases will fail" in capsys.readouterr().out


def test_a_studio_without_releases_never_touches_the_builder(tmp_path):
    root = checkout(tmp_path)
    no_pins = studio.StudioConfig.from_values(BASE, root)

    def forbidden(*_, **__):
        raise AssertionError("no builder is configured")

    assert studio.refreshed_builder(no_pins, root, forbidden) is no_pins


def test_the_real_expected_toolchain_is_stable_and_never_needs_the_engine():
    tool = str(ROOT / "tools/narrative/prepare_builder.py")
    runs = [
        studio.subprocess.run(
            [sys.executable, tool, "--expected-toolchain"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        for _ in range(2)
    ]
    assert runs[0].returncode == 0, runs[0].stderr
    assert len(runs[0].stdout.strip()) == 64
    assert runs[0].stdout == runs[1].stdout
