"""Downloads the pinned models onto the Network Volume, once, and checks each against its pin.

Run on a temporary pod with the volume mounted at /runpod-volume, under a runtime that has PyYAML:

    /app/runtimes/imagegen/.venv/bin/python /app/fetch_weights.py
"""

import hashlib
import subprocess
import sys
from pathlib import Path

import yaml

MODELS_ROOT = Path("/models")
MANIFEST = "flintgraph-download.json"


def main() -> None:
    pinned = yaml.safe_load(Path("/app/models.yml").read_text("utf-8"))["flintgraph_models"]
    for model in pinned:
        out = MODELS_ROOT / model["name"]
        if not (out / MANIFEST).is_file():
            subprocess.run(
                [
                    sys.executable,
                    "/app/fetch_model.py",
                    "--repo",
                    model["repo"],
                    "--revision",
                    model["revision"],
                    "--license",
                    model["license"],
                    "--out",
                    str(out),
                    *[f"--file={name}" for name in model["files"]],
                ],
                check=True,
            )
        if hashlib.sha256((out / MANIFEST).read_bytes()).hexdigest() != model["manifest_sha256"]:
            raise SystemExit(f"{model['name']} does not match its pin")
        print(f"verified {model['name']}", flush=True)
    print("FETCHED", flush=True)


if __name__ == "__main__":
    main()
