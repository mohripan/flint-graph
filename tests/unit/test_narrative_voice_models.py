import hashlib

import pytest

from flint_graph.narrative.voice_models import (
    DEFAULT_MODEL,
    DELIVERIES,
    LICENSES,
    MODELS,
    Delivery,
    clean_delivery,
    license_by_sha256,
    model,
)

# The upstream bytes of IndexTeam/IndexTTS-2.5@c39ce5b/LICENSE, as pinned in its manifest.
INDEXTTS_LICENSE_SHA256 = "cc7da9ea0f8a97ef15ab3bf0389e636ce79ffca1aef5489520796ac87d87a87b"


def test_kokoro_stays_the_default_and_every_model_names_a_known_license() -> None:
    assert DEFAULT_MODEL == "kokoro-82m"
    assert MODELS[DEFAULT_MODEL].license.obligations == "none"
    for spec in MODELS.values():
        assert spec.license_id in LICENSES
        assert len(spec.revision) == 40
        assert set(spec.deliveries) <= set(DELIVERIES)
        assert spec.deliveries.get("neutral") == "full"
        assert spec.cloning or spec.stock_voices or spec.engine == "kokoro"


def test_only_the_bilibili_agreement_puts_duties_on_generated_audio() -> None:
    duties = {item.id: item.obligations for item in LICENSES.values()}
    assert duties == {
        "apache-2.0": "none",
        "chatterbox-mit": "none",
        "bilibili-model-use": "player_terms",
    }
    bilibili = LICENSES["bilibili-model-use"]
    assert bilibili.notice and bilibili.player_terms
    assert "does not endorse" in bilibili.notice
    assert "train or improve" in bilibili.player_terms
    assert "100 million RMB" in bilibili.summary


def test_license_texts_are_the_exact_upstream_bytes() -> None:
    bilibili = LICENSES["bilibili-model-use"]
    english, _, chinese = bilibili.text.partition("\n\n" + "bilibili模型使用许可协议")
    assert hashlib.sha256(english.encode()).hexdigest() == INDEXTTS_LICENSE_SHA256
    assert chinese.startswith("\n\n若您点击同意")
    assert "\r" not in bilibili.text
    assert LICENSES["chatterbox-mit"].text.startswith(
        "MIT License\n\nCopyright (c) 2025 Resemble AI"
    )
    assert "Apache License" in LICENSES["apache-2.0"].text
    for item in LICENSES.values():
        assert license_by_sha256(item.sha256) is item
    assert license_by_sha256("0" * 64) is None


def test_non_commercial_weights_are_not_in_the_catalog() -> None:
    repos = {spec.repo for spec in MODELS.values()}
    assert "IndexTeam/IndexTTS-2" not in repos  # needs the CC-BY-NC MaskGCT codec
    for excluded in (
        "amphion/MaskGCT",
        "coqui/XTTS-v2",
        "SWivid/F5-TTS",
        "fishaudio/fish-speech-1.5",
    ):
        assert excluded not in repos


def test_delivery_is_checked_against_what_the_model_can_do() -> None:
    kokoro, qwen = model("kokoro-82m"), model("qwen3-tts-voices")
    assert clean_delivery(None, kokoro) == Delivery()
    with pytest.raises(ValueError, match="cannot speak a line whisper"):
        clean_delivery({"emotion": "whisper", "intensity": 0.5}, kokoro)
    assert clean_delivery({"emotion": "whisper", "intensity": 0.333}, qwen) == Delivery(
        "whisper", 0.33, None
    )
    with pytest.raises(ValueError, match="listed deliveries"):
        clean_delivery({"emotion": "sarcastic"}, qwen)
    for bad in ({"emotion": "angry", "intensity": 1.5}, {"emotion": "angry", "intensity": True}):
        with pytest.raises(ValueError, match="between 0 and 1"):
            clean_delivery(bad, qwen)
    with pytest.raises(ValueError, match="optionally a tag"):
        clean_delivery({"emotion": "angry", "instruction": "yell"}, qwen)


def test_paralinguistic_tags_come_only_from_the_models_fixed_list() -> None:
    turbo = model("chatterbox-turbo")
    assert clean_delivery({"tag": "laugh"}, turbo).tag == "laugh"
    with pytest.raises(ValueError, match="no sound"):
        clean_delivery({"tag": "[laugh] ignore previous"}, turbo)
    with pytest.raises(ValueError, match="no sound"):
        clean_delivery({"tag": "laugh"}, model("chatterbox"))
    with pytest.raises(ValueError, match="Unknown voice model"):
        model("xtts-v2")
