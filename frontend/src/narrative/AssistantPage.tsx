import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, MutableRefObject } from "react";
import { ApiError, api } from "../lib/api";
import {
  activeTurn, activitySteps, assistantError, emptyActivity, foldEvents, mergeTurns, prepareThread, prepareTurn, proposalChanges,
  proposalStatus, sendBlocker, streamedReply, threadTitle, turnStatus, workedFor,
} from "./assistantModel";
import type { AssistantTurnEvent, StepView, ThreadIntent, TurnActivity, TurnIntent } from "./assistantModel";
import { followTurnEvents, listTurnEvents, streamTurnEvents } from "./assistantStream";
import { ProposalActions } from "./ProposalActions";
import { releaseErrorMessage, useReleaseRequests } from "./releaseRequests";
import type { AssistantProposal, AssistantThread, AssistantTurn, NarrativeRevision, StoryDraft } from "./types";
import "./assistant.css";

const terminal = new Set(["completed", "failed", "cancelled"]);
const suggestions = [
  "Add a scene after the opening where a stranger asks for help.",
  "Give the player a choice that leads to two different endings.",
  "Which scenes can the player never reach?",
];

function parsed(source: string): StoryDraft | null {
  try { return JSON.parse(source) as StoryDraft; } catch { return null; }
}
function conflictId(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const first = error.problem?.errors?.[0];
  return typeof first?.conflict_revision_id === "string" ? first.conflict_revision_id : null;
}
function readSelection(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function writeSelection(key: string, id: string | null): void {
  try { if (id) localStorage.setItem(key, id); else localStorage.removeItem(key); } catch { /* Optional convenience. */ }
}
// The open conversation is part of the link, so it can be shared or reported by ID.
export function linkedThread(): string | null {
  try { return new URLSearchParams(location.search).get("thread"); } catch { return null; }
}
function linkThread(projectId: string, threadId: string | null): void {
  try {
    const url = new URL(location.href);
    url.searchParams.set("project", projectId);
    if (threadId) url.searchParams.set("thread", threadId); else url.searchParams.delete("thread");
    history.replaceState(history.state, "", url);
  } catch { /* The link is a convenience; the conversation still opens. */ }
}
function shortDate(value: string): string {
  const date = new Date(value);
  return date.toDateString() === new Date().toDateString()
    ? date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : date.toLocaleDateString();
}

function Thinking({ text, live, label }: { text: string; live: boolean; label: string }) {
  const body = useRef<HTMLParagraphElement>(null);
  useLayoutEffect(() => { if (live && body.current) body.current.scrollTop = body.current.scrollHeight; }, [text, live]);
  return <details className="assistant-thinking" open={live}>
    <summary>{label}</summary>
    <p ref={body}>{text}</p>
  </details>;
}

function StepIcon({ state }: { state: StepView["state"] }) {
  return <span className={`assistant-step-icon is-${state}`} aria-hidden="true">
    {state === "done" ? "✓" : state === "failed" ? "!" : state === "stopped" ? "–" : ""}</span>;
}

// A full-height chat for one project. Turns run in the background worker; their
// steps, thinking and reply stream from persisted events and resume after a reload.
// Proposals stay suggestions until accepted, which creates a normal saved revision.
export function AssistantPage({ tenantId, projectId, revision, focus, canWrite, dirty, saving, scopeRef,
  onSave, onAccepted, onConflict, onInspect, onOpenEditor, onAccessLost }: {
  tenantId: string; projectId: string; revision: NarrativeRevision; focus: string | null; canWrite: boolean;
  dirty: boolean; saving: boolean; scopeRef: MutableRefObject<(() => void) | null>;
  onSave: () => Promise<NarrativeRevision | null>; onAccepted: (revision: NarrativeRevision) => void;
  onConflict: (conflictRevisionId: string) => void; onInspect: (revisionId: string) => void;
  onOpenEditor: () => void; onAccessLost: () => void;
}) {
  const { run, cancel, invalidate } = useReleaseRequests(onAccessLost);
  useLayoutEffect(() => {
    scopeRef.current = invalidate;
    return () => { if (scopeRef.current === invalidate) scopeRef.current = null; };
  }, [scopeRef, invalidate]);
  const selectionKey = `flintgraph.assistant.thread.${tenantId}.${projectId}`;
  const [threads, setThreads] = useState<AssistantThread[]>([]);
  const [threadsMore, setThreadsMore] = useState(false);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const threadRef = useRef<string | null>(null);
  const [turns, setTurns] = useState<AssistantTurn[]>([]);
  const [proposals, setProposals] = useState<Record<string, AssistantProposal>>({});
  const [activities, setActivities] = useState<Record<string, TurnActivity>>({});
  const cursors = useRef(new Map<string, number>()), ended = useRef(new Set<string>());
  const [text, setText] = useState(""), [sending, setSending] = useState(false);
  const [deciding, setDeciding] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [visible, setVisible] = useState(() => document.visibilityState !== "hidden");
  const [drawer, setDrawer] = useState(false), [withFocus, setWithFocus] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const intent = useRef<TurnIntent | null>(null), threadIntent = useRef<ThreadIntent | null>(null);
  const decisionKeys = useRef(new Map<string, string>()), composer = useRef<HTMLTextAreaElement>(null);
  const scroller = useRef<HTMLDivElement>(null), stick = useRef(true), requested = useRef(new Map<string, string>());
  const story = useMemo(() => parsed(revision.story_json), [revision.story_json]);
  const active = activeTurn(turns);
  const live = [...turns].reverse().find(turn => !terminal.has(turn.status));
  const liveId = live?.id ?? null;
  const thread = threads.find(row => row.id === threadId);
  const target = withFocus ? focus : null;

  const apply = useCallback((turnId: string, events: AssistantTurnEvent[]) => {
    const own = events.filter(event => event.turn_id === turnId);
    if (!own.length) return;
    cursors.current.set(turnId, Math.max(cursors.current.get(turnId) ?? 0, ...own.map(event => event.sequence)));
    if (own.some(event => event.kind === "status")) ended.current.add(turnId);
    setActivities(current => {
      const before = current[turnId] ?? emptyActivity(), after = foldEvents(before, own);
      return after === before ? current : { ...current, [turnId]: after };
    });
  }, []);
  const loadTurns = useCallback((id: string) => {
    void run("turns", signal => api.listAssistantTurns(tenantId, projectId, id, { signal }), rows => {
      if (threadRef.current !== id) return;
      setTurns(current => mergeTurns(current, rows.filter(row => row.thread_id === id)));
    }, failure => setError(releaseErrorMessage(failure)));
  }, [run, tenantId, projectId]);
  const choose = useCallback((id: string | null) => {
    if (threadRef.current) cancel("turns");
    threadRef.current = id; setThreadId(id); setTurns([]); setProposals({}); setActivities({}); setConflict(null);
    cursors.current.clear(); ended.current.clear(); requested.current.clear(); stick.current = true;
    setDrawer(false); writeSelection(selectionKey, id); linkThread(projectId, id);
    if (id) loadTurns(id);
  }, [cancel, loadTurns, selectionKey, projectId]);
  const loadThreads = useCallback((older?: string) => {
    void run("threads", signal => api.listAssistantThreads(tenantId, projectId, { beforeId: older, signal }), rows => {
      const own = rows.filter(row => row.project_id === projectId);
      setThreads(current => older ? [...current, ...own.filter(row => !current.some(item => item.id === row.id))] : own);
      setThreadsMore(rows.length === 25);
      if (older || threadRef.current) return;
      // A conversation in the link wins, even one older than the first page of the list.
      const linked = linkedThread();
      if (linked && !own.some(row => row.id === linked)) {
        void run("linked", signal => api.getAssistantThread(tenantId, projectId, linked, signal), row => {
          if (row.project_id !== projectId || threadRef.current) return;
          setThreads(current => current.some(item => item.id === row.id) ? current : [row, ...current]);
          choose(row.id);
        }, () => { if (!threadRef.current && own[0]) choose(own[0].id); });
        return;
      }
      const stored = linked ?? readSelection(selectionKey);
      const initial = own.find(row => row.id === stored) ?? own[0];
      if (initial) choose(initial.id); else linkThread(projectId, null);
    }, failure => setError(releaseErrorMessage(failure)));
  }, [run, tenantId, projectId, selectionKey, choose]);
  useEffect(() => { loadThreads(); }, [loadThreads]);
  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== "hidden");
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  // Follow the running turn's persisted events; reconnects resume from the last sequence.
  useEffect(() => {
    if (!threadId || !liveId || !visible) return;
    const channel = `stream:${liveId}`, turnId = liveId, forThread = threadId;
    void run(channel, signal => followTurnEvents(
      after => streamTurnEvents(tenantId, projectId, forThread, turnId, after, { signal, onEvents: events => apply(turnId, events) }),
      { cursor: () => cursors.current.get(turnId) ?? 0, finished: () => ended.current.has(turnId) }, signal),
    () => { if (threadRef.current === forThread) loadTurns(forThread); },
    failure => { if (!(failure instanceof ApiError && failure.status === 404)) setError(releaseErrorMessage(failure)); });
    return () => cancel(channel);
  }, [threadId, liveId, visible, run, cancel, apply, loadTurns, tenantId, projectId]);
  // A slow safety-net poll; the stream's final event normally refreshes the turn at once.
  useEffect(() => {
    if (!threadId || !active || !visible) return;
    const timer = window.setTimeout(() => loadTurns(threadId), 8000);
    return () => window.clearTimeout(timer);
  }, [threadId, active, visible, turns, loadTurns]);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  // Proposal details carry the operations needed for the change list; fetch each once.
  useEffect(() => {
    for (const turn of turns) {
      const summary = turn.proposal;
      if (!summary || proposals[summary.id]?.status === summary.status
        || requested.current.get(summary.id) === summary.status) continue;
      requested.current.set(summary.id, summary.status);
      void run(`proposal:${summary.id}`, signal => api.getAssistantProposal(tenantId, projectId, summary.id, signal),
        detail => { if (detail.thread_id === threadRef.current) setProposals(current => ({ ...current, [detail.id]: detail })); },
        failure => { requested.current.delete(summary.id); setError(releaseErrorMessage(failure)); });
    }
  }, [turns, proposals, run, tenantId, projectId]);
  // The latest finished reply shows how long it took without a click; older ones load on demand.
  const last = turns[turns.length - 1];
  useEffect(() => {
    if (last && terminal.has(last.status) && !activities[last.id]) loadActivity(last.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [last?.id, last?.status]);
  useLayoutEffect(() => {
    const element = scroller.current;
    if (element && stick.current) element.scrollTop = element.scrollHeight;
  }, [turns, activities, proposals]);

  function loadActivity(turnId: string) {
    if (!threadId || ended.current.has(turnId) || turnId === liveId) return;
    const forThread = threadId;
    void run(`events:${turnId}`, async signal => {
      const rows: AssistantTurnEvent[] = [];
      for (let after = cursors.current.get(turnId) ?? 0; ;) {
        const page = await listTurnEvents(tenantId, projectId, forThread, turnId, after, signal);
        rows.push(...page);
        if (page.length < 500) return rows;
        after = page[page.length - 1].sequence;
      }
    }, rows => { if (threadRef.current === forThread) { apply(turnId, rows); ended.current.add(turnId); } },
    failure => {
      // A server without live progress (or a vanished turn) just has no recorded steps.
      if (failure instanceof ApiError && failure.status === 404) ended.current.add(turnId);
      else setError(releaseErrorMessage(failure));
    });
  }
  const blocker = sendBlocker({ canWrite, dirty, saving, sending, active, text });
  function send(event?: FormEvent) {
    event?.preventDefault();
    if (blocker) return;
    setSending(true); setError(null); stick.current = true;
    const message = text.trim(), next = prepareTurn(intent.current, message, revision.id, target);
    intent.current = next;
    void run("send", async signal => {
      let id = threadRef.current;
      if (!id) {
        const thread = threadIntent.current = prepareThread(threadIntent.current, threadTitle(message));
        id = (await api.createAssistantThread(tenantId, projectId, thread.title, thread.key, signal)).id;
      }
      return { id, turn: await api.postAssistantTurn(tenantId, projectId, id, next, signal) };
    }, ({ id, turn }) => {
      intent.current = null; threadIntent.current = null; setText("");
      if (threadRef.current !== id) {
        threadRef.current = id; setThreadId(id); writeSelection(selectionKey, id); linkThread(projectId, id);
        setThreads(current => current.some(row => row.id === id) ? current
          : [{ id, tenant_id: tenantId, project_id: projectId, title: threadTitle(message), archived_at: null,
            created_at: turn.created_at, updated_at: turn.created_at }, ...current]);
      }
      setTurns(current => mergeTurns(current, [turn]));
    }, failure => {
      // The retained key makes a resend safe after an ambiguous failure.
      setError(failure instanceof ApiError && failure.status === 503 ? assistantError("assistant_unavailable")
        : releaseErrorMessage(failure));
    }, () => setSending(false));
  }
  function stop(turn: AssistantTurn) {
    if (!threadId) return;
    void run(`cancel:${turn.id}`, signal => api.cancelAssistantTurn(tenantId, projectId, threadId, turn.id, signal),
      row => setTurns(current => mergeTurns(current, [row])), failure => setError(releaseErrorMessage(failure)));
  }
  function accept(proposal: AssistantProposal) {
    if (!canWrite || dirty || deciding) return;
    const key = decisionKeys.current.get(proposal.id) ?? crypto.randomUUID();
    decisionKeys.current.set(proposal.id, key);
    setDeciding(proposal.id); setError(null); setConflict(null);
    void run("decide", signal => api.acceptAssistantProposal(tenantId, projectId, proposal.id, key, signal), saved => {
      decisionKeys.current.delete(proposal.id);
      setProposals(current => ({ ...current, [proposal.id]: { ...proposal, status: "accepted", accepted_revision_id: saved.id } }));
      onAccepted(saved);
      if (threadRef.current) loadTurns(threadRef.current);
    }, failure => {
      const kept = conflictId(failure);
      if (kept) {
        decisionKeys.current.delete(proposal.id); setConflict(kept); onConflict(kept);
        if (threadRef.current) loadTurns(threadRef.current);
      } else setError(releaseErrorMessage(failure));
    }, () => setDeciding(null));
  }
  function reject(proposal: AssistantProposal) {
    if (!canWrite || deciding) return;
    setDeciding(proposal.id); setError(null);
    void run("decide", signal => api.rejectAssistantProposal(tenantId, projectId, proposal.id, signal), row => {
      setProposals(current => ({ ...current, [row.id]: row }));
      setTurns(current => current.map(turn => turn.proposal?.id === row.id
        ? { ...turn, proposal: { ...turn.proposal, status: row.status } } : turn));
    }, failure => setError(releaseErrorMessage(failure)), () => setDeciding(null));
  }
  function compose(value: string) {
    setText(value);
    window.requestAnimationFrame(() => { composer.current?.focus(); resize(); });
  }
  function resize() {
    const element = composer.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 240)}px`;
  }

  const announced = live ? activitySteps(activities[live.id] ?? emptyActivity(), true).filter(view => view.state === "active").pop()?.label : null;
  return <section className="assistant-page" aria-label="Story assistant">
    <aside className={`assistant-threads ${drawer ? "is-open" : ""}`} aria-label="Conversations">
      <div className="assistant-threads-head">
        <strong>Conversations</strong>
        <button type="button" className="studio-link assistant-drawer-close" onClick={() => setDrawer(false)}>Close</button>
      </div>
      {canWrite && <button type="button" className="studio-primary assistant-new" disabled={sending}
        onClick={() => { choose(null); compose(""); }}>New chat</button>}
      <ul className="assistant-thread-list">
        {threads.map(row => <li key={row.id}><button type="button" aria-current={row.id === threadId ? "true" : undefined}
          className={row.id === threadId ? "selected" : ""} onClick={() => choose(row.id)}>
          <span>{row.title}</span><small>{shortDate(row.created_at)}</small></button></li>)}
      </ul>
      {!threads.length && <p className="studio-hint">No conversations yet.</p>}
      {threadsMore && <button type="button" className="studio-link" onClick={() => loadThreads(threads[threads.length - 1]?.id)}>
        Show older conversations</button>}
      <button type="button" className="studio-secondary assistant-editor-link" onClick={onOpenEditor}>Back to the editor</button>
    </aside>
    {drawer && <button type="button" className="assistant-scrim" aria-label="Close conversations" onClick={() => setDrawer(false)} />}
    <div className="assistant-main">
      <header className="assistant-bar">
        <button type="button" className="studio-secondary assistant-drawer-open" aria-expanded={drawer}
          onClick={() => setDrawer(true)}>Conversations</button>
        <h2>{thread?.title ?? "New chat"}</h2>
        {threadId && <button type="button" className="assistant-thread-id" title={`Conversation ${threadId} · copy`}
          aria-label="Copy this conversation's ID" onClick={() => {
            void navigator.clipboard?.writeText(threadId).then(() => {
              setCopied(true); window.setTimeout(() => setCopied(false), 1500);
            }, () => undefined);
          }}><code>{copied ? "Copied" : threadId.slice(0, 8)}</code></button>}
        <span className="studio-hint">Revision {revision.revision_number}{dirty ? " · unsaved edits" : ""}</span>
      </header>
      <div className="studio-visually-hidden" role="status">{announced ?? ""}</div>
      <div ref={scroller} className="assistant-scroll" onScroll={event => {
        const element = event.currentTarget;
        stick.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80;
      }}>
        <div className="assistant-column">
          {error && <p className="studio-error" role="alert">{error}</p>}
          {conflict && <div className="studio-conflict"><strong>The story changed after this proposal.</strong>
            <p>It was kept as a conflict revision. Your current story is unchanged.</p>
            <button type="button" className="studio-secondary" onClick={() => onInspect(conflict)}>View conflict copy</button></div>}
          {!turns.length && <div className="assistant-welcome">
            <h3>What should we write next?</h3>
            <p>Describe a scene, a choice or a twist, or ask about your story. The assistant proposes changes;
              nothing changes until you accept.</p>
            {canWrite && <div className="assistant-suggestions">{suggestions.map(item =>
              <button type="button" key={item} onClick={() => compose(item)}>{item}</button>)}</div>}
          </div>}
          <ol className="assistant-log">{turns.map(turn => {
            const detail = turn.proposal ? proposals[turn.proposal.id] : undefined;
            const activity = activities[turn.id] ?? emptyActivity(), running = !terminal.has(turn.status);
            const steps = activitySteps(activity, running), current = steps.filter(view => view.state === "active").pop();
            const elapsed = Math.max(0, Math.round((now - Date.parse(activity.startedAt ?? turn.created_at)) / 1000));
            const reply = running ? streamedReply(activity) : turn.reply ?? "";
            const status = turnStatus(turn), calls = Object.keys(activity.calls).map(Number).sort((a, b) => a - b);
            const thinking = calls.filter(call => activity.calls[call].thinking);
            return <li key={turn.id} className="assistant-turn" aria-busy={running}>
              <p className="assistant-user">{turn.request}</p>
              <div className="assistant-answer">
                <details className="assistant-activity" open={running}
                  onToggle={event => { if (event.currentTarget.open) loadActivity(turn.id); }}>
                  <summary>{running ? <><span className="assistant-spinner" aria-hidden="true" />
                    {turn.status === "queued" && !activity.cursor ? "Waiting for the assistant" : current?.label ?? "Starting"}… · {elapsed} s</>
                    : workedFor(activity) || "Show what the assistant did"}</summary>
                  {steps.length > 0 && <ol className="assistant-steps">{steps.map(view => <li key={view.key} className={`is-${view.state}`}>
                    <StepIcon state={view.state} /><span>{view.label}</span>{view.detail && <small>{view.detail}</small>}</li>)}</ol>}
                  {thinking.map(call => <Thinking key={call} text={activity.calls[call].thinking}
                    live={running && call === activity.call && !activity.calls[call].text}
                    label={thinking.length > 1 || call > 1 ? `Thinking (attempt ${call})` : "Thinking"} />)}
                  {!steps.length && !thinking.length && !running && <p className="studio-hint">No step details were recorded for this reply.</p>}
                </details>
                {reply && <p className={`assistant-reply ${running ? "is-streaming" : ""}`}>{reply}</p>}
                {status && !running && <p className={turn.status === "failed" ? "studio-error" : "studio-hint"}>
                  {turn.status === "failed" ? assistantError(turn.error_code) : status}</p>}
                {running && turn.cancel_requested && <p className="studio-hint">Stopping…</p>}
                {canWrite && running && !turn.cancel_requested
                  && <button type="button" className="studio-secondary assistant-stop" onClick={() => stop(turn)}>Stop</button>}
                {turn.proposal && <section className="studio-proposal" aria-label="Proposed changes">
                  <div className="studio-section-heading"><strong>{turn.proposal.summary}</strong>
                    <span className={`studio-release-status is-${{ ready: "active", invalid: "failed", accepted: "ready",
                      rejected: "muted" }[detail?.status ?? turn.proposal.status]}`}>{proposalStatus(detail?.status ?? turn.proposal.status)}</span></div>
                  {detail ? <>
                    <ul className="studio-proposal-changes">{proposalChanges(story, detail.operations).map((change, index) =>
                      <li key={`${change.target}:${index}`}><span className={`studio-change is-${change.kind}`}>{change.kind}</span>
                        <span>{change.label}</span>
                        {change.after && <q>{change.after.slice(0, 240)}</q>}
                        {!change.after && change.before && <q className="studio-change-before">{change.before.slice(0, 240)}</q>}
                      </li>)}</ul>
                    <ProposalActions proposal={detail} story={story} tenantId={tenantId} projectId={projectId} canWrite={canWrite} />
                    {detail.status === "invalid" && <p className="studio-error">The assistant's change didn't fit the story's rules
                      ({detail.diagnostics.slice(0, 3).map(item => `${item.code.replaceAll("_", " ")} at ${item.location}`).join("; ")}).
                      Ask again or rephrase.</p>}
                    {detail.warnings.length > 0 && <p className="studio-hint">Some scenes would be unreachable or loop; review the map after accepting.</p>}
                    <div className="studio-actions">
                      {canWrite && detail.status === "ready" && <>
                        <button type="button" className="studio-primary" aria-disabled={dirty || deciding !== null}
                          onClick={() => accept(detail)}>{deciding === detail.id ? "Accepting…" : "Accept"}</button>
                        <button type="button" className="studio-secondary" aria-disabled={deciding !== null}
                          onClick={() => reject(detail)}>Reject</button>
                        <button type="button" className="studio-link" onClick={() => compose(`About "${detail.summary}": `)}>Refine</button></>}
                      {detail.accepted_revision_id && <>
                        <button type="button" className="studio-link" onClick={onOpenEditor}>Open in the editor</button>
                        <button type="button" className="studio-link" onClick={() => onInspect(detail.accepted_revision_id!)}>View accepted revision</button></>}
                    </div>
                    {canWrite && detail.status === "ready" && dirty
                      && <p className="studio-hint">Save or undo your unsaved edits before accepting.</p>}
                  </> : <p className="studio-hint">Loading the proposed changes…</p>}
                </section>}
              </div>
            </li>;
          })}</ol>
        </div>
      </div>
      {canWrite ? <form className="assistant-composer" onSubmit={send}>
        {dirty && <div className="studio-notice studio-release-dirty"><span>Save your changes so the assistant sees them.</span>
          <button type="button" className="studio-secondary" aria-disabled={saving} onClick={() => { if (!saving) void onSave(); }}>
            {saving ? "Saving…" : "Save revision"}</button></div>}
        <div className="assistant-input">
          <label className="studio-visually-hidden" htmlFor="assistant-message">Message the assistant</label>
          <textarea id="assistant-message" ref={composer} rows={1} value={text} maxLength={8000}
            placeholder="Describe a scene, a choice or a question…"
            onChange={event => { setText(event.target.value); resize(); }}
            onKeyDown={event => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(); }
            }} />
          <button type="submit" className="studio-primary" aria-disabled={Boolean(blocker)}>{sending ? "Sending…" : "Send"}</button>
        </div>
        <div className="assistant-composer-foot">
          {target ? <span className="assistant-focus">Focused on scene <code>{target}</code>
            <button type="button" className="studio-link" onClick={() => setWithFocus(false)}>Clear</button></span>
            : focus && <button type="button" className="studio-link" onClick={() => setWithFocus(true)}>Focus on scene {focus}</button>}
          <small>{blocker && !dirty && text.trim() ? blocker : "Enter sends · Shift + Enter adds a line"}</small>
        </div>
      </form> : <p className="studio-notice assistant-readonly">Read-only access. You can read conversations but not ask for changes.</p>}
    </div>
  </section>;
}
