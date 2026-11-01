"""Explicit real-model qualification, never part of the offline test suite."""

import hashlib
import os
from pathlib import Path

import pytest

from flint_graph.config import Settings
from flint_graph.infrastructure.narrative_posegen import PoseGenerationRequest
from flint_graph.narrative.imagegen import content_policy
from flint_graph.narrative.poses import pose_request
from flint_graph.processes.narrative_pose_worker import build_generator

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("FLINT_GRAPH_NARRATIVE_POSE_LIVE") != "1",
    reason="Opt in to the installed pose model and otherwise idle GPU",
)


async def test_real_editing_model_returns_a_verified_transparent_pose():
    settings = Settings(env="test")
    generator = build_generator(settings)
    reference = (ROOT / "evals/character-preservation/pilot-v1/references/aster.png").read_bytes()
    prompt = pose_request(
        "adult, white bob hair, red eyes, blue coat with gold trim, "
        "red scarf, dark trousers, boots",
        "sitting on a chair, hands resting in lap",
        policy=content_policy(None),
    )
    request = PoseGenerationRequest(
        prompt=prompt.prompt,
        negative_prompt="",
        width=768,
        height=1152,
        steps=4,
        guidance=1,
        seeds=(187,),
        reference=reference,
        cutout=True,
    )
    progress = []

    async def update(done):
        progress.append(done)

    result = await generator.generate(request, on_progress=update)
    assert result.images[0].data[25] == 6
    assert result.images[0].box is not None
    assert result.images[0].width > 64 and result.images[0].height > 64
    assert result.images[0].seed == 187 and 1 in progress
    assert result.runtime["source_sha256"] == hashlib.sha256(reference).hexdigest()
    assert result.runtime["direct_cuda_loading"] == "true"
    assert result.runtime["text_encoder_released_before_transformer"] == "true"
    assert result.cutout is not None and result.truncated is False
