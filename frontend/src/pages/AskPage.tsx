import { useCallback, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { streamQueryRun } from "../lib/stream";
import type { AnswerProvenance, QueryRunEvent } from "../lib/types";
import { useWorkspace } from "../lib/workspace";
import { Button, Card, Spinner } from "../components/ui";
import { ProgressTrail } from "../components/ProgressTrail";
import { CitationsPanel } from "../components/CitationsPanel";

type Phase = "idle" | "streaming" | "done" | "error";

// Provisional deltas may arrive as either incremental chunks or a growing
// cumulative string. Detect and merge either way.
function mergeDelta(prev: string, incoming: string): string {
  if (!incoming) return prev;
  if (incoming.startsWith(prev) && incoming.length >= prev.length) return incoming;
  return prev + incoming;
}

export function AskPage() {
  const { workspace } = useWorkspace();
  const tenantId = workspace!.id;

  const [input, setInput] = useState("");
  const [question, setQuestion] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [seenEvents, setSeenEvents] = useState<string[]>([]);
  const [streamedText, setStreamedText] = useState("");
  const [finalText, setFinalText] = useState<string | null>(null);
  const [abstainReason, setAbstainReason] = useState<string | null>(null);
  const [provenance, setProvenance] = useState<AnswerProvenance | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [highlightId, setHighlightId] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  const ask = useCallback(async () => {
    const q = input.trim();
    if (!q || phase === "streaming") return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setQuestion(q);
    setPhase("streaming");
    setSeenEvents([]);
    setStreamedText("");
    setFinalText(null);
    setAbstainReason(null);
    setProvenance(null);
    setError(null);

    let completed = false;
    let failed = false;

    try {
      const run = await api.createQueryRun(tenantId, q);
      await streamQueryRun(tenantId, run.id, {
        signal: controller.signal,
        onEvent: (event: QueryRunEvent) => {
          setSeenEvents((prev) => [...prev, event.event_type]);
          handleEvent(event);
          if (event.event_type === "query.completed") completed = true;
          if (event.event_type === "query.failed") failed = true;
        },
      });

      if (failed) {
        setPhase("error");
        setError("The query could not be answered. Please try again.");
        return;
      }

      // Pull authoritative citations + support once the run is complete.
      if (completed) {
        try {
          const prov = await api.getAnswerProvenance(tenantId, run.id);
          setProvenance(prov);
          if (prov.answer_text) setFinalText(prov.answer_text);
          if (prov.abstained) setAbstainReason(prov.abstain_reason ?? "Not enough supporting evidence.");
        } catch {
          /* provenance is best-effort; the streamed answer still shows */
        }
      }
      setPhase("done");
    } catch (err) {
      if (controller.signal.aborted) return;
      setPhase("error");
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not reach the AtlasRAG API. Is the backend running?",
      );
    }

    function handleEvent(event: QueryRunEvent) {
      const p = event.payload as Record<string, unknown>;
      switch (event.event_type) {
        case "answer.delta": {
          const text = typeof p.text === "string" ? p.text : "";
          if (p.provisional === false) {
            setFinalText(text);
          } else {
            setStreamedText((prev) => mergeDelta(prev, text));
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
  }, [input, phase, tenantId]);

  const answerText = finalText ?? streamedText;
  const showAnswer = phase !== "idle";

  return (
    <div className="mx-auto flex h-full max-w-6xl flex-col gap-6 p-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Ask a question</h1>
        <p className="text-sm text-slate-500">
          Answers are drawn only from the documents in your workspace, with sources.
        </p>
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
          className="w-full resize-none rounded-lg border border-slate-200 p-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
        <div className="mt-3 flex items-center justify-between">
          <span className="text-xs text-slate-400">
            Press <kbd className="rounded border border-slate-300 px-1">⌘/Ctrl</kbd> +{" "}
            <kbd className="rounded border border-slate-300 px-1">Enter</kbd> to ask
          </span>
          <Button onClick={ask} disabled={phase === "streaming" || !input.trim()}>
            {phase === "streaming" && <Spinner className="h-4 w-4" />}
            {phase === "streaming" ? "Thinking…" : "Ask"}
          </Button>
        </div>
      </Card>

      {showAnswer && (
        <div className="grid flex-1 grid-cols-1 gap-6 overflow-hidden lg:grid-cols-[1fr_340px]">
          {/* Answer column */}
          <div className="flex min-h-0 flex-col gap-4">
            <p className="text-sm font-medium text-slate-500">{question}</p>

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
                  Not enough evidence to answer
                </p>
                <p className="text-sm text-amber-700">{abstainReason}</p>
              </Card>
            )}

            {answerText && (
              <Card className="scroll-thin min-h-0 flex-1 overflow-y-auto p-6">
                <AnswerText
                  text={answerText}
                  highlightId={highlightId}
                  onHoverCitation={setHighlightId}
                  streaming={phase === "streaming"}
                />
              </Card>
            )}
          </div>

          {/* Sources column */}
          <div className="scroll-thin min-h-0 overflow-y-auto">
            {provenance ? (
              <CitationsPanel
                provenance={provenance}
                highlightId={highlightId}
                onHover={setHighlightId}
              />
            ) : phase === "streaming" ? (
              <p className="text-sm text-slate-400">Sources will appear here…</p>
            ) : null}
          </div>
        </div>
      )}

      <p className="text-xs text-slate-400">
        Tip: if answers look like placeholder text, the backend is running with
        deterministic (stub) models. See the frontend README to enable real answers.
      </p>
    </div>
  );
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
    <div className="prose prose-slate max-w-none text-[15px] leading-7 text-slate-800">
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
