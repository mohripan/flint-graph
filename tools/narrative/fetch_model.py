"""Download pinned Hugging Face model files and write their FlintGraph manifest.

Usage (one model directory per catalog entry; see the voice runbook):

    uv run python tools/narrative/fetch_model.py --repo ResembleAI/chatterbox-turbo \
        --revision 749d1c1a46eb10492095d68fbcf55691ccf137cd --license mit \
        --file t3_turbo_v1.safetensors --file ve.safetensors ... --out notes/models/x

Extra sources (auxiliary weights a model needs) go into a subdirectory:

    --source facebook/w2v-bert-2.0@<rev>:mit:hf_cache/w2v-bert-2.0=model.safetensors,config.json

Every file is checked against the hash Hugging Face publishes for that revision (the
LFS SHA-256 for large files, the git blob SHA-1 otherwise) before the manifest is
written. Interrupted downloads resume. Only the Python standard library is used.
"""

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

MANIFEST = "flintgraph-download.json"
HUB = "https://huggingface.co"
CHUNK = 1024 * 1024


def _metadata(repo: str, revision: str) -> dict[str, dict]:
    url = f"{HUB}/api/models/{repo}/revision/{revision}?blobs=true"
    with urllib.request.urlopen(url, timeout=60) as response:
        data = json.load(response)
    if data.get("sha") != revision:
        raise SystemExit(f"{repo}: revision {revision} is not a full commit hash")
    return {item["rfilename"]: item for item in data["siblings"]}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def _git_blob(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _download(repo: str, revision: str, name: str, target: Path, size: int) -> None:
    partial = target.with_name(target.name + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size == size:
        return
    done = partial.stat().st_size if partial.is_file() else 0
    request = urllib.request.Request(f"{HUB}/{repo}/resolve/{revision}/{name}")
    if done:
        request.add_header("Range", f"bytes={done}-")
    with urllib.request.urlopen(request, timeout=120) as response:
        if done and response.status != 206:
            done = 0
        with partial.open("ab" if done else "wb") as stream:
            while block := response.read(CHUNK):
                stream.write(block)
    if partial.stat().st_size != size:
        raise SystemExit(f"{repo}/{name}: incomplete download")
    partial.replace(target)


def fetch(repo: str, revision: str, names: list[str], root: Path, prefix: str) -> dict[str, dict]:
    siblings = _metadata(repo, revision)
    entries = {}
    for name in names:
        item = siblings.get(name)
        if item is None:
            raise SystemExit(f"{repo}@{revision} has no file {name}")
        lfs = item.get("lfs")
        size = int(lfs["size"] if lfs else item["size"])
        local = f"{prefix}/{name}" if prefix else name
        target = root / local
        print(f"{repo}/{name} ({size / 1e6:.1f} MB)", flush=True)
        _download(repo, revision, name, target, size)
        sha = _sha256(target)
        if lfs:
            if sha != lfs["sha256"]:
                raise SystemExit(f"{repo}/{name}: SHA-256 differs from the published LFS hash")
        elif _git_blob(target) != item["blobId"]:
            raise SystemExit(f"{repo}/{name}: content differs from the published git blob")
        entries[local] = {"size": size, "sha256": sha, "lfs_verified": bool(lfs)}
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--license", required=True)
    parser.add_argument("--file", action="append", required=True, dest="files")
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=True)
    files = fetch(args.repo, args.revision, args.files, root, "")
    sources = []
    for spec in args.source:
        head, _, names = spec.partition("=")
        ident, license_name, prefix = head.split(":", 2)
        repo, _, revision = ident.partition("@")
        files.update(fetch(repo, revision, names.split(","), root, prefix))
        sources.append(
            {"repo": repo, "revision": revision, "license": license_name, "path": prefix}
        )
    manifest = {
        "repo": args.repo,
        "revision": args.revision,
        "license": args.license,
        **({"sources": sources} if sources else {}),
        "files": dict(sorted(files.items())),
    }
    data = (json.dumps(manifest, indent=2) + "\n").encode()
    (root / MANIFEST).write_bytes(data)
    print(f"manifest sha256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
