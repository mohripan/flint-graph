"""Run with this isolated runtime's Python; no model weights are needed."""

import unittest

from PIL import Image
from reference import reference_image


class WholeFigureReferenceTest(unittest.TestCase):
    def test_full_body_padding_keeps_head_and_feet(self):
        source = Image.new("RGB", (100, 200), "red")
        source.putpixel((50, 0), (0, 0, 255))
        source.putpixel((50, 199), (0, 255, 0))
        result = reference_image(source)
        self.assertEqual(result.size, (200, 200))
        self.assertEqual(result.getpixel((100, 0)), (0, 0, 255))
        self.assertEqual(result.getpixel((100, 199)), (0, 255, 0))
        self.assertEqual(result.getpixel((0, 100)), (255, 255, 255))

    def test_transparency_is_composited_on_white(self):
        result = reference_image(Image.new("RGBA", (100, 200), (255, 0, 0, 0)))
        self.assertEqual(result.mode, "RGB")
        self.assertEqual(result.getpixel((100, 100)), (255, 255, 255))


if __name__ == "__main__":
    unittest.main()
