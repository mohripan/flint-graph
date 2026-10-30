import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { MutableRefObject } from "react";
import { ApiError, api } from "../lib/api";
import {
  activeTurn, assistantError, mergeTurns, prepareTurn, proposalChanges, proposalStatus, sendBlocker, turnStatus,
} from "./assistantModel";
import type { TurnIntent } from "./assistantModel";
import { releaseErrorMessage, useReleaseRequests } from "./releaseRequests";
import type { AssistantProposal, AssistantThread, AssistantTurn, NarrativeRevision, StoryDraft } from "./types";

function parsed(source: string): StoryDraft | null {
  try { return JSON.parse(source) as StoryDraft; } catch { return null; }
}
function conflictId(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const first = error.problem?.errors?.[0];
  return typeof first?.conflict_revision_id === "string" ? first.conflict_revision_id : null;
}

// Proposals are suggestions until accepted: accepting creates a normal saved revision
// on the server, and the editor then loads it. Nothing here edits the draft directly.
export function AssistantPanel({ tenantId, projectId, revision, focus, canWrite, dirty, saving, scopeRef,
  onSave, onAccepted, onConflict, onInspect, onClose, onAccessLost }: {
  tenantId: string; projectId: string; revision: NarrativeRevision; focus: string | null; canWrite: boolean;
  dirty: boolean; saving: boolean; scopeRef: MutableRefObject<(() => void) | null>;
  onSave: () => Promise<NarrativeRevision | null>; onAccepted: (revision: NarrativeRevision) => void;
  onConflict: (conflictRevisionId: string) => void; onInspect: (revisionId: string) => void;
  onClose: () => void; onAccessLost: () => void;
}) {
  const { run, invalidate } = useReleaseRequests(onAccessLost);
  useLayoutEffect(() => {
    scopeRef.current = invalidate;
    return () => { if (scopeRef.current === invalidate) scopeRef.current = null; };
  }, [scopeRef, invalidate]);
  const [threads, setThreads] = useState<AssistantThread[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const threadRef = useRef<string | null>(null);
  const [turns, setTurns] = useState<AssistantTurn[]>([]);
  const [proposals, setProposals] = useState<Record<string, AssistantProposal>>({});
  const [text, setText] = useState(""), [sending, setSending] = useState(false);
  const [deciding, setDeciding] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null), [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [visible, setVisible] = useState(() => document.visibilityState !== "hidden");
  const intent = useRef<TurnIntent | null>(null), threadKey = useRef<string | null>(null);
  const decisionKeys = useRef(new Map<string, string>()), composer = useRef<HTMLTextAreaElement>(null);
  const log = useRef<HTMLOListElement>(null), requested = useRef(new Map<string, string>());
  const story = useMemo(() => parsed(revision.story_json), [revision.story_json]);
  const active = activeTurn(turns);

  const loadTurns = useCallback((id: string) => {
    void run("turns", signal => api.listAssistantTurns(tenantId, projectId, id, { signal }), rows => {
      if (threadRef.current !== id) return;
      setTurns(current => mergeTurns(current, rows.filter(row => row.thread_id === id)));
    }, failure => setError(releaseErrorMessage(failure)));
  }, [run, tenantId, projectId]);
  const choose = useCallback((id: string | null) => {
    threadRef.current = id; setThreadId(id); setTurns([]); setProposals({}); setConflict(null);
    requested.current.clear();
    if (id) loadTurns(id);
  }, [loadTurns]);
  useEffect(() => {
    void run("threads", signal => api.listAssistantThreads(tenantId, projectId, { signal }), rows => {
      const own = rows.filter(row => row.project_id === projectId);
      setThreads(own);
      if (!threadRef.current && own[0]) choose(own[0].id);
    }, failure => setError(releaseErrorMessage(failure)));
  }, [run, tenantId, projectId, choose]);
  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== "hidden");
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  useEffect(() => {
    if (!threadId || !active || !visible) return;
    const timer = window.setTimeout(() => loadTurns(threadId), 2000);
    return () => window.clearTimeout(timer);
  }, [threadId, active, visible, turns, loadTurns]);
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
  useEffect(() => { log.current?.lastElementChild?.scrollIntoView({ block: "end" }); }, [turns.length]);

  const blocker = sendBlocker({ canWrite, dirty, saving, sending, active, text });
  function send(event?: React.FormEvent) {
    event?.preventDefault();
    if (blocker) return;
    setSending(true); setError(null); setNotice(null);
    const next = prepareTurn(intent.current, text.trim(), revision.id, focus);
    intent.current = next;
    void run("send", async signal => {
      let id = threadRef.current;
      if (!id) {
        threadKey.current ??= crypto.randomUUID();
        const created = await api.createAssistantThread(tenantId, projectId, "Story chat", threadKey.current, signal);
        id = created.id;
      }
      return { id, turn: await api.postAssistantTurn(tenantId, projectId, id, next, signal) };
    }, ({ id, turn }) => {
      intent.current = null; threadKey.current = null; setText("");
      if (threadRef.current !== id) {
        threadRef.current = id; setThreadId(id);
        setThreads(current => current.some(row => row.id === id) ? current
          : [{ id, tenant_id: tenantId, project_id: projectId, title: "Story chat", archived_at: null,
            created_at: turn.created_at, updated_at: turn.created_at }, ...current]);
      }
      setTurns(current => mergeTurns(current, [turn]));
    }, failure => {
      // The retained key makes a resend safe after an ambiguous failure.
      setError(failure instanceof ApiError && failure.status === 503 ? assistantError("assistant_unavailable")
        : releaseErrorMessage(failure));
    }, () => setSending(false));
  }
  function cancel(turn: AssistantTurn) {
    if (!threadId) return;
    void run(`cancel:${turn.id}`, signal => api.cancelAssistantTurn(tenantId, projectId, threadId, turn.id, signal),
      row => setTurns(current => mergeTurns(current, [row])), failure => setError(releaseErrorMessage(failure)));
  }
  function accept(proposal: AssistantProposal) {
    if (!canWrite || dirty || deciding) return;
    const key = decisionKeys.current.get(proposal.id) ?? crypto.randomUUID();
    decisionKeys.current.set(proposal.id, key);
    setDeciding(proposal.id); setError(null); setNotice(null); setConflict(null);
    void run("decide", signal => api.acceptAssistantProposal(tenantId, projectId, proposal.id, key, signal), saved => {
      decisionKeys.current.delete(proposal.id);
      setProposals(current => ({ ...current, [proposal.id]: { ...proposal, status: "accepted", accepted_revision_id: saved.id } }));
      setNotice(`Accepted. Your story is now revision ${saved.revision_number}.`);
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
  function refine(proposal: AssistantProposal) {
    setText(`About "${proposal.summary}": `);
    window.requestAnimationFrame(() => composer.current?.focus());
  }

  return <aside className="studio-assistant" aria-label="Story assistant">
    <header className="studio-assistant-head">
      <div><p className="studio-eyebrow">Assistant</p><h2>Write with the assistant</h2></div>
      <div className="studio-actions">
        {threads.length > 1 && <label className="studio-visually-hidden" htmlFor="assistant-thread">Conversation</label>}
        {threads.length > 1 && <select id="assistant-thread" className="studio-assistant-thread" value={threadId ?? ""}
          onChange={event => choose(event.target.value)}>
          {threads.map(row => <option key={row.id} value={row.id}>{row.title} · {new Date(row.created_at).toLocaleDateString()}</option>)}
        </select>}
        {canWrite && <button type="button" className="studio-link" disabled={sending} onClick={() => choose(null)}>New chat</button>}
        <button type="button" className="studio-secondary studio-assistant-close" onClick={onClose}>Close assistant</button>
      </div>
    </header>
    <div role="status" className="studio-assistant-live">{notice && <p className="studio-notice">{notice}</p>}</div>
    {error && <p className="studio-error" role="alert">{error}</p>}
    {conflict && <div className="studio-conflict"><strong>The story changed after this proposal.</strong>
      <p>It was kept as a conflict revision. Your current story is unchanged.</p>
      <button type="button" className="studio-secondary" onClick={() => onInspect(conflict)}>View conflict copy</button></div>}
    <ol ref={log} className="studio-chat">
      {turns.map(turn => {
        const detail = turn.proposal ? proposals[turn.proposal.id] : undefined;
        const status = turnStatus(turn);
        return <li key={turn.id} className="studio-chat-turn">
          <p className="studio-chat-user">{turn.request}</p>
          <div className="studio-chat-reply">
            {turn.reply && <p>{turn.reply}</p>}
            {status && <p className={turn.status === "failed" ? "studio-error" : "studio-hint"}>
              {turn.status === "failed" ? assistantError(turn.error_code) : status}</p>}
            {canWrite && activeTurn([turn]) && !turn.cancel_requested
              && <button type="button" className="studio-link" onClick={() => cancel(turn)}>Stop</button>}
            {turn.proposal && <section className="studio-proposal" aria-label="Proposed changes">
              <div className="studio-section-heading"><strong>{turn.proposal.summary}</strong>
                <span className={`studio-release-status is-${{ ready: "active", invalid: "failed", accepted: "ready",
                  rejected: "muted" }[detail?.status ?? turn.proposal.status]}`}>{proposalStatus(detail?.status ?? turn.proposal.status)}</span></div>
              {detail ? <>
                <ul className="studio-proposal-changes">{proposalChanges(story, detail.operations).map((change, index) =>
                  <li key={`${change.target}:${index}`}><span className={`studio-change is-${change.kind}`}>{change.kind}</span>
                    <span>{change.label}</span>
                    {change.after && <q>{change.after.slice(0, 160)}</q>}
                    {!change.after && change.before && <q className="studio-change-before">{change.before.slice(0, 160)}</q>}
                  </li>)}</ul>
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
                    <button type="button" className="studio-link" onClick={() => refine(detail)}>Refine</button></>}
                  {detail.accepted_revision_id && <button type="button" className="studio-link"
                    onClick={() => onInspect(detail.accepted_revision_id!)}>View accepted revision</button>}
                </div>
                {canWrite && detail.status === "ready" && dirty
                  && <p className="studio-hint">Save or undo your unsaved edits before accepting.</p>}
              </> : <p className="studio-hint">Loading the proposed changes…</p>}
            </section>}
          </div>
        </li>;
      })}
    </ol>
    {!turns.length && <p className="studio-empty">Describe a scene, a choice or a twist. The assistant proposes changes;
      nothing changes until you accept.</p>}
    {canWrite ? <form className="studio-composer" onSubmit={send}>
      <label className="studio-field">Message the assistant
        <textarea ref={composer} rows={3} value={text} maxLength={8000} placeholder="Add a scene where Oren refuses to help…"
          onChange={event => setText(event.target.value)}
          onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") send(); }} />
        <small>{focus ? `Focused on scene ${focus}. ` : ""}Ctrl/⌘ + Enter sends.</small></label>
      {dirty && <div className="studio-notice studio-release-dirty"><span>Save your changes so the assistant sees them.</span>
        <button type="button" className="studio-secondary" aria-disabled={saving} onClick={() => { if (!saving) void onSave(); }}>
          {saving ? "Saving…" : "Save revision"}</button></div>}
      <div className="studio-actions"><button type="submit" className="studio-primary" aria-disabled={Boolean(blocker)}>
        {sending ? "Sending…" : "Send"}</button>
        {blocker && !dirty && text.trim() && <span className="studio-hint">{blocker}</span>}</div>
    </form> : <p className="studio-notice">Read-only access. You can read conversations but not ask for changes.</p>}
  </aside>;
}
