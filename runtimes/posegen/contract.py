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
        if type(request) is not dict or type(request.get("schema_version")) is not int:
            raise ValueError
        version = request["schema_version"]
        common = {
            "schema_version",
            "model_dir",
            "model_manifest_sha256",
            "prompt",
            "seeds",
            "cutout",
        }
        if version == 1:
            if set(request) != common | {"reference_sha256"}:
                raise ValueError
            hashes = [request["reference_sha256"]]
        elif version in (2, 3, 4, 5):
            if set(request) != common | {"reference_sha256s"} | (
                {"style"}
                if version == 3
                else {"adapters"}
                if version == 4
                else {"adapters", "repair"}
                if version == 5
                else set()
            ):
                raise ValueError
            hashes = request["reference_sha256s"]
            if (
                type(hashes) is not list
                or len(hashes) not in ((2,) if version in (2, 5) else (1, 2))
                or any(type(h) is not str for h in hashes)
                or len(set(hashes)) != len(hashes)
            ):
                raise ValueError
        else:
            raise ValueError
        adapters = [request["style"]] if version == 3 else request.get("adapters", [])
        if version in (4, 5):
            if type(adapters) is not list or len(adapters) not in (
                (1, 2) if version == 4 else (0, 1, 2)
            ):
                raise ValueError
            roles = [["character"], ["character", "style"]]
            if version == 5:
                roles += [[], ["style"]]
            if [item.get("role") if type(item) is dict else None for item in adapters] not in roles:
                raise ValueError
        for style in adapters:
            if type(style) is not dict or set(style) != {
                "sha256",
                "strength",
                "dataset_sha256",
                "recipe_sha256",
            } | ({"role"} if version in (4, 5) else set()):
                raise ValueError
            if type(style["strength"]) not in (int, float) or not 0.1 <= style["strength"] <= 1:
                raise ValueError
            if any(
                type(style[k]) is not str or not SHA.fullmatch(style[k])
                for k in ("sha256", "dataset_sha256", "recipe_sha256")
            ):
                raise ValueError
        if version in (4, 5) and (
            sum(item["strength"] for item in adapters) > 1 + 1e-9
            or len({item["sha256"] for item in adapters}) != len(adapters)
        ):
            raise ValueError
        for value in [request["model_manifest_sha256"], *hashes]:
            if type(value) is not str or not SHA.fullmatch(value):
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
        if version == 5:
            repair = request["repair"]
            if type(repair) is not dict or set(repair) != {
                "width",
                "height",
                "box",
                "source_box",
                "feather",
            }:
                raise ValueError
            w, h, box, crop = repair["width"], repair["height"], repair["box"], repair["source_box"]
            if (
                type(w) is not int
                or type(h) is not int
                or not 32 <= w <= WIDTH
                or not 32 <= h <= HEIGHT
                or type(repair["feather"]) is not int
                or repair["feather"] != 8
            ):
                raise ValueError
            if type(box) is not list or len(box) != 4 or any(type(v) is not int for v in box):
                raise ValueError
            left, top, right, bottom = box
            if not (
                0 <= left < right <= w
                and 0 <= top < bottom <= h
                and right - left >= 16
                and bottom - top >= 16
                and (right - left) * (bottom - top) * 4 <= w * h
            ):
                raise ValueError
            if crop is None:
                if (w, h) != (WIDTH, HEIGHT) or request["cutout"] is not None:
                    raise ValueError
            elif (
                type(crop) is not list
                or len(crop) != 4
                or any(type(v) is not int for v in crop)
                or request["cutout"] is None
                or not 0 <= crop[0] < crop[2] <= WIDTH
                or not 0 <= crop[1] < crop[3] <= HEIGHT
                or (crop[2] - crop[0], crop[3] - crop[1]) != (w, h)
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
