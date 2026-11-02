import json
import unittest
from pathlib import Path

from contract import parse_request


class PoseContractTests(unittest.TestCase):
    def request(self, **changes):
        return {
            "schema_version": 1,
            "model_dir": str(Path.cwd() / "models"),
            "model_manifest_sha256": "a" * 64,
            "reference_sha256": "b" * 64,
            "prompt": "Same character, sitting on a chair",
            "seeds": [10],
            "cutout": None,
            **changes,
        }

    def test_valid_request_and_rejection_before_loading_a_model(self):
        self.assertEqual(parse_request(json.dumps(self.request()).encode())["seeds"], [10])
        for changes in (
            {"seeds": [True]},
            {"seeds": []},
            {"seeds": [2**32]},
            {"reference_sha256": "unverified"},
            {"prompt": ""},
            {"command": "execute"},
            {"cutout": {"model": "not.onnx"}},
        ):
            with self.assertRaises(ValueError):
                parse_request(json.dumps(self.request(**changes)).encode())

    def test_two_view_protocol_is_closed_and_does_not_accept_source_paths(self):
        value = self.request(schema_version=2)
        value.pop("reference_sha256")
        value["reference_sha256s"] = ["a" * 64, "b" * 64]
        self.assertEqual(parse_request(json.dumps(value).encode())["schema_version"], 2)
        for changes in (
            {"reference_sha256s": []},
            {"reference_sha256s": ["a" * 64] * 3},
            {"reference_sha256s": ["a" * 64] * 2},
            {"reference_paths": ["C:/private.png"]},
        ):
            with self.assertRaises(ValueError):
                parse_request(json.dumps({**value, **changes}).encode())

    def test_model_manifest_rejects_invalid_entries_without_loading_ml(self):
        import hashlib
        import tempfile

        from contract import MODEL_REPO, MODEL_REVISION, verify_model

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for entry in (None, {}, {"sha256": "invalid"}):
                data = json.dumps(
                    dict(
                        repo=MODEL_REPO, revision=MODEL_REVISION, files={"model.safetensors": entry}
                    )
                ).encode()
                (root / "flintgraph-download.json").write_bytes(data)
                with self.assertRaisesRegex(ValueError, "model_invalid"):
                    verify_model(root, hashlib.sha256(data).hexdigest())

    def test_style_protocol_pins_weights_without_accepting_a_weight_path(self):
        value = self.request(schema_version=3)
        value["reference_sha256s"] = [value.pop("reference_sha256")]
        value["style"] = {
            "sha256": "c" * 64,
            "strength": 0.5,
            "dataset_sha256": "d" * 64,
            "recipe_sha256": "e" * 64,
        }
        self.assertEqual(parse_request(json.dumps(value).encode())["style"]["strength"], 0.5)
        for style in (
            {**value["style"], "strength": True},
            {**value["style"], "path": "private"},
            {**value["style"], "strength": 1.1},
        ):
            with self.assertRaises(ValueError):
                parse_request(json.dumps({**value, "style": style}).encode())

    def test_duplicate_fields_and_large_requests_are_rejected(self):
        for data in (b'{"schema_version":1,"schema_version":1}', b"x" * 65537):
            with self.assertRaises(ValueError):
                parse_request(data)

    def test_character_and_style_protocol_has_closed_unique_roles_and_a_total_strength(self):
        value = self.request(schema_version=4)
        value["reference_sha256s"] = [value.pop("reference_sha256")]
        value["adapters"] = [
            {
                "role": role,
                "sha256": digest * 64,
                "strength": strength,
                "dataset_sha256": "d" * 64,
                "recipe_sha256": "e" * 64,
            }
            for role, digest, strength in (("character", "a", 0.6), ("style", "b", 0.4))
        ]
        self.assertEqual(
            parse_request(json.dumps(value).encode())["adapters"][0]["role"], "character"
        )
        for changes in (
            {"adapters": []},
            {"adapters": value["adapters"] * 2},
            {"adapters": [value["adapters"][0]] * 2},
            {"adapters": list(reversed(value["adapters"]))},
            {"adapters": [{**value["adapters"][0], "path": "private"}]},
            {"adapters": [{**value["adapters"][0], "strength": True}]},
            {"adapters": [{**value["adapters"][0], "strength": float("nan")}]},
            {"adapters": [{**a, "strength": 0.6} for a in value["adapters"]]},
        ):
            with self.assertRaises(ValueError):
                parse_request(json.dumps({**value, **changes}).encode())

    def test_repair_protocol_pins_source_canvas_and_a_small_native_rectangle(self):
        value = self.request(schema_version=5)
        value.pop("reference_sha256")
        value["reference_sha256s"] = ["a" * 64, "b" * 64]
        value["adapters"] = []
        value["repair"] = {
            "width": 768,
            "height": 1152,
            "source_box": None,
            "box": [400, 500, 560, 660],
            "feather": 8,
        }
        self.assertEqual(
            parse_request(json.dumps(value).encode())["repair"]["box"], [400, 500, 560, 660]
        )
        for repair in (
            {**value["repair"], "box": [0, 0, 768, 1152]},
            {**value["repair"], "box": [-1, 0, 20, 40]},
            {**value["repair"], "box": [0, 0, True, 40]},
            {**value["repair"], "width": 767},
            {**value["repair"], "source_box": [0, 0, 700, 1100]},
            {**value["repair"], "feather": 9},
            {**value["repair"], "path": "private.png"},
        ):
            with self.assertRaises(ValueError):
                parse_request(json.dumps({**value, "repair": repair}).encode())
        value["repair"] = {
            "width": 512,
            "height": 900,
            "source_box": [100, 100, 612, 1000],
            "box": [100, 300, 200, 500],
            "feather": 8,
        }
        value["cutout"] = {"model": str(Path.cwd() / "cutout.onnx"), "sha256": "c" * 64}
        self.assertEqual(parse_request(json.dumps(value).encode())["repair"]["width"], 512)

    def test_pose_guide_protocol_closes_roles_and_coordinates(self):
        value = self.request(schema_version=6)
        value.pop("reference_sha256")
        value["reference_sha256s"] = ["a" * 64]
        value["adapters"] = []
        value["control"] = {
            "manifest_sha256": "c" * 64,
            "weights_sha256": "d" * 64,
            "guide_sha256": "e" * 64,
            "guide": {
                "id": "seated-front-v1",
                "label": "Seated",
                "width": 768,
                "height": 1152,
                "points": [[100, 100]] * 18,
            },
        }
        self.assertEqual(parse_request(json.dumps(value).encode())["schema_version"], 6)
        for changed in [
            dict(value["control"], path="untrusted.safetensors"),
            dict(value["control"], guide=dict(value["control"]["guide"], width=768.0)),
            dict(
                value["control"], guide=dict(value["control"]["guide"], points=[[True, 100]] * 18)
            ),
            dict(value["control"], guide=dict(value["control"]["guide"], points=[[800, 100]] * 18)),
        ]:
            with self.assertRaises(ValueError):
                parse_request(json.dumps({**value, "control": changed}).encode())

    def test_standing_and_walking_guides_use_the_same_closed_protocol(self):
        value = self.request(schema_version=6)
        value.pop("reference_sha256")
        value.update(
            reference_sha256s=["a" * 64],
            adapters=[],
            control={
                "manifest_sha256": "c" * 64,
                "weights_sha256": "d" * 64,
                "guide_sha256": "e" * 64,
                "guide": {
                    "id": "standing-front-v1",
                    "label": "Standing",
                    "width": 768,
                    "height": 1152,
                    "points": [[100, 100]] * 18,
                },
            },
        )
        for name in ["standing-front-v1", "walking-three-quarter-v1"]:
            value["control"]["guide"]["id"] = name
            self.assertEqual(
                parse_request(json.dumps(value).encode())["control"]["guide"]["id"], name
            )
        value["control"]["guide"]["id"] = "unknown-guide"
        with self.assertRaises(ValueError):
            parse_request(json.dumps(value).encode())


if __name__ == "__main__":
    unittest.main()
