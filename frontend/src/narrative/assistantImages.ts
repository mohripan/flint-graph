// Pictures attached to a message: pasted, dropped or chosen (ADR 0076).

export const MAX_SIDE = 1600;
export const SMALLER_SIDE = 1024;
export const MAX_BYTES = 8 * 1024 * 1024;

/** Fits a picture inside a square, keeping its shape and never enlarging it. */
export function scaledSize(width: number, height: number, side: number): { width: number; height: number } {
  const longest = Math.max(width, height);
  if (longest <= side) return { width, height };
  const scale = side / longest;
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

const isImage = (file: { type: string }) => file.type.startsWith("image/");

/** The pictures on a clipboard or in a drop. Text being pasted is left alone. */
export function imagesIn(data: { files: ArrayLike<File> | null } | null | undefined): File[] {
  return Array.from(data?.files ?? []).filter(isImage);
}

export function imageCount(attached: ReadonlyArray<{ kind: string }>): number {
  return attached.filter(item => item.kind === "image").length;
}

/** How many of ``wanted`` pictures fit, and what to say about the rest. */
export function roomFor(wanted: number, already: number, limit: number): { take: number; note: string | null } {
  const room = Math.max(0, limit - already);
  const take = Math.min(wanted, room);
  return { take, note: take < wanted ? `You can attach up to ${limit} pictures to a message.` : null };
}

async function encode(bitmap: ImageBitmap, side: number): Promise<Blob> {
  const size = scaledSize(bitmap.width, bitmap.height, side);
  const canvas = document.createElement("canvas");
  canvas.width = size.width; canvas.height = size.height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("This browser can't read pictures.");
  context.drawImage(bitmap, 0, 0, size.width, size.height);
  return new Promise((resolve, reject) => canvas.toBlob(
    blob => { if (blob) resolve(blob); else reject(new Error("That picture could not be read.")); }, "image/png"));
}

/** Any picture the browser can open, as a PNG small enough to send. Redrawing also drops its metadata. */
export async function toScreenshotPng(file: Blob): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  try {
    const png = await encode(bitmap, MAX_SIDE);
    return png.size <= MAX_BYTES ? png : await encode(bitmap, SMALLER_SIDE);
  } finally { bitmap.close(); }
}
