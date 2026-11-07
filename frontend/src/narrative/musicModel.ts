// What the Studio shows about generated music (ADR 0067). The server decides everything;
// this only words it.
import type { MusicJob } from "../lib/api";

export const TRACK_LENGTHS = [30, 60, 90, 120, 180] as const;
export const DEFAULT_LENGTH = 60;
export const DESCRIPTION_LIMIT = 500;

const FAILURES: Record<string, string> = {
  gpu_busy: "The GPU was busy, so this stopped. Try again in a moment.",
  gpu_unavailable: "This server has no GPU available for music.",
  generation_timeout: "This took too long and stopped. Try a shorter track.",
  worker_interrupted: "The music worker stopped before finishing. Try again.",
};

export function musicJobActive(job: Pick<MusicJob, "status">): boolean {
  return job.status === "queued" || job.status === "running";
}

export function musicJobText(job: Pick<MusicJob, "status" | "error_code" | "cancel_requested">): string {
  if (job.status === "queued") return "Waiting for the music worker…";
  if (job.status === "running") return job.cancel_requested ? "Stopping…" : "Composing… this usually takes a minute or two.";
  if (job.status === "cancelled") return "Cancelled.";
  if (job.status === "failed") return FAILURES[job.error_code ?? ""] ?? "This couldn't be made. Try again.";
  return "Finished. Listen to it below, then approve it to use it in a story.";
}

export function lengthLabel(seconds: number): string {
  if (seconds < 60) return `${seconds} seconds`;
  const minutes = Math.floor(seconds / 60), rest = seconds % 60;
  const whole = minutes === 1 ? "1 minute" : `${minutes} minutes`;
  return rest ? `${whole} ${rest} seconds` : whole;
}

/** Why this description cannot be sent yet, or null. */
export function descriptionProblem(description: string): string | null {
  const clean = description.trim();
  if (!clean) return "Describe the mood, instruments and pace.";
  if (clean.length > DESCRIPTION_LIMIT) return `Keep it under ${DESCRIPTION_LIMIT} characters.`;
  return null;
}
