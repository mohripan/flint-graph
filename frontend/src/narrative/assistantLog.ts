// A conversation's append-only log (ADR 0060), read as a timeline. The server is the
// source of truth; polling only ever adds events, so repeating a request is harmless.
export interface ThreadEvent {
  thread_id: string; sequence: number; kind: string; payload: Record<string, unknown>;
  actor_user_id: string | null; created_at: string;
}
export type LogTone = "neutral" | "good" | "bad" | "muted";
export interface LogLine { sequence: number; at: string; label: string; detail?: string; tone: LogTone }

const DETAIL_CHARS = 240;
function short(value: unknown): string | undefined {
  if (typeof value !== "string" || !value.trim()) return undefined;
  const line = value.replace(/\s+/g, " ").trim();
  return line.length <= DETAIL_CHARS ? line : `${line.slice(0, DETAIL_CHARS - 1).trimEnd()}…`;
}
const words = (value: unknown) => typeof value === "string" ? value.replaceAll("_", " ") : undefined;

export function mergeLog(current: ThreadEvent[], incoming: ThreadEvent[]): ThreadEvent[] {
  const known = new Set(current.map(event => event.sequence));
  const fresh = incoming.filter(event => !known.has(event.sequence));
  return fresh.length ? [...current, ...fresh].sort((a, b) => a.sequence - b.sequence) : current;
}

function describe(kind: string, data: Record<string, unknown>): Pick<LogLine, "label" | "detail" | "tone"> {
  switch (kind) {
    case "thread.created": return { label: "Conversation started", detail: short(data.title), tone: "neutral" };
    case "turn.requested": {
      const attached = Array.isArray(data.attached) && data.attached.length ? ` · with ${data.attached.join(", ")}` : "";
      return { label: "Request", detail: short(`${String(data.request ?? "")}${attached}`), tone: "neutral" };
    }
    case "turn.completed": return { label: "Reply", detail: short(data.reply), tone: "neutral" };
    case "turn.failed": return { label: "Reply failed", detail: words(data.error_code), tone: "bad" };
    case "turn.cancelled": return { label: "Reply stopped", tone: "muted" };
    case "proposal.created": return data.status === "invalid"
      ? { label: "Proposal couldn't be used", detail: short(data.summary), tone: "bad" }
      : { label: "Changes proposed", detail: short(data.summary), tone: "neutral" };
    case "proposal.accepted": return data.conflicted === true
      ? { label: "Accepted as a conflict copy", detail: short(data.summary), tone: "bad" }
      : { label: "Proposal accepted", detail: short(data.summary), tone: "good" };
    case "proposal.rejected": return { label: "Proposal rejected", detail: short(data.summary), tone: "muted" };
    case "action.started": return { label: "Generating", detail: short(data.label), tone: "neutral" };
    case "action.blocked": return { label: "Couldn't start", detail: short(data.detail ?? data.label), tone: "bad" };
    case "job.finished": return data.status === "completed"
      ? { label: "Generation finished", detail: `${String(data.candidates ?? 0)} to review`, tone: "good" }
      : data.status === "cancelled" ? { label: "Generation stopped", tone: "muted" }
      : { label: "Generation failed", detail: words(data.error_code), tone: "bad" };
    case "asset.approved": return { label: "Approved", detail: short(data.name), tone: "good" };
    case "child.started": return { label: "Child session started", detail: short(data.title), tone: "neutral" };
    case "child.updated": return {
      label: `Child session ${typeof data.what === "string" ? data.what : "updated"}`,
      detail: short(data.title), tone: data.what === "failed" ? "bad" : data.what === "accepted" ? "good" : "neutral",
    };
    default: return { label: kind.replaceAll(/[._]/g, " "), tone: "neutral" };
  }
}

export function logLines(events: ThreadEvent[]): LogLine[] {
  return events.map(event => ({
    sequence: event.sequence, at: event.created_at, ...describe(event.kind, event.payload ?? {}),
  }));
}
