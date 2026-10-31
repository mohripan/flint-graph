"""How a delivery becomes a model's own controls (#177, ADR 0045).

The Studio speaks one bounded vocabulary (``voice_models.DELIVERIES`` with an
intensity in [0, 1]); each engine has different knobs. This fixed table turns a
delivery into those knobs, so no free text from a creator ever reaches a model as an
instruction: Qwen3-TTS instructions and Chatterbox-Turbo tags are constants here.
The child process receives only these controls and checks their shape again.
"""

from typing import Any

from flint_graph.narrative.voice_models import Delivery, VoiceModelSpec

ENERGETIC = ("happy", "angry", "surprised", "afraid", "shout", "dramatic")
CALM = ("sad", "tender")
# Chatterbox-Turbo's tokenizer has these style tags beside its sound tags.
TURBO_STYLES = {
    "happy": "[happy]",
    "angry": "[angry]",
    "sad": "[crying]",
    "afraid": "[fear]",
    "surprised": "[surprised]",
    "whisper": "[whispering]",
    "dramatic": "[dramatic]",
}
TURBO_SOUNDS = {
    "laugh": "[laugh]",
    "chuckle": "[chuckle]",
    "sigh": "[sigh]",
    "gasp": "[gasp]",
    "cough": "[cough]",
    "groan": "[groan]",
    "sniff": "[sniff]",
    "shush": "[shush]",
    "clear_throat": "[clear throat]",
}
_QWEN = {
    "happy": "Speak in a {adverb}happy, cheerful tone.",
    "angry": "Speak in a {adverb}angry tone.",
    "sad": "Speak in a {adverb}sad, sorrowful tone.",
    "afraid": "Speak in a {adverb}frightened, trembling voice.",
    "surprised": "Speak in a {adverb}surprised tone.",
    "whisper": "Whisper {quietly}.",
    "shout": "Shout {loudly}.",
    "dramatic": "Speak in a {adverb}dramatic, theatrical way.",
    "tender": "Speak in a {adverb}tender, gentle voice.",
}
# IndexTTS emotion vector order: happy, angry, sad, afraid, disgusted, melancholic,
# surprised, calm.
_INDEX = {
    "happy": {0: 1.0},
    "angry": {1: 1.0},
    "sad": {2: 1.0},
    "afraid": {3: 1.0},
    "surprised": {6: 1.0},
    "tender": {0: 0.4, 7: 0.6},
    "shout": {1: 0.7, 6: 0.3},
    "dramatic": {5: 0.6, 6: 0.4},
}


def _level(intensity: float, low: str, middle: str, high: str) -> str:
    return low if intensity < 0.34 else middle if intensity < 0.67 else high


def controls(spec: VoiceModelSpec, delivery: Delivery) -> dict[str, Any]:
    """The engine controls for one line, or ``ValueError`` if the model cannot do it."""
    if delivery.emotion not in spec.deliveries or (
        delivery.tag is not None and delivery.tag not in spec.tags
    ):
        raise ValueError("This model cannot speak with that delivery.")
    emotion, intensity = delivery.emotion, delivery.intensity
    if spec.engine == "kokoro":
        return {}
    if spec.engine == "chatterbox" and spec.id == "chatterbox-turbo":
        prefix = [TURBO_STYLES[emotion]] if emotion in TURBO_STYLES else []
        if delivery.tag is not None:
            prefix.append(TURBO_SOUNDS[delivery.tag])
        return {"prefix": " ".join(prefix)}
    if spec.engine == "chatterbox":
        if emotion in ENERGETIC:
            reach = 0.7 if emotion in ("shout", "dramatic") else 0.5
            return {
                "exaggeration": round(0.5 + reach * intensity, 3),
                "cfg_weight": round(0.5 - 0.2 * intensity, 3),
            }
        if emotion in CALM:
            return {"exaggeration": round(0.5 - 0.25 * intensity, 3), "cfg_weight": 0.5}
        return {"exaggeration": 0.5, "cfg_weight": 0.5}
    if spec.engine == "qwen3":
        if emotion == "neutral":
            return {"instruct": ""}
        template = _QWEN[emotion]
        return {
            "instruct": template.format(
                adverb=_level(intensity, "slightly ", "", "very "),
                quietly=_level(intensity, "softly", "quietly", "very quietly"),
                loudly=_level(intensity, "a little", "loudly", "at the top of your voice"),
            )
        }
    if spec.engine == "indextts":
        if emotion == "neutral":
            return {"emo_vector": None}
        strength = 0.2 + 0.6 * intensity
        vector = [0.0] * 8
        for index, share in _INDEX[emotion].items():
            vector[index] = round(share * strength, 3)
        return {"emo_vector": vector}
    raise ValueError("Unknown voice engine")


def instructions() -> frozenset[str]:
    """Every Qwen3-TTS instruction this table can produce (the child accepts no other)."""
    found = {""}
    for emotion in _QWEN:
        for intensity in (0.0, 0.5, 1.0):
            spec_like = Delivery(emotion, intensity)
            found.add(
                _QWEN[spec_like.emotion].format(
                    adverb=_level(intensity, "slightly ", "", "very "),
                    quietly=_level(intensity, "softly", "quietly", "very quietly"),
                    loudly=_level(intensity, "a little", "loudly", "at the top of your voice"),
                )
            )
    return frozenset(found)
