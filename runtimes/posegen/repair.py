"""Source-native local compositing; no model loading and no outside changes."""

from PIL import Image


def source_canvas(original, descriptor):
    if original.size != (descriptor["width"], descriptor["height"]) or original.mode not in (
        "RGB",
        "RGBA",
    ):
        raise ValueError("reference_unavailable")
    canvas = Image.new("RGBA", (768, 1152), (0, 0, 0, 0))
    crop = descriptor["source_box"]
    canvas.paste(original, (crop[0], crop[1]) if crop else (0, 0))
    return Image.alpha_composite(Image.new("RGBA", canvas.size, "white"), canvas).convert("RGB")


def composite(original, generated, descriptor):
    crop = descriptor["source_box"]
    patch = generated.crop(crop) if crop else generated
    if patch.size != original.size:
        raise ValueError("reference_unavailable")
    left, top, right, bottom = descriptor["box"]
    feather = descriptor["feather"]
    mask = Image.new("L", original.size, 0)
    pixels = mask.load()
    for y in range(top, bottom):
        for x in range(left, right):
            distance = min(x - left, right - 1 - x, y - top, bottom - 1 - y, feather)
            pixels[x, y] = max(0, distance * 255 // feather)
    return Image.composite(patch.convert(original.mode), original, mask)
