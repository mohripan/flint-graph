import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { streamQueryRun } from "../lib/stream";
import { queryFailureMessage } from "../lib/queryOutcome";
import type {
  AnswerProvenance,
  QueryDiagnostics,
  QueryRunEvent,
  QueryRunResponse,
  SearchReadiness,
} from "../lib/types";
import { useWorkspace } from "../lib/workspace";
import { Button, Card, Spinner } from "../components/ui";
import { ProgressTrail } from "../components/ProgressTrail";
import { CitationsPanel } from "../components/CitationsPanel";
import { QueryHistory } from "../components/QueryHistory";

type Phase = "idle" | "loading" | "streaming" | "done" | "error";

export function AskPage() {
  const { workspace } = useWorkspace();
  const tenantId = workspace!.id;

  const [input, setInput] = useState("");
  const [question, setQuestion] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [seenEvents, setSeenEvents] = useState<string[]>([]);
  const [finalText, setFinalText] = useState<string | null>(null);
  const [abstainReason, setAbstainReason] = useState<string | null>(null);
  const [provenance, setProvenance] = useState<AnswerProvenance | null>(null);
  const [readiness, setReadiness] = useState<SearchReadiness | null>(null);
  const [diagnostics, setDiagnostics] = useState<QueryDiagnostics | null>(null);
  const [historyRevision, setHistoryRevision] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [highlightId, setHighlightId] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const readinessAbortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  const refreshReadiness = useCallback(async () => {
    readinessAbortRef.current?.abort();
    const controller = new AbortController();
    readinessAbortRef.current = controller;
    try {
      const nextReadiness = await api.getSearchReadiness(tenantId, controller.signal);
      if (!mountedRef.current || controller.signal.aborted) return;
      setReadiness(nextReadiness);
    } catch {
      if (mountedRef.current && !controller.signal.aborted) setReadiness(null);
    }
  }, [tenantId]);

  useEffect(() => {
    mountedRef.current = true;
    void refreshReadiness();
    const id = window.setInterval(() => void refreshReadiness(), 5000);
    return () => {
      mountedRef.current = false;
      window.clearInterval(id);
      abortRef.current?.abort();
      readinessAbortRef.current?.abort();
    };
  }, [refreshReadiness]);

  function clearAnswer() {
    setSeenEvents([]);
    setFinalText(null);
    setAbstainReason(null);
    setProvenance(null);
    setDiagnostics(null);
    setHighlightId(null);
    setError(null);
  }

  function newQuestion() {
    abortRef.current?.abort();
    setInput("");
    setQuestion("");
    setSelectedId(null);
    setPhase("idle");
    clearAnswer();
  }

  async function reopen(saved: QueryRunResponse) {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    clearAnswer();
    setInput("");
    setQuestion(saved.query_text);
    setSelectedId(saved.id);
    setPhase("loading");
    try {
      const inspected = await api.getQueryRun(tenantId, saved.id, controller.signal);
      if (!mountedRef.current || controller.signal.aborted) return;
      setQuestion(inspected.query_text);
      setDiagnostics(inspected.query_diagnostics);
      if (inspected.status !== "completed") {
        setError(inspected.status === "queued" || inspected.status === "running"
          ? `This saved question is ${inspected.status}. Refresh history to check its status.`
          : queryFailureMessage(inspected));
        setPhase("error");
        return;
      }
      setFinalText(inspected.answer_text);
      try {
        const prov = await api.getAnswerProvenance(tenantId, saved.id, controller.signal);
        if (!mountedRef.current || controller.signal.aborted) return;
        setProvenance(prov);
        setFinalText(prov.answer_text ?? inspected.answer_text);
        if (prov.abstained) setAbstainReason(prov.abstain_reason ?? "Not enough supporting evidence.");
      } catch {
        if (!mountedRef.current || controller.signal.aborted) return;
        setError("The saved result is available, but its sources could not be loaded. Reopen the question to retry.");
      }
      setPhase("done");
    } catch (err) {
      if (!mountedRef.current || controller.signal.aborted) return;
      setError(err instanceof ApiError ? err.message : "Could not load this saved question. Reopen it to retry.");
      setPhase("error");
    }
  }

  const ask = useCallback(async () => {
    const q = input.trim();
    if (!q || phase === "streaming" || phase === "loading") return;
    if (readiness && !readiness.ready) {
      setError(readinessMessage(readiness));
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setQuestion(q);
    setSelectedId(null);
    setPhase("streaming");
    setSeenEvents([]);
    setFinalText(null);
    setAbstainReason(null);
    setProvenance(null);
    setDiagnostics(null);
    setError(null);
    setHighlightId(null);

    try {
      const run = await api.createQueryRun(tenantId, q, controller.signal);
      if (!mountedRef.current || controller.signal.aborted) return;
      setSelectedId(run.id);
      await streamQueryRun(tenantId, run.id, {
        signal: controller.signal,
        onEvent: (event: QueryRunEvent) => {
          if (!mountedRef.current || controller.signal.aborted) return;
          setSeenEvents((prev) => [...prev, event.event_type]);
          handleEvent(event);
        },
      });

      const inspected = await api.getQueryRun(tenantId, run.id, controller.signal);
      if (!mountedRef.current || controller.signal.aborted) return;
      setDiagnostics(inspected.query_diagnostics);
      setHistoryRevision((previous) => previous + 1);
      const failure = queryFailureMessage(inspected);
      if (failure) {
        setPhase("error");
        setError(failure);
        await refreshReadiness();
        return;
      }

      // Pull authoritative citations + support once the run is complete.
      if (inspected.status === "completed") {
        try {
          const prov = await api.getAnswerProvenance(tenantId, run.id, controller.signal);
          if (!mountedRef.current || controller.signal.aborted) return;
          setProvenance(prov);
          if (prov.answer_text) setFinalText(prov.answer_text);
          if (prov.abstained) setAbstainReason(prov.abstain_reason ?? "Not enough supporting evidence.");
        } catch {
          /* provenance is best-effort; the streamed answer still shows */
        }
      }
      await refreshReadiness();
      if (!mountedRef.current || controller.signal.aborted) return;
      setPhase("done");
    } catch (err) {
      if (!mountedRef.current || controller.signal.aborted) return;
      setPhase("error");
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not reach the FlintGraph API. Is the backend running?",
      );
    }

    function handleEvent(event: QueryRunEvent) {
      const p = event.payload as Record<string, unknown>;
      switch (event.event_type) {
        case "answer.delta": {
          const text = typeof p.text === "string" ? p.text : "";
          if (p.provisional === false) {
            setFinalText(text);
          }
          break;
        }
        case "answer.finalized": {
          if (typeof p.answer_text === "string") setFinalText(p.answer_text);
          break;
        }
        case "answer.abstained": {
          setAbstainReason(
            typeof p.reason === "string" ? p.reason : "Not enough supporting evidence.",
          );
          break;
        }
      }
    }
  }, [input, phase, readiness, refreshReadiness, tenantId]);

  const answerText = finalText;
  const showAnswer = phase !== "idle";

  return (
    <section aria-label="Ask workspace" className="h-full overflow-y-auto">
    <div className="mx-auto flex min-h-full max-w-6xl flex-col gap-6 p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
        <h1 className="text-xl font-semibold text-slate-900">Ask a question</h1>
        <p className="text-sm text-slate-500">
          Answers are drawn only from the documents in your workspace, with sources.
        </p>
        </div>
        <Button variant="secondary" onClick={newQuestion} disabled={phase === "streaming"}>New question</Button>
      </div>

      <ReadinessBanner readiness={readiness} />

      <div>
        <QueryHistory tenantId={tenantId} revision={historyRevision} selectedId={selectedId}
          disabled={phase === "streaming"} onSelect={(run) => void reopen(run)} />
        <button onClick={() => setHistoryRevision((previous) => previous + 1)}
          className="mt-2 text-xs text-slate-500 underline underline-offset-2 hover:text-brand-700 focus-visible:outline-2 focus-visible:outline-brand-500">
          Refresh history
        </button>
      </div>

      {/* Composer */}
      <Card className="p-4">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ask();
          }}
          rows={3}
          placeholder="e.g. Where is Acme headquartered?"
          aria-label="Your question"
          className="w-full resize-none rounded-lg border border-slate-200 p-3 text-sm focus:border-brand-500 focus:outline-hidden focus:ring-1 focus:ring-brand-500"
        />
        <div className="mt-3 flex items-center justify-between">
          <span className="text-xs text-slate-400">
            Press <kbd className="rounded border border-slate-300 px-1">⌘/Ctrl</kbd> +{" "}
            <kbd className="rounded border border-slate-300 px-1">Enter</kbd> to ask
          </span>
          <Button
            onClick={ask}
            disabled={phase === "streaming" || phase === "loading" || !input.trim() || readiness?.ready === false}
          >
            {phase === "streaming" && <Spinner className="h-4 w-4" />}
            {phase === "streaming" ? "Thinking…" : "Ask"}
          </Button>
        </div>
      </Card>

      {showAnswer && (
        <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
          {/* Answer column */}
          <div className="flex min-w-0 flex-col gap-4">
            <p className="break-words text-sm font-medium text-slate-500">{question}</p>
            {phase === "loading" && <p role="status" className="text-sm text-slate-500">Opening saved result…</p>}

            {phase === "streaming" && !answerText && (
              <Card className="p-5">
                <ProgressTrail seenEvents={seenEvents} done={false} />
              </Card>
            )}

            {error && (
              <Card className="border-red-200 bg-red-50 p-5 text-sm text-red-700">
                {error}
              </Card>
            )}

            {abstainReason && (
              <Card className="border-amber-200 bg-amber-50 p-5">
                <p className="mb-1 text-sm font-semibold text-amber-800">
                  {abstainReason === "ambiguous_financial_scope"
                    ? "Please narrow your question"
                    : "Not enough evidence to answer"}
                </p>
                <p className="text-sm text-amber-700">
                  {abstainReason === "ambiguous_financial_scope"
                    ? "Several workspace reports could match this question."
                    : abstainReason}
                </p>
              </Card>
            )}

            {answerText && (
              <section aria-label="Answer">
              <Card className="p-6">
                <AnswerText
                  text={answerText}
                  highlightId={highlightId}
                  onHoverCitation={setHighlightId}
                  streaming={phase === "streaming"}
                />
              </Card>
              </section>
            )}
            {diagnostics && <DiagnosticsPanel diagnostics={diagnostics} />}
          </div>

          {/* Sources column */}
          <aside aria-label="Sources" className="min-w-0">
            {provenance ? (
              <CitationsPanel
                provenance={provenance}
                highlightId={highlightId}
                onHover={setHighlightId}
              />
            ) : phase === "streaming" ? (
              <p className="text-sm text-slate-400">Sources will appear here…</p>
            ) : null}
          </aside>
        </div>
      )}

      <p className="text-xs text-slate-400">
        Tip: if answers look like placeholder text, the backend is running with
        deterministic (stub) models. See the frontend README to enable real answers.
      </p>
    </div>
    </section>
  );
}

function ReadinessBanner({ readiness }: { readiness: SearchReadiness | null }) {
  if (!readiness) {
    return (
      <Card className="border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
        Checking workspace search readiness…
      </Card>
    );
  }
  if (readiness.ready) {
    return (
      <Card className="border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
        {readiness.completed_coverage_count} document version
        {readiness.completed_coverage_count === 1 ? " is" : "s are"} searchable.
      </Card>
    );
  }
  return (
    <Card className="border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
      {readinessMessage(readiness)}
    </Card>
  );
}

function DiagnosticsPanel({ diagnostics }: { diagnostics: QueryDiagnostics }) {
  const retrievers = diagnostics.retriever_candidate_counts ?? {};
  const support = diagnostics.support_status_counts ?? {};
  return (
    <details data-diagnostics className="rounded-xl border border-slate-200 bg-white p-5">
      <summary className="cursor-pointer text-sm font-semibold text-slate-800 focus-visible:outline-2 focus-visible:outline-brand-500">Run diagnostics</summary>
      <div className="mt-3">
      <div className="grid gap-3 text-xs text-slate-600 sm:grid-cols-2">
        <Metric label="Retrieved" value={diagnostics.retrieved_candidate_count ?? 0} />
        <Metric label="Context records" value={diagnostics.context_record_count ?? 0} />
        <Metric label="Fused" value={diagnostics.fused_candidate_count ?? 0} />
        <Metric label="Reranked" value={diagnostics.reranked_candidate_count ?? 0} />
        <Metric label="Skipped context" value={diagnostics.skipped_context_count ?? 0} />
        <Metric label="Tokens" value={diagnostics.context_token_count ?? 0} />
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-xs">
        {Object.entries(retrievers).map(([name, count]) => (
          <span key={name} className="rounded bg-slate-100 px-2 py-1 text-slate-600">
            {name}: {count}
          </span>
        ))}
        {Object.entries(support).map(([name, count]) => (
          <span key={name} className="rounded bg-emerald-50 px-2 py-1 text-emerald-700">
            {name}: {count}
          </span>
        ))}
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Answer: {diagnostics.answer_provider ?? "unknown"} · Support:{" "}
        {diagnostics.support_provider ?? "unknown"}
      </p>
      </div>
    </details>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-slate-100 px-3 py-2">
      <p className="text-slate-400">{label}</p>
      <p className="text-base font-semibold text-slate-800">{value}</p>
    </div>
  );
}

function readinessMessage(readiness: SearchReadiness): string {
  switch (readiness.reason) {
    case "no_active_index":
      return "No active retrieval index is available yet.";
    case "no_documents":
      return "Add a document before asking a question.";
    case "indexing_in_progress":
      return "Documents are still being indexed. Questions will be available once indexing completes.";
    case "indexing_failed":
      return "Indexing failed for the current documents. Check the Documents page for details.";
    default:
      return "No searchable document content is available yet.";
  }
}

// Renders answer text, turning [c1]-style markers into interactive chips.
function AnswerText({
  text,
  highlightId,
  onHoverCitation,
  streaming,
}: {
  text: string;
  highlightId: string | null;
  onHoverCitation: (id: string | null) => void;
  streaming: boolean;
}) {
  const parts = text.split(/(\[[^\]\s]+\])/g);
  return (
    <div className="prose prose-slate max-w-none text-[15px] leading-7 text-slate-800 [overflow-wrap:anywhere]">
      <p className="whitespace-pre-wrap">
        {parts.map((part, i) => {
          const marker = part.match(/^\[([^\]\s]+)\]$/);
          if (marker) {
            const id = marker[1];
            return (
              <button
                key={i}
                onMouseEnter={() => onHoverCitation(id)}
                onMouseLeave={() => onHoverCitation(null)}
                onClick={() =>
                  document
                    .getElementById(`citation-${id}`)
                    ?.scrollIntoView({ behavior: "smooth", block: "center" })
                }
                className={`mx-0.5 inline-flex -translate-y-0.5 items-center rounded px-1.5 py-0.5 align-middle font-mono text-xs font-semibold transition ${
                  highlightId === id
                    ? "bg-brand-600 text-white"
                    : "bg-brand-50 text-brand-700 hover:bg-brand-100"
                }`}
              >
                {id}
              </button>
            );
          }
          return <span key={i}>{part}</span>;
        })}
        {streaming && (
          <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-brand-400 align-middle" />
        )}
      </p>
    </div>
  );
}
