import json
import unittest
from pathlib import Path

from contract import bucket_size, parse_request


class TrainingContractTests(unittest.TestCase):
    def request(self):
        return dict(
            schema_version=1,
            model_dir=str(Path.cwd() / "model"),
            model_manifest_sha256="a" * 64,
            dataset_sha256="b" * 64,
            recipe_sha256="c" * 64,
            trigger="fgstyle_qa",
            steps=20,
            seed=1,
            images=[
                dict(sha256=str(i) * 64, caption="adult character in a coat") for i in range(4)
            ],
        )

    def test_selected_images_and_bounded_training_only(self):
        value = self.request()
        self.assertEqual(len(parse_request(json.dumps(value).encode())["images"]), 4)
        for update in [
            {"steps": True},
            {"steps": 100000},
            {"images": value["images"][:1]},
            {"images": [value["images"][0]] * 4},
            {"command": "execute"},
            {"trigger": "not a trigger"},
        ]:
            with self.assertRaises(ValueError):
                parse_request(json.dumps({**value, **update}).encode())

    def test_buckets_preserve_aspect_and_bound_work(self):
        self.assertEqual(bucket_size(832, 1216), (416, 608))
        self.assertEqual(bucket_size(1344, 768), (672, 384))
        for shape in [(2560, 64), (64, 2560), (512, 512)]:
            w, h = bucket_size(*shape)
            self.assertLessEqual(w * h, 512**2)
            self.assertLessEqual(max(w, h), 768)
            self.assertEqual(w % 32, 0)
            self.assertEqual(h % 32, 0)


if __name__ == "__main__":
    unittest.main()
