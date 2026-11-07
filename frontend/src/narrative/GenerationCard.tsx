import type { ReactNode } from "react";
import { useAccess } from "../site/accessContext";
import { quoteView } from "../site/creditsModel";
import { cardLabel, quoteParts } from "./assistantActions";
import { GpuNotice } from "./GpuNotice";
import { actionGpuKind } from "./gpuModel";
import type { ActionStatus, ActionQuote } from "./assistantActions";

const ICONS: Record<string, ReactNode> = {
  model: <><rect x="4" y="4" width="16" height="16" rx="3" /><path d="M9 9h6v6H9z" /></>,
  count: <><rect x="4" y="4" width="7" height="7" rx="1.5" /><rect x="13" y="4" width="7" height="7" rx="1.5" /><rect x="4" y="13" width="7" height="7" rx="1.5" /><rect x="13" y="13" width="7" height="7" rx="1.5" /></>,
  size: <><rect x="3" y="6" width="18" height="12" rx="2" /></>,
  people: <><circle cx="12" cy="8" r="4" /><path d="M4 20c1.5-4 4.5-6 8-6s6.5 2 8 6" /></>,
};
const icon = (children: ReactNode, size = 15) => <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"
  stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{children}</svg>;
const COINS = <><ellipse cx="9" cy="7" rx="6" ry="3" /><path d="M3 7v5c0 1.7 2.7 3 6 3s6-1.3 6-3V7" /><path d="M9 15v2c0 1.7 2.7 3 6 3s6-1.3 6-3v-5c0-1.7-2.7-3-6-3" /></>;

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
    <small className="assistant-gen-kind">{quote.kind}</small>
    <p className="assistant-gen-title">{quote.title}</p>
    <ul className="assistant-gen-facts">{quote.facts.map(fact => <li key={`${fact.icon}:${fact.text}`}>
      {ICONS[fact.icon] && icon(ICONS[fact.icon])}<span>{fact.text}</span></li>)}</ul>
    {price && <p className={`assistant-gen-cost ${price.over ? "is-over" : ""}`} data-credit-cost={price.text}>{icon(COINS, 18)}{price.text}</p>}
    {price?.over && <p className="assistant-gen-note is-bad" role="status">You don&rsquo;t have enough credits for this.</p>}
    {note && <p className={`assistant-gen-note ${note.bad ? "is-bad" : ""}`} role="status">{note.text}</p>}
    {error && <p className="assistant-gen-note is-bad" role="alert">{error}</p>}
    <GpuNotice kinds={[actionGpuKind(status.op)]} dark />
    <div className="assistant-gen-buttons">
      <button type="button" className="assistant-gen-cancel" disabled={busy} onClick={onCancel}>Cancel</button>
      <button type="button" className="assistant-gen-go" disabled={busy || status.needs_accept || Boolean(price?.over)}
        onClick={onGenerate}>{busy ? "Starting…" : cardLabel(status, quote)}</button>
    </div>
    {opens && onOpen && <p className="assistant-gen-foot">Want more control?{" "}
      <button type="button" onClick={() => onOpen(opens)}>Open {OPENS[opens]} <span aria-hidden="true">→</span></button></p>}
  </article>;
}
