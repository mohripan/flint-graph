"""Versioned structural guides and their public model identity."""

from copy import deepcopy
from hashlib import sha256
from typing import Any

from flint_graph.narrative.values import canonical_json

CONTROL_REPO = "xocialize/refcontrol-FLUX.2-klein-4B-pose-lora"
CONTROL_REVISION = "b2b0edf2622f2abd980bf868441149d71b3eb7b0"
CONTROL_WEIGHT = "refcontrol-pose-klein-4b.safetensors"
CONTROL_SHA256 = "f9880f9070576ff1603c0988ed2afc9957deb0d7dd7c52cf15decbd4087f1339"
CONTROL_SIZE = 92426792
GUIDE = {
    "id": "seated-front-v1",
    "label": "Seated — both feet on the floor",
    "width": 768,
    "height": 1152,
    "points": [
        [384, 185],
        [384, 290],
        [320, 300],
        [300, 430],
        [310, 600],
        [448, 300],
        [468, 430],
        [460, 600],
        [340, 565],
        [260, 650],
        [270, 1070],
        [428, 565],
        [480, 650],
        [500, 1070],
        [365, 177],
        [401, 177],
        [348, 192],
        [420, 192],
    ],
}


GUIDES = {
    "seated-front-v1": GUIDE,
    "standing-front-v1": {
        "id": "standing-front-v1",
        "label": "Standing — arms relaxed",
        "width": 768,
        "height": 1152,
        "points": [
            [384, 160],
            [384, 280],
            [315, 290],
            [275, 450],
            [270, 620],
            [453, 290],
            [493, 450],
            [500, 620],
            [350, 590],
            [345, 810],
            [340, 1080],
            [418, 590],
            [423, 810],
            [428, 1080],
            [363, 153],
            [405, 153],
            [346, 171],
            [422, 171],
        ],
    },
    "walking-three-quarter-v1": {
        "id": "walking-three-quarter-v1",
        "label": "Walking — three-quarter view",
        "width": 768,
        "height": 1152,
        "points": [
            [360, 170],
            [375, 285],
            [320, 300],
            [290, 455],
            [275, 640],
            [435, 300],
            [465, 455],
            [485, 635],
            [355, 590],
            [310, 790],
            [245, 1080],
            [415, 590],
            [455, 800],
            [530, 1010],
            [345, 165],
            [375, 165],
            [330, 180],
            [397, 180],
        ],
    },
}
SUGGESTED_POSES = {
    "seated-front-v1": "sitting on a chair, both feet on the floor, hands resting on thighs",
    "standing-front-v1": (
        "standing facing forward, arms relaxed at the sides, both feet on the floor"
    ),
    "walking-three-quarter-v1": (
        "walking slowly, three-quarter view, both arms relaxed down, "
        "one foot forward and the other trailing"
    ),
}


def body_guide(identifier: str) -> dict[str, Any]:
    if identifier not in GUIDES:
        raise ValueError("invalid_pose_guide")
    return deepcopy(GUIDES[identifier])


def available_body_guides() -> list[dict[str, Any]]:
    # Form suggestions are editable metadata, outside the frozen model condition.
    return [
        {**body_guide(identifier), "suggested_pose": SUGGESTED_POSES[identifier]}
        for identifier in GUIDES
    ]


def guide_sha256(guide: dict[str, Any]) -> str:
    return sha256(canonical_json(guide)).hexdigest()


def control_notice(provenance: dict[str, Any]) -> str:
    runtime = provenance.get("runtime", {})
    if (
        isinstance(runtime, dict)
        and runtime.get("pose_control_repo") == CONTROL_REPO
        and runtime.get("pose_control_revision") == CONTROL_REVISION
        and runtime.get("pose_control_weights_sha256") == CONTROL_SHA256
    ):
        return (
            "Pose guidance: " + CONTROL_REPO + "@" + CONTROL_REVISION + "; Apache-2.0. "
            "Model by xocialize; trained with ai-toolkit on attributed Wikimedia Commons "
            "and Pexels media; source media not included. "
            "https://huggingface.co/" + CONTROL_REPO
        )
    return ""
