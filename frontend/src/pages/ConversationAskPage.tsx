import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { streamQueryRun } from "../lib/stream";
import { queryFailureMessage } from "../lib/queryOutcome";
import { useTranscriptScroll } from "../lib/useTranscriptScroll";
import type { Conversation, ConversationTurn, QueryRunResponse, SearchReadiness, SystemReadiness } from "../lib/types";
import { useWorkspace } from "../lib/workspace";
import { Button, Spinner } from "../components/ui";
import { ConversationTurn as ConversationTurnMessage } from "../components/ConversationTurn";
import { ConversationSidebar } from "../components/ConversationSidebar";
import { ConversationTitle } from "../components/ConversationTitle";

export function ConversationAskPage({ capabilities }: { capabilities: NonNullable<SystemReadiness["setup_capabilities"]> }) {
  const { workspace } = useWorkspace();
  const tenantId = workspace!.id;
  const [historyRevision, setHistoryRevision] = useState(0);
  const [selected, setSelected] = useState<Conversation | null>(null);
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [readiness, setReadiness] = useState<SearchReadiness | null>(null);
  const [sending, setSending] = useState(false);
  const [retryLost, setRetryLost] = useState(false);
  const [streamingRun, setStreamingRun] = useState<string | null>(null);
  const [accessDenied, setAccessDenied] = useState(false);
  const [focusTarget, setFocusTarget] = useState<"heading" | "composer" | null>(null);
  const heading = useRef<HTMLHeadingElement | null>(null);
  const composer = useRef<HTMLTextAreaElement | null>(null);
  const selectionRequest = useRef<AbortController | null>(null);
  const sendingRef = useRef(false);
  const pendingSend = useRef<{ conversationId: string; query: string; key: string } | null>(null);
  const viewer = workspace!.role === "viewer";
  const active = turns.some((turn) => turn.run.status === "queued" || turn.run.status === "running");
  const remainingTurns = !!selected && (turns.at(-1)?.turn_number ?? 0) < selected.next_turn_number - 1;
  const scroll = useTranscriptScroll(turns.at(-1)?.run);

  useEffect(() => {
    if (loading || accessDenied || !focusTarget) return;
    const target = focusTarget === "heading" ? heading.current : composer.current;
    target?.focus({ preventScroll: true });
    setFocusTarget(null);
  }, [focusTarget, loading, accessDenied]);

  useEffect(() => {
    if (accessDenied) return;
    let controller: AbortController | null = null;
    const refresh = () => {
      controller?.abort(); controller = new AbortController();
      const request = controller;
      void api.getSearchReadiness(tenantId, request.signal)
        .then((value) => { if (!request.signal.aborted) setReadiness(value); })
        .catch((err) => {
          if (request.signal.aborted) return;
          setReadiness(null);
          if (err instanceof ApiError && [401, 403].includes(err.status)) clearDeniedAccess();
        });
    };
    refresh(); const timer = window.setInterval(refresh, 5000);
    return () => { window.clearInterval(timer); controller?.abort(); };
  }, [tenantId, accessDenied]);

  useEffect(() => {
    try {
      const savedId = localStorage.getItem(`flintgraph.conversation.${tenantId}`);
      if (savedId) void selectConversation(savedId);
    } catch { /* Storage can be unavailable; the server remains authoritative. */ }
    return () => selectionRequest.current?.abort();
  }, [tenantId]);

  function saveSelection(id: string | null) {
    try {
      const key = `flintgraph.conversation.${tenantId}`;
      if (id) localStorage.setItem(key, id); else localStorage.removeItem(key);
    } catch { /* Reopening from history does not require browser storage. */ }
  }

  async function selectConversation(row: Conversation | string) {
    const id = typeof row === "string" ? row : row.id;
    setFocusTarget(null);
    selectionRequest.current?.abort(); scroll.reset();
    const controller = new AbortController();
    selectionRequest.current = controller;
    setSelected(typeof row === "string" ? null : row); setTurns([]); setInput(""); setError(null); setLoading(true); setHistoryOpen(false);
    pendingSend.current = null; setRetryLost(false); setSending(false); sendingRef.current = false; setStreamingRun(null);
    try {
      const [conversation, messages] = await Promise.all([
        api.getConversation(tenantId, id, controller.signal),
        api.listConversationTurns(tenantId, id, { limit: 50, signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;
      setSelected(conversation); setTurns(messages); saveSelection(conversation.id);
      // Only explicit history selection moves focus; passive restore is quiet.
      if (typeof row !== "string") setFocusTarget("heading");
    } catch (err) {
      if (!controller.signal.aborted) {
        setSelected(null); saveSelection(null);
        setError(err instanceof ApiError ? err.message : "Could not reopen this conversation.");
        if (err instanceof ApiError && [401, 403].includes(err.status)) clearDeniedAccess();
      }
    } finally { if (!controller.signal.aborted) setLoading(false); }
  }

  function newChat(focusComposer = true) {
    selectionRequest.current?.abort(); scroll.reset();
    pendingSend.current = null; sendingRef.current = false; saveSelection(null);
    setSelected(null); setTurns([]); setInput(""); setError(null);
    setSending(false); setRetryLost(false); setLoading(false); setHistoryOpen(false); setStreamingRun(null);
    setFocusTarget(focusComposer && !viewer ? "composer" : null);
  }

  function clearDeniedAccess() {
    newChat(false); setAccessDenied(true); setReadiness(null);
    setError("Workspace access was denied. Conversation data has been cleared.");
  }

  function updateRun(run: QueryRunResponse) {
    setTurns((previous) => previous.map((turn) => turn.run.id === run.id ? { ...turn, run } : turn));
  }

  async function loadRemainingTurns() {
    if (!selected || loading || sending || !remainingTurns) return;
    selectionRequest.current?.abort();
    const controller = new AbortController(); selectionRequest.current = controller;
    setLoading(true); setError(null);
    try {
      const [conversation, messages] = await Promise.all([
        api.getConversation(tenantId, selected.id, controller.signal),
        api.listConversationTurns(tenantId, selected.id, { limit: 50, afterId: turns.at(-1)?.id, signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;
      setSelected(conversation);
      if (messages.length) scroll.hold();
      setTurns((previous) => [...previous, ...messages.filter((row) => !previous.some((item) => item.id === row.id))].sort((a,b) => a.turn_number-b.turn_number));
      if (!messages.length) setError("No additional turns were returned. Refresh the conversation to check its current state.");
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof ApiError ? err.message : "The remaining turns could not be loaded. Retry Load remaining turns.");
      if (err instanceof ApiError && [401, 403].includes(err.status)) clearDeniedAccess();
    } finally { if (!controller.signal.aborted) setLoading(false); }
  }

  async function executeTurn(turn: ConversationTurn, controller: AbortController) {
    setStreamingRun(turn.run.id);
    try {
      await streamQueryRun(tenantId, turn.run.id, {
        signal: controller.signal,
        onEvent: (event) => {
          if (controller.signal.aborted) return;
          if (event.event_type === "query.started") {
            setTurns((previous) => previous.map((item) => item.id === turn.id ? { ...item, run: { ...item.run, status: "running" } } : item));
          }
        },
      });
      const run = await api.getQueryRun(tenantId, turn.run.id, controller.signal);
      if (controller.signal.aborted) return;
      updateRun(run);
      const failure = queryFailureMessage(run);
      if (failure) setError(failure);
    } finally { if (!controller.signal.aborted) setStreamingRun(null); }
  }

  function stopStream() {
    if (!streamingRun) return;
    selectionRequest.current?.abort();
    setStreamingRun(null); setSending(false); sendingRef.current = false;
    setError("Stream stopped locally. Execution is request-bound; refresh the conversation to confirm the backend status.");
  }

  async function refreshConversation() {
    if (!selected || loading || sending) return;
    selectionRequest.current?.abort();
    const controller = new AbortController(); selectionRequest.current = controller;
    setLoading(true); setError(null);
    try {
      const [conversation, messages, currentRuns] = await Promise.all([
        api.getConversation(tenantId, selected.id, controller.signal),
        api.listConversationTurns(tenantId, selected.id, { limit: 50, signal: controller.signal }),
        Promise.all(turns.filter((turn) => turn.run.status === "queued" || turn.run.status === "running")
          .map((turn) => api.getQueryRun(tenantId, turn.run.id, controller.signal))),
      ]);
      if (controller.signal.aborted) return;
      setSelected(conversation);
      setTurns((previous) => {
        const merged = new Map(previous.map((turn) => [turn.id, turn]));
        for (const turn of messages) merged.set(turn.id, turn);
        return [...merged.values()].map((turn) => ({ ...turn, run: currentRuns.find((run) => run.id === turn.run.id) ?? turn.run }))
          .sort((a,b) => a.turn_number-b.turn_number);
      });
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof ApiError ? err.message : "Could not refresh this conversation. Retry Refresh conversation.");
      if (err instanceof ApiError && [401, 403].includes(err.status)) clearDeniedAccess();
    } finally { if (!controller.signal.aborted) setLoading(false); }
  }

  async function resumeQueuedTurn() {
    const turn = turns.find((item) => item.run.status === "queued");
    if (!turn || viewer || sendingRef.current || loading) return;
    selectionRequest.current?.abort();
    const controller = new AbortController(); selectionRequest.current = controller;
    sendingRef.current = true; setSending(true); setError(null);
    try {
      const current = await api.getQueryRun(tenantId, turn.run.id, controller.signal);
      if (controller.signal.aborted) return;
      updateRun(current);
      if (current.status === "queued") await executeTurn({ ...turn, run: current }, controller);
      else setError("This turn is no longer queued. Its current status is shown; refresh if it is still running.");
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof ApiError ? err.message : "The stream disconnected. Refresh the conversation to check the existing turn.");
      if (err instanceof ApiError && [401, 403].includes(err.status)) clearDeniedAccess();
    } finally { if (!controller.signal.aborted) { sendingRef.current = false; setSending(false); } }
  }

  async function cancelQueuedTurn() {
    const turn = turns.find((item) => item.run.status === "queued");
    if (!selected || !turn || viewer || sendingRef.current || loading) return;
    selectionRequest.current?.abort();
    const controller = new AbortController(); selectionRequest.current = controller;
    sendingRef.current = true; setSending(true); setError(null);
    try {
      const cancelled = await api.cancelQueuedConversationTurn(tenantId, selected.id, turn.id, controller.signal);
      if (!controller.signal.aborted) updateRun(cancelled.run);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof ApiError ? err.message : "Cancellation could not be confirmed. Refresh this conversation before retrying.");
      if (err instanceof ApiError && [401, 403].includes(err.status)) clearDeniedAccess();
    } finally { if (!controller.signal.aborted) { sendingRef.current = false; setSending(false); } }
  }

  async function send() {
    const question = pendingSend.current?.query ?? input.trim();
    if (sendingRef.current || loading || viewer || !readiness?.ready || !question || remainingTurns || (active && !retryLost)) return;
    selectionRequest.current?.abort();
    const controller = new AbortController(); selectionRequest.current = controller;
    sendingRef.current = true; setSending(true); setError(null);
    try {
      let conversation = selected;
      if (!conversation) {
        conversation = await api.createConversation(tenantId, question.slice(0, 200), controller.signal);
        if (controller.signal.aborted) return;
        setSelected(conversation); saveSelection(conversation.id); setHistoryRevision((value) => value+1);
      }
      const submission = pendingSend.current ?? { conversationId: conversation.id, query: question, key: crypto.randomUUID() };
      pendingSend.current = submission;
      const turn = await api.createConversationTurn(tenantId, submission.conversationId, submission.query, submission.key, controller.signal);
      if (controller.signal.aborted) return;
      pendingSend.current = null; setRetryLost(false); setInput("");
      setTurns((previous) => [...previous.filter((item) => item.id !== turn.id), turn].sort((a,b) => a.turn_number-b.turn_number));
      setSelected((previous) => previous ? { ...previous, next_turn_number: Math.max(previous.next_turn_number, turn.turn_number + 1) } : previous);
      await executeTurn(turn, controller);
    } catch (err) {
      if (controller.signal.aborted) return;
      if (err instanceof ApiError && err.status < 500) pendingSend.current = null;
      setRetryLost(pendingSend.current !== null);
      setError(pendingSend.current ? "The response was lost. Retry sending safely with the same request identity."
        : err instanceof ApiError ? err.message : "The request disconnected. Refresh the conversation to check its status.");
      if (err instanceof ApiError && [401, 403].includes(err.status)) clearDeniedAccess();
    } finally {
      if (!controller.signal.aborted) { sendingRef.current = false; setSending(false); }
    }
  }

  if (accessDenied) return <p role="alert" className="p-6 text-sm text-red-700">Workspace access was denied. Conversation data has been cleared. Refresh the page or switch workspace after access is restored.</p>;

  return <section aria-label="Ask workspace" className="flex h-full min-h-0 flex-col lg:flex-row">
    <div className="border-b border-slate-200 bg-white p-2 lg:hidden">
      <button aria-expanded={historyOpen} aria-controls="conversation-sidebar" onClick={() => setHistoryOpen((value) => !value)}
        className="rounded px-3 py-2 text-sm text-brand-700 focus-visible:outline-2 focus-visible:outline-brand-500">Conversation history</button>
    </div>
    <aside id="conversation-sidebar" aria-label="Conversations" className={`${historyOpen ? "block" : "hidden"} max-h-[40vh] shrink-0 overflow-y-auto border-r border-slate-200 bg-white p-4 lg:block lg:max-h-none lg:w-60`}>
      <ConversationSidebar tenantId={tenantId} selectedId={selected?.id} revision={historyRevision}
        discovery={capabilities.conversation_discovery === true} onSelect={(row) => void selectConversation(row)} onAccessDenied={clearDeniedAccess} />
    </aside>
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="shrink-0 border-b border-slate-200 bg-white px-4 py-3 sm:px-6">
        <div className="flex items-center justify-between gap-3">
          <h1 ref={heading} tabIndex={-1} className="min-w-0 truncate text-lg font-semibold text-slate-900 focus-visible:outline-2 focus-visible:outline-brand-500 [font-family:'Segoe_UI_Variable_Display','Segoe_UI',sans-serif]">{selected?.title ?? "New conversation"}</h1>
          <Button type="button" variant="secondary" className="shrink-0 whitespace-nowrap" disabled={viewer} onClick={() => newChat()}>New chat</Button>
        </div>
        {selected && <button disabled={loading || sending} onClick={() => void refreshConversation()}
          className="mr-2 rounded px-2 py-1 text-xs text-brand-700 underline underline-offset-2 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-brand-500">Refresh conversation</button>}
        {selected && !viewer && capabilities.conversation_discovery && <ConversationTitle key={selected.id} tenantId={tenantId}
          conversation={selected} disabled={sending || loading} onAccessDenied={clearDeniedAccess}
          onRenamed={(row) => { setSelected(row); setHistoryRevision((value) => value+1); }} />}
        <p className="mt-1 text-xs leading-5 text-slate-500">{capabilities.prior_year_followups
          ? "Prior-year follow-ups are supported after a grounded answer. Other follow-ups need a self-contained question."
          : "Each question is independent. Follow-up memory is unavailable on this backend."}</p>
        {remainingTurns && <button disabled={loading || sending} onClick={() => void loadRemainingTurns()}
          className="mt-2 rounded py-1 text-xs text-brand-700 underline underline-offset-2 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-brand-500">Load remaining turns</button>}
      </header>
      {error && <p role="alert" className="shrink-0 border-b border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700 [overflow-wrap:anywhere] sm:px-6">{error}</p>}
      <div ref={scroll.element} onScroll={scroll.onScroll} role="region" aria-label="Conversation transcript" tabIndex={0} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-6 focus-visible:outline-2 focus-visible:outline-brand-500 sm:px-6">
        <div className="mx-auto max-w-3xl space-y-8">
          {loading && <p role="status" className="text-sm text-slate-500">Opening conversation…</p>}
          {!loading && turns.length === 0 && <div className="py-12"><h2 className="text-xl font-semibold text-slate-800">Research with your documents</h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">Questions and source-backed answers stay together in a workspace conversation.</p></div>}
          {turns.map((turn) => <ConversationTurnMessage key={turn.id} tenantId={tenantId} turn={turn} onAccessDenied={clearDeniedAccess} onInspectEvidence={scroll.hold} />)}
        </div>
      </div>
      {scroll.showLatest && <div className="shrink-0 border-t border-slate-100 bg-white py-1 text-center">
        <button onClick={scroll.jump} className="rounded px-3 py-2 text-xs font-medium text-brand-700 focus-visible:outline-2 focus-visible:outline-brand-500">Jump to latest</button>
      </div>}
      <form onSubmit={(event) => { event.preventDefault(); void send(); }} className="shrink-0 border-t border-slate-200 bg-white px-4 py-3 sm:px-6">
        <div className="mx-auto max-w-3xl">
          <label className="sr-only" htmlFor="conversation-question">Your question</label>
          <textarea ref={composer} id="conversation-question" value={input} onChange={(event) => setInput(event.target.value)} rows={2} maxLength={1000}
            readOnly={viewer || retryLost} disabled={sending || loading}
            onKeyDown={(event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); void send(); } }}
            placeholder="Ask about the documents in this workspace…" className="w-full resize-none rounded-xl border border-slate-300 px-3 py-2 text-sm focus:outline-2 focus:outline-brand-500" />
          <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs leading-5 text-slate-500">{viewer ? "Viewer access · read-only conversations" : remainingTurns ? "Load the remaining turns before following up."
              : active ? "A turn is queued or running. Refresh to check its status."
              : readiness?.ready ? "Ctrl/⌘ + Enter to send · current workspace sources"
              : "Searchable documents are required. Check Documents or Setup."}</p>
            {!viewer && active && !sending && turns.some((turn) => turn.run.status === "queued") && <Button type="button" variant="secondary" disabled={loading || remainingTurns || !readiness?.ready} onClick={() => void resumeQueuedTurn()}>Resume queued turn</Button>}
            {!viewer && active && !sending && turns.some((turn) => turn.run.status === "queued") && <Button type="button" variant="danger" disabled={loading || remainingTurns} onClick={() => void cancelQueuedTurn()}>Cancel queued turn</Button>}
            {!viewer && streamingRun && <Button type="button" variant="secondary" onClick={stopStream}>Stop stream</Button>}
            {!viewer && <Button type="submit" disabled={sending || loading || !readiness?.ready || (!input.trim() && !retryLost) || remainingTurns || (active && !retryLost)}>
              {sending && <Spinner className="h-4 w-4" />}{sending ? "Working…" : retryLost ? "Retry sending safely" : "Send"}
            </Button>}
          </div>
        </div>
      </form>
    </div>
  </section>;
}
