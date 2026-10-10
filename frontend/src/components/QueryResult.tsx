import type { QueryDiagnostics } from "../lib/types";

export function DiagnosticsPanel({ diagnostics }: { diagnostics: QueryDiagnostics }) {
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

// Renders answer text, turning [c1]-style markers into interactive chips.
export function AnswerText({
  text,
  highlightId,
  onHoverCitation,
  streaming,
  citationPrefix = "",
  citationIds,
  onClickCitation,
}: {
  text: string;
  highlightId: string | null;
  onHoverCitation: (id: string | null) => void;
  streaming: boolean;
  citationPrefix?: string;
  citationIds?: string[];
  onClickCitation?: (id: string) => void;
}) {
  const parts = text.split(/(\[[^\]\s]+\])/g);
  return (
    <div className="prose prose-slate max-w-none text-[15px] leading-7 text-slate-800 [overflow-wrap:anywhere]">
      <p className="whitespace-pre-wrap">
        {parts.map((part, i) => {
          const marker = part.match(/^\[([^\]\s]+)\]$/);
          if (marker && (!citationIds || citationIds.includes(marker[1]))) {
            const id = marker[1];
            return (
              <button
                key={i}
                onMouseEnter={() => onHoverCitation(id)}
                onMouseLeave={() => onHoverCitation(null)}
                onClick={() => onClickCitation ? onClickCitation(id) :
                  document
                    .getElementById(`${citationPrefix}citation-${id}`)
                    ?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" })
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
