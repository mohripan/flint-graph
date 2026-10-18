"""CLI seam with Docker as the external boundary; never a real service mutation."""

import copy
import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def docker(monkeypatch):
    root = str(Path.cwd())
    apps = ("api", "ingestion-worker", "outbox-relay", "projection-cleanup")
    containers = {}
    for index, service in enumerate((*apps, "observability", "otel-gateway", "phoenix", "jaeger")):
        containers[service] = {
            "Id": service + "-old",
            "Image": "sha256:" + str(index) * 64,
            "Config": {
                "Labels": {
                    "com.docker.compose.project": "flint-graph",
                    "com.docker.compose.service": service,
                    "com.docker.compose.project.working_dir": root,
                },
                "Env": [
                    "FLINT_GRAPH_ENV=local",
                    "FLINT_GRAPH_OTEL_ENABLED=true",
                    "FLINT_GRAPH_OTEL_EXPORTER_OTLP_ENDPOINT=http://observability:4317",
                    f"FLINT_GRAPH_QUERY_ANSWER_MODEL=preserved-{index}",
                    "FLINT_GRAPH_ANTHROPIC_API_KEY=never-print-$credential=value",
                ],
                "Cmd": [
                    "--config=/etc/otelcol/config.yml",
                    "--config=/etc/otelcol/jaeger-exporter.yml",
                    "--config=/etc/otelcol/jaeger-phoenix.yml",
                ]
                if service == "otel-gateway"
                else ["owned-command", service],
                "Entrypoint": None,
                "WorkingDir": "/app",
                "User": "10001",
            },
            "State": {"Running": True, "Paused": False, "Health": {"Status": "healthy"}},
            "Mounts": [],
            "HostConfig": {
                "NetworkMode": "flint-graph_default",
                "PortBindings": {"8000/tcp": [{"HostIp": "", "HostPort": "8000"}]}
                if service == "api"
                else {},
            },
            "NetworkSettings": {"Networks": {"flint-graph_default": {}}},
        }
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if args[1] == "context":
            return subprocess.CompletedProcess(
                args, 0, '"npipe:////./pipe/dockerDesktopLinuxEngine"', ""
            )
        if args[1] == "inspect":
            selected = [
                next(c for c in containers.values() if c["Id"] == value) for value in args[2:]
            ]
            return subprocess.CompletedProcess(args, 0, json.dumps(selected), "")
        if "ps" in args:
            selected = args[args.index("-q") + 1 :]
            if "jaeger" in selected:
                assert "compose.jaeger.yaml" in args
            if "phoenix" in selected:
                assert "compose.ai-observability.yaml" in args
            return subprocess.CompletedProcess(
                args, 0, "\n".join(containers[s]["Id"] for s in selected), ""
            )
        if "config" in args:
            overrides = json.loads(kwargs["input"].replace("$$", "$"))["services"]
            # Native `compose config` re-escapes dollars for reusable output.
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"services": overrides}).replace("$", "$$"), ""
            )
        assert "up" in args and "--no-deps" in args and "--no-build" in args
        override = json.loads(kwargs["input"].replace("$$", "$"))["services"]
        service = args[-1]
        assert set(override) == {service}
        replacement = override[service]
        target = containers[service]
        assert replacement["image"] == target["Image"]
        assert replacement["command"] == target["Config"]["Cmd"]
        target["Config"]["Env"] = [
            f"{key}={value}" for key, value in replacement["environment"].items()
        ]
        target["Id"] = service + "-new"
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    return containers, calls


def test_preview_is_read_only_and_does_not_print_environment(docker, capsys):
    from flint_graph.cli.telemetry import main

    assert main(["--mode", "combined"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["applied"] is False
    assert "never-print" not in output and "$credential" not in output
    assert not any("up" in args for args, _ in docker[1])


def test_apply_preserves_each_image_and_environment_except_endpoint(docker, capsys):
    from flint_graph.cli.telemetry import main

    before = copy.deepcopy(docker[0])
    assert main(["--mode", "combined", "--apply"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["applied"] is True
    assert "never-print" not in output
    changes = [(args, kwargs) for args, kwargs in docker[1] if "up" in args]
    assert [args[-1] for args, _ in changes] == [
        "ingestion-worker",
        "outbox-relay",
        "projection-cleanup",
        "api",
    ]
    for args, _ in changes:
        service = args[-1]
        prior = dict(value.split("=", 1) for value in before[service]["Config"]["Env"])
        current = dict(value.split("=", 1) for value in docker[0][service]["Config"]["Env"])
        prior["FLINT_GRAPH_OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://otel-gateway:4317"
        assert current == prior
        assert docker[0][service]["Image"] == before[service]["Image"]


@pytest.mark.parametrize("bad", ["production", "staging"])
def test_apply_rejects_nonlocal_services_before_any_mutation(docker, bad, capsys):
    from flint_graph.cli.telemetry import main

    docker[0]["api"]["Config"]["Env"][0] = f"FLINT_GRAPH_ENV={bad}"
    assert main(["--mode", "combined", "--apply"]) == 1
    assert not any("up" in args for args, _ in docker[1])
    assert "never-print" not in capsys.readouterr().err


def test_apply_rejects_custom_mounts_and_wrong_gateway_mode(docker):
    from flint_graph.cli.telemetry import main

    docker[0]["api"]["Mounts"] = [{"Source": "/owned/custom"}]
    assert main(["--mode", "combined", "--apply"]) == 1
    docker[0]["api"]["Mounts"] = []
    docker[0]["otel-gateway"]["Config"]["Cmd"] = ["--config=/etc/otelcol/config.yml"]
    assert main(["--mode", "combined", "--apply"]) == 1
    assert not any("up" in args for args, _ in docker[1])


def test_ambient_compose_environment_drift_is_rejected_before_recreation(docker, monkeypatch):
    from flint_graph.cli.telemetry import main

    boundary = subprocess.run

    def changed_defaults(args, **kwargs):
        result = boundary(args, **kwargs)
        if "config" in args:
            document = json.loads(result.stdout)
            document["services"]["api"]["environment"]["NEW_DEFAULT"] = "not-in-snapshot"
            result.stdout = json.dumps(document)
        return result

    monkeypatch.setattr(subprocess, "run", changed_defaults)
    assert main(["--mode", "combined", "--apply"]) == 1
    assert not any("up" in args for args, _ in docker[1])


@pytest.mark.parametrize(
    "field,value", [("ExtraHosts", ["custom:127.0.0.1"]), ("Memory", 1000000), ("Privileged", True)]
)
def test_unsupported_custom_host_configuration_is_rejected_before_mutation(docker, field, value):
    from flint_graph.cli.telemetry import main

    docker[0]["api"]["HostConfig"][field] = value
    assert main(["--mode", "combined", "--apply"]) == 1
    assert not any("up" in args for args, _ in docker[1])


@pytest.mark.parametrize("mode", ["base", "phoenix", "jaeger"])
def test_fixed_modes_preserve_literal_dollars_and_do_not_use_ambient_gateway_selection(
    docker, mode
):
    from flint_graph.cli.telemetry import main

    docker[0]["api"]["Config"]["Cmd"].append("literal-$not-an-env-$$argument")
    if mode == "phoenix":
        docker[0]["otel-gateway"]["Config"]["Cmd"] = ["--config=/etc/otelcol/config.yml"]
    elif mode == "jaeger":
        docker[0]["otel-gateway"]["Config"]["Cmd"][-1] = "--config=/etc/otelcol/jaeger-only.yml"
    assert main(["--mode", mode, "--apply"]) == 0


def test_partial_docker_failure_is_explicit_and_does_not_leak_stderr(docker, monkeypatch, capsys):
    from flint_graph.cli.telemetry import main

    boundary = subprocess.run

    def fail_relay(args, **kwargs):
        if "up" in args and args[-1] == "outbox-relay":
            return subprocess.CompletedProcess(args, 1, "", "SECRET-from-docker-stderr")
        return boundary(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fail_relay)
    assert main(["--mode", "combined", "--apply"]) == 1
    output = capsys.readouterr()
    assert "SECRET" not in output.err + output.out
    error = json.loads(output.err)
    assert error["completed_services"] == ["ingestion-worker"]
    assert error["phase"] == "apply:outbox-relay"
    assert "No automatic rollback" in error["recovery"]


def test_concurrent_app_replacement_invalidates_snapshot_before_any_apply(docker, monkeypatch):
    from flint_graph.cli.telemetry import main

    boundary = subprocess.run

    def concurrent_change(args, **kwargs):
        result = boundary(args, **kwargs)
        if "config" in args:
            docker[0]["api"]["Id"] = "api-replaced-by-another-operator"
        return result

    monkeypatch.setattr(subprocess, "run", concurrent_change)
    assert main(["--mode", "combined", "--apply"]) == 1
    assert not any("up" in args for args, _ in docker[1])


def test_remote_docker_context_is_rejected_before_any_apply(docker, monkeypatch):
    from flint_graph.cli.telemetry import main

    boundary = subprocess.run

    def remote_context(args, **kwargs):
        if args[1] == "context":
            return subprocess.CompletedProcess(args, 0, '"ssh://remote.example"', "")
        return boundary(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", remote_context)
    assert main(["--mode", "combined", "--apply"]) == 1
    assert not any("up" in args for args, _ in docker[1])


def test_secondary_custom_network_is_rejected_before_recreation(docker):
    from flint_graph.cli.telemetry import main

    docker[0]["api"]["NetworkSettings"]["Networks"]["extra-operator-network"] = {}
    assert main(["--mode", "combined", "--apply"]) == 1
    assert not any("up" in args for args, _ in docker[1])
