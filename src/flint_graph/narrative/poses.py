"""The pinned first pose model's bounded editing request."""

from flint_graph.narrative.imagegen import ContentPolicy, ImageRequest, clean_appearance
from flint_graph.prompts.source import render

MODEL_ID = "flux2-klein-4b"
MODEL_REPO = "black-forest-labs/FLUX.2-klein-4B"
MODEL_REVISION = "e7b7dc27f91deacad38e78976d1f2b499d76a294"
POSE_WIDTH, POSE_HEIGHT = 768, 1152


def pose_request(appearance: str, pose: str, *, policy: ContentPolicy) -> ImageRequest:
    appearance, pose = clean_appearance(appearance), clean_appearance(pose)
    if not pose or len(pose) > 300:
        raise ValueError("Describe the pose in 1-300 characters.")
    policy.check(appearance)
    policy.check(pose)
    return ImageRequest(
        prompt=render("narrative.image.pose", appearance=appearance, pose=pose),
        # This distilled editing model does not implement SDXL negative conditioning.
        negative_prompt="",
        width=POSE_WIDTH,
        height=POSE_HEIGHT,
        steps=4,
        guidance=1.0,
    )
