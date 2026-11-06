import type { ImageJob } from "../lib/api";

const terminal = new Set(["completed", "failed", "cancelled"]);
/** A slow list response must not undo a start event, progress or a terminal result. */
export function mergeImageJobs(current: ImageJob[], incoming: ImageJob[]): ImageJob[] {
  const merged = new Map(current.map(job => [job.id, job]));
  for (const job of incoming) {
    const previous = merged.get(job.id);
    if (previous && (terminal.has(previous.status) && !terminal.has(job.status)
      || previous.status === "running" && job.status === "queued")) continue;
    merged.set(job.id, previous ? { ...job, progress: Math.max(previous.progress, job.progress),
      cancel_requested: previous.cancel_requested || job.cancel_requested } : job);
  }
  return [...merged.values()].sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id));
}
