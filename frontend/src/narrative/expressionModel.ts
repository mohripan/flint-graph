// Face boxes and expression choices for repainting a sprite's face (ADR 0041).
// Mirrors the server's rules; the server validates every request again.

export type Box = [number, number, number, number];
export const EXPRESSION_PRESETS = ["happy", "laughing", "sad", "crying", "angry", "surprised",
  "embarrassed", "worried", "smug", "thinking", "sleepy", "determined"];
export const MAX_EXPRESSIONS = 4;
export const MIN_FACE = 16;
const NAME = /^[a-z0-9][a-z0-9 '-]{0,39}$/;

/** Keep a box at least MIN_FACE wide, no larger than the image, and inside it. */
export function clampBox([left, top, right, bottom]: Box, width: number, height: number): Box {
  const side = (value: number, limit: number) => Math.round(Math.min(Math.max(value, MIN_FACE), limit));
  const w = side(right - left, width), h = side(bottom - top, height);
  const x = Math.round(Math.min(Math.max(left, 0), width - w));
  const y = Math.round(Math.min(Math.max(top, 0), height - h));
  return [x, y, x + w, y + h];
}

/**
 * A first guess at the face from the image's alpha: the head sits at the top of the
 * figure, about 11% of its height, centred over the top band. Opaque images (no
 * transparency) get a portrait-style guess. The creator adjusts it either way.
 */
export function faceBoxFromAlpha(alpha: ArrayLike<number>, width: number, height: number): Box {
  let top = -1, bottom = -1, transparent = false;
  for (let row = 0; row < height; row += 1) {
    let filled = false;
    for (let column = 0; column < width; column += 1) {
      const value = alpha[row * width + column];
      if (value > 128) filled = true;
      else transparent = true;
    }
    if (filled) { if (top < 0) top = row; bottom = row; }
  }
  if (!transparent || top < 0) {
    const face = Math.round(Math.min(width, height) * 0.3);
    return clampBox([width / 2 - face / 2, height * 0.2 - face / 2, width / 2 + face / 2, height * 0.2 + face / 2], width, height);
  }
  const figure = bottom - top + 1;
  let sum = 0, count = 0;
  for (let row = top; row < Math.min(height, top + Math.max(1, Math.round(figure * 0.12))); row += 1) {
    for (let column = 0; column < width; column += 1) {
      if (alpha[row * width + column] > 128) { sum += column; count += 1; }
    }
  }
  const cx = count ? sum / count : width / 2;
  const face = Math.max(MIN_FACE, Math.round(figure * 0.11));
  const cy = top + figure * 0.075;
  return clampBox([cx - face / 2, cy - face / 2, cx + face / 2, cy + face / 2], width, height);
}

export function moveBox(box: Box, dx: number, dy: number, width: number, height: number): Box {
  return clampBox([box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy], width, height);
}

/** Grow or shrink from the top-left corner, keeping the box square-ish. */
export function resizeBox(box: Box, dx: number, dy: number, width: number, height: number): Box {
  const side = Math.max(box[2] - box[0] + dx, box[3] - box[1] + dy);
  return clampBox([box[0], box[1], box[0] + side, box[1] + side], width, height);
}

/**
 * A square 1.6 times the face box, kept inside the image, for previewing a result's
 * face: the image's width and offsets as percentages of that square.
 */
export function faceView(box: Box, width: number, height: number): { width: number; left: number; top: number } {
  const side = Math.min(Math.max(box[2] - box[0], box[3] - box[1]) * 1.6, width, height);
  const left = Math.min(Math.max((box[0] + box[2]) / 2 - side / 2, 0), width - side);
  const top = Math.min(Math.max((box[1] + box[3]) / 2 - side / 2, 0), height - side);
  return { width: (width / side) * 100, left: -(left / side) * 100, top: -(top / side) * 100 };
}

export function normalizeExpression(name: string): string {
  return name.replace(/\s+/g, " ").trim().toLowerCase();
}
export function validExpression(name: string): boolean {
  return NAME.test(normalizeExpression(name));
}
/** The sprite key the server gives an expression (same rule as `expression_id`). */
export function expressionKey(name: string): string {
  const key = normalizeExpression(name).replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60);
  return /^[a-z]/.test(key) ? key : `e_${key}`.slice(0, 64);
}
