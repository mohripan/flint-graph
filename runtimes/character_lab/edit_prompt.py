"""Render the fixed pilot's semantic request as an editing instruction."""


def edit_prompt(case, *, background_context=False):
    if case.get("participants"):
        if len(case["participants"]) != 2:
            raise ValueError("pair pilot requires two references")
        return (
            "Show exactly two adult characters together: the character from image 1 on the left "
            "and the character from image 2 on the right. "
            + case["description"]
            + ". Preserve each person's exact face, hair, eyes, complete outfit, colors, trims "
            "and accessories from their own reference. Do not exchange their features or clothes. "
            "Keep the same anime illustration style. Keep both people in view. "
            + (
                "Use image 3 as the scene background and match its lighting. "
                if background_context
                else ""
            )
            + "No additional people."
        )
    prompt = case["prompt"]
    if ", solo, " not in prompt or ", anime coloring" not in prompt:
        raise ValueError("unrecognized pilot prompt")
    description = prompt.partition(", solo, ")[2].partition(", anime coloring")[0]
    return (
        "Show the same adult character from the reference image in a new illustration: "
        + description
        + ". Preserve the exact face, hairstyle, eyes, complete outfit, garment colors, "
        "trims and accessories from the reference. Keep the same anime illustration style. "
        "One character only. The requested pose must be clearly visible."
    )
