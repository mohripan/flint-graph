"""Server-built portrait prompts: exact, bounded and steered toward safe output."""

import pytest

from flint_graph.narrative.imagegen import (
    CHARACTER_TYPES,
    CUTOUT_TAGS,
    EXPRESSION_TAGS,
    FRAMINGS,
    MAX_APPEARANCE,
    NEGATIVE,
    appearance_tags,
    background_request,
    expression_request,
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
    assert portrait_request("x", "boy", "portrait").prompt.startswith("1boy, male focus, solo, x, ")
    assert portrait_request("x", "man", "portrait").prompt.startswith(
        "1boy, mature male, male focus, solo, x, "
    )


def test_reported_androgynous_boy_becomes_tags_the_model_knows():
    # 2026-10-31: this description produced four long-haired girls in robes.
    request = portrait_request(
        "shoulder-length white hair, red eyes, his face looks like a girl", "boy", "full_body"
    )
    assert request.prompt == (
        "1boy, male focus, solo, white hair, medium hair, red eyes, androgynous, "
        "full body, standing, looking at viewer, simple background, safe, masterpiece, "
        "high score, great score, absurdres"
    )
    assert request.negative_prompt == NEGATIVE + (
        ", 1girl, female focus, breasts, long hair, very long hair"
    )


@pytest.mark.parametrize(
    ("character_type", "extra"),
    [
        ("boy", ", 1girl, female focus, breasts"),
        ("man", ", 1girl, female focus, breasts"),
        ("girl", ", 1boy, male focus"),
        ("woman", ", 1boy, male focus"),
        ("other", ""),
    ],
)
def test_negative_prompt_excludes_the_opposite_type(character_type, extra):
    request = portrait_request("blue eyes", character_type, "portrait")
    assert request.negative_prompt == NEGATIVE + extra
    assert request.negative_prompt.startswith("nsfw, explicit, ")


@pytest.mark.parametrize(
    ("appearance", "tags"),
    [
        ("shoulder-length hair", ["medium hair"]),
        ("Shoulder length black hair", ["black hair", "medium hair"]),
        ("chin-length brown hair", ["brown hair", "short hair"]),
        ("medium-length hair", ["medium hair"]),
        ("waist-length silver hair", ["silver hair", "very long hair"]),
        ("floor-length hair", ["absurdly long hair"]),
        ("long silver hair", ["silver hair", "long hair"]),
        ("short messy black hair", ["messy black hair", "short hair"]),
        ("white-haired, red-eyed", ["white hair", "red eyes"]),
        ("green haired", ["green hair"]),
        ("knee-length skirt", ["knee-length skirt"]),
        ("long coat", ["long coat"]),
        ("medium hair, shoulder-length hair", ["medium hair"]),
        ("1boy, solo, blue eyes", ["blue eyes"]),
        ("silver hair\namber eyes; scar.  Calm", ["silver hair", "amber eyes", "scar", "Calm"]),
        ("a lantern spirit", ["a lantern spirit"]),
    ],
)
def test_common_phrases_become_danbooru_tags(appearance, tags):
    assert appearance_tags(appearance, "boy") == tags


@pytest.mark.parametrize(
    ("appearance", "character_type", "tags"),
    [
        ("his face looks like a girl", "boy", ["androgynous"]),
        ("looks like a woman", "man", ["androgynous"]),
        ("girlish face", "boy", ["androgynous"]),
        ("a girl's face", "boy", ["androgynous"]),
        ("feminine features", "man", ["androgynous"]),
        ("her face looks like a boy", "girl", ["androgynous"]),
        ("boyish face", "woman", ["androgynous"]),
        # Only the opposite type signals androgyny; other words stay the creator's.
        ("looks like a girl", "girl", ["looks like a girl"]),
        ("looks like a girl", "other", ["looks like a girl"]),
        ("dressed like a girl", "boy", ["dressed like a girl"]),
    ],
)
def test_opposite_type_looks_become_androgynous(appearance, character_type, tags):
    assert appearance_tags(appearance, character_type) == tags


@pytest.mark.parametrize(
    ("appearance", "extra"),
    [
        ("short hair", ", long hair, very long hair"),
        ("very short hair", ", long hair, very long hair"),
        ("chin-length hair", ", long hair, very long hair"),
        ("long hair", ""),
        ("short hair, long hair", ""),
        ("blue eyes", ""),
    ],
)
def test_a_short_stated_hair_length_pushes_back_on_long_hair(appearance, extra):
    request = portrait_request(appearance, "girl", "portrait")
    assert request.negative_prompt == NEGATIVE + ", 1boy, male focus" + extra


def test_longest_negative_is_fixed():
    # Measured at 68 of CLIP's 77 tokens with Animagine's tokenizers; longer is truncated.
    request = portrait_request("short hair", "boy", "portrait")
    assert request.negative_prompt == NEGATIVE + (
        ", 1girl, female focus, breasts, long hair, very long hair"
    )


def test_longest_sprite_negative_is_fixed():
    # Measured at 76 of CLIP's 77 tokens with Animagine's tokenizers; longer is truncated.
    request = portrait_request("short hair", "boy", "full_body", transparent=True)
    assert request.negative_prompt == NEGATIVE + (
        ", 1girl, female focus, breasts, long hair, very long hair"
        ", feet out of frame, gradient background"
    )


def test_transparent_sprites_are_full_body_on_a_plain_white_background():
    opaque = portrait_request("silver hair", "girl", "full_body")
    sprite = portrait_request("silver hair", "girl", "full_body", transparent=True)
    framing = FRAMINGS["full_body"][0]
    assert CUTOUT_TAGS == "white background"
    assert sprite.prompt == opaque.prompt.replace(f"{framing}, ", f"{framing}, {CUTOUT_TAGS}, ", 1)
    assert sprite.negative_prompt.startswith(NEGATIVE + ", ")
    for tag in ("feet out of frame", "gradient background"):
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


def test_expression_prompts_put_the_expression_first_and_use_the_appearance_tags():
    request = expression_request(
        "shoulder-length white hair, red eyes", "boy", ["happy", "Fond of tea"]
    )
    assert request.ids == ("happy", "fond_of_tea")
    happy, custom = request.prompts
    assert happy.startswith("1boy, male focus, solo, close-up, face, smile, open mouth, happy, ")
    assert "medium hair" in happy and "white hair" in happy and "red eyes" in happy
    assert happy.endswith("white background, safe, masterpiece, high score, great score, absurdres")
    assert "looking at viewer" not in happy
    assert "close-up, face, fond of tea, " in custom
    assert request.negative_prompt.endswith(
        "1girl, female focus, breasts, long hair, very long hair, expressionless"
    )
    assert (request.steps, request.guidance, request.strength) == (28, 6.0, 0.9)
    assert set(EXPRESSION_TAGS) >= {"happy", "sad", "angry", "surprised", "embarrassed", "thinking"}


@pytest.mark.parametrize(
    "expressions",
    [
        [],
        ["happy"] * 2,
        ["happy", "sad", "angry", "smug", "worried"],
        ["<script>"],
        ["x" * 41],
        [""],
        ["happy", "Happy"],
    ],
)
def test_expression_lists_are_bounded_unique_and_plain(expressions):
    with pytest.raises(ValueError):
        expression_request("", "girl", expressions)


def test_expressions_work_without_an_appearance_description():
    request = expression_request("", "other", ["surprised"])
    assert request.prompts == (
        "solo, close-up, face, surprised, wide-eyed, open mouth, :o, raised eyebrows, "
        "white background, safe, masterpiece, high score, great score, absurdres",
    )
