"""Real tensor checks for clean reference inputs and target-only learning."""

import unittest

import torch
from conditioning import target_prediction, training_inputs


class ReferenceTrainingTests(unittest.TestCase):
    def test_reference_is_clean_separate_and_never_a_denoising_target(self):
        noisy = torch.full((1, 128, 2, 2), 5.0)
        reference = torch.full((1, 128, 1, 2), 3.0)
        packed, ids = training_inputs(noisy, reference)
        self.assertEqual(tuple(packed.shape), (1, 6, 128))
        self.assertTrue(torch.all(packed[:, :4] == 5))
        self.assertTrue(torch.all(packed[:, 4:] == 3))
        self.assertEqual(ids[0, 0].tolist(), [0, 0, 0, 0])
        self.assertEqual(ids[0, 4].tolist(), [10, 0, 0, 0])
        self.assertEqual(ids[0, 5].tolist(), [10, 0, 1, 0])
        prediction = torch.cat(
            [torch.ones((1, 4, 128)), torch.full((1, 2, 128), 100.0)], dim=1
        ).requires_grad_()
        target = target_prediction(prediction, noisy)
        loss = torch.nn.functional.mse_loss(target, torch.zeros_like(noisy))
        self.assertEqual(loss.item(), 1.0)
        loss.backward()
        self.assertTrue(torch.all(prediction.grad[:, 4:] == 0))
        self.assertTrue(torch.any(prediction.grad[:, :4] != 0))


if __name__ == "__main__":
    unittest.main()
