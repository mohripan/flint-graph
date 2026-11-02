"""The control image contains both leg chains in the expected COCO-18 colors."""

import unittest

from guidance import render_guide


class GuideRasterTests(unittest.TestCase):
    def test_separate_ankles_and_black_background_survive_rasterization(self):
        points = [
            [384, 185],
            [384, 290],
            [320, 300],
            [300, 430],
            [355, 545],
            [448, 300],
            [468, 430],
            [410, 545],
            [340, 565],
            [260, 650],
            [270, 1070],
            [428, 565],
            [480, 650],
            [500, 1070],
            [365, 177],
            [401, 177],
            [348, 192],
            [420, 192],
        ]
        image = render_guide(
            {
                "id": "seated-front-v1",
                "label": "Seated",
                "width": 768,
                "height": 1152,
                "points": points,
            }
        )
        self.assertEqual(image.mode, "RGB")
        self.assertEqual(image.size, (768, 1152))
        self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))
        self.assertEqual(image.getpixel((270, 1070)), (0, 170, 255))
        self.assertEqual(image.getpixel((500, 1070)), (85, 0, 255))
        self.assertNotEqual(image.getpixel((265, 860)), (0, 0, 0))
        self.assertNotEqual(image.getpixel((490, 860)), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
