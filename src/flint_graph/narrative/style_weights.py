"""Bounded safetensors validation without importing torch or executing a checkpoint."""

import array
import json
import math
import re
import struct
import sys
from typing import Any

MAX_ADAPTER_BYTES = 32 * 1024**2
_NAME = re.compile(
    r"transformer\.(?:single_)?transformer_blocks\.[0-9]{1,2}\.attn\.(?:to_q|to_k|to_v|to_out\.0|to_out|to_qkv_mlp_proj)\.lora_([AB])\.weight\Z"
)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid_adapter")
        result[key] = value
    return result


def validate_adapter(data: bytes, *, base_hash: str, dataset_hash: str, recipe_hash: str) -> None:
    try:
        if not 8 < len(data) <= MAX_ADAPTER_BYTES:
            raise ValueError
        size = struct.unpack_from("<Q", data)[0]
        if not 2 <= size <= 128 * 1024 or size + 8 >= len(data):
            raise ValueError
        header = json.loads(data[8 : 8 + size], object_pairs_hook=_object)
        if not isinstance(header, dict) or not 3 <= len(header) <= 257:
            raise ValueError
        metadata = header.pop("__metadata__", None)
        if metadata != {
            "format": "pt",
            "model_manifest_sha256": base_hash,
            "dataset_sha256": dataset_hash,
            "recipe_sha256": recipe_hash,
        }:
            raise ValueError
        shapes = {}
        ranges = []
        for name, item in header.items():
            match = _NAME.fullmatch(name)
            if (
                not match
                or not isinstance(item, dict)
                or set(item) != {"dtype", "shape", "data_offsets"}
            ):
                raise ValueError
            shape, offsets = item["shape"], item["data_offsets"]
            if (
                item["dtype"] != "F32"
                or not isinstance(shape, list)
                or len(shape) != 2
                or any(type(n) is not int or not 1 <= n <= 32768 for n in shape)
                or shape[0 if match[1] == "A" else 1] != 4
                or not isinstance(offsets, list)
                or len(offsets) != 2
                or any(type(n) is not int for n in offsets)
                or offsets[0] < 0
                or offsets[1] - offsets[0] != math.prod(shape) * 4
            ):
                raise ValueError
            shapes[name] = shape
            ranges.append(tuple(offsets))
        for name, shape in shapes.items():
            if ".lora_A." in name:
                other = shapes.get(name.replace(".lora_A.", ".lora_B."))
                if other is None or other[1] != shape[0]:
                    raise ValueError
            elif name.replace(".lora_B.", ".lora_A.") not in shapes:
                raise ValueError
        end = 0
        for start, stop in sorted(ranges):
            if start != end:
                raise ValueError
            end = stop
        if end != len(data) - 8 - size:
            raise ValueError
        values = array.array("f")
        values.frombytes(data[8 + size :])
        if sys.byteorder != "little":
            values.byteswap()
        if any(not math.isfinite(n) for n in values):
            raise ValueError
    except (ValueError, TypeError, KeyError, struct.error, UnicodeError, RecursionError):
        raise ValueError("invalid_adapter") from None
