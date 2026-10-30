"""Explicit three-minute proof: the child exits even without a supervising worker."""

import json
import os
import re
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest

from flint_graph.narrative.export import export_godot
from flint_graph.narrative.package import load_text_package


def test_owned_engine_child_watchdog_survives_absent_supervisor(tmp_path):
    image = os.environ.get("FLINT_GRAPH_NARRATIVE_BUILDER_IMAGE", "")
    if os.environ.get("FLINT_GRAPH_NARRATIVE_BUILDER_WATCHDOG_LIVE") != "1":
        pytest.skip("Explicit 180-second child watchdog qualification required")
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", image)
    story = {
        "schema_version": "1",
        "id": "watchdog",
        "title": "Owned watchdog fixture",
        "language": "en",
        "entry": "end",
        "characters": {},
        "variables": {},
        "assets": {},
        "nodes": {
            "end": {"type": "end", "text_id": "end_text", "ending": "quiet", "text": "The end."}
        },
    }
    source = tmp_path / "input"
    export_godot(load_text_package(json.dumps(story).encode()), source)
    token = uuid4().hex

    def docker(*args):
        return subprocess.check_output(["docker", *args], text=True, encoding="utf-8", timeout=10)

    cid = None
    started = time.monotonic()
    try:
        cid = docker(
            "run",
            "--detach",
            "--pull",
            "never",
            "--name",
            "flint-narrative-watchdog-" + token,
            "--label",
            "io.flintgraph.narrative.watchdog-test=" + token,
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
        # No build activity, heartbeat or host-side stop is involved. Polling only.
        while time.monotonic() - started < 205:
            info = json.loads(docker("inspect", cid))[0]
            if not info["State"]["Running"]:
                break
            time.sleep(2)
        else:
            pytest.fail("Owned child exceeded watchdog deadline")
        elapsed = time.monotonic() - started
        assert info["State"]["ExitCode"] == 124 and not info["State"]["OOMKilled"]
        assert 175 <= elapsed <= 200
        receipt = {
            "image": image,
            "exit_code": 124,
            "oom_killed": False,
            "elapsed_seconds": round(elapsed, 3),
            "host_stop_before_exit": False,
        }
    finally:
        if cid:
            info = json.loads(docker("inspect", cid))[0]
            assert info["Config"]["Labels"].get("io.flintgraph.narrative.watchdog-test") == token
            docker("rm", "--force", cid)
    evidence = os.environ.get("FLINT_GRAPH_NARRATIVE_BUILD_EVIDENCE_DIR")
    if evidence:
        receipt["owned_container_removed"] = True
        with (Path(evidence) / "watchdog.json").open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2)
