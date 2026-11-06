"""Credit prices, price items and out-of-credit messages (ADR 0059)."""

import pytest
from pydantic import ValidationError

from flint_graph.application.credit_prices import (
    PRICE_ITEMS,
    assistant_item,
    clean_price_overrides,
    cost,
    image_item,
    resolve_prices,
    training_blocks,
    training_item,
    voice_item,
)
from flint_graph.application.services.access import KINDS, credit_problem
from flint_graph.config import Settings
from flint_graph.narrative.voice_models import MODELS


def test_every_item_has_a_kind_a_label_and_a_whole_price():
    assert PRICE_ITEMS
    for item_id, item in PRICE_ITEMS.items():
        assert item.id == item_id
        assert item.kind in KINDS and item_id.startswith(item.kind + ".")
        assert item.label and item.unit
        assert isinstance(item.credits, int) and 0 < item.credits <= 100_000
        assert item.per >= 1
    # Every voice model in the catalog has its own price, so none is free by accident.
    for model_id in MODELS:
        assert voice_item(model_id) in PRICE_ITEMS
    for provider in ("deterministic", "ollama", "anthropic"):
        assert assistant_item(provider) in PRICE_ITEMS


def test_cheap_work_costs_less_than_expensive_work():
    price = {item_id: item.credits for item_id, item in PRICE_ITEMS.items()}
    assert price["voice.kokoro-82m"] < price["voice.chatterbox"] < price["voice.indextts-2.5"]
    assert price["image.standard"] < price["image.high_res"] < price["image.cg"]
    assert price["image.high_res"] < price["image.pose"]
    assert price["assistant.ollama"] < price["assistant.anthropic"]
    assert price["release.build"] > price["image.pose"]
    assert price["training.style"] < price["training.character"]
    assert price["training.character"] < price["training.character_reference"]


def test_image_jobs_pick_their_item_from_what_they_make():
    assert image_item("background", transparent=False, hires=False) == "image.standard"
    assert image_item("character_portrait", transparent=False, hires=False) == "image.standard"
    assert image_item("character_portrait", transparent=True, hires=False) == "image.sprite"
    assert image_item("character_portrait", transparent=True, hires=True) == "image.high_res"
    assert image_item("character_portrait", transparent=False, hires=True) == "image.high_res"
    assert image_item("character_expression", transparent=False, hires=False) == (
        "image.expression"
    )
    assert image_item("scene_art", transparent=False, hires=False) == "image.cg"
    assert image_item("character_portrait", transparent=True, hires=False, pose=True) == (
        "image.pose"
    )
    assert (
        image_item("character_portrait", transparent=True, hires=False, pose=True, repair=True)
        == "image.pose_repair"
    )
    with pytest.raises(ValueError):
        image_item("mystery", transparent=False, hires=False)


def test_training_is_priced_per_hundred_steps_by_target():
    assert training_item(character=False, reference=False) == "training.style"
    assert training_item(character=True, reference=False) == "training.character"
    assert training_item(character=True, reference=True) == "training.character_reference"
    assert [training_blocks(steps) for steps in (20, 100, 101, 200, 400)] == [1, 1, 2, 2, 4]
    prices = resolve_prices({})
    assert cost(prices, "training.character", training_blocks(200)) == 2 * 25
    assert cost(prices, "voice.kokoro-82m", 3) == 3
    with pytest.raises(KeyError):
        cost(prices, "voice.unknown", 1)


def test_overrides_change_single_prices_and_refuse_unknown_items():
    prices = resolve_prices({"image.pose": 12, "voice.kokoro-82m": 0})
    assert prices["image.pose"].credits == 12
    assert prices["voice.kokoro-82m"].credits == 0
    assert prices["image.standard"].credits == PRICE_ITEMS["image.standard"].credits
    assert PRICE_ITEMS["image.pose"].credits != 12  # the code table is not changed
    assert clean_price_overrides({"release.build": 40}) == {"release.build": 40}
    for bad in (
        {"image.gold": 1},
        {"image.pose": -1},
        {"image.pose": 100_001},
        {"image.pose": 2.5},
        {"image.pose": True},
        ["image.pose"],
    ):
        with pytest.raises(ValueError):
            clean_price_overrides(bad)


def test_settings_validate_prices_and_default_credits(monkeypatch):
    monkeypatch.setenv("FLINT_GRAPH_ACCESS_CREDIT_PRICES", '{"image.pose": 10}')
    monkeypatch.setenv("FLINT_GRAPH_ACCESS_DEFAULT_CREDITS", "250")
    settings = Settings(env="test")
    assert settings.access_credit_prices == {"image.pose": 10}
    assert settings.access_default_credits == 250
    assert Settings(env="test", access_credit_prices={}).access_default_credits == 250
    monkeypatch.delenv("FLINT_GRAPH_ACCESS_DEFAULT_CREDITS")
    assert Settings(env="test").access_default_credits == 500
    with pytest.raises(ValidationError):
        Settings(env="test", access_credit_prices={"image.gold": 1})
    with pytest.raises(ValidationError):
        Settings(env="test", access_default_credits=-1)


def test_out_of_credit_messages_name_the_cost_the_balance_and_the_action():
    prices = resolve_prices({})
    one = credit_problem(prices["release.build"], quantity=1, balance=10)
    assert one == (
        "Release build costs 25 credits, but you have 10 left."
        " Ask the person who invited you for more credits."
    )
    many = credit_problem(prices["image.sprite"], quantity=4, balance=5)
    assert many.startswith("4 × Transparent sprite costs 12 credits (3 each), but you have 5 left.")
    blocks = credit_problem(prices["training.character"], quantity=2, balance=0)
    assert blocks.startswith(
        "Character training costs 50 credits (25 per 100 training steps), but you have none left."
    )
    single = credit_problem(prices["voice.kokoro-82m"], quantity=2, balance=1)
    assert "costs 2 credits (1 each), but you have 1 left." in single
