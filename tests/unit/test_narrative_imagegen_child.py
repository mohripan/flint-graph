"""The trusted parent of the image child: protocol, watchdog, output checks, model pin."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

from flint_graph.infrastructure.narrative_imagegen import (
    GenerationRequest,
    ImageGenerationError,
    LocalImageGenerator,
    ModelIdentity,
    verify_model,
)

FAKE = Path(__file__).parents[1] / "fixtures" / "narrative" / "fake_imagegen.py"
MODEL = ModelIdentity(repo="fixture/model", revision="a" * 40, license="openrail++")


def generator(deadline=30):
    return LocalImageGenerator(
        python=Path(sys.executable),
        script=FAKE,
        model_dir=Path(__file__).parent,
        model=MODEL,
        deadline_seconds=deadline,
    )


def request(mode="ok", seeds=(11, 22)):
    return GenerationRequest(
        prompt=f"{mode}, solo",
        negative_prompt="lowres",
        width=832,
        height=1216,
        steps=28,
        guidance=5.0,
        seeds=tuple(seeds),
    )


@pytest.mark.anyio
async def test_generator_returns_validated_images_and_reports_progress():
    progress = []

    async def on_progress(done):
        progress.append(done)

    result = await generator().generate(request(), on_progress=on_progress)
    assert progress == [1, 2]
    assert [image.seed for image in result.images] == [11, 22]
    first = result.images[0]
    assert (first.width, first.height) == (832, 1216)
    assert (first.thumbnail_width, first.thumbnail_height) == (256, 374)
    assert first.sha256 == hashlib.sha256(first.data).hexdigest()
    assert first.thumbnail_sha256 == hashlib.sha256(first.thumbnail).hexdigest()
    assert result.runtime["device"] == "Fake GPU" and result.truncated is False
    long = await generator().generate(request("long", seeds=(5,)), on_progress=on_progress)
    assert long.truncated is True and long.prompt_tokens == 81


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("busy", "gpu_busy"),
        ("crash", "generation_failed"),
        ("badpng", "invalid_output"),
        ("wrongsize", "invalid_output"),
        ("wrongseed", "invalid_output"),
        ("extra", "invalid_output"),
        ("noisy", "invalid_output"),
    ],
)
async def test_child_failures_map_to_safe_codes(mode, code):
    async def ignore(done):
        return None

    with pytest.raises(ImageGenerationError) as raised:
        await generator().generate(request(mode), on_progress=ignore)
    assert raised.value.code == code


@pytest.mark.anyio
async def test_watchdog_kills_a_hung_child():
    async def ignore(done):
        return None

    with pytest.raises(ImageGenerationError) as raised:
        await generator(deadline=2).generate(request("hang"), on_progress=ignore)
    assert raised.value.code == "generation_timeout"


def model_fixture(root: Path) -> str:
    (root / "unet").mkdir()
    weights = b"weights" * 100
    (root / "unet" / "model.safetensors").write_bytes(weights)
    (root / "model_index.json").write_bytes(b"{}")
    manifest = {
        "repo": "fixture/model",
        "revision": "b" * 40,
        "license": "openrail++",
        "files": {
            "model_index.json": {"size": 2, "sha256": hashlib.sha256(b"{}").hexdigest()},
            "unet/model.safetensors": {
                "size": len(weights),
                "sha256": hashlib.sha256(weights).hexdigest(),
            },
        },
    }
    data = json.dumps(manifest).encode()
    (root / "flintgraph-download.json").write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_model_directory_must_match_the_pinned_manifest(tmp_path):
    pin = model_fixture(tmp_path)
    identity = verify_model(tmp_path, pin)
    assert identity == ModelIdentity("fixture/model", "b" * 40, "openrail++")
    with pytest.raises(ValueError):
        verify_model(tmp_path, "0" * 64)
    (tmp_path / "unet" / "extra.py").write_text("print('no')")
    with pytest.raises(ValueError):
        verify_model(tmp_path, pin)
    (tmp_path / "unet" / "extra.py").unlink()
    (tmp_path / "unet" / "model.safetensors").write_bytes(b"tampered")
    with pytest.raises(ValueError):
        verify_model(tmp_path, pin)
