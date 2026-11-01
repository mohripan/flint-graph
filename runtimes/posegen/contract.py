"""Closed, bounded pose-child protocol; no ML imports or runtime downloads."""

import hashlib
import json
import re
from pathlib import Path

MODEL_REPO = "black-forest-labs/FLUX.2-klein-4B"
MODEL_REVISION = "e7b7dc27f91deacad38e78976d1f2b499d76a294"
WIDTH, HEIGHT = 768, 1152
REQUEST_LIMIT = 65536
SHA = re.compile(r"[a-f0-9]{64}\Z")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid_request")
        result[key] = value
    return result


def parse_request(data):
    if len(data) > REQUEST_LIMIT:
        raise ValueError("invalid_request")
    try:
        request = json.loads(data, object_pairs_hook=_object)
        if type(request) is not dict or set(request) != {
            "schema_version",
            "model_dir",
            "model_manifest_sha256",
            "reference_sha256",
            "prompt",
            "seeds",
            "cutout",
        }:
            raise ValueError
        if type(request["schema_version"]) is not int or request["schema_version"] != 1:
            raise ValueError
        for field in ("model_manifest_sha256", "reference_sha256"):
            if type(request[field]) is not str or not SHA.fullmatch(request[field]):
                raise ValueError
        if type(request["model_dir"]) is not str or not Path(request["model_dir"]).is_absolute():
            raise ValueError
        if type(request["prompt"]) is not str or not 1 <= len(request["prompt"]) <= 4096:
            raise ValueError
        seeds = request["seeds"]
        if (
            type(seeds) is not list
            or not 1 <= len(seeds) <= 4
            or any(type(seed) is not int or not 0 <= seed < 2**32 for seed in seeds)
        ):
            raise ValueError
        cutout = request["cutout"]
        if cutout is not None and (
            type(cutout) is not dict
            or set(cutout) != {"model", "sha256"}
            or type(cutout["model"]) is not str
            or not Path(cutout["model"]).is_absolute()
            or Path(cutout["model"]).suffix != ".onnx"
            or type(cutout["sha256"]) is not str
            or not SHA.fullmatch(cutout["sha256"])
        ):
            raise ValueError
        return request
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise ValueError("invalid_request") from None


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while part := stream.read(1024 * 1024):
            result.update(part)
    return result.hexdigest()


def verify_model(root, expected):
    try:
        manifest = root / "flintgraph-download.json"
        if (
            manifest.is_symlink()
            or manifest.stat().st_size > 1024 * 1024
            or digest(manifest) != expected
        ):
            raise ValueError
        data = json.loads(manifest.read_bytes(), object_pairs_hook=_object)
        if (
            type(data) is not dict
            or data.get("repo") != MODEL_REPO
            or data.get("revision") != MODEL_REVISION
        ):
            raise ValueError
        files = data.get("files")
        if type(files) is not dict or not 1 <= len(files) <= 256:
            raise ValueError
        for name, entry in files.items():
            if (
                type(name) is not str
                or type(entry) is not dict
                or type(entry.get("sha256")) is not str
                or not SHA.fullmatch(entry["sha256"])
            ):
                raise ValueError
            path = (root / name).resolve()
            if (
                not path.is_relative_to(root.resolve())
                or (root / name).is_symlink()
                or path.suffix == ".bin"
            ):
                raise ValueError
            if digest(path) != entry["sha256"]:
                raise ValueError
        return data
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise ValueError("model_invalid") from None
