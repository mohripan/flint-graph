"""Trusted parent for the isolated Kokoro child (ADR 0043), against a scripted child."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

from flint_graph.infrastructure.narrative_imagegen import ModelIdentity
from flint_graph.infrastructure.narrative_voicegen import (
    LocalVoiceGenerator,
    VoiceGenerationError,
    VoiceItem,
    VoiceRequest,
    verify_voice_model,
)
from flint_graph.narrative.wav import validate_wav

FAKE = Path(__file__).parents[1] / "fixtures" / "narrative" / "fake_voicegen.py"
MODEL = ModelIdentity(repo="hexgrad/Kokoro-82M", revision="f" * 40, license="apache-2.0")


def generator(deadline=30, device="auto"):
    return LocalVoiceGenerator(
        python=Path(sys.executable),
        script=FAKE,
        model_dir=Path(__file__).parent,
        model=MODEL,
        deadline_seconds=deadline,
        device=device,
    )


def request(first="ok", count=2):
    items = [VoiceItem(text=f"{first} line", mode="full")]
    items += [VoiceItem(text="fufu", mode="vocalization")] * (count - 1)
    return VoiceRequest(voice="af_heart", speed=1.0, seed=7, items=tuple(items))


@pytest.mark.anyio
async def test_clips_are_validated_hashed_and_report_progress():
    progress = []

    async def on_progress(done):
        progress.append(done)

    result = await generator().generate(request(), on_progress=on_progress)
    assert progress == [1, 2]
    assert [clip.index for clip in result.clips] == [0, 1]
    first = result.clips[0]
    assert first.sha256 == hashlib.sha256(first.data).hexdigest()
    assert validate_wav(first.data, "x").frames == 2400 and first.duration_ms == 100
    assert result.runtime == {
        "torch": "2.11.0+cpu",
        "kokoro": "0.9.4",
        "misaki": "0.9.4",
        "device": "cpu",
    }


async def ignore(done):
    return None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("first", "code"),
    [
        ("crash", "generation_failed"),
        ("empty", "empty_speech"),
        ("badwav", "invalid_output"),
        ("stereo", "invalid_output"),
        ("rate", "invalid_output"),
        ("extra", "invalid_output"),
        ("wrongindex", "invalid_output"),
        ("wrongsamples", "invalid_output"),
        ("noisy", "invalid_output"),
        ("baddevice", "invalid_output"),
    ],
)
async def test_child_failures_map_to_safe_codes(first, code):
    with pytest.raises(VoiceGenerationError) as raised:
        await generator().generate(request(first), on_progress=ignore)
    assert raised.value.code == code


@pytest.mark.anyio
async def test_each_clip_records_the_device_that_spoke_it():
    gpu = await generator().generate(request("gpu"), on_progress=ignore)
    assert [clip.device for clip in gpu.clips] == ["cuda", "cuda"]
    forced = await generator(device="cpu").generate(request("gpu"), on_progress=ignore)
    assert [clip.device for clip in forced.clips] == ["cpu", "cpu"]
    with pytest.raises(ValueError):
        generator(device="tpu")


def test_the_child_keeps_compiled_cuda_kernels_between_jobs(tmp_path):
    cached = LocalVoiceGenerator(
        python=Path(sys.executable),
        script=FAKE,
        model_dir=Path(__file__).parent,
        model=MODEL,
        deadline_seconds=30,
        cuda_cache=tmp_path / "cuda",
    )._environment(tmp_path / "work")
    assert cached["CUDA_CACHE_PATH"] == str(tmp_path / "cuda")
    assert cached["CUDA_CACHE_MAXSIZE"] == str(4 * 1024**3)
    assert "CUDA_CACHE_PATH" not in generator()._environment(tmp_path / "work")


@pytest.mark.anyio
async def test_watchdog_kills_a_hung_child():
    with pytest.raises(VoiceGenerationError) as raised:
        await generator(deadline=2).generate(request("hang"), on_progress=ignore)
    assert raised.value.code == "generation_timeout"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "bad",
    [
        VoiceRequest(voice="AF heart", speed=1.0, seed=1, items=(VoiceItem("hi", "full"),)),
        VoiceRequest(voice="af_heart", speed=3.0, seed=1, items=(VoiceItem("hi", "full"),)),
        VoiceRequest(voice="af_heart", speed=1.0, seed=1, items=()),
        VoiceRequest(
            voice="af_heart", speed=1.0, seed=1, items=(VoiceItem("x" * 41, "vocalization"),)
        ),
        VoiceRequest(voice="af_heart", speed=1.0, seed=1, items=(VoiceItem("hi", "whisper"),)),
    ],
)
async def test_invalid_requests_never_reach_the_child(bad):
    with pytest.raises(VoiceGenerationError) as raised:
        await generator().generate(bad, on_progress=ignore)
    assert raised.value.code == "bad_request"


def test_voice_model_directory_must_match_its_pinned_manifest(tmp_path):
    (tmp_path / "voices").mkdir()
    files = {
        "config.json": b"{}",
        "kokoro-v1_0.pth": b"weights" * 10,
        "voices/af_heart.pt": b"voice" * 10,
    }
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    manifest = {
        "repo": "hexgrad/Kokoro-82M",
        "revision": "f" * 40,
        "license": "apache-2.0",
        "files": {
            name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()
        },
    }
    data = json.dumps(manifest).encode()
    (tmp_path / "flintgraph-download.json").write_bytes(data)
    model, voices = verify_voice_model(tmp_path, hashlib.sha256(data).hexdigest())
    assert model == MODEL and voices == ("af_heart",)
    with pytest.raises(ValueError):
        verify_voice_model(tmp_path, "0" * 64)
    (tmp_path / "voices" / "af_heart.pt").write_bytes(b"tampered")
    with pytest.raises(ValueError):
        verify_voice_model(tmp_path, hashlib.sha256(data).hexdigest())
