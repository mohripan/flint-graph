import pytest

from flint_graph.narrative.voice_delivery import TURBO_SOUNDS, controls, instructions
from flint_graph.narrative.voice_models import DELIVERIES, MODELS, Delivery


def test_every_supported_delivery_maps_to_controls_and_others_refuse() -> None:
    for spec in MODELS.values():
        for emotion in DELIVERIES:
            delivery = Delivery(emotion, 0.5)
            if emotion in spec.deliveries:
                assert isinstance(controls(spec, delivery), dict)
            else:
                with pytest.raises(ValueError):
                    controls(spec, delivery)


def test_chatterbox_intensity_raises_exaggeration_and_slows_pacing() -> None:
    spec = MODELS["chatterbox"]
    assert controls(spec, Delivery()) == {"exaggeration": 0.5, "cfg_weight": 0.5}
    assert controls(spec, Delivery("angry", 1.0)) == {"exaggeration": 1.0, "cfg_weight": 0.3}
    assert controls(spec, Delivery("dramatic", 1.0)) == {"exaggeration": 1.2, "cfg_weight": 0.3}
    assert controls(spec, Delivery("sad", 1.0)) == {"exaggeration": 0.25, "cfg_weight": 0.5}


def test_turbo_uses_its_own_style_and_sound_tags() -> None:
    spec = MODELS["chatterbox-turbo"]
    assert controls(spec, Delivery()) == {"prefix": ""}
    assert controls(spec, Delivery("whisper", 0.5, "sigh")) == {"prefix": "[whispering] [sigh]"}
    assert set(TURBO_SOUNDS) == set(spec.tags)
    assert TURBO_SOUNDS["clear_throat"] == "[clear throat]"


def test_qwen_instructions_come_from_a_fixed_table() -> None:
    spec = MODELS["qwen3-tts-voices"]
    assert controls(spec, Delivery()) == {"instruct": ""}
    assert controls(spec, Delivery("angry", 0.9)) == {"instruct": "Speak in a very angry tone."}
    assert controls(spec, Delivery("angry", 0.1)) == {"instruct": "Speak in a slightly angry tone."}
    assert controls(spec, Delivery("whisper", 0.5)) == {"instruct": "Whisper quietly."}
    made = {
        controls(spec, Delivery(emotion, intensity))["instruct"]
        for emotion in DELIVERIES
        for intensity in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    }
    assert made <= instructions() and len(instructions()) == 28


def test_indextts_emotion_vectors_scale_with_intensity() -> None:
    spec = MODELS["indextts-2.5"]
    assert controls(spec, Delivery()) == {"emo_vector": None}
    angry = controls(spec, Delivery("angry", 1.0))["emo_vector"]
    assert angry == [0.0, 0.8, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    tender = controls(spec, Delivery("tender", 0.0))["emo_vector"]
    assert tender == [0.08, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.12]
    assert sum(controls(spec, Delivery("shout", 1.0))["emo_vector"]) == pytest.approx(0.8)
