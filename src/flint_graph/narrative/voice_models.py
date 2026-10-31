"""The voice models FlintGraph knows, their licenses and what each can do (ADR 0045).

This registry is code, not configuration: an operator only says which of these
models are installed (a pinned directory and runtime per model), so a catalog entry,
its license text, the license's SHA-256 and the duties it puts on generated audio can
never be supplied by a server setting or a client. Kokoro-82M stays the default.

Delivery (#177) is a generation input with a bounded vocabulary and an intensity in
[0, 1]. Each model either has a real control for a delivery ("full"), approximates it
with a coarser knob ("approximate"), or cannot do it at all (absent), so the Studio
can show which deliveries a voice cannot do instead of silently ignoring them.
Paralinguistic tags (laugh, sigh) are a fixed list per model; free text never reaches
a model as a control.
"""

import hashlib
import re
from dataclasses import dataclass, field
from importlib import resources
from typing import Literal

Obligations = Literal["none", "attribution", "player_terms"]
Support = Literal["full", "approximate"]

DELIVERIES = (
    "neutral",
    "happy",
    "angry",
    "sad",
    "afraid",
    "surprised",
    "whisper",
    "shout",
    "dramatic",
    "tender",
)
DEFAULT_MODEL = "kokoro-82m"
LANGUAGE = re.compile(r"[a-z]{2}\Z")
REFERENCE_TRANSCRIPT_LIMIT = 600


def _text(name: str) -> str:
    return (
        (resources.files("flint_graph.narrative") / "voice_licenses" / name).read_bytes().decode()
    )


@dataclass(frozen=True)
class VoiceLicense:
    id: str
    name: str
    text: str
    obligations: Obligations
    # What the license asks of a game that ships this model's audio, in plain words.
    summary: str
    # The attribution line NOTICES carries for each clip (empty: the default credit only).
    notice: str = ""
    # What players see once before playing, when the license requires player terms.
    player_terms: str = ""
    # The agreement as players read it in the game (the bundled font has no CJK glyphs,
    # so a Chinese text that prevails stays in NOTICES, which every build ships).
    in_game_text: str = ""

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


@dataclass(frozen=True)
class StockVoice:
    id: str
    name: str
    description: str


@dataclass(frozen=True)
class VoiceModelSpec:
    id: str
    name: str
    engine: Literal["kokoro", "chatterbox", "qwen3", "indextts"]
    repo: str
    revision: str
    license_id: str
    # Which runtimes/ directory runs it (each has its own lock).
    runtime: str
    cloning: bool
    sample_rate: int
    languages: tuple[str, ...]
    deliveries: dict[str, Support]
    stock_voices: tuple[StockVoice, ...] = ()
    tags: tuple[str, ...] = ()
    watermark: str | None = None
    # Free dedicated GPU memory the child needs before it uses the card: the measured
    # peak it reserves on the shared 12 GB card plus headroom (ADR 0045).
    min_free_gib: float = 1.0
    # Whether a job may finish on the CPU when the card is busy (otherwise it refuses).
    cpu_fallback: bool = True
    description: str = ""
    reference_transcript: Literal["unused", "optional"] = "unused"
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def license(self) -> VoiceLicense:
        return LICENSES[self.license_id]


_BILIBILI_TERMS = (
    "This game contains voice audio generated with IndexTTS-2.5, a model by bilibili, "
    "used under the bilibili Model Use License Agreement. That audio is a derivative work "
    "of the model under the agreement.\n"
    "\n"
    "bilibili does not endorse, guarantee or take responsibility for this game.\n"
    "\n"
    "By playing you agree to use that audio only as the agreement allows. In particular, "
    "you may not use it, or anything derived from it, to train or improve any other "
    "artificial intelligence model, and you must pass these terms on to anyone you share "
    "the audio with. Disputes about the agreement are governed by the laws of the "
    "People's Republic of China.\n"
    "\n"
    "The agreement follows in English. Its Chinese version, which prevails, is in the "
    "NOTICES.txt file that comes with this game."
)

LICENSES: dict[str, VoiceLicense] = {
    license.id: license
    for license in (
        VoiceLicense(
            id="apache-2.0",
            name="Apache License 2.0",
            text=_text("apache-2.0.txt"),
            obligations="none",
            summary="Puts no duties on the audio you generate. NOTICES credits the model.",
        ),
        VoiceLicense(
            id="chatterbox-mit",
            name="MIT License (Resemble AI)",
            text=_text("chatterbox-mit.txt"),
            obligations="none",
            summary=(
                "Puts no duties on the audio you generate. Every clip carries Resemble AI's "
                "inaudible PerTh watermark. NOTICES credits the model."
            ),
        ),
        VoiceLicense(
            id="bilibili-model-use",
            name="bilibili Model Use License Agreement",
            text=(
                _text("bilibili-model-use-license.en.txt")
                + "\n\n"
                + _text("bilibili-model-use-license.zh.txt").rstrip("\n")
            ),
            obligations="player_terms",
            summary=(
                "Free below 100 million monthly users or 100 million RMB of yearly revenue. "
                "Audio you generate counts as a derivative work of the model, so every game "
                "that ships it must keep bilibili's notice and this agreement, say that "
                "bilibili does not endorse the game, and put terms on players: they may not "
                "use the audio to improve other AI models. FlintGraph adds the notice and the "
                "agreement to the game's NOTICES and shows players a one-time license screen. "
                "Chinese law governs; the Chinese text prevails. This is a summary, not legal "
                "advice."
            ),
            notice=(
                "Voice generated with IndexTTS-2.5 by bilibili under the bilibili Model Use "
                "License Agreement. bilibili does not endorse or guarantee this work."
            ),
            player_terms=_BILIBILI_TERMS,
            in_game_text=_text("bilibili-model-use-license.en.txt"),
        ),
    )
}

_EXPRESSIVE = ("happy", "angry", "surprised", "afraid", "shout", "dramatic")
_CHATTERBOX: dict[str, Support] = {
    "neutral": "full",
    **dict.fromkeys(_EXPRESSIVE, "approximate"),
    "sad": "approximate",
    "tender": "approximate",
}
_QWEN_SPEAKERS = (
    StockVoice("Vivian", "Vivian", "Bright, slightly edgy young female voice (Chinese)."),
    StockVoice("Serena", "Serena", "Warm, gentle young female voice (Chinese)."),
    StockVoice("Uncle_Fu", "Uncle Fu", "Seasoned male voice with a low, mellow timbre (Chinese)."),
    StockVoice("Dylan", "Dylan", "Youthful Beijing male voice with a clear timbre (Chinese)."),
    StockVoice("Eric", "Eric", "Lively Chengdu male voice with a slightly husky brightness."),
    StockVoice("Ryan", "Ryan", "Dynamic male voice with strong rhythmic drive (English)."),
    StockVoice("Aiden", "Aiden", "Sunny American male voice with a clear midrange (English)."),
    StockVoice("Ono_Anna", "Ono Anna", "Playful Japanese female voice, light and nimble."),
    StockVoice("Sohee", "Sohee", "Warm Korean female voice with rich emotion."),
)
_QWEN_LANGUAGES = ("en", "ja", "zh", "ko", "de", "fr", "ru", "pt", "es", "it")

MODELS: dict[str, VoiceModelSpec] = {
    spec.id: spec
    for spec in (
        VoiceModelSpec(
            id="kokoro-82m",
            name="Kokoro-82M",
            engine="kokoro",
            repo="hexgrad/Kokoro-82M",
            revision="f3ff3571791e39611d31c381e3a41a3af07b4987",
            license_id="apache-2.0",
            runtime="voicegen",
            cloning=False,
            sample_rate=24000,
            languages=("en",),
            deliveries={"neutral": "full"},
            description="Fast stock English voices. No cloning and no delivery control.",
        ),
        VoiceModelSpec(
            id="chatterbox",
            name="Chatterbox (English)",
            engine="chatterbox",
            repo="ResembleAI/chatterbox",
            revision="5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18",
            license_id="chatterbox-mit",
            runtime="voicegen-chatterbox",
            cloning=True,
            sample_rate=24000,
            languages=("en",),
            deliveries=_CHATTERBOX,
            watermark="perth",
            min_free_gib=4.5,
            description=(
                "Clones a voice from a reference. Delivery is one expressiveness control, "
                "so emotions are approximate."
            ),
        ),
        VoiceModelSpec(
            id="chatterbox-turbo",
            name="Chatterbox-Turbo (English)",
            engine="chatterbox",
            repo="ResembleAI/chatterbox-turbo",
            revision="749d1c1a46eb10492095d68fbcf55691ccf137cd",
            license_id="chatterbox-mit",
            runtime="voicegen-chatterbox",
            cloning=True,
            sample_rate=24000,
            languages=("en",),
            # Style tags in its tokenizer approximate these; sounds go before the line.
            deliveries={
                "neutral": "full",
                **dict.fromkeys(
                    ("happy", "angry", "sad", "afraid", "surprised", "whisper", "dramatic"),
                    "approximate",
                ),
            },
            tags=(
                "laugh",
                "chuckle",
                "sigh",
                "gasp",
                "cough",
                "groan",
                "sniff",
                "shush",
                "clear_throat",
            ),
            watermark="perth",
            min_free_gib=3.5,
            description="Fast cloning with laughs, sighs and style tags.",
        ),
        VoiceModelSpec(
            id="chatterbox-multilingual",
            name="Chatterbox Multilingual V3",
            engine="chatterbox",
            repo="ResembleAI/chatterbox",
            revision="5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18",
            license_id="chatterbox-mit",
            runtime="voicegen-chatterbox",
            cloning=True,
            sample_rate=24000,
            languages=("en", "ja", "zh", "ko", "de", "fr", "es", "it", "pt", "ru"),
            deliveries=_CHATTERBOX,
            watermark="perth",
            min_free_gib=4.5,
            description="Chatterbox cloning in 23 languages, including Japanese.",
            extra={"t3": "t3_mtl23ls_v3.safetensors"},
        ),
        VoiceModelSpec(
            id="qwen3-tts-clone",
            name="Qwen3-TTS 1.7B (cloning)",
            engine="qwen3",
            repo="Qwen/Qwen3-TTS-12Hz-1.7B-Base",
            revision="fd4b254389122332181a7c3db7f27e918eec64e3",
            license_id="apache-2.0",
            runtime="voicegen-qwen3",
            cloning=True,
            sample_rate=24000,
            languages=_QWEN_LANGUAGES,
            deliveries={"neutral": "full"},
            min_free_gib=5.5,
            reference_transcript="optional",
            description=(
                "Clones a voice from a few seconds of speech; a transcript of the reference "
                "improves it. The cloning model takes no delivery instructions."
            ),
        ),
        VoiceModelSpec(
            id="qwen3-tts-voices",
            name="Qwen3-TTS 1.7B (stock voices)",
            engine="qwen3",
            repo="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
            revision="0c0e3051f131929182e2c023b9537f8b1c68adfe",
            license_id="apache-2.0",
            runtime="voicegen-qwen3",
            cloning=False,
            sample_rate=24000,
            languages=_QWEN_LANGUAGES,
            deliveries=dict.fromkeys(DELIVERIES, "full"),
            stock_voices=_QWEN_SPEAKERS,
            min_free_gib=5.5,
            description="Nine stock voices whose delivery follows fixed instructions.",
        ),
        VoiceModelSpec(
            id="indextts-2.5",
            name="IndexTTS-2.5",
            engine="indextts",
            repo="IndexTeam/IndexTTS-2.5",
            revision="c39ce5ba981572cb187443877ff559dfb246ce63",
            license_id="bilibili-model-use",
            runtime="voicegen-indextts",
            cloning=True,
            sample_rate=22050,
            languages=("en", "zh", "ja"),
            deliveries={
                "neutral": "full",
                "happy": "full",
                "angry": "full",
                "sad": "full",
                "afraid": "full",
                "surprised": "full",
                "tender": "approximate",
                "shout": "approximate",
                "dramatic": "approximate",
            },
            min_free_gib=7.0,
            cpu_fallback=False,
            description=(
                "Clones a voice and controls its emotion separately. Its license puts duties "
                "on every game that ships its audio."
            ),
        ),
    )
}


def model(model_id: str) -> VoiceModelSpec:
    try:
        return MODELS[model_id]
    except KeyError:
        raise ValueError("Unknown voice model") from None


def license_by_sha256(sha256: str) -> VoiceLicense | None:
    return next((item for item in LICENSES.values() if item.sha256 == sha256), None)


@dataclass(frozen=True)
class Delivery:
    emotion: str = "neutral"
    intensity: float = 0.5
    tag: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"emotion": self.emotion, "intensity": self.intensity, "tag": self.tag}


def clean_delivery(value: object, spec: VoiceModelSpec) -> Delivery:
    """A delivery this model can do, or ``ValueError`` naming why not."""
    if value is None:
        return Delivery()
    if not isinstance(value, dict) or not set(value) <= {"emotion", "intensity", "tag"}:
        raise ValueError("Delivery must name an emotion, an intensity and optionally a tag.")
    emotion = value.get("emotion", "neutral")
    intensity = value.get("intensity", 0.5)
    tag = value.get("tag")
    if emotion not in DELIVERIES:
        raise ValueError("Choose one of the listed deliveries.")
    if emotion not in spec.deliveries:
        raise ValueError(f"{spec.name} cannot speak a line {emotion}.")
    if type(intensity) not in (int, float) or not 0 <= intensity <= 1:
        raise ValueError("Intensity is between 0 and 1.")
    if tag is not None and tag not in spec.tags:
        raise ValueError(f"{spec.name} has no sound “{tag}”.")
    return Delivery(emotion, round(float(intensity), 2), tag)
