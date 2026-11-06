import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { logLines, mergeLog } from "./assistantLog";
import type { ThreadEvent } from "./assistantLog";

const PAGE = 200, POLL_MS = 5000;

function clock(value: string): string {
  const date = new Date(value);
  return date.toDateString() === new Date().toDateString()
    ? date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

// What happened in this conversation, from its append-only log (ADR 0060). The parent
// mounts one per thread, so a thread's cursor and events never leak into another.
export function ThreadHistory({ tenantId, projectId, threadId, version, onClose }: {
  tenantId: string; projectId: string; threadId: string; version: string; onClose: () => void;
}) {
  const [events, setEvents] = useState<ThreadEvent[]>([]);
  const [failed, setFailed] = useState(false);
  const cursor = useRef(0), list = useRef<HTMLOListElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        for (;;) {
          const page = await api.listAssistantThreadEvents(tenantId, projectId, threadId, cursor.current, controller.signal);
          if (controller.signal.aborted) return;
          setFailed(false);
          if (page.length) {
            cursor.current = page[page.length - 1].sequence;
            setEvents(current => mergeLog(current, page));
          }
          if (page.length < PAGE) return;
        }
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      }
    }
    void load();
    const timer = window.setInterval(() => { if (document.visibilityState !== "hidden") void load(); }, POLL_MS);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [tenantId, projectId, threadId, version]);
  useLayoutEffect(() => {
    if (list.current) list.current.scrollTop = list.current.scrollHeight;
  }, [events.length]);
  const lines = useMemo(() => logLines(events), [events]);
  return <aside className="assistant-history" aria-label="Activity log">
    <div className="assistant-history-head">
      <strong>Activity log</strong>
      <button type="button" className="studio-link" onClick={onClose}>Close</button>
    </div>
    {failed && <p className="studio-error" role="alert">The log couldn't be loaded. It will try again.</p>}
    {!lines.length && !failed && <p className="studio-hint">Nothing has happened yet.</p>}
    <ol ref={list} className="assistant-history-list">{lines.map(line =>
      <li key={line.sequence} className={`is-${line.tone}`}>
        <span className="assistant-history-label">{line.label}</span>
        <time dateTime={line.at}>{clock(line.at)}</time>
        {line.detail && <p>{line.detail}</p>}
      </li>)}</ol>
  </aside>;
}
