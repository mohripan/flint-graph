"""Local app-only OTLP switching without ambient Compose model defaults.

Docker inspection/environment values stay in memory and are never printed or
written to files. Telemetry backends must already be explicitly started.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

SERVICES = ("ingestion-worker", "outbox-relay", "projection-cleanup", "api")
ENDPOINT = "FLINT_GRAPH_OTEL_EXPORTER_OTLP_ENDPOINT"
MODES = {
    "base": ([], []),
    "phoenix": (["compose.ai-observability.yaml"], ["ai-observability"]),
    "jaeger": (["compose.jaeger.yaml", "compose.jaeger-gateway.yaml"], ["jaeger"]),
    "combined": (
        ["compose.ai-observability.yaml", "compose.jaeger.yaml", "compose.jaeger-gateway.yaml"],
        ["ai-observability", "jaeger"],
    ),
}


def _docker(args: list[str], *, data: str | None = None) -> str:
    result = subprocess.run(
        ["docker", *args],
        input=data,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode:
        # Docker errors can include interpolated environment; never echo them.
        raise ValueError("Docker operation failed; inspect local service state separately")
    return result.stdout


def _environment(container: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for value in container["Config"]["Env"]:
        key, separator, content = value.partition("=")
        if not separator or key in values:
            raise ValueError("Unsupported container environment")
        values[key] = content
    return values


def _inspect(compose: list[str], services: Sequence[str]) -> dict[str, dict[str, Any]]:
    identifiers = _docker([*compose, "ps", "--all", "-q", *services]).split()
    if len(identifiers) != len(services) or len(set(identifiers)) != len(services):
        raise ValueError("Expected exactly one existing container for every selected service")
    inspected = json.loads(_docker(["inspect", *identifiers]))
    result = {item["Config"]["Labels"]["com.docker.compose.service"]: item for item in inspected}
    if set(result) != set(services):
        raise ValueError("Container ownership did not match selected services")
    return result


def _owned_running(container: dict[str, Any], root: Path, project: str) -> None:
    labels = container["Config"]["Labels"]
    if (
        labels["com.docker.compose.project"] != project
        or Path(labels["com.docker.compose.project.working_dir"]).resolve() != root
        or not container["State"]["Running"]
        or container["State"].get("Paused", False)
    ):
        raise ValueError("Expected running, unpaused containers owned by this local project")


def _standard_app(container: dict[str, Any], service: str) -> None:
    host = container["HostConfig"]
    unsupported = (
        "ExtraHosts",
        "Memory",
        "MemoryReservation",
        "MemorySwap",
        "NanoCpus",
        "CpuQuota",
        "CpuPeriod",
        "CpuShares",
        "CpusetCpus",
        "CpusetMems",
        "Privileged",
        "ReadonlyRootfs",
        "CapAdd",
        "CapDrop",
        "SecurityOpt",
        "Devices",
        "DeviceRequests",
        "Tmpfs",
        "Ulimits",
        "Binds",
        "VolumesFrom",
    )
    if any(host.get(key) for key in unsupported) or host.get("PidsLimit") not in (None, 0, -1):
        raise ValueError("Custom app host configuration is unsupported; no services changed")
    if host["NetworkMode"] != "flint-graph_default" or set(
        container["NetworkSettings"]["Networks"]
    ) != {"flint-graph_default"}:
        raise ValueError("Custom app network is unsupported; no services changed")
    expected_ports = {"8000/tcp": [{"HostIp": "", "HostPort": "8000"}]} if service == "api" else {}
    if (host.get("PortBindings") or {}) != expected_ports:
        raise ValueError("Custom app port binding is unsupported; no services changed")
    policy = host.get("RestartPolicy", {})
    if policy.get("Name", "") not in ("", "no") or policy.get("MaximumRetryCount", 0):
        raise ValueError("Custom restart policy is unsupported; no services changed")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--apply", action="store_true", help="recreate only the four app services")
    options = parser.parse_args(argv)
    changed: list[str] = []
    phase = "preflight"
    try:
        endpoint_override = os.environ.get("DOCKER_HOST")
        if endpoint_override and not endpoint_override.startswith(
            ("unix:///", "npipe:////./pipe/")
        ):
            raise ValueError("Remote Docker endpoints are unsupported")
        docker_host = json.loads(
            _docker(
                [
                    "context",
                    "inspect",
                    "--format",
                    "{{json .Endpoints.docker.Host}}",
                ]
            )
        )
        if not isinstance(docker_host, str) or not docker_host.startswith(
            ("unix:///", "npipe:////./pipe/")
        ):
            raise ValueError("Only local Unix sockets or local Windows named pipes are supported")
        root = Path.cwd().resolve()
        if not (root / "compose.yaml").is_file():
            raise ValueError("Run from the FlintGraph repository root")
        project = "flint-graph"
        compose = [
            "compose",
            "--project-name",
            project,
            "--project-directory",
            str(root),
            "-f",
            "compose.yaml",
        ]
        files, profiles = MODES[options.mode]
        selected = list(compose)
        for file in files:
            selected += ["-f", file]
        for profile in profiles:
            selected += ["--profile", profile]
        before = _inspect(compose, SERVICES)
        for service, container in before.items():
            _owned_running(container, root, project)
            _standard_app(container, service)
            environment = _environment(container)
            if environment.get("FLINT_GRAPH_ENV") != "local":
                raise ValueError("Only explicit local environments may use this helper")
            if environment.get("FLINT_GRAPH_OTEL_ENABLED", "").lower() != "true":
                raise ValueError("Tracing must already be explicitly enabled")
            if container["Mounts"]:
                raise ValueError("Custom app mounts are unsupported; no services changed")

        required = ["observability"]
        if options.mode != "base":
            required.append("otel-gateway")
        if options.mode in {"phoenix", "combined"}:
            required.append("phoenix")
        if options.mode in {"jaeger", "combined"}:
            required.append("jaeger")
        backends = _inspect(selected, required)
        for name, container in backends.items():
            _owned_running(container, root, project)
            if (
                name != "otel-gateway"
                and container["State"].get("Health", {}).get("Status") != "healthy"
            ):
                raise ValueError("Selected telemetry backend is not healthy")
        if options.mode != "base":
            command = ["--config=/etc/otelcol/config.yml"]
            if options.mode in {"jaeger", "combined"}:
                mode = "jaeger-only" if options.mode == "jaeger" else "jaeger-phoenix"
                command += [
                    "--config=/etc/otelcol/jaeger-exporter.yml",
                    f"--config=/etc/otelcol/{mode}.yml",
                ]
            if backends["otel-gateway"]["Config"]["Cmd"] != command:
                raise ValueError("Start the selected gateway configuration before switching apps")

        target = (
            "http://observability:4317" if options.mode == "base" else "http://otel-gateway:4317"
        )
        selected += ["-f", "-"]
        overrides = {}
        expected_environments = {}
        for service in SERVICES:
            old = before[service]
            environment = _environment(old)
            environment[ENDPOINT] = target
            overrides[service] = {
                "image": old["Image"],
                "command": old["Config"]["Cmd"],
                "entrypoint": old["Config"]["Entrypoint"],
                "working_dir": old["Config"]["WorkingDir"],
                "user": old["Config"]["User"],
                "environment": environment,
            }
            expected_environments[service] = environment
        # Render all four first: an ambient default must fail before any app changes.
        # `compose config` re-escapes every dollar for reusable output. Undo
        # exactly that serialization layer before comparing actual values.
        phase = "render"
        rendered = json.loads(
            _docker(
                [*selected, "config", "--format", "json"],
                data=json.dumps({"services": overrides}).replace("$", "$$"),
            ).replace("$$", "$")
        )["services"]
        for service in SERVICES:
            if rendered[service]["environment"] != expected_environments[service]:
                raise ValueError("Compose environment drift; no services changed")
            for key in ("image", "command", "entrypoint", "working_dir", "user"):
                if rendered[service].get(key) != overrides[service][key]:
                    raise ValueError("Compose process configuration drift; no services changed")
        if options.apply:
            refreshed = _inspect(compose, SERVICES)
            if any(refreshed[name]["Id"] != before[name]["Id"] for name in SERVICES):
                raise ValueError(
                    "Application snapshot changed during preflight; no services changed"
                )
        for service in SERVICES:
            old = before[service]
            environment = expected_environments[service]
            if options.apply:
                phase = f"apply:{service}"
                if _inspect(compose, [service])[service]["Id"] != old["Id"]:
                    raise ValueError("Application snapshot changed before recreation")
                _docker(
                    [*selected, "up", "-d", "--no-deps", "--no-build", "--pull", "never", service],
                    # Compose interpolates command arguments too. Escape once.
                    data=json.dumps({"services": {service: overrides[service]}}).replace("$", "$$"),
                )
                changed.append(service)
                phase = f"verify:{service}"
                current = _inspect(compose, [service])[service]
                _owned_running(current, root, project)
                if current["Image"] != old["Image"] or _environment(current) != environment:
                    raise ValueError(
                        "Image/environment postcondition failed; stop rollout and inspect"
                    )
                for key in ("Cmd", "Entrypoint", "WorkingDir", "User"):
                    if current["Config"][key] != old["Config"][key]:
                        raise ValueError("Process configuration postcondition failed")
                if current["Mounts"] != old["Mounts"]:
                    raise ValueError("App mount postcondition failed")
        print(
            json.dumps(
                {
                    "mode": options.mode,
                    "applied": options.apply,
                    "services": list(SERVICES),
                    "target_endpoint": target,
                    "images_and_environment_preserved": bool(options.apply),
                }
            )
        )
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        print(
            json.dumps(
                {
                    "error": "Local telemetry preflight/switch failed",
                    "phase": phase,
                    "completed_services": changed,
                    "recovery": (
                        "Services may be mixed after apply. Inspect state; prepare the prior "
                        "telemetry mode, preview it, then explicitly apply it. "
                        "No automatic rollback."
                    ),
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
