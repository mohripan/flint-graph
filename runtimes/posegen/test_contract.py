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

    def test_duplicate_fields_and_large_requests_are_rejected(self):
        for data in (b'{"schema_version":1,"schema_version":1}', b"x" * 65537):
            with self.assertRaises(ValueError):
                parse_request(data)


if __name__ == "__main__":
    unittest.main()
