"""Bounded experimental parameters, validated before model/GPU work."""

import math


def gpu_floor_gib(method, cached):
    """Measured device overhead plus margin; uncached control is a solo baseline."""
    if method == "control":
        return 11 if cached else 11.6
    if method == "klein":
        return 11
    return 10


def img2img_strength(value):
    strength = float(value)
    if not math.isfinite(strength) or not 0.1 <= strength <= 1:
        raise ValueError("img2img strength must be finite and between 0.1 and 1")
    return strength
