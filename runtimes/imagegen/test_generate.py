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


class RequestTest(unittest.TestCase):
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

    def test_segmenter_bytes_must_match_the_pinned_hash(self):
        with self.assertRaises(SystemExit):
            generate.load_segmenter({"model": str(self.segmenter), "sha256": "0" * 64})


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
