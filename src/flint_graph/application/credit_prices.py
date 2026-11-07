"""What each kind of generation costs in credits (ADR 0059).

Prices live in code so a review sees every change; a deployment may override single
items with ``FLINT_GRAPH_ACCESS_CREDIT_PRICES``. This module must not import settings:
the settings validate their overrides with it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from math import ceil

from flint_graph.narrative.voice_models import MODELS

MAX_PRICE = 100_000


@dataclass(frozen=True, slots=True)
class PriceItem:
    id: str
    # The usage kind whose caps (ADR 0058) also count this item.
    kind: str
    credits: int
    label: str
    unit: str
    # A quantity is counted in blocks of this many units (training steps).
    per: int = 1


def _item(item_id: str, credits: int, label: str, unit: str, per: int = 1) -> PriceItem:
    return PriceItem(item_id, item_id.split(".", 1)[0], credits, label, unit, per)


_VOICE_PRICES = {
    "kokoro-82m": 1,
    "chatterbox-turbo": 2,
    "chatterbox": 3,
    "chatterbox-multilingual": 3,
    "qwen3-tts-voices": 3,
    "qwen3-tts-clone": 4,
    "indextts-2.5": 5,
}

PRICE_ITEMS: dict[str, PriceItem] = {
    item.id: item
    for item in (
        _item("image.expression", 1, "Expression", "image"),
        _item("image.standard", 2, "Standard image", "image"),
        _item("image.sprite", 3, "Transparent sprite", "image"),
        _item("image.high_res", 5, "High-resolution image", "image"),
        _item("image.cg", 6, "Event CG", "image"),
        _item("image.pose_repair", 6, "Pose repair", "image"),
        _item("image.pose", 8, "Pose", "image"),
        *(
            _item(f"voice.{model_id}", credits, f"{MODELS[model_id].name} line", "line")
            for model_id, credits in _VOICE_PRICES.items()
        ),
        _item("music.track", 10, "Music track", "track"),
        _item("assistant.deterministic", 1, "Assistant reply (test model)", "turn"),
        _item("assistant.ollama", 2, "Assistant reply (local model)", "turn"),
        _item("assistant.anthropic", 10, "Assistant reply (Claude)", "turn"),
        # No GPU: only some CPU and storage (ADR 0075).
        _item("release.build", 5, "Release build", "build"),
        _item("training.style", 20, "Project style training", "100 training steps", 100),
        _item("training.character", 25, "Character training", "100 training steps", 100),
        _item(
            "training.character_reference",
            30,
            "Character training with reference",
            "100 training steps",
            100,
        ),
    )
}


def clean_price_overrides(value: object) -> dict[str, int]:
    """Validated ``{item: credits}`` overrides; raises ValueError naming the problem."""
    if not isinstance(value, Mapping):
        raise ValueError("Credit prices must map a price item to its credits.")
    cleaned: dict[str, int] = {}
    for item_id, credits in value.items():
        if item_id not in PRICE_ITEMS:
            raise ValueError(f"Unknown price item: {item_id}.")
        if isinstance(credits, bool) or not isinstance(credits, int):
            raise ValueError(f"The price of {item_id} must be a whole number of credits.")
        if not 0 <= credits <= MAX_PRICE:
            raise ValueError(f"The price of {item_id} must be between 0 and {MAX_PRICE}.")
        cleaned[str(item_id)] = credits
    return cleaned


def resolve_prices(overrides: Mapping[str, int] | None) -> dict[str, PriceItem]:
    """The code table with a deployment's overrides applied."""
    cleaned = clean_price_overrides(overrides or {})
    return {
        item_id: replace(item, credits=cleaned[item_id]) if item_id in cleaned else item
        for item_id, item in PRICE_ITEMS.items()
    }


def cost(prices: Mapping[str, PriceItem], item_id: str, quantity: int) -> int:
    return prices[item_id].credits * quantity


def image_item(
    purpose: str, *, transparent: bool, hires: bool, pose: bool = False, repair: bool = False
) -> str:
    """The price item of one image candidate."""
    if pose:
        return "image.pose_repair" if repair else "image.pose"
    if purpose == "scene_art":
        return "image.cg"
    if purpose == "character_expression":
        return "image.expression"
    if purpose not in ("character_portrait", "background"):
        raise ValueError(f"Unknown image purpose: {purpose}.")
    if hires:
        return "image.high_res"
    return "image.sprite" if transparent else "image.standard"


def voice_item(model_id: str) -> str:
    return f"voice.{model_id}"


def assistant_item(provider: str) -> str:
    return f"assistant.{provider}"


def training_item(*, character: bool, reference: bool) -> str:
    if not character:
        return "training.style"
    return "training.character_reference" if reference else "training.character"


def training_blocks(steps: int) -> int:
    """Training is priced per 100 steps, rounded up."""
    return max(1, ceil(steps / 100))
