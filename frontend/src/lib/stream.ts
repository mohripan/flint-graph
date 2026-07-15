import { ApiError } from "./api";
import type { QueryRunEvent } from "./types";

// Native EventSource cannot send the required X-Tenant-ID header, so we consume
// the text/event-stream response over fetch() and parse SSE frames ourselves.

export interface StreamHandlers {
  onEvent: (event: QueryRunEvent) => void;
  signal?: AbortSignal;
}

function parseFrame(frame: string): QueryRunEvent | null {
  // A frame is one or more lines; we only need the `data:` line, which holds the
  // full serialized QueryRunEvent JSON.
  const dataLines = frame
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).replace(/^ /, ""));
  if (dataLines.length === 0) return null;
  try {
    return JSON.parse(dataLines.join("\n")) as QueryRunEvent;
  } catch {
    return null;
  }
}

export async function streamQueryRun(
  tenantId: string,
  queryRunId: string,
  { onEvent, signal }: StreamHandlers,
): Promise<void> {
  const res = await fetch(`/v1/query-runs/${queryRunId}/events/stream`, {
    headers: { "X-Tenant-ID": tenantId, Accept: "text/event-stream" },
    signal,
  });
  if (!res.ok || !res.body) {
    let problem;
    try {
      problem = await res.json();
    } catch {
      /* ignore */
    }
    throw new ApiError(
      problem?.detail ?? `Stream failed (${res.status})`,
      res.status,
      problem,
    );
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const event = parseFrame(frame);
      if (event) onEvent(event);
    }
  }

  // Flush any trailing frame that lacked a terminating blank line.
  const tail = parseFrame(buffer);
  if (tail) onEvent(tail);
}
