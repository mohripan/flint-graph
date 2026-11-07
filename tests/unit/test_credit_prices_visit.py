"""Invited people are here to play for a short while, and the default credits must fit that."""

from flint_graph.application.credit_prices import PRICE_ITEMS
from flint_graph.config import Settings

# About 15 minutes: a short chat, two characters, a place, a few voiced lines, a song, a build.
A_SHORT_VISIT = {
    "assistant.ollama": 10,
    "image.high_res": 8,  # Two sets of four high-resolution sprites.
    "image.standard": 4,  # A set of four backgrounds.
    "voice.kokoro-82m": 5,
    "music.track": 1,
    "release.build": 1,
}


def cost_of(visit: dict[str, int]) -> int:
    return sum(PRICE_ITEMS[item].credits * quantity for item, quantity in visit.items())


def test_the_default_credits_cover_a_short_visit_without_covering_much_more():
    credits = Settings(env="test").access_default_credits
    assert credits == 100
    assert cost_of(A_SHORT_VISIT) <= credits
    # Twice that is no longer a short visit.
    assert cost_of(A_SHORT_VISIT) * 2 > credits


def test_a_release_build_costs_little_because_it_uses_no_gpu():
    build = PRICE_ITEMS["release.build"].credits
    assert build == 5
    assert build < cost_of({"image.high_res": 4}), "less than one set of sprites"
    assert build < PRICE_ITEMS["music.track"].credits
