import unittest

from PIL import Image
from repair import composite, source_canvas


class RepairTests(unittest.TestCase):
    def test_rgb_patch_changes_only_the_selected_region(self):
        source = Image.new("RGB", (768, 1152), (10, 20, 30))
        descriptor = {
            "width": 768,
            "height": 1152,
            "source_box": None,
            "box": [400, 500, 560, 660],
            "feather": 8,
        }
        result = composite(source, Image.new("RGB", (768, 1152), (90, 80, 70)), descriptor)
        self.assertEqual(result.getpixel((399, 550)), (10, 20, 30))
        self.assertEqual(result.getpixel((480, 580)), (90, 80, 70))
        self.assertEqual(result.getpixel((560, 550)), (10, 20, 30))

    def test_transparent_crops_keep_dimensions_placement_and_outside_alpha(self):
        source = Image.new("RGBA", (512, 900), (10, 20, 30, 128))
        descriptor = {
            "width": 512,
            "height": 900,
            "source_box": [100, 100, 612, 1000],
            "box": [100, 300, 200, 500],
            "feather": 8,
        }
        canvas = source_canvas(source, descriptor)
        self.assertEqual(canvas.size, (768, 1152))
        self.assertEqual(canvas.getpixel((0, 0)), (255, 255, 255))
        result = composite(source, Image.new("RGBA", (768, 1152), (90, 80, 70, 0)), descriptor)
        self.assertEqual(result.size, source.size)
        self.assertEqual(result.getpixel((99, 350)), (10, 20, 30, 128))
        self.assertEqual(result.getpixel((150, 400)), (90, 80, 70, 0))
        self.assertEqual(source.getpixel((150, 400)), (10, 20, 30, 128))


if __name__ == "__main__":
    unittest.main()
