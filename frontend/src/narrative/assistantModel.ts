import type { AssistantAction, AssistantTurn, ProposalStatus, StoryDraft, StoryOperation, TurnWrite } from "./types";

export interface TurnIntent extends TurnWrite {}
// A lost acknowledgement resends the same key; any change to the message is a new turn.
export function prepareTurn(previous: TurnIntent | null, request: string, baseRevisionId: string,
  focus: string | null, key = () => crypto.randomUUID()): TurnIntent {
  return previous && previous.request === request && previous.base_revision_id === baseRevisionId
    && previous.focus_node === focus ? previous
    : { request, base_revision_id: baseRevisionId, focus_node: focus, idempotency_key: key() };
}
export function sendBlocker(state: { canWrite: boolean; dirty: boolean; saving: boolean; sending: boolean;
  active: boolean; text: string }): string | null {
  if (!state.canWrite) return "Viewers can read conversations but cannot ask for changes.";
  if (state.dirty) return "Save your changes first. The assistant works from saved revisions.";
  if (state.saving) return "Saving your draft…";
  if (state.active || state.sending) return "Wait for the current reply to finish.";
  if (!state.text.trim()) return "Describe what you want to write or change.";
  if (state.text.length > 8000) return "Keep a message under 8,000 characters.";
  return null;
}
const terminal = new Set(["completed", "failed", "cancelled"]);
const decided = new Set(["accepted", "rejected"]);
export function activeTurn(turns: Array<Pick<AssistantTurn, "status">>): boolean {
  return turns.some(turn => !terminal.has(turn.status));
}
function newerTurn(known: AssistantTurn | undefined, incoming: AssistantTurn): AssistantTurn {
  if (!known) return incoming;
  if (terminal.has(known.status) && !terminal.has(incoming.status)) return known;
  if (known.proposal && decided.has(known.proposal.status)
    && (!incoming.proposal || !decided.has(incoming.proposal.status))) return known;
  return Date.parse(incoming.updated_at) < Date.parse(known.updated_at) && !incoming.proposal ? known : incoming;
}
export function mergeTurns(current: AssistantTurn[], incoming: AssistantTurn[]): AssistantTurn[] {
  const merged = new Map(current.map(turn => [turn.id, turn]));
  for (const turn of incoming) merged.set(turn.id, newerTurn(merged.get(turn.id), turn));
  return [...merged.values()].sort((a, b) => a.sequence - b.sequence);
}
export interface ProposalChange {
  kind: "added" | "changed" | "removed"; target: string; label: string; before?: string; after?: string;
}
function text(value: unknown): string | undefined {
  return value && typeof value === "object" && "text" in value && typeof value.text === "string" ? value.text : undefined;
}
export function isAction(operation: StoryOperation): operation is AssistantAction {
  return operation.op === "generate_character_images" || operation.op === "generate_backgrounds";
}
/** One line per suggested image job, and whether it can start against the saved story. */
export function proposalActions(story: Pick<StoryDraft, "characters"> | null, operations: StoryOperation[]):
  Array<{ action: AssistantAction; label: string; ready: boolean }> {
  return operations.filter(isAction).map(action => action.op === "generate_backgrounds"
    ? { action, label: `Generate backgrounds: ${action.description}`, ready: true }
    : { action, ready: Boolean(story?.characters[action.character]),
        label: `Generate ${action.transparent ? "transparent sprites" : action.framing === "full_body" ? "full-body portraits" : "portraits"}`
          + ` for ${story?.characters[action.character]?.name ?? action.character}: ${action.appearance}` });
}
export function proposalChanges(story: Pick<StoryDraft, "nodes" | "characters" | "variables"> | null,
  operations: StoryOperation[]): ProposalChange[] {
  if (!story) return [];
  return operations.filter(operation => !isAction(operation)).map((operation): ProposalChange => {
    switch (operation.op) {
      case "upsert_node": {
        const before = story.nodes[operation.id];
        return { kind: before ? "changed" : "added", target: `nodes.${operation.id}`, label: `Scene ${operation.id}`,
          before: text(before), after: text(operation.node) };
      }
      case "delete_node":
        return { kind: "removed", target: `nodes.${operation.id}`, label: `Scene ${operation.id}`,
          before: text(story.nodes[operation.id]) };
      case "upsert_character":
        return { kind: story.characters[operation.id] ? "changed" : "added", target: `characters.${operation.id}`,
          label: `Character ${operation.name}` };
      case "delete_character":
        return { kind: "removed", target: `characters.${operation.id}`,
          label: `Character ${story.characters[operation.id]?.name ?? operation.id}` };
      case "upsert_variable":
        return { kind: story.variables[operation.id] ? "changed" : "added", target: `variables.${operation.id}`,
          label: `State ${operation.id}` };
      case "delete_variable":
        return { kind: "removed", target: `variables.${operation.id}`, label: `State ${operation.id}` };
      case "set_entry":
        return { kind: "changed", target: "entry", label: `Start scene → ${operation.id}` };
      case "set_title":
        return { kind: "changed", target: "title", label: `Title → ${operation.title}` };
      case "set_theme":
        return { kind: operation.theme ? "changed" : "removed", target: "theme", label: "Look (theme)" };
      case "add_asset":
        return { kind: "added", target: `assets.${operation.id}`, label: `${operation.asset.kind === "font" ? "Font" : "Image"} ${operation.id} from the library` };
      default: {
        // A newer server may send an operation this Studio doesn't know yet.
        const op = (operation as { op: string }).op;
        return { kind: "changed", target: op, label: op };
      }
    }
  });
}
export function turnStatus(turn: Pick<AssistantTurn, "status" | "cancel_requested">): string {
  if (!terminal.has(turn.status) && turn.cancel_requested) return "Stopping…";
  return { queued: "Waiting for the assistant…", running: "Writing a reply…", completed: "",
    failed: "The assistant couldn't reply.", cancelled: "Stopped." }[turn.status];
}
export function assistantError(code: string | null): string {
  const messages: Record<string, string> = {
    provider_unavailable: "The local model isn't reachable. Check that Ollama is running, then try again.",
    provider_timeout: "The model took too long. Try again, or ask for a smaller change.",
    provider_refused: "The model declined this request. Try rephrasing it.",
    invalid_response: "The model's answer couldn't be read. Try again.",
    assistant_unavailable: "The assistant isn't configured on this server. Manual writing still works.",
    worker_interrupted: "The assistant stopped unexpectedly. Try again.",
  };
  return (code && messages[code]) || "The assistant couldn't finish this reply. Try again.";
}
export function proposalStatus(status: ProposalStatus): string {
  return { ready: "Ready to review", invalid: "Can't be used", accepted: "Accepted", rejected: "Rejected" }[status];
}

// Live turn progress (#171): the worker persists ordered events; the page folds them.
export type TurnEventKind = "step" | "thinking" | "text" | "status";
export interface AssistantTurnEvent {
  turn_id: string; sequence: number; attempt: number; kind: TurnEventKind;
  payload: Record<string, unknown>; created_at: string;
}
interface StepRecord { key: string; name: string; state: string; payload: Record<string, unknown> }
export interface TurnActivity {
  cursor: number; attempt: number; call: number; steps: StepRecord[];
  calls: Record<number, { thinking: string; text: string }>;
  status: string | null; errorCode: string | null; startedAt: string | null; endedAt: string | null;
}
export function emptyActivity(): TurnActivity {
  return { cursor: 0, attempt: 0, call: 0, steps: [], calls: {}, status: null, errorCode: null, startedAt: null, endedAt: null };
}
const number = (value: unknown): number => typeof value === "number" && Number.isFinite(value) ? value : 0;
const string = (value: unknown): string => typeof value === "string" ? value : "";
function stepKey(payload: Record<string, unknown>): string {
  const name = string(payload.name);
  return name === "truncated" ? `${name}:${string(payload.kind)}:${number(payload.call)}`
    : name === "start" || name === "context" ? name : `${name}:${number(payload.call)}`;
}
// Idempotent by sequence, so a resumed stream may replay events safely. A new
// attempt (a retried or recovered execution) replaces the abandoned attempt's view.
export function foldEvents(activity: TurnActivity, events: AssistantTurnEvent[]): TurnActivity {
  let next: TurnActivity | null = null;
  for (const event of events) {
    const current: TurnActivity = next ?? activity;
    if (event.sequence <= current.cursor || event.attempt < current.attempt) continue;
    const state: TurnActivity = next ??= { ...activity, steps: [...activity.steps], calls: { ...activity.calls } };
    state.cursor = event.sequence;
    state.startedAt ??= event.created_at;
    if (event.attempt > state.attempt) Object.assign(state, { attempt: event.attempt, call: 0, steps: [], calls: {} });
    const payload = event.payload ?? {};
    if (event.kind === "status") {
      state.status = string(payload.status) || null; state.errorCode = string(payload.error_code) || null;
      state.endedAt = event.created_at;
    } else if (event.kind === "step") {
      const key = stepKey(payload), index = state.steps.findIndex(item => item.key === key);
      const record = { key, name: string(payload.name), state: string(payload.state), payload };
      if (index < 0) state.steps.push(record);
      else state.steps[index] = { ...record, payload: { ...state.steps[index].payload, ...payload } };
      if (record.name === "model") state.call = Math.max(state.call, number(payload.call));
    } else {
      const call = number(payload.call), known = state.calls[call] ?? { thinking: "", text: "" };
      const field = event.kind === "thinking" ? "thinking" : "text";
      state.calls[call] = { ...known, [field]: known[field] + string(payload.text) };
      state.call = Math.max(state.call, call);
    }
  }
  return next ?? activity;
}
export function streamedReply(activity: TurnActivity): string {
  const calls = Object.keys(activity.calls).map(Number).filter(call => activity.calls[call].text).sort((a, b) => b - a);
  return calls.length ? activity.calls[calls[0]].text : "";
}
export type StepState = "active" | "done" | "failed" | "stopped";
export interface StepView { key: string; label: string; detail?: string; state: StepState }
const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;
const humanCodes = (codes: unknown) => Array.isArray(codes) ? codes.map(code => string(code).replaceAll("_", " ")).join(", ") : "";
export function activitySteps(activity: TurnActivity, active: boolean): StepView[] {
  const modelDone = new Set(activity.steps.filter(item => item.name === "model" && item.state === "done").map(item => number(item.payload.call)));
  const settle = (state: StepState): StepState => state !== "active" || active ? state
    : activity.status === "completed" ? "done" : "stopped";
  const views: StepView[] = [];
  for (const { key, name, state, payload } of activity.steps) {
    const call = number(payload.call);
    if (name === "start") {
      if (activity.attempt > 1) views.push({ key, label: `Reconnected and started again (attempt ${activity.attempt})`, state: "done" });
    } else if (name === "context") {
      const omitted = number(payload.omitted), focus = string(payload.focus), history = number(payload.history);
      views.push({ key, label: "Read the story", state: "done", detail: plural(number(payload.scenes), "scene")
        + (omitted ? `, ${omitted} left out to fit` : "") + (focus ? ` · focus ${focus}` : "")
        + (history ? ` · ${plural(history, "earlier message")}` : "") });
    } else if (name === "model") {
      const finished = state === "done" || (!active && activity.status === "completed");
      views.push({ key, state: settle(state === "done" ? "done" : "active"),
        label: call > 1 ? (finished ? "Rewrote the reply" : "Rewriting the reply") : finished ? "Wrote a reply" : "Writing a reply" });
    } else if (name === "drafting") {
      const finished = modelDone.has(call), operations = number(payload.operations);
      views.push({ key, label: finished ? "Drafted changes" : "Drafting changes", state: settle(finished ? "done" : "active"),
        detail: operations ? plural(operations, "edit") : undefined });
    } else if (name === "validating") {
      const problems = number(payload.problems);
      views.push(payload.valid === true ? { key, label: "Checked the changes against the story rules", state: "done" }
        : { key, label: `Found ${plural(problems, "problem")}`, state: "failed", detail: humanCodes(payload.codes) || undefined });
    } else if (name === "repair") {
      views.push({ key, state: "done",
        label: `Fixing ${plural(number(payload.problems), "problem")} (attempt ${call} of ${number(payload.of)})` });
    } else if (name === "truncated") {
      views.push({ key, state: "done", label: string(payload.kind) === "thinking"
        ? "Thinking was too long to keep in full" : "The reply was too long to keep in full" });
    }
  }
  return views;
}
export function workedFor(activity: TurnActivity): string {
  if (!activity.startedAt || !activity.endedAt) return "";
  const seconds = Math.max(0, Math.round((Date.parse(activity.endedAt) - Date.parse(activity.startedAt)) / 1000));
  return seconds < 60 ? `Worked for ${seconds} s` : `Worked for ${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}
export function threadTitle(request: string): string {
  const line = request.replace(/\s+/g, " ").trim();
  if (!line) return "Story chat";
  return line.length <= 60 ? line : `${line.slice(0, 59).trimEnd()}…`;
}
// The server rejects a reused creation key with a different title, so a changed
// first message (and title) gets a new key; an identical resend replays safely.
export interface ThreadIntent { title: string; key: string }
export function prepareThread(previous: ThreadIntent | null, title: string,
  key = () => crypto.randomUUID()): ThreadIntent {
  return previous?.title === title ? previous : { title, key: key() };
}
