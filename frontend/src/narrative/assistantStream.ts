import { ApiError, authHeaders } from "../lib/api";
import type { ProblemDetail } from "../lib/types";
import type { AssistantTurnEvent } from "./assistantModel";

// Live turn progress is persisted by the worker and read back by sequence. Native
// EventSource cannot send the workspace header, so the stream is read over fetch.
function eventsPath(projectId: string, threadId: string, turnId: string): string {
  return `/v1/narrative/projects/${encodeURIComponent(projectId)}/assistant/threads/${encodeURIComponent(threadId)}`
    + `/turns/${encodeURIComponent(turnId)}/events`;
}

async function failure(response: Response): Promise<ApiError> {
  let problem: ProblemDetail | undefined;
  try { problem = await response.json(); } catch { /* non-JSON body */ }
  return new ApiError(problem?.detail ?? problem?.title ?? `${response.status} ${response.statusText}`, response.status, problem);
}

async function headers(tenantId: string, extra: Record<string, string> = {}): Promise<HeadersInit> {
  return { ...(await authHeaders()), "X-Tenant-ID": tenantId, ...extra };
}

export async function listTurnEvents(tenantId: string, projectId: string, threadId: string, turnId: string,
  afterSequence: number, signal?: AbortSignal): Promise<AssistantTurnEvent[]> {
  const query = new URLSearchParams({ after_sequence: String(afterSequence), limit: "500" });
  const response = await fetch(`${eventsPath(projectId, threadId, turnId)}?${query}`, {
    headers: await headers(tenantId), signal, cache: "no-store",
  });
  if (!response.ok) throw await failure(response);
  return await response.json() as AssistantTurnEvent[];
}

// Incremental server-sent-event parser: comments, retry hints and unknown frames are ignored.
export class SseFrames {
  private buffer = "";
  private carriage = false;
  push(text: string): AssistantTurnEvent[] {
    // A CRLF split across chunks must not read as two line breaks.
    let chunk = (this.carriage ? "\r" : "") + text;
    this.carriage = chunk.endsWith("\r");
    if (this.carriage) chunk = chunk.slice(0, -1);
    this.buffer += chunk.replace(/\r\n?/g, "\n");
    const events: AssistantTurnEvent[] = [];
    let end: number;
    while ((end = this.buffer.indexOf("\n\n")) >= 0) {
      const frame = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + 2);
      const data = frame.split("\n").filter(line => line.startsWith("data:")).map(line => line.slice(5).replace(/^ /, ""));
      if (!data.length) continue;
      try {
        const event = JSON.parse(data.join("\n")) as AssistantTurnEvent;
        if (typeof event?.sequence === "number" && typeof event.kind === "string") events.push(event);
      } catch { /* A malformed frame is skipped; the next resume replays by sequence. */ }
    }
    return events;
  }
}

export async function streamTurnEvents(tenantId: string, projectId: string, threadId: string, turnId: string,
  afterSequence: number, { onEvents, signal }: { onEvents: (events: AssistantTurnEvent[]) => void; signal?: AbortSignal }): Promise<void> {
  const query = new URLSearchParams({ after_sequence: String(afterSequence) });
  const response = await fetch(`${eventsPath(projectId, threadId, turnId)}/stream?${query}`, {
    headers: await headers(tenantId, { Accept: "text/event-stream" }), signal, cache: "no-store",
  });
  if (!response.ok || !response.body) throw await failure(response);
  const reader = response.body.getReader(), decoder = new TextDecoder(), frames = new SseFrames();
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      const events = frames.push(decoder.decode(value, { stream: true }));
      if (events.length) onEvents(events);
    }
  } finally { reader.releaseLock(); }
}

function delay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise(resolve => {
    const timer = window.setTimeout(resolve, milliseconds);
    signal.addEventListener("abort", () => { window.clearTimeout(timer); resolve(); }, { once: true });
  });
}

// Reconnects from the last applied sequence until the turn's final event arrives,
// backing off after failures. Client errors (not found, access) end the follow.
export async function followTurnEvents(open: (afterSequence: number) => Promise<void>,
  state: { cursor: () => number; finished: () => boolean }, signal: AbortSignal,
  wait: (milliseconds: number, signal: AbortSignal) => Promise<void> = delay): Promise<void> {
  let failures = 0;
  while (!signal.aborted && !state.finished()) {
    try {
      await open(state.cursor());
      failures = 0;
    } catch (error) {
      if (signal.aborted || (error instanceof Error && error.name === "AbortError")) return;
      if (error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 408 && error.status !== 429) throw error;
      failures += 1;
    }
    if (signal.aborted || state.finished()) return;
    await wait(Math.min(5000, 500 * 2 ** failures), signal);
  }
}
