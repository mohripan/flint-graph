import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { AnswerProvenance, ConversationTurn as Turn } from "../lib/types";
import { AnswerText, DiagnosticsPanel } from "./QueryResult";
import { CitationsPanel } from "./CitationsPanel";

export function ConversationTurn({ tenantId, turn, onAccessDenied, onInspectEvidence }: {
  tenantId: string; turn: Turn; onAccessDenied: () => void; onInspectEvidence: () => void;
}) {
  const { run } = turn;
  const [provenance, setProvenance] = useState<AnswerProvenance | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [focusedCitation, setFocusedCitation] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const details = useRef<HTMLDetailsElement | null>(null);
  const prefix = `${run.id}-`;
  useEffect(() => () => request.current?.abort(), [tenantId, run.id]);
  useEffect(() => {
    if (!provenance || !focusedCitation) return;
    const citation = document.getElementById(`${prefix}citation-${focusedCitation}`);
    citation?.focus({ preventScroll: true });
    citation?.scrollIntoView({
      block: "center", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    });
    setFocusedCitation(null);
  }, [provenance, focusedCitation, prefix]);

  async function loadSources() {
    if (provenance || (request.current && !request.current.signal.aborted)) return;
    const controller = new AbortController(); request.current = controller;
    setLoading(true); setError(null);
    try {
      const value = await api.getAnswerProvenance(tenantId, run.id, controller.signal);
      if (controller.signal.aborted) return;
      if (value.query_run_id !== run.id) throw new Error("Source response identity mismatch");
      setProvenance(value);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError("Sources could not be loaded. Close and reopen sources to retry.");
      if (err instanceof ApiError && [401, 403].includes(err.status)) onAccessDenied();
    } finally {
      if (!controller.signal.aborted) setLoading(false);
      controller.abort();
    }
  }
  const reason = run.query_diagnostics?.abstention_reason;
  const clarified = reason === "ambiguous_conversation_scope" || reason === "ambiguous_financial_scope";
  const partial = (run.query_diagnostics?.support_status_counts?.partial ?? 0) > 0 || (run.query_diagnostics?.support_status_counts?.unsupported ?? 0) > 0;
  const outcome = run.status !== "completed" ? run.status : clarified ? "Clarification" : reason ? "Not enough evidence" : partial ? "Partly supported" : "Completed";

  return <article aria-label={`Turn ${turn.turn_number}`} className="space-y-4">
    <div className="ml-auto w-fit max-w-[90%] rounded-2xl rounded-br-md bg-brand-50 px-4 py-3 text-sm leading-6 text-slate-800 [overflow-wrap:anywhere]">
      <p className="mb-1 text-xs font-medium text-brand-700">You</p><p className="whitespace-pre-wrap">{run.query_text}</p>
    </div>
    <div className="text-[15px] leading-7 text-slate-800 [overflow-wrap:anywhere]">
      <p className="mb-2 text-xs font-semibold text-slate-500">FlintGraph · {outcome}</p>
      <AnswerText text={run.answer_text ?? run.error_message ?? (run.status === "cancelled" ? "This turn was cancelled before a final answer." : "No final answer is available yet.")}
        highlightId={highlight} onHoverCitation={setHighlight} streaming={false}
        citationPrefix={prefix} citationIds={(run.answer_citations ?? []).map((citation) => String(citation.citation_id))}
        onClickCitation={(id) => { onInspectEvidence(); if (details.current) details.current.open = true; setFocusedCitation(id); void loadSources(); }} />
      {run.metadata?.conversation_context?.mode === "resolved" && <p className="mt-3 border-l-2 border-brand-200 pl-3 text-xs leading-5 text-slate-500">Interpreted as: {run.metadata.conversation_context.resolved_query}</p>}
      {run.status === "completed" && <details ref={details} className="mt-4 rounded-lg border border-slate-200 px-3 py-2 text-sm"
        onToggle={(event) => { if (event.currentTarget.open) { onInspectEvidence(); void loadSources(); } else { request.current?.abort(); setLoading(false); } }}>
        <summary aria-label={`Sources for turn ${turn.turn_number}`} className="cursor-pointer text-xs font-medium text-brand-700 focus-visible:outline-2 focus-visible:outline-brand-500">
          Sources · {(run.answer_citations ?? []).length} citation{run.answer_citations?.length === 1 ? "" : "s"}
        </summary>
        <div className="mt-3">
          {loading && <p role="status" className="text-xs text-slate-500">Loading authorized sources…</p>}
          {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
          {provenance && <CitationsPanel provenance={provenance} highlightId={highlight} onHover={setHighlight} idPrefix={prefix} fullExcerpts />}
        </div>
      </details>}
      {run.query_diagnostics && <div className="mt-3"><DiagnosticsPanel diagnostics={run.query_diagnostics} /></div>}
    </div>
  </article>;
}
