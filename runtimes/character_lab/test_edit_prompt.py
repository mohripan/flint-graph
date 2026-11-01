"""The model-specific wording must retain the fixed bench's pose and scene intent."""

import unittest

from edit_prompt import edit_prompt


class EditPromptTest(unittest.TestCase):
    def test_preserves_pose_object_scene_and_lighting_without_inferring_a_new_look(self):
        case = {
            "prompt": "adult, white hair, solo, sitting, holding a flower, garden, sunset, "
            "anime coloring, masterpiece"
        }
        prompt = edit_prompt(case)
        for detail in (
            "sitting",
            "holding a flower",
            "garden",
            "sunset",
            "same adult character",
            "outfit",
        ):
            self.assertIn(detail, prompt)
        self.assertNotIn("white hair", prompt)

    def test_refuses_an_unrecognized_fixture_prompt(self):
        with self.assertRaises(ValueError):
            edit_prompt({"prompt": "another unspecified scene"})

    def test_pair_keeps_each_reference_on_its_side_and_can_take_background_context(self):
        case = {
            "participants": ["aster", "nera"],
            "description": "sitting on a bench, garden, sunset",
        }
        prompt = edit_prompt(case, background_context=True)
        for detail in (
            "two adult characters",
            "image 1 on the left",
            "image 2 on the right",
            "image 3",
            "sunset",
        ):
            self.assertIn(detail, prompt)
        self.assertNotIn("One character only", prompt)


if __name__ == "__main__":
    unittest.main()
