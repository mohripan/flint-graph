import { useState } from "react";
import { useWorkspace } from "../lib/workspace";
import { ApiError } from "../lib/api";
import { Button, Card, Spinner } from "./ui";

// First-run screen: create a workspace (tenant) before anything else.
export function WorkspaceGate() {
  const { create } = useWorkspace();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (trimmed.length < 2) {
      setError("Please enter a workspace name (at least 2 characters).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await create(trimmed);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not reach the FlintGraph API. Is the backend running?",
      );
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <Card className="w-full max-w-md p-8">
        <div className="mb-6 flex items-center gap-3">
          <Logo />
          <div>
            <h1 className="text-lg font-semibold text-slate-900">FlintGraph</h1>
            <p className="text-sm text-slate-500">Ask questions about your documents</p>
          </div>
        </div>

        <h2 className="mb-1 text-base font-semibold text-slate-800">
          Create your workspace
        </h2>
        <p className="mb-5 text-sm text-slate-500">
          A workspace keeps your documents and answers together. You can create
          one to get started — no account needed.
        </p>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label
              htmlFor="ws-name"
              className="mb-1 block text-sm font-medium text-slate-700"
            >
              Workspace name
            </label>
            <input
              id="ws-name"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Research Notes"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
          </div>
          {error && (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          )}
          <Button type="submit" disabled={busy} className="w-full">
            {busy && <Spinner className="h-4 w-4" />}
            {busy ? "Creating…" : "Create workspace"}
          </Button>
        </form>
      </Card>
    </div>
  );
}

export function Logo({ className = "" }: { className?: string }) {
  return (
    <div
      className={`flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-sm ${className}`}
    >
      <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" aria-hidden="true">
        <circle cx="12" cy="5" r="2.2" fill="currentColor" />
        <circle cx="5" cy="17" r="2.2" fill="currentColor" />
        <circle cx="19" cy="17" r="2.2" fill="currentColor" />
        <path
          d="M12 7v3m0 0l-5.5 5m5.5-5l5.5 5"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
      </svg>
    </div>
  );
}
