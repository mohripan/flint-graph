"""Closed body guide schema and the versioned COCO-18 rasterizer."""

LIMBS = [
    (1, 2),
    (1, 5),
    (2, 3),
    (3, 4),
    (5, 6),
    (6, 7),
    (1, 8),
    (8, 9),
    (9, 10),
    (1, 11),
    (11, 12),
    (12, 13),
    (1, 0),
    (0, 14),
    (14, 16),
    (0, 15),
    (15, 17),
]
COLORS = [
    (255, 0, 0),
    (255, 85, 0),
    (255, 170, 0),
    (255, 255, 0),
    (170, 255, 0),
    (85, 255, 0),
    (0, 255, 0),
    (0, 255, 85),
    (0, 255, 170),
    (0, 255, 255),
    (0, 170, 255),
    (0, 85, 255),
    (0, 0, 255),
    (85, 0, 255),
    (170, 0, 255),
    (255, 0, 255),
    (255, 0, 170),
    (255, 0, 85),
]


def validate_guide(guide):
    if type(guide) is not dict or set(guide) != {"id", "label", "width", "height", "points"}:
        raise ValueError("invalid_guide")
    if type(guide["width"]) is not int or type(guide["height"]) is not int:
        raise ValueError("invalid_guide")
    if guide["id"] != "seated-front-v1" or (guide["width"], guide["height"]) != (768, 1152):
        raise ValueError("invalid_guide")
    if type(guide["label"]) is not str or not 1 <= len(guide["label"]) <= 80:
        raise ValueError("invalid_guide")
    points = guide["points"]
    if type(points) is not list or len(points) != 18:
        raise ValueError("invalid_guide")
    for point in points:
        if (
            type(point) is not list
            or len(point) != 2
            or any(type(v) is not int for v in point)
            or not 0 <= point[0] < 768
            or not 0 <= point[1] < 1152
        ):
            raise ValueError("invalid_guide")


def render_guide(guide):
    validate_guide(guide)
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (768, 1152), "black")
    draw = ImageDraw.Draw(image)
    points = guide["points"]
    for i, (a, b) in enumerate(LIMBS):
        draw.line([tuple(points[a]), tuple(points[b])], fill=COLORS[i], width=10)
    for i, (x, y) in enumerate(points):
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=COLORS[i])
    return image
