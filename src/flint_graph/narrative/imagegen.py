"""Exact, bounded image prompts built from structured creator input (ADR 0039).

The server owns the prompt so every stored job records exactly what the model saw.
Tags follow Animagine XL 4.0's recommended order: subject, appearance, framing,
rating and quality. The ``safe`` rating tag and explicit-content negative prompt
steer output; creator review before approval remains the control.
"""

import re
import unicodedata
from dataclasses import dataclass

MAX_APPEARANCE = 600
CHARACTER_TYPES = {
    "girl": "1girl",
    "boy": "1boy",
    "woman": "1girl, mature female",
    "man": "1boy, mature male",
    "other": "",
}
FRAMINGS = {
    "portrait": ("upper body, portrait", (832, 1216)),
    "full_body": ("full body, standing", (832, 1216)),
}
STEPS = 28
GUIDANCE = 5.0
QUALITY = (
    "looking at viewer, simple background, safe, masterpiece, high score, great score, absurdres"
)
NEGATIVE = (
    "nsfw, explicit, lowres, bad anatomy, bad hands, text, error, missing finger, "
    "extra digits, fewer digits, cropped, worst quality, low quality, low score, "
    "bad score, average score, signature, watermark, username, blurry"
)


@dataclass(frozen=True)
class ImageRequest:
    prompt: str
    negative_prompt: str
    width: int
    height: int
    steps: int
    guidance: float


def clean_appearance(appearance: str) -> str:
    """Collapse whitespace; reject control characters and over-long text."""
    if any(unicodedata.category(char) == "Cc" and char not in "\n\t\r" for char in appearance):
        raise ValueError("Appearance contains control characters")
    text = re.sub(r"\s+", " ", appearance).strip()
    if len(text) > MAX_APPEARANCE:
        raise ValueError("Appearance is too long")
    return text


def portrait_request(appearance: str, character_type: str, framing: str) -> ImageRequest:
    if character_type not in CHARACTER_TYPES or framing not in FRAMINGS:
        raise ValueError("Unknown character type or framing")
    if len(appearance) > MAX_APPEARANCE * 2:
        raise ValueError("Appearance is too long")
    text = clean_appearance(appearance)
    if not text:
        raise ValueError("Describe the character's appearance")
    framing_tags, (width, height) = FRAMINGS[framing]
    parts = [CHARACTER_TYPES[character_type], "solo", text, framing_tags, QUALITY]
    return ImageRequest(
        prompt=", ".join(part for part in parts if part),
        negative_prompt=NEGATIVE,
        width=width,
        height=height,
        steps=STEPS,
        guidance=GUIDANCE,
    )


BACKGROUND_SIZE = (1344, 768)
BACKGROUND_QUALITY = "safe, masterpiece, high score, great score, absurdres"
# People in a background would be fixed into every scene that uses it.
BACKGROUND_NEGATIVE = NEGATIVE + ", 1girl, 1boy, people, person, character, crowd"


def background_request(description: str) -> ImageRequest:
    if len(description) > MAX_APPEARANCE * 2:
        raise ValueError("Description is too long")
    text = clean_appearance(description)
    if not text:
        raise ValueError("Describe the place")
    width, height = BACKGROUND_SIZE
    return ImageRequest(
        prompt=", ".join(("no humans", "scenery", text, BACKGROUND_QUALITY)),
        negative_prompt=BACKGROUND_NEGATIVE,
        width=width,
        height=height,
        steps=STEPS,
        guidance=GUIDANCE,
    )
