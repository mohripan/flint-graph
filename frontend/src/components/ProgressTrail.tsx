import { Spinner } from "./ui";

// Maps raw query-run event types onto a small set of user-friendly phases.
const PHASES: { key: string; label: string; events: string[] }[] = [
  { key: "understand", label: "Understanding your question", events: ["query.started", "query.classified", "entities.linked"] },
  { key: "search", label: "Searching your documents", events: ["retrieval.started", "retrieval.progress", "retrieval.completed"] },
  { key: "rank", label: "Ranking the best passages", events: ["fusion.completed", "rerank.completed"] },
  { key: "context", label: "Gathering supporting context", events: ["context.packed"] },
  { key: "write", label: "Writing the answer", events: ["answer.delta", "answer.citation", "answer.finalized"] },
  { key: "verify", label: "Checking the answer is supported", events: ["support.checked", "answer.abstained"] },
];

const EVENT_PHASE = new Map<string, number>();
PHASES.forEach((phase, i) => phase.events.forEach((e) => EVENT_PHASE.set(e, i)));

export function ProgressTrail({
  seenEvents,
  done,
}: {
  seenEvents: string[];
  done: boolean;
}) {
  let reached = -1;
  for (const e of seenEvents) {
    const idx = EVENT_PHASE.get(e);
    if (idx !== undefined && idx > reached) reached = idx;
  }

  return (
    <ol className="space-y-2.5">
      {PHASES.map((phase, i) => {
        const isDone = done || i < reached || (i === reached && done);
        const isActive = !done && i === reached;
        const isPending = i > reached;
        return (
          <li key={phase.key} className="flex items-center gap-3 text-sm">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center">
              {isActive ? (
                <Spinner className="h-4 w-4 text-brand-600" />
              ) : isDone ? (
                <CheckIcon className="h-5 w-5 text-emerald-500" />
              ) : (
                <span className="h-2 w-2 rounded-full bg-slate-300" />
              )}
            </span>
            <span
              className={
                isPending
                  ? "text-slate-400"
                  : isActive
                    ? "font-medium text-slate-900"
                    : "text-slate-600"
              }
            >
              {phase.label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function CheckIcon({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className={className} aria-hidden="true">
      <path
        fillRule="evenodd"
        d="M16.7 5.3a1 1 0 010 1.4l-7.5 7.5a1 1 0 01-1.4 0L3.3 9.7a1 1 0 011.4-1.4l3.3 3.3 6.8-6.8a1 1 0 011.4 0z"
        clipRule="evenodd"
      />
    </svg>
  );
}
