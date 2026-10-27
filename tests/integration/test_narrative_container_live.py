"""Opt-in real package smoke in a local immutable image without services/network."""

import json
import os
import subprocess
from pathlib import Path

import pytest

IMAGE = os.environ.get("FLINT_GRAPH_NARRATIVE_CONTAINER_IMAGE")
pytestmark = pytest.mark.skipif(
    not IMAGE, reason="Set FLINT_GRAPH_NARRATIVE_CONTAINER_IMAGE for local image proof"
)
FIXTURE = Path(__file__).parents[1] / "fixtures/narrative/lantern_archive"


def test_real_readonly_image_exports_without_application_services_or_network() -> None:
    context = subprocess.run(
        ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    endpoint = (
        context if os.environ.get("DOCKER_CONTEXT") else os.environ.get("DOCKER_HOST", context)
    )
    if not endpoint.startswith(("unix://", "npipe:////./pipe/")):
        pytest.skip("Native bind-mount smoke requires a local Docker endpoint")
    assert IMAGE
    immutable = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert immutable.startswith("sha256:")
    base = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--mount",
        f"type=bind,source={FIXTURE.resolve()},target=/fixture,readonly",
        immutable,
        "flint-graph-narrative",
    ]
    validated = subprocess.run(
        [*base, "validate", "/fixture"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert validated.returncode == 0, validated.stderr
    assert json.loads(validated.stdout)["package_hash"] == (
        "057e54a191c2a79d35a52a2d3502d749e214058b79214d5e967a9afb894b3850"
    )
    exported = subprocess.run(
        [*base, "export-godot", "/fixture", "--output", "/tmp/source-proof"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert exported.returncode == 0, exported.stderr
    report = json.loads(exported.stdout)
    assert report["godot_version"] == "4.7.2.stable"
    assert report["file_count"] >= 16
