import type { AnswerProvenance, CitationProvenance } from "../lib/types";
import { Card } from "./ui";

const SUPPORT_STYLES: Record<string, string> = {
  supported: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  partial: "bg-amber-50 text-amber-700 ring-amber-200",
  unsupported: "bg-red-50 text-red-700 ring-red-200",
};

function SupportBadge({ status }: { status: string }) {
  const style = SUPPORT_STYLES[status] ?? "bg-slate-100 text-slate-600 ring-slate-200";
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${style}`}
    >
      {status}
    </span>
  );
}

export function CitationsPanel({
  provenance,
  highlightId,
  onHover,
}: {
  provenance: AnswerProvenance;
  highlightId?: string | null;
  onHover?: (id: string | null) => void;
}) {
  const { citations, supported_claim_count, unsupported_claim_count, answer_provider } =
    provenance;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span className="font-medium text-slate-700">
          {citations.length} source{citations.length === 1 ? "" : "s"}
        </span>
        <span className="text-slate-300">•</span>
        <span>{supported_claim_count} supported</span>
        {unsupported_claim_count > 0 && (
          <>
            <span className="text-slate-300">•</span>
            <span className="text-red-600">{unsupported_claim_count} unsupported</span>
          </>
        )}
        {answer_provider && (
          <>
            <span className="text-slate-300">•</span>
            <span>via {answer_provider}</span>
          </>
        )}
      </div>

      {citations.length === 0 ? (
        <p className="text-sm text-slate-400">No sources were cited for this answer.</p>
      ) : (
        <ul className="space-y-2">
          {citations.map((c) => (
            <CitationItem
              key={c.citation_id}
              citation={c}
              highlighted={highlightId === c.citation_id}
              onHover={onHover}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function CitationItem({
  citation,
  highlighted,
  onHover,
}: {
  citation: CitationProvenance;
  highlighted: boolean;
  onHover?: (id: string | null) => void;
}) {
  const support = citation.claims[0]?.support_status;
  const title =
    (citation.metadata?.title as string | undefined) ??
    citation.source_ids?.document_id ??
    citation.context_id;

  return (
    <li
      id={`citation-${citation.citation_id}`}
      onMouseEnter={() => onHover?.(citation.citation_id)}
      onMouseLeave={() => onHover?.(null)}
    >
      <Card
        className={`p-3 transition ${
          highlighted ? "ring-2 ring-brand-400" : ""
        }`}
      >
        <div className="mb-1.5 flex items-center justify-between gap-2">
          <span className="inline-flex min-w-0 flex-1 items-center gap-1.5">
            <span className="shrink-0 rounded bg-brand-50 px-1.5 py-0.5 font-mono text-xs font-semibold text-brand-700">
              {citation.citation_id}
            </span>
            <span className="truncate text-xs font-medium text-slate-600" title={title}>
              {title}
            </span>
          </span>
          {support && <SupportBadge status={support} />}
        </div>
        <p className="line-clamp-4 text-sm leading-relaxed text-slate-600 [overflow-wrap:anywhere]">
          {citation.text}
        </p>
      </Card>
    </li>
  );
}
