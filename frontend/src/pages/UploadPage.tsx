import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useTrackedJobs, type TrackedJob } from "../lib/jobs";
import type { SearchReadiness } from "../lib/types";
import { useWorkspace } from "../lib/workspace";
import { Button, Card, Spinner, StatusPill } from "../components/ui";

type Mode = "file" | "url";

export function UploadPage() {
  const { workspace } = useWorkspace();
  const tenantId = workspace!.id;
  const { jobs, add, remove, cancel } = useTrackedJobs(tenantId);

  const [mode, setMode] = useState<Mode>("file");
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [readiness, setReadiness] = useState<SearchReadiness | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function resetForm() {
    setTitle("");
    setUrl("");
    setFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  const refreshReadiness = useCallback(async () => {
    try {
      setReadiness(await api.getSearchReadiness(tenantId));
    } catch {
      setReadiness(null);
    }
  }, [tenantId]);

  useEffect(() => {
    void refreshReadiness();
    const id = window.setInterval(() => void refreshReadiness(), 5000);
    return () => window.clearInterval(id);
  }, [refreshReadiness]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const t = title.trim();
    if (!t) return setError("Please give this document a title.");
    if (mode === "file" && !file) return setError("Please choose a file to upload.");
    if (mode === "url" && !url.trim()) return setError("Please enter a URL.");

    setBusy(true);
    try {
      const res =
        mode === "file"
          ? await api.uploadDocument(tenantId, { title: t, file: file! })
          : await api.ingestUrl(tenantId, { title: t, sourceUrl: url.trim() });
      const job: TrackedJob = {
        jobId: res.ingestion_job_id,
        documentId: res.document_id,
        title: res.title,
        kind: mode,
        status: res.job_status,
        createdAt: res.created_at,
        error: null,
      };
      add(job);
      resetForm();
      void refreshReadiness();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Upload failed. Is the backend (and worker) running?",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col gap-6 overflow-y-auto p-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Documents</h1>
        <p className="text-sm text-slate-500">
          Add documents to your workspace. Once processed, you can ask questions
          about them.
        </p>
      </div>

      <Card className="p-5">
        <div className="mb-4 inline-flex rounded-lg bg-slate-100 p-1">
          {(["file", "url"] as Mode[]).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`rounded-md px-4 py-1.5 text-sm font-medium transition ${
                mode === m
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {m === "file" ? "Upload a file" : "From a URL"}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="space-y-4">
          <Field label="Title">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Acme 2024 Annual Report"
              className={inputClass}
            />
          </Field>

          {mode === "file" ? (
            <Field label="File">
              <input
                ref={fileInputRef}
                type="file"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full text-sm text-slate-600 file:mr-4 file:rounded-lg file:border-0 file:bg-brand-50 file:px-4 file:py-2 file:text-sm file:font-medium file:text-brand-700 hover:file:bg-brand-100"
              />
              <p className="mt-1 text-xs text-slate-400">
                Supported formats include Markdown, plain text, HTML, and PDF.
              </p>
            </Field>
          ) : (
            <Field label="URL">
              <input
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://example.org/article"
                className={inputClass}
              />
            </Field>
          )}

          {error && (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
          )}

          <Button type="submit" disabled={busy}>
            {busy && <Spinner className="h-4 w-4" />}
            {busy ? "Adding…" : "Add document"}
          </Button>
        </form>
      </Card>

      <div>
        <h2 className="mb-3 text-sm font-semibold text-slate-700">
          Search readiness
        </h2>
        <Card className="mb-6 p-4">
          {readiness ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <StatusPill status={readiness.ready ? "completed" : "running"} />
                <p className="text-xs text-slate-500">
                  {readiness.completed_coverage_count} searchable ·{" "}
                  {readiness.running_coverage_count} indexing ·{" "}
                  {readiness.failed_coverage_count} failed
                </p>
              </div>
              {readiness.active_index_version && (
                <p className="text-xs text-slate-500">
                  Index: {readiness.active_index_version.embedding_provider}/
                  {readiness.active_index_version.embedding_model}
                </p>
              )}
              {readiness.documents.length > 0 && (
                <ul className="divide-y divide-slate-100">
                  {readiness.documents.map((doc) => (
                    <li
                      key={doc.document_version_id}
                      className="flex items-center justify-between gap-4 py-3"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-slate-800">
                          {doc.title}
                        </p>
                        <p className="text-xs text-slate-400">
                          v{doc.version_number} · {doc.chunk_count} chunks
                        </p>
                        {doc.error_message && (
                          <p className="mt-1 truncate text-xs text-red-600">
                            {doc.error_message}
                          </p>
                        )}
                      </div>
                      <StatusPill status={statusForReadiness(doc.status)} />
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <p className="text-sm text-slate-400">Checking readiness…</p>
          )}
        </Card>

        <h2 className="mb-3 text-sm font-semibold text-slate-700">
          Your documents {jobs.length > 0 && `(${jobs.length})`}
        </h2>
        {jobs.length === 0 ? (
          <Card className="p-8 text-center text-sm text-slate-400">
            No documents yet. Add one above to get started.
          </Card>
        ) : (
          <ul className="space-y-2">
            {jobs.map((job) => (
              <li key={job.jobId}>
                <Card className="flex items-center justify-between gap-4 p-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium text-slate-800">
                        {job.title}
                      </span>
                      <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] uppercase text-slate-500">
                        {job.kind}
                      </span>
                    </div>
                    {job.error && (
                      <p className="mt-0.5 truncate text-xs text-red-600" title={job.error}>
                        {job.error}
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    <StatusPill status={job.status} />
                    {(job.status === "queued" || job.status === "running") && (
                      <Button variant="danger" onClick={() => cancel(job.jobId)}>
                        Cancel
                      </Button>
                    )}
                    {(job.status === "completed" ||
                      job.status === "failed" ||
                      job.status === "cancelled") && (
                      <button
                        onClick={() => remove(job.jobId)}
                        className="text-slate-400 hover:text-slate-600"
                        title="Remove from list"
                        aria-label="Remove from list"
                      >
                        <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
                          <path d="M6 6l8 8M14 6l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                        </svg>
                      </button>
                    )}
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function statusForReadiness(status: string) {
  if (status === "searchable") return "completed";
  if (status === "indexing" || status === "ingesting" || status === "ingested") {
    return "running";
  }
  if (status === "cancelled") return "cancelled";
  if (status === "failed") return "failed";
  return "queued";
}

const inputClass =
  "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-slate-700">{label}</label>
      {children}
    </div>
  );
}
