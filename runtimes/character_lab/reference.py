"""Keep the entire approved image when CLIP applies its square centre crop."""

from PIL import Image


def reference_image(source):
    flat = Image.new("RGBA", source.size, "white")
    flat.alpha_composite(source.convert("RGBA"))
    rgb = flat.convert("RGB")
    side = max(rgb.size)
    square = Image.new("RGB", (side, side), "white")
    square.paste(rgb, ((side - rgb.width) // 2, (side - rgb.height) // 2))
    return square
