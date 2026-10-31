import type { CharacterFraming, CharacterType, ImageJob } from "../lib/api";

// Mirrors the server's fixed choices (flint_graph.narrative.imagegen).
export const CHARACTER_TYPES: Array<[CharacterType, string]> = [
  ["girl", "Girl"], ["boy", "Boy"], ["woman", "Woman"], ["man", "Man"], ["other", "Other"],
];
export const FRAMINGS: Array<[CharacterFraming, string]> = [["portrait", "Portrait"], ["full_body", "Full body"]];
export const MAX_APPEARANCE = 600;
export const PORTRAITS_PER_JOB = 4;
// High resolution renders, upscales by this much and repaints the detail (HIRES_SCALE).
export const HIRES_SCALE = 2;

const ERRORS: Record<string, string> = {
  gpu_busy: "The GPU is busy with another model, such as the story assistant. Try again in a minute.",
  out_of_memory: "The GPU ran out of memory. Close other GPU programs and try again.",
  gpu_unavailable: "No supported GPU was found by the image worker.",
  generation_timeout: "Generation took too long and was stopped.",
  invalid_output: "The generator returned an image that failed verification.",
  storage_unavailable: "The images could not be stored. Try again.",
  image_generation_unavailable: "Image generation is not configured on this server.",
  worker_interrupted: "The image worker stopped before finishing. Try again.",
  model_invalid: "The image model failed its integrity check.",
  cutout_failed: "The character could not be separated from the background. Try again or adjust the description.",
  cutout_unavailable: "Transparent sprites need the cutout model; this image worker has none configured.",
  cancelled: "Cancelled.",
};

// Transparent stage sprites are cut out of full-body renders only (the server checks too).
export function canCutOut(framing: CharacterFraming): boolean {
  return framing === "full_body";
}

// Sprites can be drawn far larger than their render on stage; portraits stay small.
export function defaultHires(transparent: boolean): boolean {
  return transparent;
}

export function hiresLabel(): string {
  return `High resolution: ${HIRES_SCALE}× larger with redrawn detail, so characters stay sharp when the stage shows them big.`
    + " Takes longer and uses more of the story's asset budget.";
}

// The size of what the job makes: the render, how it was upscaled, and the sprite crops.
export function jobSize(job: Pick<ImageJob, "width" | "height" | "output_width" | "output_height" | "hires" | "transparent">
  & { assets: Array<{ width: number | null; height: number | null }> }): string {
  let size = `${job.output_width}×${job.output_height}`;
  if (job.hires) {
    size += ` (rendered at ${job.width}×${job.height}, upscaled ${job.hires.scale}× and refined at strength ${job.hires.strength})`;
  }
  const crops = [...new Set(job.assets.map(asset => `${asset.width}×${asset.height}`))];
  return job.transparent && crops.length ? `${size}; sprites cropped to ${crops.join(", ")}` : size;
}

export function generateLabel(transparent: boolean): string {
  return `Generate ${PORTRAITS_PER_JOB} ${transparent ? "sprites" : "portraits"}`;
}

export function jobError(code: string | null): string {
  return (code && ERRORS[code]) || "Generation failed. Try again.";
}

export function isActive(job: ImageJob | null | undefined): boolean {
  return job?.status === "queued" || job?.status === "running";
}

// One line the creator can read at a glance while the GPU works.
export function jobStatus(job: ImageJob): string {
  if (job.status === "queued") return job.cancel_requested ? "Cancelling…" : "Waiting for the image worker…";
  if (job.status === "running") {
    if (job.cancel_requested) return "Cancelling…";
    return job.progress === 0 ? "Loading the model…" : `Generated ${job.progress} of ${job.count}…`;
  }
  if (job.status === "completed") {
    const noun = job.transparent ? "sprite" : "portrait";
    return `${job.assets.length} ${noun}${job.assets.length === 1 ? "" : "s"} ready`;
  }
  if (job.status === "cancelled") return "Cancelled.";
  return jobError(job.error_code);
}

// Normalize like the server so an unchanged description is not saved again.
export function cleanAppearance(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}
