"""Native Compose serialization and isolated runtime string-preservation seam."""

import base64
import json
import os
import subprocess
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("FLINT_GRAPH_TELEMETRY_NATIVE_CONFIG_INTEGRATION") != "1",
    reason="requires an explicitly selected known local Python sender image and Docker",
)


def run(args, payload):
    result = subprocess.run(
        args,
        input=json.dumps(payload).replace("$", "$$"),
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    if result.returncode:
        raise AssertionError("Owned native Compose probe failed; captured output is not exposed")
    return result.stdout


def test_native_compose_preserves_literal_dollars_in_environment_and_command():
    expected = "OWNED-$literal-$$double-${braced}=value"
    encoded = base64.b64encode(expected.encode()).decode()
    # Runtime oracle contains no dollars, so interpolation cannot corrupt both
    # input and expected value in the same way and yield a false positive.
    script = (
        "import base64,json,os,sys;"
        f"expected=base64.b64decode('{encoded}').decode();"
        "assert os.environ['OWNED_LITERAL_PROBE']==expected;"
        "assert sys.argv[1]==expected;print(json.dumps({'literal_preservation':True}))"
    )
    spec = {
        "services": {
            "probe": {
                "image": os.environ["FLINT_GRAPH_JAEGER_SENDER_IMAGE"],
                "entrypoint": ["/app/.venv/bin/python"],
                "command": ["-c", script, expected],
                "environment": {"OWNED_LITERAL_PROBE": expected},
                "network_mode": "none",
                "mem_limit": "128m",
                "cpus": 0.25,
                "pids_limit": 64,
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
            }
        }
    }
    compose = ["docker", "compose", "--project-name", f"flint-literal-{uuid4().hex}", "-f", "-"]
    rendered = run([*compose, "config", "--format", "json"], spec)
    config = json.loads(rendered.replace("$$", "$"))["services"]["probe"]
    assert config["environment"]["OWNED_LITERAL_PROBE"] == expected
    assert config["command"][-1] == expected
    # --rm and network_mode:none leave no container, network, volume or data.
    result = run([*compose, "run", "--rm", "--no-deps", "--pull", "never", "-T", "probe"], spec)
    assert json.loads(result)["literal_preservation"] is True
