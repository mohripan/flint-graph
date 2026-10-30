import type { ArtifactKind, NarrativeRelease, ReleaseArtifact, ReleaseJob, RevisionSummary } from "./types";

type RevisionLabelRow = Pick<RevisionSummary, "id" | "revision_number" | "conflicted">;
export interface BuildTarget { id: string; label: string }
// Saved snapshots only: the draft base first if history has not loaded it yet.
export function buildTargets(current: RevisionLabelRow | null, rows: RevisionLabelRow[],
  headId: string | null): BuildTarget[] {
  const known = current && !rows.some(row => row.id === current.id) ? [current, ...rows] : rows;
  return known.map(row => ({ id: row.id, label: `Revision ${row.revision_number}${row.id === headId
    ? " · current" : row.conflicted ? " · conflict copy" : ""}` }));
}
export function revisionLabel(revisionId: string, rows: RevisionLabelRow[], current: RevisionLabelRow | null): string {
  const row = current?.id === revisionId ? current : rows.find(item => item.id === revisionId);
  return row ? `Revision ${row.revision_number}` : "Earlier saved revision";
}
export function buildBlocker(state: { canWrite: boolean; dirty: boolean; saving: boolean; busy: boolean;
  targetId: string | null; releases: Array<Pick<NarrativeRelease, "revision_id"> & { job: Pick<ReleaseJob, "status"> }> }): string | null {
  if (!state.canWrite) return "Viewers can download ready releases but cannot start builds.";
  if (state.dirty) return "Save your changes first. Releases are built only from saved revisions.";
  if (state.saving) return "Saving your draft…";
  if (state.busy) return "Requesting a build…";
  if (!state.targetId) return "Choose a saved revision to build.";
  if (state.releases.some(row => row.revision_id === state.targetId && activeRelease(row.job)))
    return "This revision is already being built.";
  return null;
}
// A resent key returns the original attempt, possibly long finished or retried.
export function replayedRelease(release: { job: Pick<ReleaseJob, "status" | "attempt_number"> }, known: boolean): boolean {
  return known || release.job.status !== "queued" || release.job.attempt_number !== 1;
}
export function scopedRelease(release: Pick<NarrativeRelease, "tenant_id" | "project_id">,
  tenantId: string, projectId: string): boolean {
  return release.tenant_id === tenantId && release.project_id === projectId;
}
const artifactOrder: ArtifactKind[] = ["source", "web", "manifest"];
// List/create/retry summaries omit artifacts; only an item GET supplies them.
export function readyArtifacts(release: Pick<NarrativeRelease, "artifacts"> & { job: Pick<ReleaseJob, "status"> }): ReleaseArtifact[] {
  if (release.job.status !== "completed") return [];
  return artifactOrder.flatMap(kind => release.artifacts.find(row => row.kind === kind) ?? []);
}
export function artifactLabel(kind: ArtifactKind): string {
  return { source: "Godot source", web: "Browser build", manifest: "Release details (JSON)" }[kind];
}
export function formatBytes(size: number): string {
  return size < 1024 ? `${size} B` : size < 1048576 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1048576).toFixed(1)} MB`;
}

export interface ReleaseIntent { revision_id: string; idempotency_key: string }
export interface RetryIntent { job_id: string; idempotency_key: string }
// In-memory only, keyed by immutable revision/job ID, and kept by the studio so
// reopening Releases after an ambiguous failure resends the same key.
export interface ReleaseIntents { builds: Map<string, ReleaseIntent>; retries: Map<string, RetryIntent> }
export function releaseIntents(): ReleaseIntents { return { builds: new Map(), retries: new Map() }; }
export function prepareRelease(previous: ReleaseIntent | null, revisionId: string,
  key = () => crypto.randomUUID()): ReleaseIntent {
  return previous?.revision_id === revisionId ? previous : { revision_id: revisionId, idempotency_key: key() };
}
export function prepareReleaseRetry(previous: RetryIntent | null, jobId: string,
  key = () => crypto.randomUUID()): RetryIntent {
  return previous?.job_id === jobId ? previous : { job_id: jobId, idempotency_key: key() };
}
export function mergeReleases(current: NarrativeRelease[], incoming: NarrativeRelease[], older = false): NarrativeRelease[] {
  const known = new Map(current.map(row => [row.id, row]));
  const updates = new Map(incoming.map(row => [row.id, newerRelease(known.get(row.id), row)]));
  const merged = new Map<string, NarrativeRelease>();
  for (const row of older ? [...current, ...incoming] : [...incoming, ...current]) {
    if (!merged.has(row.id)) merged.set(row.id, updates.get(row.id) ?? row);
  }
  return [...merged.values()];
}
export function newerRelease(known: NarrativeRelease | undefined, incoming: NarrativeRelease): NarrativeRelease {
  if (!known) return incoming;
  const before = known.job, after = incoming.job;
  if (before.status === "completed" && after.status !== "completed") return known;
  if ((after.attempt_number ?? 0) < (before.attempt_number ?? 0)) return known;
  if ((after.attempt_number ?? 0) > (before.attempt_number ?? 0)) return incoming;
  if (before.id !== after.id || (!activeRelease(before) && after.status !== before.status)
    || (before.status === "running" && after.status === "queued")
    || (before.cancel_requested && activeRelease(after) && !after.cancel_requested)
    || Date.parse(after.updated_at) < Date.parse(before.updated_at)) return known;
  return !incoming.artifacts?.length && known.artifacts?.length
    ? { ...incoming, artifacts: known.artifacts } : incoming;
}
export function activeRelease(job: Pick<ReleaseJob, "status">): boolean {
  return job.status === "queued" || job.status === "running";
}
export function releaseStatus(job: Pick<ReleaseJob, "status" | "cancel_requested">): string {
  if (activeRelease(job) && job.cancel_requested) return "Cancelling";
  return { queued: "Queued", running: "Building", completed: "Ready", failed: "Failed", cancelled: "Cancelled" }[job.status];
}
export function releaseFailure(code: string | null): string {
  const messages: Record<string, string> = {
    runtime_unavailable: "The build tools for this release are unavailable. Ask an administrator to restore them before retrying.",
    worker_interrupted: "The build was interrupted. You can retry this saved release.",
    engine_failed: "The game could not be exported. Playtest the saved revision, then try again.",
    engine_timeout: "The export took too long. Try the build again.",
    build_timeout: "The build took too long. Try again.",
    artifact_storage: "The game files could not be stored. Try the build again.",
    output_size_limit: "The exported game is larger than the release size limit.",
  };
  return (code && messages[code]) || "The release could not be verified. Ask an administrator to inspect it before retrying.";
}
export function releaseEventLabel(code: string): string {
  const labels: Record<string, string> = {
    "release.queued": "Release requested", "release.dispatched": "Sent to the build worker",
    "release.running": "Build started", "release.execution_replaced": "Build resumed",
    "release.cancel_requested": "Cancellation requested", "release.cancelled": "Build cancelled",
    "release.failed": "Build failed", "release.completed": "Files ready to download",
  };
  return labels[code] ?? "Build status updated";
}
