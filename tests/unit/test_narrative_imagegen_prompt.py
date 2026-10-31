"""Server-built portrait prompts: exact, bounded and steered toward safe output."""

import pytest

from flint_graph.narrative.imagegen import (
    CHARACTER_TYPES,
    CUTOUT_TAGS,
    FRAMINGS,
    MAX_APPEARANCE,
    NEGATIVE,
    background_request,
    portrait_request,
)


def test_background_prompt_is_landscape_scenery_without_people():
    request = background_request(" harbor at dusk,\n fog ")
    assert request.prompt == (
        "no humans, scenery, harbor at dusk, fog, safe, masterpiece, high score, "
        "great score, absurdres"
    )
    assert (request.width, request.height) == (1344, 768)
    assert request.negative_prompt.endswith("1girl, 1boy, people, person, character, crowd")
    for bad in ("", "  ", "x" * (MAX_APPEARANCE + 1)):
        with pytest.raises(ValueError):
            background_request(bad)


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


def test_transparent_sprites_are_full_body_on_a_plain_white_background():
    opaque = portrait_request("silver hair", "girl", "full_body")
    sprite = portrait_request("silver hair", "girl", "full_body", transparent=True)
    framing = FRAMINGS["full_body"][0]
    assert CUTOUT_TAGS == "white background"
    assert sprite.prompt == opaque.prompt.replace(f"{framing}, ", f"{framing}, {CUTOUT_TAGS}, ", 1)
    assert sprite.negative_prompt.startswith(NEGATIVE + ", ")
    for tag in ("feet out of frame", "scenery", "detailed background", "gradient background"):
        assert tag in sprite.negative_prompt and tag not in opaque.negative_prompt
    assert (sprite.width, sprite.height, sprite.steps) == (
        opaque.width,
        opaque.height,
        opaque.steps,
    )
    with pytest.raises(ValueError, match="full-body"):
        portrait_request("silver hair", "girl", "portrait", transparent=True)


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
