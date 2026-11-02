"""Guided image attribution survives package binding and repair provenance."""

from types import SimpleNamespace

from flint_graph.application.services.narrative_package_v2 import Bound, compose_notices
from flint_graph.narrative.pose_guides import CONTROL_REPO, CONTROL_REVISION, CONTROL_SHA256


def test_guided_images_carry_the_pinned_pose_model_credit_in_game_notices():
    runtime = {
        "pose_control_repo": CONTROL_REPO,
        "pose_control_revision": CONTROL_REVISION,
        "pose_control_weights_sha256": CONTROL_SHA256,
        "pose_control_applied": "false",
    }
    asset = SimpleNamespace(
        source="generated",
        license="apache-2.0",
        notice="Approved synthetic image",
        provenance={
            "model_repo": "black-forest-labs/FLUX.2-klein-4B",
            "model_revision": "base",
            "runtime": runtime,
        },
    )
    bound = Bound("aster", "image", "a" * 64, asset)
    text = compose_notices("Creator credit", [bound])
    assert CONTROL_REPO in text and CONTROL_REVISION in text
    assert "Apache-2.0" in text
    assert compose_notices(text, [bound]) == text
    asset.source = "uploaded"
    assert CONTROL_REPO not in compose_notices("", [bound])


def test_deployed_seated_v1_guide_is_byte_identical():
    from flint_graph.narrative.pose_guides import body_guide, guide_sha256

    assert (
        guide_sha256(body_guide("seated-front-v1"))
        == "665c6b7508ec44ab3a132fa5d514a20f16264ce9cd15486c9697d4bc7ebecf0a"
    )
