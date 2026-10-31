"""Trusted parent for the protocol 2 voice children (ADR 0044), against a scripted child."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

from flint_graph.infrastructure.narrative_imagegen import MANIFEST, ModelIdentity
from flint_graph.infrastructure.narrative_voicegen import (
    LocalEngineVoiceGenerator,
    ReferenceInput,
    VoiceGenerationError,
    VoiceItem,
    VoiceRequest,
    verify_engine_model,
)
from flint_graph.narrative.voice_models import MODELS, Delivery
from flint_graph.narrative.wav import canonical_wav, validate_wav

FAKE = Path(__file__).parents[1] / "fixtures" / "narrative" / "fake_voicegen_engine.py"
REFERENCE = canonical_wav(1, 24000, b"\x10\x00" * 24000 * 6)
DIGEST = hashlib.sha256(REFERENCE).hexdigest()


def generator(model_id: str, device="auto"):
    spec = MODELS[model_id]
    return LocalEngineVoiceGenerator(
        spec=spec,
        python=Path(sys.executable),
        script=FAKE,
        model_dir=Path(__file__).parent,
        model=ModelIdentity(spec.repo, spec.revision, spec.license_id),
        deadline_seconds=30,
        device=device,
    )


def cloned(model_id: str, first="ok", **changes):
    items = (
        VoiceItem(f"{first} line {DIGEST}", "full", Delivery("angry", 0.8)),
        VoiceItem("hmm", "vocalization"),
    )
    base = {
        "voice": None,
        "speed": 1.0,
        "seed": 11,
        "items": items,
        "model": model_id,
        "reference": ReferenceInput(REFERENCE, DIGEST, "The lanterns are lit."),
        "language": "en",
    }
    return VoiceRequest(**{**base, **changes})


async def ignore(done):
    return None


@pytest.mark.anyio
@pytest.mark.parametrize(("model_id", "rate"), [("chatterbox", 24000), ("indextts-2.5", 22050)])
async def test_cloned_clips_come_back_at_the_models_sample_rate(model_id, rate):
    progress = []

    async def on_progress(done):
        progress.append(done)

    result = await generator(model_id).generate(cloned(model_id), on_progress=on_progress)
    assert progress == [1, 2]
    first = result.clips[0]
    assert (first.sample_rate, first.device) == (rate, "cuda")
    assert validate_wav(first.data, "x").sample_rate == rate and first.duration_ms == 100
    assert result.runtime["engine"] in ("chatterbox", "indextts")


@pytest.mark.anyio
async def test_stock_voices_need_no_reference_and_refuse_one():
    qwen = generator("qwen3-tts-voices")
    stock = cloned("qwen3-tts-voices", voice="Ono_Anna", reference=None, language="ja")
    result = await qwen.generate(stock, on_progress=ignore)
    assert len(result.clips) == 2
    for bad in (
        cloned("qwen3-tts-voices", voice="Ono_Anna"),  # a reference for a stock voice
        cloned("qwen3-tts-voices", voice="Nobody", reference=None),
        cloned("qwen3-tts-voices", voice="Ono_Anna", reference=None, language="xx"),
    ):
        with pytest.raises(VoiceGenerationError) as failure:
            await qwen.generate(bad, on_progress=ignore)
        assert failure.value.code == "bad_request"


@pytest.mark.anyio
async def test_requests_the_model_cannot_do_never_reach_the_child():
    chatterbox = generator("chatterbox")
    whisper = (VoiceItem("ok line", "full", Delivery("whisper", 0.5)),)
    forged = ReferenceInput(REFERENCE, "0" * 64, None)
    for bad in (
        cloned("chatterbox", items=whisper),
        cloned("chatterbox", reference=None),
        cloned("chatterbox", reference=forged),
        cloned("chatterbox", language="ja"),
        cloned("chatterbox", model="chatterbox-turbo"),
    ):
        with pytest.raises(VoiceGenerationError) as failure:
            await chatterbox.generate(bad, on_progress=ignore)
        assert failure.value.code == "bad_request"


@pytest.mark.anyio
@pytest.mark.parametrize(("first", "code"), [("busy", "gpu_busy"), ("rate", "invalid_output")])
async def test_child_failures_map_to_safe_codes(first, code):
    with pytest.raises(VoiceGenerationError) as failure:
        await generator("indextts-2.5").generate(
            cloned("indextts-2.5", first=first), on_progress=ignore
        )
    assert failure.value.code == code


def test_a_pinned_directory_must_name_the_catalog_repository(tmp_path):
    spec = MODELS["chatterbox-turbo"]
    (tmp_path / "ve.safetensors").write_bytes(b"weights")
    files = {"ve.safetensors": {"size": 7, "sha256": hashlib.sha256(b"weights").hexdigest()}}

    def pin(repo, revision):
        data = json.dumps(
            {"repo": repo, "revision": revision, "license": "mit", "files": files}
        ).encode()
        (tmp_path / MANIFEST).write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    identity = verify_engine_model(tmp_path, pin(spec.repo, spec.revision), spec)
    assert (identity.repo, identity.license) == (spec.repo, "chatterbox-mit")
    with pytest.raises(ValueError, match="another model"):
        verify_engine_model(tmp_path, pin("someone/else", spec.revision), spec)
