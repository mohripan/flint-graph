// Credits, prices and the ledger as the Studio shows them (ADR 0059). The server is
// authoritative; the item rules here mirror flint_graph.application.credit_prices.
export interface Price { credits: number; kind: string; label: string; unit: string; per: number }
export type Prices = Record<string, Price>;

/** The parts of the access status that decide whether credits are shown. */
export interface CreditStatus {
  mode: "open" | "invite"; is_admin: boolean; credits: number | null; unlimited: boolean; prices?: Prices;
  credits_used?: number;
  /** On your own server: nothing is charged, and what you use is counted (ADR 0075). */
  own_server?: boolean;
}

export interface LedgerEntry {
  change: "join" | "charge" | "add" | "remove" | "set" | "unlimited" | "limited";
  amount: number; item: string | null; quantity: number | null; note: string | null; actor_email: string | null;
}

export const MAX_CREDITS = 10_000_000;

export function imageItem(job: {
  purpose: "character_portrait" | "background" | "character_expression" | "scene_art";
  transparent?: boolean; hires?: boolean; pose?: boolean; repair?: boolean;
}): string {
  if (job.pose) return job.repair ? "image.pose_repair" : "image.pose";
  if (job.purpose === "scene_art") return "image.cg";
  if (job.purpose === "character_expression") return "image.expression";
  if (job.hires) return "image.high_res";
  return job.transparent ? "image.sprite" : "image.standard";
}

export const voiceItem = (model: string) => `voice.${model}`;
export const assistantItem = (provider: string) => `assistant.${provider}`;

export function trainingItem(target: { character: boolean; reference?: boolean }): string {
  if (!target.character) return "training.style";
  return target.reference ? "training.character_reference" : "training.character";
}

/** Training is priced per 100 steps, rounded up. */
export const trainingBlocks = (steps: number) => Math.max(1, Math.ceil(steps / 100));

export const creditsText = (amount: number) => amount === 1 ? "1 credit" : `${amount} credits`;

/** Does this person spend credits? Open mode, operators, unlimited and older grants do not. */
export function metered(status: CreditStatus | null): status is CreditStatus & { credits: number } {
  // An API from before ADR 0059 sends no credits at all: nothing to show.
  return Boolean(status && status.mode === "invite" && !status.unlimited && !status.is_admin && typeof status.credits === "number");
}

/** Someone running their own server: unlimited, but still shown what things cost. */
export function ownServer(status: CreditStatus | null): boolean {
  return Boolean(status?.own_server);
}

export interface CostView { cost: number; text: string; over: boolean }

/** What starting ``quantity`` of ``item`` costs, or null when no price should show. */
export function costView(status: CreditStatus | null, item: string, quantity: number): CostView | null {
  return partsCostView(status, [[item, quantity]]);
}

/** The total of several items, e.g. one voice job per speaker, each with its own model. */
export function partsCostView(status: CreditStatus | null, parts: Array<[string, number]>): CostView | null {
  if (!status || (!metered(status) && !ownServer(status))) return null;
  const counted = parts.filter(([, quantity]) => quantity > 0);
  if (!counted.length || counted.some(([item]) => !status.prices?.[item])) return null;
  const cost = counted.reduce((total, [item, quantity]) => total + status.prices![item].credits * quantity, 0);
  const over = metered(status) && cost > status.credits;
  return { cost, over, text: over ? `${creditsText(cost)} · you have ${status.credits}` : creditsText(cost) };
}

export interface QuoteView { text: string; over: boolean }

/** The price on a generation card: anyone who pays nothing is told so, not shown a blank. */
export function quoteView(status: CreditStatus | null, parts: Array<[string, number]>): QuoteView | null {
  if (!status?.prices || !parts.length || parts.some(([item]) => !status.prices![item])) return null;
  const cost = parts.reduce((total, [item, quantity]) => total + status.prices![item].credits * quantity, 0);
  if (!metered(status)) return { text: `${creditsText(cost)} · free for you`, over: false };
  return { text: `${creditsText(cost)} · you have ${status.credits}`, over: cost > status.credits };
}

/** "3 credits per line", for choosing between models; empty when no price should show. */
export function unitPrice(status: CreditStatus | null, item: string): string {
  const price = metered(status) || ownServer(status) ? status?.prices?.[item] : undefined;
  return price ? `${creditsText(price.credits)} per ${price.unit}` : "";
}

export function balanceLabel(status: CreditStatus | null): string | null {
  if (ownServer(status)) return "Unlimited";
  if (!status || status.mode !== "invite") return null;
  if (status.unlimited || status.is_admin) return "Unlimited";
  return typeof status.credits === "number" ? creditsText(status.credits) : null;
}

// POSTs that admit paid work; the Studio reloads the balance after them.
const PAID = [
  /\/assets\/(background|scene-art)-jobs$/,
  /\/music-jobs$/,
  /\/characters\/[^/]+\/(portrait|expression|voice)-jobs$/,
  /\/characters\/[^/]+\/looks\/(portrait|expression|pose)-jobs$/,
  /\/characters\/[^/]+\/looks\/pose-repairs$/,
  /\/look-scene-art-jobs$/,
  /\/style-jobs$/,
  /\/assistant\/threads\/[^/]+\/turns$/,
  /\/assistant\/proposals\/[^/]+\/actions\/\d+$/,
  /\/narrative\/projects\/[^/]+\/releases$/,
];

export function paidRequest(method: string | undefined, path: string): boolean {
  if ((method ?? "GET").toUpperCase() !== "POST") return false;
  const bare = path.split("?")[0];
  return PAID.some(pattern => pattern.test(bare));
}

export function usageProblem(type: string | undefined): boolean {
  return Boolean(type && (type.endsWith(":out-of-credits") || type.endsWith(":usage-limit")));
}

export const signed = (amount: number) => amount > 0 ? `+${amount}` : amount < 0 ? `−${-amount}` : "0";

const CHANGE_LABEL: Record<LedgerEntry["change"], string> = {
  join: "Joined", charge: "Charge", add: "Added", remove: "Removed", set: "Balance set",
  unlimited: "Made unlimited", limited: "Unlimited turned off",
};

export function ledgerText(entry: LedgerEntry, prices: Prices | undefined): string {
  if (entry.change === "charge" && entry.item) {
    const price = prices?.[entry.item];
    if (!price) return entry.item;
    return price.per === 1 && (entry.quantity ?? 1) > 1 ? `${entry.quantity} × ${price.label}` : price.label;
  }
  const by = entry.actor_email ? ` by ${entry.actor_email}` : "";
  return `${CHANGE_LABEL[entry.change]}${by}${entry.note ? `: ${entry.note}` : ""}`;
}

/** An operator's credit change typed into the form, or why it cannot be sent. */
export function parseCreditChange(change: "add" | "remove" | "set", text: string): { change: typeof change; amount: number } | string {
  const value = text.trim();
  if (!/^\d{1,9}$/.test(value)) return "Enter a whole number of credits.";
  const amount = Number(value);
  if (amount > MAX_CREDITS) return `Enter at most ${MAX_CREDITS} credits.`;
  if (change !== "set" && amount < 1) return "Enter at least 1 credit.";
  return { change, amount };
}
