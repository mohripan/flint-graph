"""Reviewed content-tag proposals, separate from style and policy instructions."""

from typing import Any

from flint_graph.application.services.narrative_look_tags import (
    COLORS,
    TRAITS,
    validate_observation,
)
from flint_graph.narrative.character_bench import CLOTHING_V1
from flint_graph.narrative.imagegen import ContentPolicy

CONTEXT_TAGS = frozenset(
    "standing sitting walking running kneeling lying arms_crossed arms_behind_back "
    "hands_on_hips hand_on_hip hands_in_lap holding holding_flower holding_book holding_cup "
    "looking_at_viewer looking_away looking_back from_behind from_side profile full_body "
    "upper_body cowboy_shot close-up indoors outdoors night day sunset scenery forest "
    "city street train_interior chair bench window long_sleeves short_sleeves sleeveless "
    "wide_sleeves detached_sleeves cuffs buttons".split()
)
CLOTHING_MODIFIERS = frozenset(COLORS) | {
    "school",
    "military",
    "hooded",
    "collared",
    "open",
    "frilled",
    "striped",
    "plaid",
    "torn",
    "fingerless",
    "knee",
    "high",
    "thigh",
}
CONTENT_TAGS = (
    TRAITS
    | CLOTHING_V1
    | CONTEXT_TAGS
    | {f"{modifier}_{garment}" for modifier in CLOTHING_MODIFIERS for garment in CLOTHING_V1}
)


def caption_suggestion(result: dict[str, Any], policy: ContentPolicy) -> dict[str, Any]:
    validate_observation(result)
    selected: list[dict[str, str | float]] = []
    caption = ""
    for tag, confidence in sorted(
        result["general_tags"].items(), key=lambda item: (-item[1], item[0])
    ):
        if confidence < 0.35 or tag not in CONTENT_TAGS:
            continue
        text = tag.replace("_", " ")
        proposed = ", ".join(filter(None, (caption, text)))
        if len(proposed) > 600 or len(selected) >= 48:
            continue
        try:
            policy.check(proposed)
        except ValueError:
            continue
        caption = proposed
        selected.append({"tag": text, "confidence": confidence})
    return {
        "caption": caption,
        "tags": selected,
        "caption_version": "training-caption-v1",
        "requires_review": True,
    }
