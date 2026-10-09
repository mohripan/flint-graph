import { useState } from "react";
import { useWorkspace } from "../lib/workspace";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";
import { Button, Card, Spinner } from "./ui";

export function AuthGate() {
  const auth = useAuth();
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <Card className="w-full max-w-md p-8">
        <div className="mb-6 flex items-center gap-3">
          <Logo />
          <div>
            <h1 className="text-lg font-semibold text-slate-900">FlintGraph</h1>
            <p className="text-sm text-slate-500">Sign in to your workspace</p>
          </div>
        </div>
        {auth.mode === "oidc" ? (
          <Button
            className="w-full"
            onClick={() =>
              auth.signIn().catch((err) =>
                setError(err instanceof Error ? err.message : "Sign in failed."),
              )
            }
          >
            Sign in
          </Button>
        ) : (
          <p className="text-sm text-slate-500">Local development auth is active.</p>
        )}
        {error && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      </Card>
    </div>
  );
}

// First workspace screen after authentication.
export function WorkspaceGate() {
  const { create, workspaces, select } = useWorkspace();
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
          Choose a workspace
        </h2>
        <p className="mb-5 text-sm text-slate-500">
          Workspaces keep each team or department's documents and answers separate.
        </p>

        {workspaces.length > 0 && (
          <div className="mb-5 space-y-2">
            {workspaces.map((workspace) => (
              <button
                key={workspace.id}
                onClick={() => select(workspace)}
                className="flex w-full items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-left text-sm hover:bg-slate-50"
              >
                <span className="font-medium text-slate-800">{workspace.name}</span>
                <span className="rounded-sm bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                  {workspace.role}
                </span>
              </button>
            ))}
          </div>
        )}

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
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-xs focus:border-brand-500 focus:outline-hidden focus:ring-1 focus:ring-brand-500"
            />
          </div>
          {error && (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          )}
          <Button type="submit" disabled={busy} className="w-full">
            {busy && <Spinner className="h-4 w-4" />}
            {busy ? "Creating…" : "Create new workspace"}
          </Button>
        </form>
      </Card>
    </div>
  );
}

export function Logo({ className = "h-10 w-10" }: { className?: string }) {
  return (
    <div
      className={`flex items-center justify-center rounded-xl bg-linear-to-br from-brand-500 to-brand-700 text-white shadow-xs ${className}`}
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
