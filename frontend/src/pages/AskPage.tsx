import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { SystemReadiness } from "../lib/types";
import { useWorkspace } from "../lib/workspace";
import { ConversationAskPage } from "./ConversationAskPage";
import { StandaloneAskPage } from "./StandaloneAskPage";

export function AskPage() {
  const { workspace } = useWorkspace();
  const [capabilities, setCapabilities] = useState<SystemReadiness["setup_capabilities"] | null>(null);
  const [checked, setChecked] = useState(false);
  const [independent, setIndependent] = useState(false);
  const [accessDenied, setAccessDenied] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void api.getSystemReadiness(workspace!.id, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setCapabilities(value.setup_capabilities); })
      .catch((err) => {
        if (!controller.signal.aborted && err instanceof ApiError && [401, 403].includes(err.status)) setAccessDenied(true);
        // Only older/unavailable backends retain independent questions.
      })
      .finally(() => { if (!controller.signal.aborted) setChecked(true); });
    return () => controller.abort();
  }, [workspace!.id]);
  if (accessDenied) return <p role="alert" className="p-6 text-sm text-red-700">Workspace access was denied. Refresh the page or switch workspace after access is restored.</p>;
  if (!checked) return <p role="status" className="p-6 text-sm text-slate-600">Checking conversation support…</p>;
  const supported = capabilities?.conversation_ledger === true;
  return <div className="flex h-full min-h-0 flex-col">
    <div className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-2 text-xs text-slate-600">
      <span>{supported && !independent ? "Workspace-shared conversations" : "Independent questions · no follow-up memory"}</span>
      {supported && <button className="shrink-0 rounded px-2 py-1 text-brand-700 underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-brand-500"
        onClick={() => setIndependent((value) => !value)}>{independent ? "Conversations" : "Independent question history"}</button>}
    </div>
    <div className="min-h-0 flex-1">{supported && !independent
      ? <ConversationAskPage capabilities={capabilities!} /> : <StandaloneAskPage />}</div>
  </div>;
}
