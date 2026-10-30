import type { CharacterFraming, CharacterType, ImageJob } from "../lib/api";

// Mirrors the server's fixed choices (flint_graph.narrative.imagegen).
export const CHARACTER_TYPES: Array<[CharacterType, string]> = [
  ["girl", "Girl"], ["boy", "Boy"], ["woman", "Woman"], ["man", "Man"], ["other", "Other"],
];
export const FRAMINGS: Array<[CharacterFraming, string]> = [["portrait", "Portrait"], ["full_body", "Full body"]];
export const MAX_APPEARANCE = 600;
export const PORTRAITS_PER_JOB = 4;

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
  cancelled: "Cancelled.",
};

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
  if (job.status === "completed") return `${job.assets.length} portrait${job.assets.length === 1 ? "" : "s"} ready`;
  if (job.status === "cancelled") return "Cancelled.";
  return jobError(job.error_code);
}

// Normalize like the server so an unchanged description is not saved again.
export function cleanAppearance(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}
