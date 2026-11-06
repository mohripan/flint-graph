import { useAccess } from "../site/accessContext";
import { partsCostView } from "../site/creditsModel";

/**
 * What starting this work costs, shown before the person starts it (ADR 0059). Renders
 * nothing for anyone who spends no credits: open mode, operators and unlimited people.
 * Pass ``item`` and ``quantity``, or ``parts`` when several items start together.
 */
export function CreditCost({ item, quantity = 1, parts, className = "" }: {
  item?: string; quantity?: number; parts?: Array<[string, number]>; className?: string;
}) {
  const view = partsCostView(useAccess(), parts ?? (item ? [[item, quantity]] : []));
  if (!view) return null;
  return (
    <span data-credit-cost={view.cost} title={view.over ? "Not enough credits for this" : "Credits this will use"}
      className={`whitespace-nowrap text-xs ${view.over ? "font-medium text-red-700" : "text-slate-500"} ${className}`}>
      {view.text}
    </span>
  );
}
