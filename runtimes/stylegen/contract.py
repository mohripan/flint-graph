"""Closed training request and bounded aspect buckets; standard library only."""

import json
import math
import re
from pathlib import Path

SHA = re.compile(r"[a-f0-9]{64}\Z")
LIMIT = 65536


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid_request")
        result[key] = value
    return result


def bucket_size(width, height):
    if (
        type(width) is not int
        or type(height) is not int
        or not 64 <= min(width, height)
        or max(width, height) > 2560
    ):
        raise ValueError("invalid_image")
    scale = min(math.sqrt(512**2 / (width * height)), 768 / max(width, height))
    return max(32, int(width * scale) // 32 * 32), max(32, int(height * scale) // 32 * 32)


def parse_request(raw):
    try:
        if len(raw) > LIMIT:
            raise ValueError
        value = json.loads(raw, object_pairs_hook=_object)
        if type(value) is not dict or set(value) != {
            "schema_version",
            "model_dir",
            "model_manifest_sha256",
            "dataset_sha256",
            "recipe_sha256",
            "trigger",
            "steps",
            "seed",
            "images",
        }:
            raise ValueError
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError
        for key in ["model_manifest_sha256", "dataset_sha256", "recipe_sha256"]:
            if type(value[key]) is not str or not SHA.fullmatch(value[key]):
                raise ValueError
        if type(value["model_dir"]) is not str or not Path(value["model_dir"]).is_absolute():
            raise ValueError
        if type(value["trigger"]) is not str or not re.fullmatch(
            r"fgstyle_[a-z0-9]{2,32}", value["trigger"]
        ):
            raise ValueError
        if type(value["steps"]) is not int or not 20 <= value["steps"] <= 400:
            raise ValueError
        if type(value["seed"]) is not int or not 0 <= value["seed"] < 2**32:
            raise ValueError
        images = value["images"]
        if type(images) is not list or not 4 <= len(images) <= 12:
            raise ValueError
        seen = set()
        for image in images:
            if type(image) is not dict or set(image) != {"sha256", "caption"}:
                raise ValueError
            if (
                type(image["sha256"]) is not str
                or not SHA.fullmatch(image["sha256"])
                or image["sha256"] in seen
            ):
                raise ValueError
            seen.add(image["sha256"])
            if (
                type(image["caption"]) is not str
                or not 1 <= len(image["caption"]) <= 600
                or any(ord(c) < 32 for c in image["caption"])
            ):
                raise ValueError
        return value
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise ValueError("invalid_request") from None
