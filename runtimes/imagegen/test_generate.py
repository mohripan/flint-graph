"""The child's own checks, run with its locked environment (no GPU, no model needed):

    uv run --frozen python -I -m unittest discover -s . -p "test_*.py"

Set FLINT_IMAGEGEN_CUTOUT_MODEL to the anime-seg ``isnetis.onnx`` path to also check
the real segmenter's input and output contract on the CPU.
"""

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import generate
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent


def soft_disc(height: int, width: int, centre: tuple[int, int], radius: float, edge: float):
    """A figure mask: 1 inside, a linear ramp ``edge`` pixels wide, 0 outside."""
    rows, cols = np.mgrid[0:height, 0:width]
    distance = np.hypot(rows - centre[0], cols - centre[1])
    return np.clip((radius - distance) / edge + 0.5, 0, 1).astype(np.float32)


def composite(color, mask, background=(255, 255, 255)):
    """What a renderer draws: the figure blended over a plain background."""
    figure = np.asarray(color, dtype=np.float32)
    plain = np.asarray(background, dtype=np.float32)
    return np.rint(mask[..., None] * figure + (1 - mask[..., None]) * plain).astype(np.uint8)


class MaskToAlphaTest(unittest.TestCase):
    def test_confident_mask_values_become_fully_opaque_or_fully_transparent(self):
        mask = np.array([[0.0, 0.05, 0.1, 0.5, 0.9, 0.95, 1.0]], dtype=np.float32)
        alpha = generate.alpha_from_mask(mask)
        self.assertEqual(alpha.dtype, np.uint8)
        self.assertEqual(alpha.tolist(), [[0, 0, 0, 128, 255, 255, 255]])

    def test_edges_are_decontaminated_so_no_white_halo_remains(self):
        mask = soft_disc(120, 120, (60, 60), 40, 6)
        rgb = composite((200, 30, 40), mask)
        rgba, _ = generate.cut_out(rgb, mask)
        edge = (rgba[..., 3] > 0) & (rgba[..., 3] < 255)
        self.assertGreater(edge.sum(), 50)
        colours = rgba[edge][:, :3].astype(int)
        # Without decontamination these pixels would be pink: red mixed with white.
        self.assertLess(np.abs(colours - (200, 30, 40)).max(), 12)

    def test_transparent_pixels_carry_bled_figure_colour_not_the_background(self):
        mask = soft_disc(120, 120, (60, 60), 40, 2)
        rgba, _ = generate.cut_out(composite((20, 90, 160), mask), mask)
        clear = rgba[..., 3] == 0
        self.assertTrue(clear.any())
        # Filtering a scaled sprite mixes these in; white would draw a light fringe.
        self.assertLess(np.abs(rgba[clear][:, :3].astype(int) - (20, 90, 160)).max(), 12)

    def test_crop_keeps_a_small_margin_inside_the_image(self):
        mask = np.zeros((400, 300), dtype=np.float32)
        mask[100:300, 20:280] = 1
        rgba, box = generate.cut_out(composite((10, 10, 10), mask), mask)
        margin = generate.CROP_MARGIN
        self.assertEqual(box, (20 - margin, 100 - margin, 280 + margin, 300 + margin))
        self.assertEqual(rgba.shape, (200 + 2 * margin, 260 + 2 * margin, 4))
        self.assertEqual(rgba[0, 0, 3], 0)
        self.assertEqual(rgba[margin + 5, margin + 5, 3], 255)
        mask = np.zeros((400, 300), dtype=np.float32)
        mask[5:395, 1:20] = 1
        mask[5:20, 1:299] = 1
        _, box = generate.cut_out(composite((10, 10, 10), mask), mask)
        self.assertEqual(box, (0, 0, 300, 400), "The margin is clamped to the image")

    def test_narrow_figures_keep_a_crop_at_least_a_thumbnail_wide(self):
        mask = np.zeros((600, 500), dtype=np.float32)
        mask[50:550, 30:60] = 1
        rgba, box = generate.cut_out(composite((10, 10, 10), mask), mask)
        self.assertEqual(box[2] - box[0], generate.THUMBNAIL_WIDTH)
        self.assertEqual(box[0], 0, "Widened inside the image")
        self.assertEqual(rgba.shape[1], generate.THUMBNAIL_WIDTH)

    def test_empty_or_whole_image_masks_are_failed_segmentations(self):
        for mask in (np.zeros((200, 200), np.float32), np.ones((200, 200), np.float32)):
            with self.assertRaises(generate.CutoutError):
                generate.cut_out(composite((10, 10, 10), mask), mask)

    def test_letterbox_round_trip_returns_the_mask_at_image_size(self):
        image = Image.new("RGB", (832, 1216), "white")
        batch, placement = generate.letterbox(image)
        self.assertEqual(batch.shape, (1, 3, generate.CUTOUT_SIZE, generate.CUTOUT_SIZE))
        self.assertEqual(batch.dtype, np.float32)
        left, top, width, height = placement
        self.assertEqual((top, height), (0, 1024))
        self.assertAlmostEqual(width / height, 832 / 1216, places=2)
        self.assertEqual(float(batch[0, :, 512, left + 5].min()), 1.0, "Pixels in 0..1")
        self.assertEqual(float(batch[0, :, 512, 0].max()), 0.0, "Padded with black")
        output = np.zeros((1, 1, generate.CUTOUT_SIZE, generate.CUTOUT_SIZE), np.float32)
        output[0, 0, :, left : left + width] = 1
        mask = generate.unletterbox(output, placement, image.size)
        self.assertEqual(mask.shape, (1216, 832))
        self.assertGreater(float(mask.min()), 0.99)


class HiresTest(unittest.TestCase):
    def test_every_base_size_upscales_to_whole_latents_within_the_png_bounds(self):
        for width, height in generate.SIZES:
            for scale in generate.HIRES_SCALES:
                out_width, out_height = generate.hires_size(width, height, scale)
                self.assertEqual((out_width % 8, out_height % 8), (0, 0))
                self.assertLessEqual(max(out_width, out_height), 4096)
                self.assertLessEqual(out_width * out_height, 16_777_216)
        self.assertEqual(generate.hires_size(832, 1216, 2.0), (1664, 2432))
        self.assertEqual(generate.hires_size(832, 1216, 1.5), (1248, 1824))

    def test_upscaling_is_lanczos_to_the_exact_size(self):
        image = Image.new("RGB", (832, 1216), (128, 128, 128))
        image.putpixel((10, 10), (0, 0, 0))
        large = generate.upscale(image, 2.0)
        self.assertEqual(large.size, (1664, 2432))
        self.assertEqual(large.mode, "RGB")
        # Lanczos overshoots beside a dark dot (143 here); bicubic reaches 136, bilinear 128.
        self.assertGreater(max(large.getpixel((x, 21))[0] for x in range(14, 28)), 140)

    def test_high_resolution_needs_more_free_memory_than_a_standard_render(self):
        standard = generate.required_free_bytes(None)
        self.assertEqual(standard, generate.MIN_FREE_BYTES)
        for scale in generate.HIRES_SCALES:
            hires = generate.required_free_bytes({"scale": scale, "strength": 0.35})
            self.assertGreaterEqual(hires, standard)
            self.assertLess(hires, 12 * 1024**3, "Still fits the 12 GB development GPU")


class ChildRequestCase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        root = Path(self.work.name)
        (root / "model").mkdir()
        (root / "model" / "model_index.json").write_text("{}")
        (root / "out").mkdir()
        self.segmenter = root / "isnetis.onnx"
        self.segmenter.write_bytes(b"weights")
        self.request = {
            "protocol": 1,
            "model_dir": str(root / "model"),
            "output_dir": str(root / "out"),
            "prompt": "1girl, solo",
            "negative_prompt": "lowres",
            "width": 832,
            "height": 1216,
            "steps": 28,
            "guidance": 5.0,
            "seeds": [1],
        }

    def tearDown(self):
        self.work.cleanup()

    def run_child(self, request):
        """Only validation runs: every case here stops before any heavy import."""
        return subprocess.run(
            [sys.executable, "-I", str(HERE / "generate.py")],
            input=json.dumps(request).encode(),
            capture_output=True,
            timeout=60,
        )


class RequestTest(ChildRequestCase):
    def test_bad_cutout_fields_are_rejected_before_any_model_loads(self):
        sha = hashlib.sha256(b"weights").hexdigest()
        for cutout in (
            {"model": "isnetis.onnx", "sha256": sha},
            {"model": str(self.segmenter), "sha256": "ABC"},
            {"model": str(self.segmenter), "sha256": sha, "extra": 1},
            {"model": str(self.segmenter.with_suffix(".bin")), "sha256": sha},
            "yes",
        ):
            completed = self.run_child({**self.request, "cutout": cutout})
            self.assertEqual(completed.returncode, 2, cutout)
            event = json.loads(completed.stdout.decode().splitlines()[-1])
            self.assertEqual(event["code"], "bad_request", cutout)

    def test_valid_cutout_requests_pass_validation(self):
        sha = hashlib.sha256(b"weights").hexdigest()
        stdin = sys.stdin
        try:
            for extra in (
                {},
                {"cutout": None},
                {"cutout": {"model": str(self.segmenter), "sha256": sha}},
            ):
                sys.stdin = io.TextIOWrapper(
                    io.BytesIO(json.dumps({**self.request, **extra}).encode())
                )
                self.assertEqual(generate.read_request()["cutout"], extra.get("cutout"))
        finally:
            sys.stdin = stdin

    def test_bad_hires_fields_are_rejected_before_any_model_loads(self):
        for hires in (
            {"scale": 3, "strength": 0.35},
            {"scale": "2", "strength": 0.35},
            {"scale": True, "strength": 0.35},
            {"scale": 2.0, "strength": 0.05},
            {"scale": 2.0, "strength": 0.9},
            {"scale": 2.0},
            {"scale": 2.0, "strength": 0.35, "steps": 9},
            "yes",
        ):
            completed = self.run_child({**self.request, "hires": hires})
            self.assertEqual(completed.returncode, 2, hires)
            event = json.loads(completed.stdout.decode().splitlines()[-1])
            self.assertEqual(event["code"], "bad_request", hires)

    def test_valid_hires_requests_pass_validation(self):
        stdin = sys.stdin
        try:
            for extra in (
                {},
                {"hires": None},
                {"hires": {"scale": 2.0, "strength": 0.35}},
                {"hires": {"scale": 1.5, "strength": 0.4}},
                {"hires": {"scale": 2, "strength": 0.3}, "width": 1344, "height": 768},
            ):
                sys.stdin = io.TextIOWrapper(
                    io.BytesIO(json.dumps({**self.request, **extra}).encode())
                )
                self.assertEqual(generate.read_request()["hires"], extra.get("hires"))
        finally:
            sys.stdin = stdin

    def test_segmenter_bytes_must_match_the_pinned_hash(self):
        with self.assertRaises(SystemExit):
            generate.load_segmenter({"model": str(self.segmenter), "sha256": "0" * 64})


def sprite(width=200, height=300):
    """A transparent figure: a blue body with a skin-coloured head near the top."""
    pixels = np.zeros((height, width, 4), dtype=np.uint8)
    pixels[40:290, 60:140] = (30, 60, 160, 255)
    pixels[20:70, 75:125] = (240, 200, 180, 255)
    return Image.fromarray(pixels, "RGBA")


class FaceInpaintTest(unittest.TestCase):
    def test_context_is_a_square_around_the_face_padded_with_white(self):
        base = sprite()
        box = (75, 20, 125, 70)
        region, crop = generate.face_context(base, box)
        self.assertEqual(region.size, (generate.INPAINT_SIZE, generate.INPAINT_SIZE))
        self.assertEqual(region.mode, "RGB")
        left, top, right, bottom = crop
        self.assertEqual(right - left, bottom - top)
        self.assertEqual(right - left, round(50 * generate.FACE_CONTEXT))
        self.assertEqual(((left + right) / 2, (top + bottom) / 2), (100, 45))
        # The crop reaches above the image; that part is white, never black.
        self.assertLess(top, 0)
        self.assertEqual(region.getpixel((generate.INPAINT_SIZE // 2, 2)), (255, 255, 255))
        # Transparent pixels inside the image are white too, like the renders.
        self.assertEqual(region.getpixel((4, generate.INPAINT_SIZE // 2)), (255, 255, 255))

    def test_mask_covers_the_face_and_fades_out_well_before_the_crop_edge(self):
        box = (75, 20, 125, 70)
        _, crop = generate.face_context(sprite(), box)
        mask = np.asarray(generate.face_mask(box, crop))
        middle = generate.INPAINT_SIZE // 2
        self.assertEqual(mask[middle, middle], 255)
        self.assertEqual(mask[0, 0], 0)
        self.assertEqual(mask[middle, 0], 0)
        self.assertEqual(mask[-1, middle], 0)

    def test_paste_changes_only_the_face_and_keeps_size_and_alpha(self):
        base = sprite()
        box = (75, 20, 125, 70)
        region, crop = generate.face_context(base, box)
        mask = generate.face_mask(box, crop)
        painted = Image.new("RGB", region.size, (255, 0, 0))
        result = generate.paste_face(base, painted, crop, mask)
        self.assertEqual((result.size, result.mode), (base.size, "RGBA"))
        before, after = np.asarray(base), np.asarray(result)
        self.assertTrue((before[..., 3] == after[..., 3]).all(), "alpha never changes")
        self.assertTrue((before[200:, :] == after[200:, :]).all(), "the body is untouched")
        self.assertEqual(tuple(after[45, 100, :3]), (255, 0, 0), "the face is repainted")
        opaque = generate.paste_face(base.convert("RGB"), painted, crop, mask)
        self.assertEqual((opaque.size, opaque.mode), (base.size, "RGB"))


class InpaintRequestTest(ChildRequestCase):
    def setUp(self):
        super().setUp()
        root = Path(self.work.name)
        self.base = root / "base.png"
        sprite().save(self.base, format="PNG")
        self.inpaint = {
            "image": str(self.base),
            "sha256": hashlib.sha256(self.base.read_bytes()).hexdigest(),
            "box": [75, 20, 125, 70],
            "strength": 0.85,
            "prompts": ["1girl, smile"],
        }
        self.request = {**self.request, "width": 200, "height": 300, "inpaint": self.inpaint}

    def read(self, request):
        stdin = sys.stdin
        try:
            sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps(request).encode()))
            return generate.read_request()
        finally:
            sys.stdin = stdin

    def test_valid_inpaint_requests_pass_validation(self):
        self.assertEqual(self.read(self.request)["inpaint"]["box"], [75, 20, 125, 70])

    def test_high_resolution_sprites_are_accepted_up_to_the_limit(self):
        for height, accepted in ((2432, True), (2600, False)):
            Image.new("RGBA", (1664, height)).save(self.base, format="PNG")
            inpaint = {**self.inpaint, "sha256": hashlib.sha256(self.base.read_bytes()).hexdigest()}
            request = {**self.request, "width": 1664, "height": height, "inpaint": inpaint}
            if accepted:
                self.assertEqual(self.read(request)["height"], height)
            else:
                completed = self.run_child(request)
                self.assertEqual(completed.returncode, 2)

    def test_bad_inpaint_fields_are_rejected_before_any_model_loads(self):
        cases = [
            {"image": "base.png"},
            {"sha256": "0" * 64},
            {"box": [75, 20, 85, 30]},
            {"box": [150, 20, 250, 70]},
            {"box": [75, 20, 125]},
            {"strength": 0.1},
            {"strength": True},
            {"prompts": []},
            {"prompts": ["a", "b"]},
            {"extra": 1},
        ]
        for change in cases:
            completed = self.run_child({**self.request, "inpaint": {**self.inpaint, **change}})
            self.assertEqual(completed.returncode, 2, change)
            self.assertEqual(json.loads(completed.stdout.decode().splitlines()[-1])["code"],
                             "bad_request", change)
        for request in (
            {**self.request, "width": 201},
            {**self.request, "cutout": {"model": str(self.segmenter),
                                        "sha256": hashlib.sha256(b"weights").hexdigest()}},
            # A hires repaint would redraw the whole base, not just its face.
            {**self.request, "hires": {"scale": 2.0, "strength": 0.35}},
        ):
            completed = self.run_child(request)
            self.assertEqual(completed.returncode, 2)


class ReferenceImageTest(unittest.TestCase):
    def test_a_transparent_sprite_becomes_a_white_square_centred_on_the_figure(self):
        reference = generate.reference_image(sprite())
        side = generate.REFERENCE_SIZE
        self.assertEqual((reference.size, reference.mode), ((side, side), "RGB"))
        # The figure (80 x 270) fills the height; the sides are white padding.
        self.assertEqual(reference.getpixel((side // 2, side - 4)), (30, 60, 160))
        self.assertEqual(reference.getpixel((side // 2, 4)), (240, 200, 180))
        self.assertEqual(reference.getpixel((4, side // 2)), (255, 255, 255))
        self.assertEqual(reference.getpixel((side - 4, side // 2)), (255, 255, 255))

    def test_an_opaque_image_is_cropped_to_what_differs_from_its_backdrop(self):
        pixels = np.full((400, 300, 3), (205, 205, 215), dtype=np.uint8)
        pixels[100:300, 120:180] = (200, 30, 40)
        reference = generate.reference_image(Image.fromarray(pixels, "RGB"))
        side = generate.REFERENCE_SIZE
        self.assertEqual(reference.getpixel((side // 2, side // 2)), (200, 30, 40))
        self.assertEqual(reference.getpixel((side // 2, 2)), (200, 30, 40))
        self.assertEqual(reference.getpixel((2, side // 2)), (255, 255, 255))

    def test_an_image_without_a_distinct_figure_is_used_whole(self):
        reference = generate.reference_image(Image.new("RGB", (300, 200), (90, 90, 90)))
        side = generate.REFERENCE_SIZE
        self.assertEqual(reference.size, (side, side))
        self.assertEqual(reference.getpixel((side // 2, side // 2)), (90, 90, 90))
        self.assertEqual(reference.getpixel((side // 2, 2)), (255, 255, 255))


class SceneRequestTest(ChildRequestCase):
    def setUp(self):
        super().setUp()
        root = Path(self.work.name)
        adapter = root / "ip-adapter"
        (adapter / "sdxl_models").mkdir(parents=True)
        (adapter / "sdxl_models" / "ip-adapter-plus_sdxl_vit-h.safetensors").write_bytes(b"w")
        (adapter / "models" / "image_encoder").mkdir(parents=True)
        (adapter / "models" / "image_encoder" / "config.json").write_text("{}")
        (adapter / "models" / "image_encoder" / "model.safetensors").write_bytes(b"e")
        self.reference = root / "reference-0.png"
        sprite().save(self.reference, format="PNG")
        self.scene = {
            "adapter": str(adapter),
            "weight": "sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors",
            "encoder": "models/image_encoder",
            "scale": 0.5,
            "references": [
                {
                    "image": str(self.reference),
                    "sha256": hashlib.sha256(self.reference.read_bytes()).hexdigest(),
                }
            ],
        }
        self.request = {**self.request, "width": 1344, "height": 768, "scene": self.scene}

    def read(self, request):
        stdin = sys.stdin
        try:
            sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps(request).encode()))
            return generate.read_request()
        finally:
            sys.stdin = stdin

    def test_valid_scene_requests_pass_validation(self):
        self.assertEqual(self.read(self.request)["scene"]["scale"], 0.5)
        self.assertIsNone(self.read({**self.request, "scene": None})["scene"])

    def test_scenes_need_more_free_memory_than_a_portrait(self):
        self.assertGreater(generate.SCENE_MIN_FREE_BYTES, generate.MIN_FREE_BYTES)
        self.assertEqual(
            generate.required_free_bytes(None, self.scene), generate.SCENE_MIN_FREE_BYTES
        )

    def test_bad_scene_fields_are_rejected_before_any_model_loads(self):
        reference = self.scene["references"][0]
        cases = [
            {"adapter": "ip-adapter"},
            {"adapter": str(Path(self.work.name) / "missing")},
            {"weight": "../ip-adapter-plus_sdxl_vit-h.safetensors"},
            {"weight": "sdxl_models/missing.safetensors"},
            {"weight": "sdxl_models/ip-adapter-plus_sdxl_vit-h.bin"},
            {"encoder": "models"},
            {"scale": 0.0},
            {"scale": 1.5},
            {"scale": True},
            {"references": []},
            {"references": [reference, reference, reference]},
            {"references": [{**reference, "sha256": "0" * 64}]},
            {"references": [{**reference, "image": "reference-0.png"}]},
            {"references": [{**reference, "extra": 1}]},
            {"extra": 1},
        ]
        for change in cases:
            completed = self.run_child({**self.request, "scene": {**self.scene, **change}})
            self.assertEqual(completed.returncode, 2, change)
            self.assertEqual(json.loads(completed.stdout.decode().splitlines()[-1])["code"],
                             "bad_request", change)
        sha = hashlib.sha256(b"weights").hexdigest()
        for request in (
            # Scenes are landscape event art at the 16:9 bucket only.
            {**self.request, "width": 832, "height": 1216},
            {**self.request, "cutout": {"model": str(self.segmenter), "sha256": sha}},
            {**self.request, "hires": {"scale": 2.0, "strength": 0.35}},
            {**self.request, "inpaint": {"image": str(self.reference), "sha256": sha,
                                         "box": [75, 20, 125, 70], "strength": 0.9,
                                         "prompts": ["x"]}},
        ):
            completed = self.run_child(request)
            self.assertEqual(completed.returncode, 2)

    def test_two_characters_each_bring_a_reference(self):
        second = Path(self.work.name) / "reference-1.png"
        sprite(240, 320).save(second, format="PNG")
        references = [
            *self.scene["references"],
            {"image": str(second), "sha256": hashlib.sha256(second.read_bytes()).hexdigest()},
        ]
        request = {**self.request, "scene": {**self.scene, "references": references}}
        self.assertEqual(len(self.read(request)["scene"]["references"]), 2)
        for bad in (
            {**self.scene, "references": references + references[:1]},
            {**self.scene, "references": references, "regions": {}},
        ):
            completed = self.run_child({**self.request, "scene": bad})
            self.assertEqual(completed.returncode, 2)

    def test_a_reference_too_small_or_not_a_png_is_rejected(self):
        for write in (
            lambda path: Image.new("RGB", (40, 40)).save(path, format="PNG"),
            lambda path: path.write_bytes(b"not a png"),
        ):
            write(self.reference)
            reference = {"image": str(self.reference),
                         "sha256": hashlib.sha256(self.reference.read_bytes()).hexdigest()}
            completed = self.run_child(
                {**self.request, "scene": {**self.scene, "references": [reference]}}
            )
            self.assertEqual(completed.returncode, 2)


@unittest.skipUnless(os.getenv("FLINT_IMAGEGEN_CUTOUT_MODEL"), "set the anime-seg ONNX path")
class RealSegmenterTest(unittest.TestCase):
    def test_the_pinned_model_accepts_a_letterboxed_image_and_returns_a_mask(self):
        path = os.environ["FLINT_IMAGEGEN_CUTOUT_MODEL"]
        sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        session, version = generate.load_segmenter({"model": path, "sha256": sha})
        self.assertTrue(version)
        mask = generate.segment(session, Image.new("RGB", (832, 1216), "white"))
        self.assertEqual(mask.shape, (1216, 832))
        self.assertGreaterEqual(float(mask.min()), 0.0)
        self.assertLessEqual(float(mask.max()), 1.0)


if __name__ == "__main__":
    unittest.main()
