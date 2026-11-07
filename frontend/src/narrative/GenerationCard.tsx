import { useAccess } from "../site/accessContext";
import { quoteView } from "../site/creditsModel";
import { cardLabel, quoteParts } from "./assistantActions";
import { GpuNotice } from "./GpuNotice";
import { actionGpuKind } from "./gpuModel";
import type { ActionStatus, ActionQuote } from "./assistantActions";

const OPENS: Record<string, string> = { assets: "Assets", characters: "Characters" };

// What the assistant would like to generate, and what it costs. Nothing runs until Generate
// is pressed (ADR 0068); the server wrote all of this, including the price items it will charge.
export function GenerationCard({ quote, status, note, busy, error, onGenerate, onCancel, onOpen }: {
  quote: ActionQuote; status: ActionStatus; note: { text: string; bad: boolean } | null; busy: boolean; error: string | undefined;
  onGenerate: () => void; onCancel: () => void; onOpen?: (panel: "assets" | "characters") => void;
}) {
  const price = quoteView(useAccess(), quoteParts(quote));
  const opens = quote.opens && OPENS[quote.opens] ? quote.opens as "assets" | "characters" : null;
  return <article className="assistant-gen-card" aria-label={`${quote.kind}, waiting for you to start it`}>
    <header className="assistant-gen-head">
      <small className="assistant-gen-kind">{quote.kind}</small>
      {price && <span className={`assistant-gen-cost ${price.over ? "is-over" : ""}`} data-credit-cost={price.text}>{price.text}</span>}
    </header>
    <p className="assistant-gen-title">{quote.title}</p>
    <p className="assistant-gen-facts">{quote.facts.map(fact => fact.text).join(" · ")}</p>
    {price?.over && <p className="assistant-gen-note is-bad" role="status">You don&rsquo;t have enough credits for this.</p>}
    {note && <p className={`assistant-gen-note ${note.bad ? "is-bad" : ""}`} role="status">{note.text}</p>}
    {error && <p className="assistant-gen-note is-bad" role="alert">{error}</p>}
    <GpuNotice kinds={[actionGpuKind(status.op)]} />
    <footer className="assistant-gen-foot">
      {opens && onOpen && <button type="button" className="assistant-gen-open" onClick={() => onOpen(opens)}>Adjust in {OPENS[opens]} <span aria-hidden="true">→</span></button>}
      <div className="assistant-gen-buttons">
        <button type="button" className="assistant-gen-cancel" disabled={busy} onClick={onCancel}>Cancel</button>
        <button type="button" className="assistant-gen-go" disabled={busy || status.needs_accept || Boolean(price?.over)}
          onClick={onGenerate}>{busy ? "Starting…" : cardLabel(status, quote)}</button>
      </div>
    </footer>
  </article>;
}
