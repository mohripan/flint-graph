"""Server-built portrait prompts: exact, bounded and steered toward safe output."""

import pytest

from flint_graph.narrative.imagegen import (
    CHARACTER_TYPES,
    CUTOUT_TAGS,
    DEFAULT_POLICY,
    DEFAULT_POLICY_PATH,
    EXPRESSION_TAGS,
    FRAMINGS,
    HIRES_SCALE,
    HIRES_STRENGTH,
    MAX_APPEARANCE,
    NEGATIVE,
    QUALITY_NEGATIVE,
    SCENE_ADAPTER_SCALE,
    SCENE_SIZE,
    ContentPolicy,
    HiresFix,
    appearance_tags,
    background_request,
    expression_request,
    portrait_request,
    scene_art_request,
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


def test_high_resolution_upscales_the_same_render_and_refines_it():
    standard = portrait_request("silver hair", "girl", "full_body", transparent=True)
    hires = portrait_request("silver hair", "girl", "full_body", transparent=True, hires=True)
    assert standard.hires is None and standard.output_size == (832, 1216)
    assert hires.hires == HiresFix(scale=HIRES_SCALE, strength=HIRES_STRENGTH)
    assert (hires.prompt, hires.negative_prompt) == (standard.prompt, standard.negative_prompt)
    assert (hires.width, hires.height, hires.steps) == (832, 1216, 28), "The base render"
    assert hires.output_size == (round(832 * HIRES_SCALE), round(1216 * HIRES_SCALE))
    assert HIRES_SCALE in (1.5, 2.0) and 0.25 <= HIRES_STRENGTH <= 0.45
    portrait = portrait_request("silver hair", "girl", "portrait", hires=True)
    assert portrait.hires == hires.hires, "Opaque portraits may be sharp too"
    # The output stays inside the strict PNG validator's bounds (4096 px, 16 MP).
    width, height = hires.output_size
    assert width % 8 == 0 and height % 8 == 0
    assert max(width, height) <= 4096 and width * height <= 16_777_216


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


def test_blocked_terms_refuse_descriptions_before_any_job():
    for build in (
        lambda: portrait_request("white hair, Nude", "boy", "full_body"),
        lambda: background_request("a lewd poster on the wall"),
        lambda: expression_request("white hair", "boy", ["happy", "naked"]),
    ):
        with pytest.raises(ValueError, match="blocked"):
            build()
    # Whole words and phrases only, so place names and longer words still work.
    assert background_request("Sussex harbor, sextant on a desk").prompt
    policy = ContentPolicy.create(["nsfw"], ["Sussex", "cat ears"])
    with pytest.raises(ValueError, match='"cat ears"'):
        portrait_request("white hair, CAT  EARS", "girl", "portrait", policy=policy)
    assert portrait_request("white hair, nude", "girl", "portrait", policy=policy).prompt


def test_the_safety_negative_leads_every_negative_prompt_and_can_be_changed():
    assert DEFAULT_POLICY.negative == "nsfw, explicit" and NEGATIVE.startswith("nsfw, explicit, ")
    policy = ContentPolicy.create(["nsfw", "explicit", "sensitive"], [])
    for request in (
        portrait_request("white hair", "girl", "portrait", policy=policy),
        background_request("harbor", policy=policy),
    ):
        assert request.negative_prompt.startswith("nsfw, explicit, sensitive, lowres, ")
    expression = expression_request("white hair", "girl", ["happy"], policy=policy)
    assert expression.negative_prompt.startswith("nsfw, explicit, sensitive, lowres, ")
    bare = portrait_request("white hair", "girl", "portrait", policy=ContentPolicy.create([], []))
    assert bare.negative_prompt.startswith("lowres, ")
    assert portrait_request("white hair", "girl", "portrait").negative_prompt.startswith(NEGATIVE)


def test_policy_lists_are_trimmed_deduplicated_and_bounded():
    policy = ContentPolicy.create([" nsfw ", "", "explicit"], [" Nude", "nude ", "BARE  chest"])
    assert policy.negative == "nsfw, explicit"
    assert policy.blocked == ("nude", "bare chest")
    for negative, blocked in (
        (["nsfw\x00"], []),
        (["a, b"], []),
        ([], ["x" * 61]),
        ([], [str(n) for n in range(201)]),
        ([1], []),
    ):
        with pytest.raises(ValueError):
            ContentPolicy.create(negative, blocked)


def test_the_policy_is_a_versioned_file_not_code(tmp_path):
    shipped = ContentPolicy.load(DEFAULT_POLICY_PATH)
    assert shipped == DEFAULT_POLICY and "nude" in shipped.blocked
    custom = tmp_path / "policy.toml"
    custom.write_text('version = 1\nnegative = ["nsfw"]\nblocked = ["gore"]\n', encoding="utf-8")
    assert ContentPolicy.load(custom) == ContentPolicy.create(["nsfw"], ["gore"])
    for text in (
        "version = 2\nnegative = []\nblocked = []\n",
        'version = 1\nnegative = "nsfw"\nblocked = []\n',
        "version = 1\nnegative = []\n",
        "version = 1\nnegative = []\nblocked = []\nextra = 1\n",
        "not toml",
    ):
        custom.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError):
            ContentPolicy.load(custom)
    with pytest.raises(ValueError):
        ContentPolicy.load(tmp_path / "missing.toml")


QUEN = ("shoulder-length white hair, red eyes, androgynous, casual clothes", "boy")
LINA = ("long black hair, blue eyes, hair ribbon, school uniform", "girl")


def test_scene_art_puts_the_referenced_character_into_the_described_scene():
    request = scene_art_request(" Quen sitting on the couch by the window,\n at night ", [QUEN])
    # Subject, scene, then looks; no "looking at viewer" or plain background in a scene.
    assert request.prompt == (
        "1boy, male focus, solo, Quen sitting on the couch by the window, at night, "
        "white hair, medium hair, red eyes, androgynous, casual clothes, "
        "safe, masterpiece, high score, great score, absurdres"
    )
    assert (request.width, request.height) == SCENE_SIZE == (1344, 768)
    assert (request.steps, request.guidance) == (28, 5.0)
    assert request.adapter_scale == SCENE_ADAPTER_SCALE == 0.5
    # The character's own negatives, a shorter stated length kept, and no second person.
    assert request.negative_prompt.startswith(NEGATIVE + ", 1girl, female focus, breasts, ")
    assert request.negative_prompt.endswith("long hair, very long hair, multiple boys")


def test_scene_art_works_for_any_character_type_and_without_a_description():
    girl = scene_art_request("reading in a library", [("long black hair", "woman")])
    assert girl.prompt.startswith(
        "1girl, mature female, solo, reading in a library, black hair, long hair, safe, "
    )
    assert girl.negative_prompt.endswith("1boy, male focus, multiple girls")
    other = scene_art_request("on a beach at sunset", [("", "other")])
    assert other.prompt == (
        "solo, on a beach at sunset, safe, masterpiece, high score, great score, absurdres"
    )
    assert other.negative_prompt.endswith(QUALITY_NEGATIVE + ", multiple girls, multiple boys")


def test_scene_art_needs_a_bounded_scene_and_refuses_blocked_words():
    for scene in ("", "   ", "x" * (MAX_APPEARANCE + 1)):
        with pytest.raises(ValueError):
            scene_art_request(scene, [QUEN])
    for characters in ([], [QUEN, LINA, QUEN], [("white hair", "dragon")]):
        with pytest.raises(ValueError):
            scene_art_request("on a couch", characters)
    # The scene and every referenced character's own description pass the policy.
    for scene, appearance in (("a NUDE beach", "white hair"), ("on a couch", "hentai, white hair")):
        with pytest.raises(ValueError, match="blocked"):
            scene_art_request(scene, [(appearance, "girl")])
        with pytest.raises(ValueError, match="blocked"):
            scene_art_request(scene, [QUEN, (appearance, "girl")])
    policy = ContentPolicy.create(["nsfw", "sensitive"], ["rain"])
    with pytest.raises(ValueError, match='"rain"'):
        scene_art_request("walking in the rain", [("", "girl")], policy=policy)
    allowed = scene_art_request("walking home", [("", "girl"), QUEN], policy=policy)
    assert allowed.negative_prompt.startswith("nsfw, sensitive, lowres, ")


def test_two_characters_are_counted_and_both_looks_listed():
    request = scene_art_request("sitting on the couch together at night", [QUEN, LINA])
    # Each reference conditions its half; the prompt counts both people and both looks.
    assert request.prompt == (
        "1boy, 1girl, sitting on the couch together at night, white hair, medium hair, "
        "red eyes, androgynous, casual clothes, black hair, long hair, blue eyes, hair ribbon, "
        "school uniform, safe, masterpiece, high score, great score, absurdres"
    )
    assert request.negative_prompt.endswith(QUALITY_NEGATIVE + ", multiple boys, multiple girls")
    assert request.adapter_scale == SCENE_ADAPTER_SCALE


def test_two_characters_of_one_kind_are_counted_together():
    girls = scene_art_request("at the beach", [LINA, ("short red hair", "woman")])
    assert girls.prompt.startswith("2girls, at the beach, ")
    assert girls.negative_prompt.endswith("1boy, male focus, 3girls")
    boys = scene_art_request("at the beach", [QUEN, ("black hair", "man")])
    assert boys.prompt.startswith("2boys, at the beach, ")
    assert boys.negative_prompt.endswith("1girl, female focus, 3boys")
    mixed = scene_art_request("at the beach", [("", "other"), LINA])
    assert mixed.prompt.startswith("1other, 1girl, at the beach, ")
