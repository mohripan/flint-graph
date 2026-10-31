"""The trusted parent of the image child: protocol, watchdog, output checks, model pin."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

from flint_graph.infrastructure.narrative_imagegen import (
    CutoutModel,
    GenerationRequest,
    ImageGenerationError,
    InpaintRequest,
    IpAdapterModel,
    LocalImageGenerator,
    ModelIdentity,
    SceneRequest,
    verify_cutout_model,
    verify_ip_adapter_model,
    verify_model,
)
from flint_graph.narrative.imagegen import HiresFix

FAKE = Path(__file__).parents[1] / "fixtures" / "narrative" / "fake_imagegen.py"
MODEL = ModelIdentity(repo="fixture/model", revision="a" * 40, license="openrail++")


SEGMENTER = ModelIdentity(repo="fixture/segmenter", revision="d" * 40, license="apache-2.0")


def generator(deadline=30, cutout=None, ip_adapter=None):
    return LocalImageGenerator(
        python=Path(sys.executable),
        script=FAKE,
        model_dir=Path(__file__).parent,
        model=MODEL,
        deadline_seconds=deadline,
        cutout=cutout,
        ip_adapter=ip_adapter,
    )


HIRES = HiresFix(scale=2.0, strength=0.35)


def request(mode="ok", seeds=(11, 22), cutout=False, hires=None):
    return GenerationRequest(
        prompt=f"{mode}, solo",
        negative_prompt="lowres",
        width=832,
        height=1216,
        steps=28,
        guidance=5.0,
        seeds=tuple(seeds),
        cutout=cutout,
        hires=hires,
    )


def segmenter(root: Path, sha256: str | None = None) -> CutoutModel:
    data = b"onnx-weights" * 50
    (root / "isnetis.onnx").write_bytes(data)
    return CutoutModel(
        path=root / "isnetis.onnx",
        sha256=sha256 or hashlib.sha256(data).hexdigest(),
        identity=SEGMENTER,
    )


async def ignore(done):
    return None


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
async def test_cutout_returns_cropped_rgba_sprites_with_their_box(tmp_path):
    model = segmenter(tmp_path)
    result = await generator(cutout=model).generate(
        request(seeds=(7, 8), cutout=True), on_progress=ignore
    )
    assert result.cutout == model and result.runtime["onnxruntime"] == "fake"
    first = result.images[0]
    assert first.box == (100, 40, 612, 1176)
    assert (first.width, first.height) == (512, 1136)
    assert first.data[24:26] == bytes([8, 6]), "8-bit RGBA"
    assert (first.thumbnail_width, first.thumbnail_height) == (256, 568)
    noisy = await generator(cutout=model).generate(
        request("metadata", seeds=(7,), cutout=True), on_progress=ignore
    )
    assert b"tEXt" not in noisy.images[0].data, "Normalized like an upload"
    assert noisy.images[0].data[24:26] == bytes([8, 6]), "Normalizing keeps the alpha"
    assert noisy.images[0].sha256 == hashlib.sha256(noisy.images[0].data).hexdigest()
    plain = await generator(cutout=model).generate(request(seeds=(7,)), on_progress=ignore)
    assert plain.cutout is None and plain.images[0].box is None
    assert (plain.images[0].width, plain.images[0].height) == (832, 1216)
    assert "onnxruntime" not in plain.runtime


@pytest.mark.anyio
async def test_a_render_without_a_figure_is_skipped_and_the_others_are_kept(tmp_path):
    progress = []

    async def on_progress(done):
        progress.append(done)

    result = await generator(cutout=segmenter(tmp_path)).generate(
        request("cutskip", seeds=(7, 8, 9), cutout=True), on_progress=on_progress
    )
    assert [(image.index, image.seed) for image in result.images] == [(0, 7), (2, 9)]
    assert all(image.box == (100, 40, 612, 1176) for image in result.images)
    assert progress == [1, 2, 3], "A skipped render still counts as done"
    for mode, cutout, code in (
        ("cutskipall", True, "cutout_failed"),
        ("skipwrong", True, "invalid_output"),
        ("skipplain", False, "invalid_output"),
    ):
        with pytest.raises(ImageGenerationError) as raised:
            await generator(cutout=segmenter(tmp_path)).generate(
                request(mode, seeds=(7, 8, 9), cutout=cutout), on_progress=ignore
            )
        assert raised.value.code == code, mode


@pytest.mark.anyio
async def test_cutout_needs_a_configured_and_matching_segmenter(tmp_path):
    with pytest.raises(ImageGenerationError) as raised:
        await generator().generate(request(cutout=True), on_progress=ignore)
    assert raised.value.code == "cutout_unavailable"
    wrong = segmenter(tmp_path, sha256="0" * 64)
    with pytest.raises(ImageGenerationError) as raised:
        await generator(cutout=wrong).generate(request(cutout=True), on_progress=ignore)
    assert raised.value.code == "model_invalid", "The child hashes the bytes it loads"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("opaquecut", "invalid_output"),
        ("badbox", "invalid_output"),
        ("outsidebox", "invalid_output"),
        ("nobox", "invalid_output"),
        ("nocutruntime", "invalid_output"),
        ("cutfail", "cutout_failed"),
    ],
)
async def test_cutout_output_is_checked(tmp_path, mode, code):
    with pytest.raises(ImageGenerationError) as raised:
        await generator(cutout=segmenter(tmp_path)).generate(
            request(mode, seeds=(3,), cutout=True), on_progress=ignore
        )
    assert raised.value.code == code


@pytest.mark.anyio
async def test_high_resolution_images_are_checked_at_the_upscaled_size(tmp_path):
    result = await generator().generate(request(seeds=(4,), hires=HIRES), on_progress=ignore)
    image = result.images[0]
    assert (image.width, image.height) == (1664, 2432)
    assert (image.thumbnail_width, image.thumbnail_height) == (256, 374)
    with pytest.raises(ImageGenerationError) as raised:
        await generator().generate(request("hireslow", seeds=(4,), hires=HIRES), on_progress=ignore)
    assert raised.value.code == "invalid_output", "A base-size image is not what was asked"
    with pytest.raises(ImageGenerationError) as raised:
        await generator().generate(request("hiresonly"), on_progress=ignore)
    assert raised.value.code == "invalid_output", "Nor is an upscaled one for a standard job"


@pytest.mark.anyio
async def test_high_resolution_sprites_are_cropped_inside_the_upscaled_render(tmp_path):
    model = segmenter(tmp_path)
    result = await generator(cutout=model).generate(
        request(seeds=(7,), cutout=True, hires=HIRES), on_progress=ignore
    )
    sprite = result.images[0]
    assert sprite.box == (200, 80, 1224, 2352), "Outside 832x1216, inside 1664x2432"
    assert (sprite.width, sprite.height) == (1024, 2272)
    assert sprite.data[24:26] == bytes([8, 6])
    with pytest.raises(ImageGenerationError) as raised:
        await generator(cutout=model).generate(
            request("outsidebox", seeds=(7,), cutout=True, hires=HIRES), on_progress=ignore
        )
    assert raised.value.code == "invalid_output"


@pytest.mark.anyio
async def test_unsupported_high_resolution_settings_never_reach_the_child():
    for hires in (HiresFix(scale=3.0, strength=0.35), HiresFix(scale=2.0, strength=0.9)):
        with pytest.raises(ImageGenerationError) as raised:
            await generator().generate(request(seeds=(1,), hires=hires), on_progress=ignore)
        assert raised.value.code == "bad_request"


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


def test_cutout_model_is_the_single_onnx_file_of_its_pinned_manifest(tmp_path):
    weights = b"onnx" * 100
    (tmp_path / "isnetis.onnx").write_bytes(weights)
    (tmp_path / "README.md").write_bytes(b"readme")

    def pin(files):
        manifest = {
            "repo": "skytnt/anime-seg",
            "revision": "e" * 40,
            "license": "apache-2.0",
            "files": {
                name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in files.items()
            },
        }
        data = json.dumps(manifest).encode()
        (tmp_path / "flintgraph-download.json").write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    model = verify_cutout_model(tmp_path, pin({"isnetis.onnx": weights, "README.md": b"readme"}))
    assert model.path == (tmp_path / "isnetis.onnx").resolve()
    assert model.sha256 == hashlib.sha256(weights).hexdigest()
    assert model.identity == ModelIdentity("skytnt/anime-seg", "e" * 40, "apache-2.0")
    (tmp_path / "isnetis.onnx").unlink()
    (tmp_path / "README.md").write_bytes(weights)
    with pytest.raises(ValueError, match="one ONNX"):
        verify_cutout_model(tmp_path, pin({"README.md": weights}))
    (tmp_path / "a.onnx").write_bytes(weights)
    (tmp_path / "b.onnx").write_bytes(weights)
    with pytest.raises(ValueError, match="one ONNX"):
        verify_cutout_model(
            tmp_path, pin({"README.md": weights, "a.onnx": weights, "b.onnx": weights})
        )


def base_png(width=300, height=500, alpha=True):
    import struct
    import zlib

    def chunk(kind, payload):
        crc = struct.pack(">I", zlib.crc32(kind + payload))
        return struct.pack(">I", len(payload)) + kind + payload + crc

    row = b"\x00" + bytes([90, 60, 200, 255][: 4 if alpha else 3]) * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height, 9))
        + chunk(b"IEND", b"")
    )


def inpaint_request(mode="ok", alpha=True, seeds=(7, 8)):
    return GenerationRequest(
        prompt=f"{mode}, face",
        negative_prompt="lowres",
        width=300,
        height=500,
        steps=28,
        guidance=6.0,
        seeds=tuple(seeds),
        inpaint=InpaintRequest(
            image=base_png(alpha=alpha),
            box=(100, 20, 160, 80),
            strength=0.85,
            prompts=tuple(f"{mode}, expression {seed}" for seed in seeds),
        ),
    )


@pytest.mark.anyio
async def test_inpainting_keeps_the_base_size_and_transparency(tmp_path):
    for alpha in (True, False):
        result = await generator().generate(inpaint_request(alpha=alpha), on_progress=ignore)
        assert [(image.width, image.height) for image in result.images] == [(300, 500)] * 2
        assert all(image.data[25] == (6 if alpha else 2) for image in result.images)
        assert all(image.box is None for image in result.images)
        assert result.cutout is None


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["flatexpr", "wrongsize", "basehash"])
async def test_inpainting_output_and_base_are_checked(mode):
    with pytest.raises(ImageGenerationError) as raised:
        await generator().generate(inpaint_request(mode), on_progress=ignore)
    assert raised.value.code == ("model_invalid" if mode == "basehash" else "invalid_output")


@pytest.mark.anyio
async def test_inpainting_needs_one_prompt_per_seed_and_no_cutout(tmp_path):
    from dataclasses import replace

    request = inpaint_request()
    for bad in (
        replace(request, inpaint=replace(request.inpaint, prompts=("only one",))),
        replace(request, cutout=True),
        # A hires repaint would redraw the whole base, not just its face.
        replace(request, hires=HIRES),
    ):
        with pytest.raises(ImageGenerationError) as raised:
            await generator(cutout=segmenter(tmp_path)).generate(bad, on_progress=ignore)
        assert raised.value.code == "bad_request"


ADAPTER = ModelIdentity(repo="h94/IP-Adapter", revision="1" * 40, license="apache-2.0")
WEIGHT = "sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors"
ENCODER = "models/image_encoder"


def adapter(root: Path) -> IpAdapterModel:
    return IpAdapterModel(root=root, weight=WEIGHT, encoder=ENCODER, identity=ADAPTER)


def scene_request(mode="ok", seeds=(5, 6), references=None):
    return GenerationRequest(
        prompt=f"{mode}, solo, sitting on a couch",
        negative_prompt="lowres",
        width=1344,
        height=768,
        steps=28,
        guidance=5.0,
        seeds=tuple(seeds),
        scene=SceneRequest(
            references=references if references is not None else (base_png(),), scale=0.5
        ),
    )


@pytest.mark.anyio
async def test_scene_art_sends_its_reference_and_returns_opaque_landscape_scenes(tmp_path):
    result = await generator(ip_adapter=adapter(tmp_path)).generate(
        scene_request(), on_progress=ignore
    )
    assert [(image.width, image.height) for image in result.images] == [(1344, 768)] * 2
    # Opaque RGB scenes, even from a transparent reference sprite.
    assert all(image.data[25] == 2 and image.box is None for image in result.images)
    assert result.ip_adapter == adapter(tmp_path) and result.cutout is None


@pytest.mark.anyio
async def test_scene_art_needs_a_configured_ip_adapter():
    with pytest.raises(ImageGenerationError) as raised:
        await generator().generate(scene_request(), on_progress=ignore)
    assert raised.value.code == "ip_adapter_unavailable"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("rgbascene", "invalid_output"),
        ("refhash", "model_invalid"),
        ("wrongsize", "invalid_output"),
    ],
)
async def test_scene_art_output_and_reference_are_checked(tmp_path, mode, code):
    with pytest.raises(ImageGenerationError) as raised:
        await generator(ip_adapter=adapter(tmp_path)).generate(
            scene_request(mode), on_progress=ignore
        )
    assert raised.value.code == code


@pytest.mark.anyio
async def test_scene_art_takes_one_reference_and_no_other_mode(tmp_path):
    from dataclasses import replace

    request = scene_request()
    for bad in (
        scene_request(references=()),
        scene_request(references=(base_png(), base_png(alpha=False))),
        replace(request, width=832, height=1216),
        replace(request, cutout=True),
        replace(request, hires=HIRES),
        replace(request, inpaint=inpaint_request().inpaint),
        replace(request, scene=replace(request.scene, scale=1.5)),
    ):
        with pytest.raises(ImageGenerationError) as raised:
            await generator(cutout=segmenter(tmp_path), ip_adapter=adapter(tmp_path)).generate(
                bad, on_progress=ignore
            )
        assert raised.value.code == "bad_request", bad


def ip_adapter_fixture(root: Path, files: dict[str, bytes]) -> str:
    for name, data in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
    manifest = {
        "repo": "h94/IP-Adapter",
        "revision": "1" * 40,
        "license": "apache-2.0",
        "files": {
            name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()
        },
    }
    data = json.dumps(manifest).encode()
    (root / "flintgraph-download.json").write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_ip_adapter_is_one_sdxl_weight_and_its_image_encoder_under_one_pin(tmp_path):
    files = {
        "README.md": b"readme",
        WEIGHT: b"adapter" * 10,
        f"{ENCODER}/config.json": b"{}",
        f"{ENCODER}/model.safetensors": b"encoder" * 10,
    }
    pin = ip_adapter_fixture(tmp_path, files)
    model = verify_ip_adapter_model(tmp_path, pin)
    assert model == IpAdapterModel(
        root=tmp_path.resolve(), weight=WEIGHT, encoder=ENCODER, identity=ADAPTER
    )
    with pytest.raises(ValueError):
        verify_ip_adapter_model(tmp_path, "0" * 64)
    (tmp_path / WEIGHT).write_bytes(b"tampered")
    with pytest.raises(ValueError):
        verify_ip_adapter_model(tmp_path, pin)
    for broken in (
        # No SDXL weight, two of them, or no image encoder beside it.
        {name: data for name, data in files.items() if name != WEIGHT},
        {**files, "sdxl_models/ip-adapter_sdxl.safetensors": b"other"},
        {name: data for name, data in files.items() if not name.startswith(ENCODER)},
    ):
        root = tmp_path / f"case-{len(broken)}-{hash(tuple(broken)) & 0xFFFF}"
        root.mkdir()
        with pytest.raises(ValueError, match="IP-Adapter"):
            verify_ip_adapter_model(root, ip_adapter_fixture(root, broken))
