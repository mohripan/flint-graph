import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { Conversation } from "../lib/types";

export function ConversationSidebar({ tenantId, selectedId, revision, discovery, onSelect, onAccessDenied }: {
  tenantId: string; selectedId?: string; revision: number; discovery: boolean;
  onSelect: (conversation: Conversation) => void; onAccessDenied: () => void;
}) {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [more, setMore] = useState(false);
  const pageRequest = useRef<AbortController | null>(null);
  const denied = useRef(onAccessDenied); denied.current = onAccessDenied;
  useEffect(() => {
    const controller = new AbortController();
    setRows([]); setLoading(true); setError(null); setMore(false);
    const timer = window.setTimeout(() => {
      void api.listConversations(tenantId, { limit: 25, query, signal: controller.signal })
        .then((value) => { if (!controller.signal.aborted) { setRows(value); setMore(value.length === 25); } })
        .catch((err) => {
          if (controller.signal.aborted) return;
          setError("Could not load conversations. Use Refresh history to retry.");
          if (err instanceof ApiError && [401, 403].includes(err.status)) denied.current();
        }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 200);
    return () => { window.clearTimeout(timer); controller.abort(); pageRequest.current?.abort(); };
  }, [tenantId, query, revision, refresh]);
  async function loadMore() {
    if (loading || !more || !rows.length) return;
    pageRequest.current?.abort();
    const controller = new AbortController(); pageRequest.current = controller;
    setLoading(true); setError(null);
    try {
      const value = await api.listConversations(tenantId, { limit: 25, beforeId: rows.at(-1)!.id, query, signal: controller.signal });
      if (controller.signal.aborted) return;
      setRows((previous) => [...previous, ...value.filter((row) => !previous.some((item) => item.id === row.id))]);
      setMore(value.length === 25);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError("Older conversations could not be loaded. Retry Load older conversations.");
      if (err instanceof ApiError && [401, 403].includes(err.status)) denied.current();
    } finally { if (!controller.signal.aborted) setLoading(false); }
  }
  return <>
    <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Conversations</h2>
    {discovery && <label className="mb-3 block text-xs text-slate-500">Search conversations
      <input aria-label="Search conversations" value={query} maxLength={200} onChange={(event) => { pageRequest.current?.abort(); setQuery(event.target.value); }}
        placeholder="Search titles…" className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-2 text-sm text-slate-800 focus:outline-2 focus:outline-brand-500" />
    </label>}
    <button onClick={() => setRefresh((value) => value+1)} className="mb-3 rounded text-xs text-brand-700 underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-brand-500">Refresh history</button>
    {loading && <p role="status" className="text-sm text-slate-500">Loading history…</p>}
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    <ul className="space-y-1">{rows.map((row) => <li key={row.id}>
      <button onClick={() => onSelect(row)} aria-current={selectedId === row.id ? "true" : undefined}
        className={`w-full rounded-lg px-3 py-3 text-left text-sm [overflow-wrap:anywhere] focus-visible:outline-2 focus-visible:outline-brand-500 ${selectedId === row.id ? "bg-brand-50 text-brand-800" : "text-slate-700 hover:bg-slate-50"}`}>{row.title}</button>
    </li>)}</ul>
    {more && <button disabled={loading} onClick={() => void loadMore()} className="mt-3 rounded py-2 text-xs text-brand-700 underline underline-offset-2 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-brand-500">Load older conversations</button>}
    {!loading && !error && rows.length === 0 && <p className="text-sm text-slate-500">{query.trim() ? "No matching conversations." : "No conversations yet."}</p>}
  </>;
}
