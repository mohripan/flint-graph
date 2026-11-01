import json
import struct

import pytest

from flint_graph.narrative.style_weights import validate_adapter


def weights(**changes):
    header = {
        "__metadata__": {
            "format": "pt",
            "model_manifest_sha256": "b" * 64,
            "dataset_sha256": "c" * 64,
            "recipe_sha256": "d" * 64,
        },
        "transformer.transformer_blocks.0.attn.to_q.lora_A.weight": {
            "dtype": "F32",
            "shape": [4, 8],
            "data_offsets": [0, 128],
        },
        "transformer.transformer_blocks.0.attn.to_q.lora_B.weight": {
            "dtype": "F32",
            "shape": [8, 4],
            "data_offsets": [128, 256],
        },
    }
    header.update(changes)
    raw = json.dumps(header).encode()
    return struct.pack("<Q", len(raw)) + raw + struct.pack("<64f", *([0.25] * 64))


def test_private_adapter_accepts_only_paired_finite_rank_four_tensors():
    validate_adapter(weights(), base_hash="b" * 64, dataset_hash="c" * 64, recipe_hash="d" * 64)
    for data in (
        weights() + b"junk",
        weights()[:-1],
        weights(extra={"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}),
        weights().replace(b'"F32"', b'"F16"'),
    ):
        with pytest.raises(ValueError):
            validate_adapter(data, base_hash="b" * 64, dataset_hash="c" * 64, recipe_hash="d" * 64)
    bad = bytearray(weights())
    struct.pack_into("<f", bad, len(bad) - 4, float("nan"))
    with pytest.raises(ValueError):
        validate_adapter(
            bytes(bad), base_hash="b" * 64, dataset_hash="c" * 64, recipe_hash="d" * 64
        )
    with pytest.raises(ValueError):
        validate_adapter(weights(), base_hash="a" * 64, dataset_hash="c" * 64, recipe_hash="d" * 64)
