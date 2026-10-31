"""Exact, bounded image prompts built from structured creator input (ADR 0039).

The server owns the prompt so every stored job records exactly what the model saw.
Tags follow Animagine XL 4.0's recommended order: subject, appearance, framing,
rating and quality. The ``safe`` rating tag and explicit-content negative prompt
steer output; creator review before approval remains the control.

Animagine is trained on Danbooru tags, so a fixed phrase map turns common
natural-language looks ("shoulder-length", "face looks like a girl") into tags it
knows. The map is deterministic and local: the same description always yields the
same recorded prompt. Text it does not recognize passes through unchanged.
"""

import re
import unicodedata
from dataclasses import dataclass

MAX_APPEARANCE = 600
CHARACTER_TYPES = {
    "girl": "1girl",
    "boy": "1boy, male focus",
    "woman": "1girl, mature female",
    "man": "1boy, mature male, male focus",
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
# Without these, a girl-leaning word or look in the description beats "1boy".
# CLIP reads 77 tokens; the longest negative (boy or man, short hair) measures 68.
TYPE_NEGATIVES = {
    "girl": "1boy, male focus",
    "boy": "1girl, female focus, breasts",
    "woman": "1boy, male focus",
    "man": "1girl, female focus, breasts",
    "other": "",
}
SHORT_LENGTHS = ("very short hair", "short hair", "medium hair")
LONG_LENGTHS = ("long hair", "very long hair", "absurdly long hair")
# The model's prior toward long hair otherwise overrides a shorter stated length.
LONG_HAIR_NEGATIVE = "long hair, very long hair"

# "<reach>-length hair", by where Danbooru's length tags end.
_REACH = {
    "ear": "short hair",
    "chin": "short hair",
    "jaw": "short hair",
    "neck": "medium hair",
    "shoulder": "medium hair",
    "collarbone": "medium hair",
    "medium": "medium hair",
    "mid": "medium hair",
    "back": "long hair",
    "mid-back": "long hair",
    "waist": "very long hair",
    "hip": "very long hair",
    "knee": "very long hair",
    "ankle": "absurdly long hair",
    "floor": "absurdly long hair",
}
_REACH_LENGTH = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, _REACH), key=len, reverse=True)) + r")[- ]length\b",
    re.IGNORECASE,
)
_LEADING_LENGTH = re.compile(
    r"^(very short|short|medium|long|very long|absurdly long) (?!hair$)(.+ hair)$", re.IGNORECASE
)
_HAIRED = re.compile(r"\b([a-z]+)[- ]haired\b", re.IGNORECASE)
_EYED = re.compile(r"\b([a-z]+)[- ]eyed\b", re.IGNORECASE)
_LOOK = r"(?:face|looks?|looking|appears?|appearance|resembles?|features?)"
_FEATURES = r"(?:face|features|looks|appearance)"


def _looks_like(nouns: str, adjectives: str) -> re.Pattern[str]:
    return re.compile(
        rf"\b{_LOOK}\b.*\b(?:{nouns})s?\b|\b(?:{nouns})(?:'s)?\s+{_FEATURES}\b"
        rf"|\b(?:{adjectives})\s+{_FEATURES}\b",
        re.IGNORECASE,
    )


# A boy who looks like a girl (or the reverse) is androgyny, not a second subject.
# Left as words, "girl" competes with "1boy" and usually wins.
_FEMININE = _looks_like("girl|woman|lady", "girlish|girly|feminine|effeminate|womanly")
_MASCULINE = _looks_like("boy|man|guy", "boyish|masculine|manly")
_ANDROGYNY = {"boy": _FEMININE, "man": _FEMININE, "girl": _MASCULINE, "woman": _MASCULINE}
# Stage sprites are cut out of a plain white background, which the segmenter
# separates most cleanly; the whole figure has to stay inside the frame. The
# positive "simple background, white background" already rules out scenery; these
# two keep the longest sprite negative (boy or man, short hair) at 76 of 77 tokens.
CUTOUT_TAGS = "white background"
CUTOUT_NEGATIVE = "feet out of frame, gradient background"


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


def _segment_tags(segment: str, character_type: str) -> list[str]:
    androgyny = _ANDROGYNY.get(character_type)
    if androgyny is not None and androgyny.search(segment):
        return ["androgynous"]
    text = _EYED.sub(lambda match: f"{match[1].lower()} eyes", segment)
    text = _HAIRED.sub(lambda match: f"{match[1].lower()} hair", text)
    if not re.search(r"\bhair\b", text, re.IGNORECASE):
        return [text]
    if reach := _REACH_LENGTH.search(text):
        rest = re.sub(r"\s+", " ", _REACH_LENGTH.sub("", text, count=1)).strip()
        length = _REACH[reach[1].lower()]
        return [length] if rest.lower() == "hair" else [rest, length]
    if leading := _LEADING_LENGTH.match(text):
        return [leading[2], f"{leading[1].lower()} hair"]
    return [text]


def appearance_tags(appearance: str, character_type: str) -> list[str]:
    """Split a description into tags, mapping common phrases to Danbooru tags."""
    fixed = {"solo", *(tag.strip() for tag in CHARACTER_TYPES[character_type].split(","))}
    tags: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[,;\n]|\.(?=\s|$)", appearance):
        segment = re.sub(r"\s+", " ", raw).strip()
        for tag in _segment_tags(segment, character_type) if segment else ():
            if tag.lower() not in fixed | seen:
                tags.append(tag)
                seen.add(tag.lower())
    return tags


def _portrait_negative(tags: list[str], character_type: str, transparent: bool) -> str:
    parts = [NEGATIVE, TYPE_NEGATIVES[character_type]]
    lengths = {tag.lower() for tag in tags}
    if lengths.intersection(SHORT_LENGTHS) and not lengths.intersection(LONG_LENGTHS):
        parts.append(LONG_HAIR_NEGATIVE)
    if transparent:
        parts.append(CUTOUT_NEGATIVE)
    return ", ".join(part for part in parts if part)


def portrait_request(
    appearance: str, character_type: str, framing: str, *, transparent: bool = False
) -> ImageRequest:
    if character_type not in CHARACTER_TYPES or framing not in FRAMINGS:
        raise ValueError("Unknown character type or framing")
    if transparent and framing != "full_body":
        raise ValueError("Transparent sprites need full-body framing")
    if len(appearance) > MAX_APPEARANCE * 2:
        raise ValueError("Appearance is too long")
    text = clean_appearance(appearance)
    if not text:
        raise ValueError("Describe the character's appearance")
    framing_tags, (width, height) = FRAMINGS[framing]
    # Tags come from the raw text so line breaks still separate them.
    tags = appearance_tags(appearance, character_type)
    parts = [CHARACTER_TYPES[character_type], "solo", *tags, framing_tags, QUALITY]
    if transparent:
        parts.insert(parts.index(framing_tags) + 1, CUTOUT_TAGS)
    return ImageRequest(
        prompt=", ".join(part for part in parts if part),
        negative_prompt=_portrait_negative(tags, character_type, transparent),
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
