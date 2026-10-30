"""Opt-in actual pinned Linux image; no default Docker/provider/service fallback."""

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest

from flint_graph.narrative.build_child import WEB_FILES
from flint_graph.narrative.export import TEMPLATE_FILES, export_godot
from flint_graph.narrative.package import load_text_package
from flint_graph.narrative.release_artifacts import (
    make_artifact_zip,
    read_child_files,
    web_pack_has_project_settings,
)


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, encoding="utf-8", timeout=20)


@pytest.mark.parametrize("tampered", [False, True])
def test_real_trusted_child_exports_or_rejects_changed_runtime(tmp_path, monkeypatch, tampered):
    image = os.environ.get("FLINT_GRAPH_NARRATIVE_BUILDER_IMAGE")
    pin = os.environ.get("FLINT_GRAPH_NARRATIVE_BUILDER_TOOLCHAIN")
    if not image or not pin:
        pytest.skip("Explicit owned Linux builder image and toolchain required")
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", image)
    assert re.fullmatch(r"[0-9a-f]{64}", pin)
    image_info = json.loads(docker("image", "inspect", image))[0]
    assert image_info["Id"] == image
    assert image_info["Config"]["Labels"]["io.flintgraph.narrative.toolchain.sha256"] == pin
    token = uuid4().hex
    story = json.loads(
        (Path(__file__).parents[1] / "fixtures/narrative/lantern_archive/story.json").read_bytes()
    )
    story["assets"] = {}
    for node in story["nodes"].values():
        node.pop("background", None)
        node.pop("portrait", None)
    package = load_text_package(json.dumps(story).encode(), b"Original Lantern text. CC0.\n")
    source = tmp_path / "input"
    export_godot(package, source)
    source_files = {
        name: (source / name).read_bytes()
        for name in (
            *TEMPLATE_FILES,
            "content/story.json",
            "content/NOTICES.txt",
            "content/package-manifest.json",
            "build-manifest.json",
        )
    }
    if tampered:
        script = source / "runtime/player.gd"
        script.write_bytes(b"THIS_RUNTIME_MUST_NEVER_REACH_GODOT")
        manifest_path = source / "build-manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["files"]["runtime/player.gd"] = hashlib.sha256(script.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("FLINT_GRAPH_BUILD_SECRET_CANARY", token)
    cid = None
    try:
        cid = docker(
            "run",
            "--detach",
            "--pull",
            "never",
            "--name",
            "flint-narrative-live-" + token,
            "--label",
            "io.flintgraph.narrative.test=" + token,
            "--network",
            "none",
            "--read-only",
            "--user",
            "10001:10001",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "128",
            "--cpus",
            "2",
            "--memory",
            "1g",
            "--memory-swap",
            "1g",
            "--tmpfs",
            "/scratch:rw,size=268435456,mode=1777",
            "--tmpfs",
            "/tmp:rw,size=16777216,mode=1777",
            "--mount",
            "type=bind,source=" + str(source) + ",target=/input,readonly",
            image,
        ).strip()
        effective = json.loads(docker("inspect", cid))[0]
        config = effective["HostConfig"]
        assert effective["Config"]["User"] == "10001:10001"
        assert not any(token in value for value in effective["Config"]["Env"])
        assert config["NetworkMode"] == "none" and config["ReadonlyRootfs"]
        assert config["Memory"] == config["MemorySwap"] == 1073741824
        assert config["NanoCpus"] == 2000000000 and config["PidsLimit"] == 128
        assert config["CapDrop"] == ["ALL"] and "no-new-privileges" in config["SecurityOpt"]
        assert not config["Privileged"] and not config["Devices"]
        assert config["Tmpfs"] == {
            "/scratch": "rw,size=268435456,mode=1777",
            "/tmp": "rw,size=16777216,mode=1777",
        }
        binds = [mount for mount in effective["Mounts"] if mount["Type"] == "bind"]
        assert len(binds) == 1 and binds[0]["Destination"] == "/input" and not binds[0]["RW"]
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            probe = subprocess.run(
                [
                    "docker",
                    "exec",
                    cid,
                    "python",
                    "-c",
                    "from pathlib import Path; import sys; p=Path('/scratch/status.json'); "
                    "sys.exit(1) if not p.exists() else None; "
                    "assert p.stat().st_size < 65536; sys.stdout.buffer.write(p.read_bytes())",
                ],
                capture_output=True,
                timeout=5,
            )
            if probe.returncode == 0:
                outcome = json.loads(probe.stdout)
                break
            time.sleep(0.2)
        else:
            pytest.fail("Owned engine did not complete within qualification deadline")
        if tampered:
            assert outcome == {"schema_version": "1", "status": "failed", "code": "input_integrity"}
            return
        assert outcome["status"] == "ready" and set(outcome["files"]) == WEB_FILES
        process = subprocess.Popen(
            ["docker", "exec", cid, "python", "/opt/build_child.py", "archive"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            files = read_child_files(process.stdout, expected_names=WEB_FILES)
            assert process.wait(timeout=5) == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()
        for name, data in files.items():
            assert {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} == (
                outcome["files"][name]
            )
        # A browser cannot boot a pack whose project.binary failed to stage.
        assert web_pack_has_project_settings(files["index.pck"])
        source_zip, web_zip = make_artifact_zip(source_files), make_artifact_zip(files)
        evidence = os.environ.get("FLINT_GRAPH_NARRATIVE_BUILD_EVIDENCE_DIR")
        if evidence:
            output = Path(evidence)
            output.mkdir()  # Explicit fresh operator destination; never overwrite.
            (output / "source.zip").write_bytes(source_zip)
            (output / "web.zip").write_bytes(web_zip)
            receipt = {
                "image": image,
                "toolchain_sha256": pin,
                "package_hash": package.content_hash,
                "files": outcome["files"],
                "source_zip_sha256": hashlib.sha256(source_zip).hexdigest(),
                "web_zip_sha256": hashlib.sha256(web_zip).hexdigest(),
                "effective": {
                    "user": effective["Config"]["User"],
                    "host_config": config,
                    "mounts": effective["Mounts"],
                },
            }
            (output / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    finally:
        if cid:
            owned = json.loads(docker("inspect", cid))[0]
            assert owned["Config"]["Labels"].get("io.flintgraph.narrative.test") == token
            docker("rm", "--force", cid)
