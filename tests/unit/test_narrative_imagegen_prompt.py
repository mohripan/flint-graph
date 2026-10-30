"""Server-built portrait prompts: exact, bounded and steered toward safe output."""

import pytest

from flint_graph.narrative.imagegen import (
    CHARACTER_TYPES,
    FRAMINGS,
    MAX_APPEARANCE,
    portrait_request,
)


def test_portrait_prompt_puts_subject_and_appearance_before_quality_tags():
    request = portrait_request("  silver hair,\n amber   eyes ", "woman", "portrait")
    assert request.prompt == (
        "1girl, mature female, solo, silver hair, amber eyes, upper body, portrait, "
        "looking at viewer, simple background, safe, masterpiece, high score, "
        "great score, absurdres"
    )
    assert request.negative_prompt.startswith("nsfw, explicit, ")
    assert "worst quality" in request.negative_prompt
    assert (request.width, request.height, request.steps, request.guidance) == (832, 1216, 28, 5.0)


def test_types_and_framings_map_to_fixed_tags_and_sizes():
    assert set(CHARACTER_TYPES) == {"girl", "boy", "woman", "man", "other"}
    assert set(FRAMINGS) == {"portrait", "full_body"}
    other = portrait_request("a lantern spirit", "other", "full_body")
    assert other.prompt.startswith("solo, a lantern spirit, full body, standing, ")
    assert portrait_request("x", "boy", "portrait").prompt.startswith("1boy, solo, x, ")


@pytest.mark.parametrize(
    ("appearance", "character_type", "framing"),
    [
        ("", "girl", "portrait"),
        ("   \n ", "girl", "portrait"),
        ("x" * (MAX_APPEARANCE + 1), "girl", "portrait"),
        ("ok", "robot", "portrait"),
        ("ok", "girl", "landscape"),
        ("bad\x00control", "girl", "portrait"),
    ],
)
def test_invalid_portrait_input_is_rejected(appearance, character_type, framing):
    with pytest.raises(ValueError):
        portrait_request(appearance, character_type, framing)
