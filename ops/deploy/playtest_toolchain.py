"""Downloads the pinned Godot engine and web templates while building the playtest image.

Each archive is checked against its pinned SHA-256 and SHA-512 before anything is taken from it, and
only the named members are taken, then checked against their own pins. Standard library only.

    python playtest_toolchain.py RUNTIME_PIN LINUX_PIN OUTPUT
"""

import hashlib
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

RELEASE = "https://github.com/godotengine/godot-builds/releases/download"
CHUNK = 1024 * 1024
ENGINE = "Godot_v4.7.2-stable_linux.x86_64"


def download(url: str, target: Path, sha256: str, sha512: str) -> None:
    short, long = hashlib.sha256(), hashlib.sha512()
    partial = target.with_name(target.name + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as stream:
        while block := response.read(CHUNK):
            short.update(block)
            long.update(block)
            stream.write(block)
    if short.hexdigest() != sha256 or long.hexdigest() != sha512:
        partial.unlink()
        raise SystemExit(f"{target.name} does not match its pin")
    partial.replace(target)


def extract(archive: Path, member: str, sha256: str, target: Path) -> None:
    with zipfile.ZipFile(archive) as opened:
        data = opened.read(member)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise SystemExit(f"{member} does not match its pin")
    target.write_bytes(data)


def main() -> None:
    runtime = json.loads(Path(sys.argv[1]).read_bytes())
    linux = json.loads(Path(sys.argv[2]).read_bytes())
    output = Path(sys.argv[3])
    (output / "engine").mkdir(parents=True)
    (output / "templates").mkdir()
    release = f"{RELEASE}/{runtime['release_tag']}"

    engine = linux["archive"]
    archive = output / engine["name"]
    download(f"{release}/{engine['name']}", archive, engine["sha256"], engine["sha512"])
    extract(archive, ENGINE, linux["engine_sha256"], output / "engine" / ENGINE)
    (output / "engine" / ENGINE).chmod(0o555)
    archive.unlink()

    templates = runtime["artifacts"]["export_templates"]
    archive = output / templates["name"]
    download(f"{release}/{templates['name']}", archive, templates["sha256"], templates["sha512"])
    for name, sha256 in linux["templates"].items():
        extract(archive, f"templates/{name}", sha256, output / "templates" / name)
    archive.unlink()
    print("toolchain verified", flush=True)


if __name__ == "__main__":
    main()
