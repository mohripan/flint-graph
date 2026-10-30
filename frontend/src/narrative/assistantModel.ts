import type { AssistantTurn, ProposalStatus, StoryDraft, StoryOperation, TurnWrite } from "./types";

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
export function proposalChanges(story: Pick<StoryDraft, "nodes" | "characters" | "variables"> | null,
  operations: StoryOperation[]): ProposalChange[] {
  if (!story) return [];
  return operations.map((operation): ProposalChange => {
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
