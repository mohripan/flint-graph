import unittest

from settings import gpu_floor_gib, img2img_strength


class RepaintStrengthTest(unittest.TestCase):
    def test_control_admission_includes_measured_device_overhead(self):
        self.assertEqual(gpu_floor_gib("control", True), 11)
        self.assertEqual(gpu_floor_gib("control", False), 11.6)
        self.assertEqual(gpu_floor_gib("locked", False), 10)
        self.assertEqual(gpu_floor_gib("klein", False), 11)

    def test_high_denoising_ablation_is_allowed(self):
        self.assertEqual(img2img_strength("0.95"), 0.95)
        self.assertEqual(img2img_strength("0.7"), 0.7)

    def test_invalid_values_cannot_spend_a_gpu_run(self):
        for value in ("0", "-1", "1.1", "nan", "inf"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                img2img_strength(value)


if __name__ == "__main__":
    unittest.main()
