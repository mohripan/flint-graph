// What the Assistant shows for its generation actions (ADR 0061). The server decides and
// starts them; this only reads their state and works out what a click would do.
import type { ImageJob, NarrativeImage, VoiceJob } from "../lib/api";
import type { AssistantThread, StoryDraft } from "./types";

export type ActionState = "offered" | "pending" | "started" | "blocked" | "finished" | "skipped" | "declined";
/** What a generation card promises before anything runs (ADR 0068). */
export interface ActionQuote {
  kind: string; title: string; facts: Array<{ icon: string; text: string }>;
  parts: Array<{ item: string; quantity: number }>; button: string; opens: string | null;
}
export interface ActionStatus {
  index: number; op: string; label: string; status: ActionState; needs_accept: boolean;
  error_code: string | null; detail: string | null;
  image_job: ImageJob | null; voice_job: VoiceJob | null;
  child_thread?: AssistantThread | null; quote?: ActionQuote | null;
}
export type ActionTone = "muted" | "good" | "bad";

const ACTIVE = new Set(["queued", "running"]);
const FAILURES: Record<string, string> = {
  gpu_busy: "The GPU was busy, so this stopped. Ask again in a moment.",
  host_memory_busy: "The computer ran out of memory, so this stopped. Ask again in a moment.",
  generation_timeout: "This took too long and stopped. Ask again.",
  cutout_failed: "The background couldn't be removed from these pictures. Ask again.",
  voice_generation_unavailable: "The voice worker isn't running.",
  reference_deleted: "The voice reference was deleted. Choose another one in Characters.",
};

export function actionJob(action: ActionStatus): ImageJob | VoiceJob | null {
  return action.image_job ?? action.voice_job;
}
export function actionWatching(action: ActionStatus): boolean {
  if (action.status === "pending") return true;
  const job = actionJob(action);
  return action.status === "started" && (!job || ACTIVE.has(job.status));
}

const STATE_RANK: Record<ActionState, number> = { offered: 0, pending: 1, blocked: 1, declined: 1, started: 2, finished: 3, skipped: 3 };
const JOB_RANK: Record<string, number> = { queued: 0, running: 1, completed: 2, failed: 2, cancelled: 2 };
/** Responses can arrive out of order; a slow one must not undo a start, progress or a finish. */
export function mergeAction(known: ActionStatus | undefined, incoming: ActionStatus): ActionStatus {
  if (!known) return incoming;
  if (STATE_RANK[incoming.status] < STATE_RANK[known.status]) return known;
  const before = actionJob(known), after = actionJob(incoming);
  if (before && !after) return known;
  if (before && after) {
    if (JOB_RANK[after.status] < JOB_RANK[before.status]) return known;
    if (after.progress < before.progress) return { ...incoming, ...jobWith(incoming, before.progress) };
  }
  return incoming;
}
function jobWith(action: ActionStatus, progress: number): Partial<ActionStatus> {
  return action.image_job ? { image_job: { ...action.image_job, progress } }
    : { voice_job: { ...action.voice_job!, progress } };
}

export function actionState(action: ActionStatus): { text: string; tone: ActionTone } {
  const job = actionJob(action);
  if (action.status === "blocked") return { text: action.detail ?? "This couldn't start.", tone: "bad" };
  if (action.status === "declined") return { text: "Cancelled. Nothing was generated.", tone: "muted" };
  if (action.status === "pending") return { text: "Waiting for a free slot…", tone: "muted" };
  if (action.status === "skipped") return { text: "Not generated: the proposal was rejected.", tone: "muted" };
  if (action.status === "offered") {
    return { text: action.needs_accept ? "Accept the proposal before generating this." : "", tone: "muted" };
  }
  if (action.child_thread) {
    return action.status === "finished" ? { text: "It has replied. Open it to review.", tone: "good" }
      : { text: "Working on it…", tone: "muted" };
  }
  if (!job) return { text: "Starting…", tone: "muted" };
  if (job.status === "queued") return { text: "Queued…", tone: "muted" };
  if (job.status === "running") return { text: `Generating ${job.progress} of ${job.count}…`, tone: "muted" };
  if (job.status === "cancelled") return { text: "Stopped.", tone: "muted" };
  if (job.status === "failed") {
    return { text: FAILURES[job.error_code ?? ""] ?? "Generation failed. Ask again, or try it from the editor.", tone: "bad" };
  }
  return { text: `${job.assets.length} to review.`, tone: "good" };
}
/** A card asks before anything runs; a cancelled one stays folded unless asked to show again. */
export function actionShowsCard(action: ActionStatus, reopened: boolean): boolean {
  if (!action.quote) return false;
  return action.status === "offered" || action.status === "blocked" || (action.status === "declined" && reopened);
}
export function cardLabel(action: Pick<ActionStatus, "status">, quote: Pick<ActionQuote, "button">): string {
  return action.status === "blocked" ? "Try again" : quote.button;
}
export const quoteParts = (quote: Pick<ActionQuote, "parts">): Array<[string, number]> =>
  quote.parts.map(({ item, quantity }) => [item, quantity]);

const slug = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
const spriteHashes = (story: StoryDraft, character: string) => Object.values(story.characters[character]?.sprites ?? {})
  .map(key => story.assets[key]?.sha256);

export interface ImageUse {
  kind: "sprite"; character: string;
  /** The expression to fill; null leaves the name to the asset, as the Characters tab does. */
  expression: string | null; label: string; done: boolean;
}
/** What "use this" means for a picture, or null when it can only be approved. */
export function imageUse(job: Pick<ImageJob, "purpose" | "transparent" | "character_id">, asset: Pick<NarrativeImage, "sha256" | "provenance">,
  story: StoryDraft | null): ImageUse | null {
  const character = job.character_id;
  if (!story || !character || !story.characters[character]) return null;
  const done = spriteHashes(story, character).includes(asset.sha256);
  if (job.purpose === "character_expression") {
    const name = String(asset.provenance.expression ?? "").toLowerCase();
    return name ? { kind: "sprite", character, expression: slug(name), label: `Use as ${name}`, done } : null;
  }
  if (job.purpose !== "character_portrait" || !job.transparent) return null;
  const sprites = story.characters[character].sprites ?? {};
  return { kind: "sprite", character, expression: "neutral" in sprites ? null : "neutral", label: "Use on stage", done };
}
export interface ClipUse { node: string; label: string; done: boolean }
export function clipUse(asset: Pick<NarrativeImage, "sha256" | "provenance">, story: StoryDraft | null): ClipUse | null {
  const node = typeof asset.provenance.node_id === "string" ? asset.provenance.node_id : null;
  const line = node ? story?.nodes[node] : undefined;
  if (!node || line?.type !== "line" || !story) return null;
  const bound = line.voice?.audio ? story.assets[line.voice.audio]?.sha256 : undefined;
  return { node, label: "Use on the line", done: bound === asset.sha256 };
}
