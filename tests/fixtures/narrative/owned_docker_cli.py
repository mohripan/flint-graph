"""Tiny external CLI protocol fixture, not an engine or Docker qualification.

Only owned pytest directories are read/written. Modes force faults at real pipe/
process boundaries without mocking the runner's internal methods.
"""

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

root, mode = Path(sys.argv[1]), sys.argv[2]
args = sys.argv[3:]
state_file = root / "state.json"
identity = "c" * 64
image = "sha256:" + "a" * 64
files = {
    name: b"fixture"
    for name in (
        "index.html",
        "index.js",
        "index.wasm",
        "index.pck",
        "index.png",
        "index.audio.worklet.js",
        "index.audio.position.worklet.js",
    )
}


def state():
    return json.loads(state_file.read_bytes())


if args[:2] == ["image", "inspect"]:
    print(
        json.dumps(
            [
                {
                    "Id": image,
                    "Os": "linux",
                    "Architecture": "amd64",
                    "Config": {
                        "User": "10001:10001",
                        "Entrypoint": ["python", "/opt/build_child.py"],
                        "Labels": {"io.flintgraph.narrative.toolchain.sha256": "b" * 64},
                    },
                }
            ]
        )
    )
elif args[0] == "create":
    if mode == "create_failure":
        raise SystemExit(2)
    execution = next(
        x.split("=", 1)[1] for x in args if x.startswith("io.flintgraph.narrative.execution=")
    )
    state_file.write_text(json.dumps({"execution": execution}), encoding="utf-8")
    print(identity)
elif args[:2] == ["container", "inspect"]:
    saved = state()
    print(
        json.dumps(
            [
                {
                    "Id": identity,
                    "Image": image,
                    "Config": {
                        "User": "10001:10001",
                        "Labels": {
                            "io.flintgraph.narrative.execution": saved["execution"],
                            "io.flintgraph.narrative.expires": saved.get("expires", "9999999999"),
                        },
                    },
                    "HostConfig": {
                        "NetworkMode": "none",
                        "ReadonlyRootfs": True,
                        "Memory": 1073741824,
                        "MemorySwap": 1073741824,
                        "NanoCpus": 2000000000,
                        "PidsLimit": 128,
                        "CapDrop": ["ALL"],
                        "SecurityOpt": ["no-new-privileges"],
                        "Tmpfs": {"/scratch": "rw,size=268435456,mode=1777"},
                    },
                    "Mounts": [{"Type": "bind", "Destination": "/input", "RW": False}],
                }
            ]
        )
    )
elif args[:2] == ["container", "ls"]:
    if state_file.exists():
        print(identity)
elif args[0] == "start":
    print(identity)
elif args[0] == "exec":
    if args[-1] == "archive":
        (root / "archive-cli.pid").write_text(str(os.getpid()))
        if mode == "stalled_archive":
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(7)"])
            (root / "descendant.pid").write_text(str(child.pid))
            (root / "archive-entered").write_text("ready")
            time.sleep(7)
        else:
            import io

            with tarfile.open(
                fileobj=sys.stdout.buffer, mode="w|", format=tarfile.USTAR_FORMAT
            ) as t:
                for name, payload in files.items():
                    info = tarfile.TarInfo("web/" + name)
                    info.size = len(payload)
                    t.addfile(info, io.BytesIO(payload))
    else:
        print(
            json.dumps(
                {
                    "schema_version": "1",
                    "status": "ready",
                    "files": {
                        name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                        for name, data in files.items()
                    },
                }
            )
        )
elif args[0] == "rm":
    assert args[-1] == identity, "Cleanup must use inspected immutable ID"
    if mode == "cleanup_delay":
        (root / "cleanup-entered").write_text("ready")
        time.sleep(0.5)
    state_file.unlink()
else:
    raise SystemExit(2)
