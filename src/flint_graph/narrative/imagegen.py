"""Exact, bounded image prompts built from structured creator input (ADR 0039).

The server owns the prompt so every stored job records exactly what the model saw.
Tags follow Animagine XL 4.0's recommended order: subject, appearance, framing,
rating and quality. The ``safe`` rating tag and the content policy steer output:
the policy's tags lead every negative prompt, and a description with a blocked word
is refused before a job starts. The policy is a versioned file, not code; creator
review before approval remains the control.

Animagine is trained on Danbooru tags, so a fixed phrase map turns common
natural-language looks ("shoulder-length", "face looks like a girl") into tags it
knows. The map is deterministic and local: the same description always yields the
same recorded prompt. Text it does not recognize passes through unchanged.
"""

import re
import tomllib
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache, partial
from pathlib import Path

from flint_graph.prompts.source import conditioning, current_snapshot, render

MAX_APPEARANCE = 600
CHARACTER_TYPES = conditioning("CHARACTER_TYPES")
FRAMINGS = {
    key: (conditioning("FRAMING_TAGS")[key], (832, 1216)) for key in ("portrait", "full_body")
}
STEPS = 28
GUIDANCE = 5.0
QUALITY = conditioning("QUALITY")
QUALITY_NEGATIVE = conditioning("QUALITY_NEGATIVE")
# The shipped policy; FLINT_GRAPH_NARRATIVE_IMAGE_CONTENT_POLICY points at another copy.
DEFAULT_POLICY_PATH = Path(__file__).with_name("image_content_policy.toml")
POLICY_VERSION = 1
MAX_POLICY_TERMS = 200
MAX_POLICY_TERM = 60


def _terms(values: Sequence[object]) -> list[str]:
    terms: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("Content policy entries are strings")
        term = " ".join(value.lower().split())
        if any(unicodedata.category(char) == "Cc" for char in value) or "," in term:
            raise ValueError("Content policy entries are single tags or phrases")
        if len(term) > MAX_POLICY_TERM:
            raise ValueError(f"Content policy entries are at most {MAX_POLICY_TERM} characters")
        if term and term not in terms:
            terms.append(term)
    if len(terms) > MAX_POLICY_TERMS:
        raise ValueError(f"A content policy list has at most {MAX_POLICY_TERMS} entries")
    return terms


@dataclass(frozen=True)
class ContentPolicy:
    """Tags that lead every negative prompt and words that refuse a description."""

    negative: str
    blocked: tuple[str, ...]

    @classmethod
    def create(cls, negative: Sequence[object], blocked: Sequence[object]) -> "ContentPolicy":
        return cls(", ".join(_terms(negative)), tuple(_terms(blocked)))

    @classmethod
    def load(cls, path: str | Path) -> "ContentPolicy":
        try:
            data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise ValueError(f"Cannot read the image content policy: {error}") from None
        if set(data) != {"version", "negative", "blocked"} or data["version"] != POLICY_VERSION:
            raise ValueError("The image content policy has version = 1, negative and blocked")
        if not isinstance(data["negative"], list) or not isinstance(data["blocked"], list):
            raise ValueError("The image content policy's negative and blocked are lists")
        return cls.create(data["negative"], data["blocked"])

    def check(self, text: str) -> None:
        folded = " ".join(text.lower().split())
        for term in self.blocked:
            if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", folded):
                raise ValueError(f'"{term}" is blocked in image descriptions')


def _catalog_policy() -> ContentPolicy:
    data = current_snapshot().entry("narrative.image.content_policy").config
    if (
        set(data) != {"version", "negative", "blocked"}
        or type(data["version"]) is not int
        or data["version"] != POLICY_VERSION
    ):
        raise ValueError("Invalid catalog image content policy")
    if not isinstance(data["negative"], list) or not isinstance(data["blocked"], list):
        raise ValueError("Image policy entries must be lists")
    return ContentPolicy.create(data["negative"], data["blocked"])


DEFAULT_POLICY = _catalog_policy()


@lru_cache(maxsize=4)
def _legacy_policy_file(path: str) -> ContentPolicy:
    return ContentPolicy.load(path)


def content_policy(path: str | None) -> ContentPolicy:
    """The scoped catalog policy, or an explicit legacy operator file override."""
    return _catalog_policy() if path is None else _legacy_policy_file(path)


def _negative(policy: ContentPolicy) -> str:
    return ", ".join(part for part in (policy.negative, conditioning("QUALITY_NEGATIVE")) if part)


NEGATIVE = _negative(DEFAULT_POLICY)
# Without these, a girl-leaning word or look in the description beats "1boy".
# CLIP reads 77 tokens; the longest negative (boy or man, short hair) measures 68.
TYPE_NEGATIVES = conditioning("TYPE_NEGATIVES")
SHORT_LENGTHS = tuple(conditioning("SHORT_LENGTHS"))
LONG_LENGTHS = tuple(conditioning("LONG_LENGTHS"))
# The model's prior toward long hair otherwise overrides a shorter stated length.
LONG_HAIR_NEGATIVE = conditioning("LONG_HAIR_NEGATIVE")

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
CUTOUT_TAGS = conditioning("CUTOUT_TAGS")
CUTOUT_NEGATIVE = conditioning("CUTOUT_NEGATIVE")


# High resolution ("hires fix"): the base render is upscaled with Lanczos, then the
# same model repaints it lightly at the larger size (img2img with the same prompt and
# seed), which adds real detail instead of stretched pixels. Strength is the share of
# the denoising schedule that is rerun: low keeps the composition, high redraws it.
HIRES_SCALES = (1.5, 2.0)
HIRES_STRENGTHS = (0.2, 0.6)
HIRES_SCALE = 2.0
HIRES_STRENGTH = 0.35


@dataclass(frozen=True)
class HiresFix:
    scale: float
    strength: float

    def valid(self) -> bool:
        low, high = HIRES_STRENGTHS
        return self.scale in HIRES_SCALES and low <= self.strength <= high

    def size(self, width: int, height: int) -> tuple[int, int]:
        return round(width * self.scale), round(height * self.scale)


@dataclass(frozen=True)
class ImageRequest:
    prompt: str
    negative_prompt: str
    width: int
    height: int
    steps: int
    guidance: float
    hires: HiresFix | None = None

    @property
    def output_size(self) -> tuple[int, int]:
        """The rendered image's size: the base size, or the upscaled one."""
        if self.hires is None:
            return self.width, self.height
        return self.hires.size(self.width, self.height)


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
    fixed = {
        "solo",
        *(tag.strip() for tag in conditioning("CHARACTER_TYPES")[character_type].split(",")),
    }
    tags: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[,;\n]|\.(?=\s|$)", appearance):
        segment = re.sub(r"\s+", " ", raw).strip()
        for tag in _segment_tags(segment, character_type) if segment else ():
            if tag.lower() not in fixed | seen:
                tags.append(tag)
                seen.add(tag.lower())
    return tags


def _portrait_negative(
    tags: list[str], character_type: str, transparent: bool, policy: ContentPolicy
) -> str:
    parts = [_negative(policy), conditioning("TYPE_NEGATIVES")[character_type]]
    lengths = {tag.lower() for tag in tags}
    if lengths.intersection(conditioning("SHORT_LENGTHS")) and not lengths.intersection(
        conditioning("LONG_LENGTHS")
    ):
        parts.append(conditioning("LONG_HAIR_NEGATIVE"))
    if transparent:
        parts.append(conditioning("CUTOUT_NEGATIVE"))
    return ", ".join(part for part in parts if part)


def portrait_request(
    appearance: str,
    character_type: str,
    framing: str,
    *,
    transparent: bool = False,
    policy: ContentPolicy | None = None,
    hires: bool = False,
) -> ImageRequest:
    policy = policy or content_policy(None)
    if character_type not in conditioning("CHARACTER_TYPES") or framing not in FRAMINGS:
        raise ValueError("Unknown character type or framing")
    if transparent and framing != "full_body":
        raise ValueError("Transparent sprites need full-body framing")
    if len(appearance) > MAX_APPEARANCE * 2:
        raise ValueError("Appearance is too long")
    text = clean_appearance(appearance)
    if not text:
        raise ValueError("Describe the character's appearance")
    policy.check(text)
    framing_tags, (width, height) = FRAMINGS[framing]
    framing_tags = conditioning("FRAMING_TAGS")[framing]
    # Tags come from the raw text so line breaks still separate them.
    tags = appearance_tags(appearance, character_type)

    def suffix(value: str) -> str:
        return ", " + value if value else ""

    subject = conditioning("CHARACTER_TYPES")[character_type]
    return ImageRequest(
        prompt=render(
            "narrative.image.portrait",
            subject=subject + ", " if subject else "",
            appearance="".join(suffix(tag) for tag in tags),
            framing=suffix(framing_tags),
            cutout=suffix(conditioning("CUTOUT_TAGS")) if transparent else "",
            quality=suffix(conditioning("QUALITY")),
        ),
        negative_prompt=_portrait_negative(tags, character_type, transparent, policy),
        width=width,
        height=height,
        steps=STEPS,
        guidance=GUIDANCE,
        hires=HiresFix(scale=HIRES_SCALE, strength=HIRES_STRENGTH) if hires else None,
    )


# Expressions repaint only the face of a base sprite (ADR 0041). Presets carry tag sets
# that read clearly at the default strength; anything else is used as tags as typed.
EXPRESSION_TAGS = conditioning("EXPRESSION_TAGS")
MAX_EXPRESSIONS = 4
EXPRESSION_GUIDANCE = 6.0
EXPRESSION_STRENGTH = 0.9
# "looking at viewer" would fight expressions that look away or down.
EXPRESSION_QUALITY = conditioning("EXPRESSION_QUALITY")
_EXPRESSION_NAME = re.compile(r"[a-z0-9][a-z0-9 '\-]{0,39}\Z")


@dataclass(frozen=True)
class ExpressionRequest:
    ids: tuple[str, ...]
    prompts: tuple[str, ...]
    negative_prompt: str
    steps: int
    guidance: float
    strength: float


def expression_id(name: str) -> str:
    """The sprite key a story uses for an expression name."""
    key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:60]
    return key if re.match(r"[a-z]", key) else f"e_{key}"[:64]


def expression_names(expressions: list[str]) -> list[str]:
    """Normalized expression names; ValueError when one is not a short tag."""
    names = [re.sub(r"\s+", " ", str(name)).strip().lower() for name in expressions]
    if not 1 <= len(names) <= MAX_EXPRESSIONS:
        raise ValueError(f"Choose one to {MAX_EXPRESSIONS} expressions")
    if any(not _EXPRESSION_NAME.fullmatch(name) for name in names):
        raise ValueError("Expressions are short words: letters, digits, spaces, - and '")
    if len({expression_id(name) for name in names}) != len(names):
        raise ValueError("Each expression can be asked for once")
    return names


def expression_request(
    appearance: str,
    character_type: str,
    expressions: list[str],
    *,
    policy: ContentPolicy | None = None,
) -> ExpressionRequest:
    """One face-inpainting prompt per expression: subject, expression, then looks."""
    policy = policy or content_policy(None)
    if character_type not in conditioning("CHARACTER_TYPES"):
        raise ValueError("Unknown character type")
    if len(appearance) > MAX_APPEARANCE * 2:
        raise ValueError("Appearance is too long")
    names = expression_names(expressions)
    for text in (clean_appearance(appearance), *names):
        policy.check(text)
    ids = tuple(expression_id(name) for name in names)
    tags = appearance_tags(clean_appearance(appearance), character_type) if appearance else []

    def suffix(value: str) -> str:
        return ", " + value if value else ""

    subject = conditioning("CHARACTER_TYPES")[character_type]
    prompts = tuple(
        render(
            "narrative.image.expression",
            subject=subject + ", " if subject else "",
            expression=suffix(conditioning("EXPRESSION_TAGS").get(name, name)),
            appearance="".join(suffix(tag) for tag in tags),
            quality=suffix(conditioning("EXPRESSION_QUALITY")),
        )
        for name in names
    )
    negative = render(
        "narrative.image.expression_negative",
        base=_portrait_negative(tags, character_type, False, policy),
    )
    return ExpressionRequest(
        ids, prompts, negative, STEPS, EXPRESSION_GUIDANCE, EXPRESSION_STRENGTH
    )


BACKGROUND_SIZE = (1344, 768)
BACKGROUND_QUALITY = conditioning("BACKGROUND_QUALITY")
# People in a background would be fixed into every scene that uses it.
BACKGROUND_PEOPLE_NEGATIVE = conditioning("BACKGROUND_PEOPLE_NEGATIVE")


# Scene art (ADR 0041 slice C): an event CG of one or two existing characters, identity
# from an approved image of each through IP-Adapter. At 0.5 a character stays
# recognizable and the scene keeps its own light; from about 0.6 the reference's pose
# and plain backdrop start to show.
SCENE_SIZE = BACKGROUND_SIZE
SCENE_ADAPTER_SCALE = 0.5
SCENE_QUALITY = BACKGROUND_QUALITY
MAX_SCENE_CHARACTERS = 2
# One person: a second figure would take on the same face.
SOLO_NEGATIVES = {
    "girl": "multiple girls",
    "woman": "multiple girls",
    "boy": "multiple boys",
    "man": "multiple boys",
    "other": "multiple girls, multiple boys",
}
# Two characters: each reference conditions its half of the image (first left), and the
# prompt counts them and lists both looks. Looks still swap in about 5 renders of 12
# (docs/reports/2026-10-31-scene-art-cgs.md); a repaint of each half did not help.
_KINDS = {"girl": "girl", "woman": "girl", "boy": "boy", "man": "boy", "other": "other"}


@dataclass(frozen=True)
class SceneArtRequest:
    prompt: str
    negative_prompt: str
    width: int
    height: int
    steps: int
    guidance: float
    adapter_scale: float


def _count_tag(count: int, kind: str) -> str:
    return f"{count}{kind}" if count == 1 else f"{count}{kind}s"


def _pair_negative(kinds: list[str], policy: ContentPolicy) -> str:
    """Nobody of a kind that is not there, and no third person of one that is."""
    parts = [_negative(policy)]
    if "boy" not in kinds:
        parts.append("1boy, male focus")
    if "girl" not in kinds:
        parts.append("1girl, female focus")
    for kind, plural in (("boy", "boys"), ("girl", "girls")):
        count = kinds.count(kind)
        if count:
            parts.append(f"multiple {plural}" if count == 1 else f"3{plural}")
    return ", ".join(part for part in parts if part)


def _solo_scene(
    text: str, appearance: str, character_type: str, policy: ContentPolicy
) -> tuple[str, str, list[str]]:
    looks = clean_appearance(appearance)
    policy.check(looks)
    tags = appearance_tags(appearance, character_type) if looks else []
    parts = [CHARACTER_TYPES[character_type], "solo", text, *tags, SCENE_QUALITY]
    negative = _portrait_negative(tags, character_type, False, policy)
    prompt = ", ".join(part for part in parts if part)
    return prompt, f"{negative}, {SOLO_NEGATIVES[character_type]}", tags


def scene_art_request(
    scene: str,
    characters: Sequence[tuple[str, str]],
    *,
    policy: ContentPolicy = DEFAULT_POLICY,
) -> SceneArtRequest:
    """Prompts for a CG of one or two characters, given as (appearance, character type).

    One character: subject, the scene as written, then its looks (the reference does
    the rest). Two: count both people, the scene, then both looks.
    """
    if not 1 <= len(characters) <= MAX_SCENE_CHARACTERS:
        raise ValueError(f"A CG shows one to {MAX_SCENE_CHARACTERS} characters")
    if any(kind not in CHARACTER_TYPES for _, kind in characters):
        raise ValueError("Unknown character type")
    if len(scene) > MAX_APPEARANCE * 2 or any(
        len(appearance) > MAX_APPEARANCE * 2 for appearance, _ in characters
    ):
        raise ValueError("Description is too long")
    text = clean_appearance(scene)
    if not text:
        raise ValueError("Describe the scene")
    policy.check(text)
    solos = [_solo_scene(text, appearance, kind, policy) for appearance, kind in characters]
    width, height = SCENE_SIZE
    scene_art = partial(
        SceneArtRequest,
        width=width,
        height=height,
        steps=STEPS,
        guidance=GUIDANCE,
        adapter_scale=SCENE_ADAPTER_SCALE,
    )
    if len(solos) == 1:
        [(prompt, negative, _)] = solos
        return scene_art(prompt=prompt, negative_prompt=negative)
    kinds = [_KINDS[kind] for _, kind in characters]
    counts = ", ".join(_count_tag(kinds.count(kind), kind) for kind in dict.fromkeys(kinds))
    looks: list[str] = []
    for _, _, tags in solos:
        looks.extend(tag for tag in tags if tag.lower() not in {seen.lower() for seen in looks})
    return scene_art(
        prompt=", ".join((counts, text, *looks, SCENE_QUALITY)),
        negative_prompt=_pair_negative(kinds, policy),
    )


def background_request(description: str, *, policy: ContentPolicy | None = None) -> ImageRequest:
    policy = policy or content_policy(None)
    if len(description) > MAX_APPEARANCE * 2:
        raise ValueError("Description is too long")
    text = clean_appearance(description)
    if not text:
        raise ValueError("Describe the place")
    policy.check(text)
    width, height = BACKGROUND_SIZE
    return ImageRequest(
        prompt=render(
            "narrative.image.background",
            description=text,
            quality=conditioning("BACKGROUND_QUALITY"),
        ),
        negative_prompt=render(
            "narrative.image.background_negative",
            base=_negative(policy),
            people=conditioning("BACKGROUND_PEOPLE_NEGATIVE"),
        ),
        width=width,
        height=height,
        steps=STEPS,
        guidance=GUIDANCE,
    )
