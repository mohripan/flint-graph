"""Explicit app-restart rehearsal; no inference, uploads or corpus mutations."""

from __future__ import annotations

import json
import os
import subprocess
import time

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("FLINT_GRAPH_TELEMETRY_SWITCH_INTEGRATION") != "1",
    reason="explicit local app recreation/restart/rollback opt-in required",
)
APPS = ("ingestion-worker", "outbox-relay", "projection-cleanup", "api")
DATA = ("postgres", "minio", "neo4j", "opensearch", "temporal")
ENDPOINT = "FLINT_GRAPH_OTEL_EXPORTER_OTLP_ENDPOINT"


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=180, check=False)
    if result.returncode:
        raise AssertionError(
            "Owned rehearsal command failed; no captured environment output exposed"
        )
    return result.stdout


def inspect(services):
    identifiers = command("docker", "compose", "ps", "--all", "-q", *services).split()
    if len(identifiers) != len(services):
        raise AssertionError("Expected single owned containers")
    return {
        item["Config"]["Labels"]["com.docker.compose.service"]: item
        for item in json.loads(command("docker", "inspect", *identifiers))
    }


def environment(item):
    return dict(value.split("=", 1) for value in item["Config"]["Env"])


def check_apps(before, endpoint):
    current = inspect(APPS)
    for service in APPS:
        expected = environment(before[service])
        expected[ENDPOINT] = endpoint
        if environment(current[service]) != expected:
            raise AssertionError("App environment changed outside OTLP endpoint")
        if current[service]["Image"] != before[service]["Image"]:
            raise AssertionError("App immutable image changed")
        for key in ("Cmd", "Entrypoint", "WorkingDir", "User"):
            if current[service]["Config"][key] != before[service]["Config"][key]:
                raise AssertionError("App process configuration changed")
    return current


def wait_api(client):
    deadline = time.monotonic() + 60
    while True:
        try:
            live = client.get("http://127.0.0.1:8000/health/live")
            ready = client.get("http://127.0.0.1:8000/health/ready")
            if live.status_code == ready.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() >= deadline:
            raise AssertionError("API did not recover after owned process recreation")
        time.sleep(0.2)


def system_readiness(client, workspace):
    response = client.get(
        "http://127.0.0.1:8000/v1/system-readiness", headers={"X-Tenant-ID": workspace}
    )
    response.raise_for_status()
    report = response.json()
    return {key: report[key] for key in ("embedding", "query", "search_readiness")}


def test_owned_app_combined_transition_clean_restart_and_base_rollback_preserve_configuration():
    workspace = os.environ["FLINT_GRAPH_TELEMETRY_VERIFY_WORKSPACE"]
    before = inspect(APPS)
    data = inspect(DATA)
    if any(
        environment(item).get(ENDPOINT) != "http://observability:4317" for item in before.values()
    ):
        raise AssertionError("Rehearsal requires all apps to start in base mode")
    with httpx.Client(timeout=3, trust_env=False) as client:
        wait_api(client)
        readiness = system_readiness(client, workspace)
        try:
            switched = json.loads(
                command("uv", "run", "flint-graph-telemetry", "--mode", "combined", "--apply")
            )
            assert switched["applied"] is True
            wait_api(client)
            combined = check_apps(before, "http://otel-gateway:4317")
            # Clean process restart uses the exact already-qualified owned IDs.
            command("docker", "restart", *(combined[name]["Id"] for name in APPS))
            wait_api(client)
            check_apps(before, "http://otel-gateway:4317")
            if system_readiness(client, workspace) != readiness:
                raise AssertionError("Public workspace index/readiness/model configuration changed")
        finally:
            command("uv", "run", "flint-graph-telemetry", "--mode", "base", "--apply")
            wait_api(client)
        check_apps(before, "http://observability:4317")
        if system_readiness(client, workspace) != readiness:
            raise AssertionError("Public workspace metadata changed after rollback")
        if {name: item["Id"] for name, item in inspect(DATA).items()} != {
            name: item["Id"] for name, item in data.items()
        }:
            raise AssertionError("Unrelated data service was recreated")
        assert client.get("http://127.0.0.1:5173").status_code == 200
    print(
        json.dumps(
            {
                "status": "passed",
                "combined_switch": True,
                "clean_restart": True,
                "base_rollback": True,
                "per_process_settings_preserved": True,
                "data_containers_unchanged": True,
                "public_readiness_unchanged": True,
            }
        )
    )
