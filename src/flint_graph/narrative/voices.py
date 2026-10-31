"""Kokoro voices a character can speak with, and the texts a voice job may speak.

Only the English voice packs are offered (Misaki's English G2P with the eSpeak NG
fallback ships with the child); other languages need more G2P packages (ADR 0043).
"""

import re
from dataclasses import dataclass

SPEEDS = (0.7, 1.3)
TEXT_LIMIT = 600
VOCALIZATION_LIMIT = 40
MAX_ITEMS = 24
VOICE_ID = re.compile(r"[ab][fm]_[a-z]{2,20}\Z")


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    accent: str  # "American" or "British"
    gender: str  # "female" or "male"


_NAMES = {
    "af": "alloy aoede bella heart jessica kore nicole nova river sarah sky",
    "am": "adam echo eric fenrir liam michael onyx puck santa",
    "bf": "alice emma isabella lily",
    "bm": "daniel fable george lewis",
}
VOICES = tuple(
    Voice(
        id=f"{prefix}_{name}",
        name=name.capitalize(),
        accent="American" if prefix[0] == "a" else "British",
        gender="female" if prefix[1] == "f" else "male",
    )
    for prefix, names in _NAMES.items()
    for name in names.split()
)
VOICE_IDS = frozenset(voice.id for voice in VOICES)


def clean_voice_text(text: str, mode: str) -> str:
    """One text to speak: a whole line, or a short vocalization such as "fufu"."""
    if mode not in ("full", "vocalization"):
        raise ValueError("Choose full voice or a vocalization.")
    clean = " ".join(text.split())
    limit = VOCALIZATION_LIMIT if mode == "vocalization" else TEXT_LIMIT
    if not clean:
        raise ValueError("There is nothing to say.")
    if len(clean) > limit:
        raise ValueError(
            f"Keep {'vocalizations' if mode == 'vocalization' else 'lines'} to {limit} characters."
        )
    return clean
