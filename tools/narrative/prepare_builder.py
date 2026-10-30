"""Explicit operator preparation from predownloaded verified inputs; no auto-install.

Default prepares a fresh context only. --build opts into Docker image construction
(including distribution font libraries). Application jobs use a pinned resulting
image ID with --pull=never and never call this tool.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from flint_graph.narrative.export import TEMPLATE_FILES
from flint_graph.narrative.values import canonical_json

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError("unqualified_file")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(engine, templates, output):
    pin = json.loads((ROOT / "ops/narrative/toolchain-linux.json").read_bytes())
    if digest(engine) != pin["engine_sha256"]:
        raise ValueError("unqualified_engine")
    for name, expected in pin["templates"].items():
        if digest(templates / name) != expected:
            raise ValueError("unqualified_template")
    absolute = output.absolute()
    if (
        absolute.exists()
        or absolute.is_symlink()
        or absolute.parent.resolve(strict=True) != absolute.parent
    ):
        raise ValueError("unsafe_output")
    runtime = ROOT / "runtimes/godot"
    runtime_hashes = {name: digest(runtime / name) for name in TEMPLATE_FILES}
    child = ROOT / "src/flint_graph/narrative/build_child.py"
    recipe = ROOT / "ops/narrative/Dockerfile"
    identity = {
        "schema_version": "1",
        "pin": pin,
        "runtime_files": runtime_hashes,
        "child_sha256": digest(child),
        "recipe_sha256": digest(recipe),
    }
    toolchain_hash = hashlib.sha256(canonical_json(identity)).hexdigest()
    absolute.mkdir()
    shutil.copyfile(engine, absolute / "godot")
    for name in pin["templates"]:
        shutil.copyfile(templates / name, absolute / name)
    shutil.copyfile(child, absolute / "build_child.py")
    shutil.copyfile(recipe, absolute / "Dockerfile")
    (absolute / "runtime-files.json").write_bytes(canonical_json(runtime_hashes))
    expected_copies = {
        "godot": pin["engine_sha256"],
        **pin["templates"],
        "build_child.py": identity["child_sha256"],
        "Dockerfile": identity["recipe_sha256"],
    }
    for name, expected in expected_copies.items():
        if digest(absolute / name) != expected:
            raise ValueError("copied_input_changed")
    receipt = {"toolchain_sha256": toolchain_hash, "identity": identity}
    (absolute / "toolchain.json").write_bytes(canonical_json(receipt))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--templates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    try:
        receipt = prepare(args.engine, args.templates, args.output)
    except (ValueError, OSError) as exc:
        parser.error(str(exc) if isinstance(exc, ValueError) else "preparation_io")
    if args.build:
        result = subprocess.run(
            [
                "docker",
                "build",
                "--pull=false",
                "--build-arg",
                "TOOLCHAIN_SHA256=" + receipt["toolchain_sha256"],
                "--iidfile",
                str(args.output / "image.id"),
                str(args.output),
            ],
            timeout=300,
            check=False,
        )
        if result.returncode:
            raise SystemExit("Image preparation failed; context retained")
        image = (args.output / "image.id").read_text().strip()
        receipt["image"] = image
        (args.output / "toolchain.json").write_bytes(canonical_json(receipt))
    print(
        json.dumps({key: receipt[key] for key in ("toolchain_sha256", "image") if key in receipt})
    )


if __name__ == "__main__":
    main()
