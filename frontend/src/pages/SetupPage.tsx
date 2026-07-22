import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { IndexBackfillJob, SystemReadiness } from "../lib/types";
import { useWorkspace } from "../lib/workspace";
import { Button, Card, Spinner, StatusPill } from "../components/ui";

export function SetupPage() {
  const { workspace } = useWorkspace();
  const tenantId = workspace!.id;
  const canAdmin = workspace!.role === "owner" || workspace!.role === "admin";
  const [readiness, setReadiness] = useState<SystemReadiness | null>(null);
  const [backfills, setBackfills] = useState<IndexBackfillJob[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [nextReadiness, nextBackfills] = await Promise.all([
        api.getSystemReadiness(tenantId),
        canAdmin ? api.listIndexBackfills(tenantId) : Promise.resolve([]),
      ]);
      setReadiness(nextReadiness);
      setBackfills(nextBackfills);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load setup status.");
    }
  }, [canAdmin, tenantId]);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(id);
  }, [refresh]);

  async function run(action: "bootstrap" | "backfill") {
    setBusy(action);
    setError(null);
    try {
      if (action === "bootstrap") await api.bootstrapRetrievalIndex(tenantId);
      else await api.backfillActiveIndex(tenantId);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Setup action failed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-6 overflow-y-auto p-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Setup</h1>
        <p className="text-sm text-slate-500">
          Prepare search and check workspace readiness.
        </p>
      </div>

      {error && <Card className="border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</Card>}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <p className="mb-3 text-sm font-semibold text-slate-800">Search</p>
          {readiness ? (
            <div className="space-y-3 text-sm text-slate-600">
              <div className="flex items-center justify-between">
                <span>Workspace readiness</span>
                <StatusPill status={readiness.search_readiness.ready ? "completed" : "running"} />
              </div>
              <p className="text-xs text-slate-500">{readiness.search_readiness.reason}</p>
              <Metric label="Searchable" value={readiness.search_readiness.completed_coverage_count} />
              <Metric label="Indexing" value={readiness.search_readiness.running_coverage_count} />
              <Metric label="Failed" value={readiness.search_readiness.failed_coverage_count} />
              {readiness.search_readiness.active_index_version && (
                <p className="text-xs text-slate-500">
                  Index: {readiness.search_readiness.active_index_version.embedding_provider}/
                  {readiness.search_readiness.active_index_version.embedding_model}
                </p>
              )}
            </div>
          ) : (
            <p className="text-sm text-slate-400">Checking readiness...</p>
          )}
        </Card>

        <Card className="p-5">
          <p className="mb-3 text-sm font-semibold text-slate-800">Providers</p>
          {readiness ? (
            <div className="space-y-2 text-sm text-slate-600">
              <p>Auth: {readiness.auth.mode}</p>
              <p>
                Embeddings: {readiness.embedding.provider}/{readiness.embedding.model} (
                {readiness.embedding.dimensions})
              </p>
              <p>
                Answer: {readiness.query.answer_provider}/{readiness.query.answer_model}
              </p>
              <p>
                Support: {readiness.query.support_provider}/{readiness.query.support_model}
              </p>
            </div>
          ) : (
            <p className="text-sm text-slate-400">Checking providers...</p>
          )}
        </Card>
      </div>

      <Card className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-slate-800">Actions</p>
            <p className="text-xs text-slate-500">
              Owner/admin actions for preparing searchable content.
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={refresh}>
              Refresh
            </Button>
            <Button disabled={!canAdmin || busy === "bootstrap"} onClick={() => run("bootstrap")}>
              {busy === "bootstrap" && <Spinner className="h-4 w-4" />}
              Prepare search
            </Button>
            <Button disabled={!canAdmin || busy === "backfill"} onClick={() => run("backfill")}>
              {busy === "backfill" && <Spinner className="h-4 w-4" />}
              Backfill
            </Button>
          </div>
        </div>
      </Card>

      <Card className="p-5">
        <p className="mb-3 text-sm font-semibold text-slate-800">Backfills</p>
        {backfills.length === 0 ? (
          <p className="text-sm text-slate-400">No backfill jobs yet.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {backfills.map((job) => (
              <li key={job.id} className="flex items-center justify-between py-3 text-sm">
                <div>
                  <p className="font-medium text-slate-800">{job.id}</p>
                  <p className="text-xs text-slate-500">
                    {job.processed_count}/{job.total_count} processed · {job.failed_count} failed
                  </p>
                </div>
                <StatusPill status={job.status} />
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="inline-flex items-center gap-2 rounded border border-slate-100 px-3 py-2">
      <span className="text-xs text-slate-400">{label}</span>
      <span className="text-sm font-semibold text-slate-800">{value}</span>
    </div>
  );
}
