import { useEffect, useState } from "react";
import { api } from "./lib/api";
import { useAuth } from "./lib/auth";
import { useWorkspace } from "./lib/workspace";
import { AuthGate, WorkspaceGate, Logo } from "./components/WorkspaceGate";
import { AskPage } from "./pages/AskPage";
import { UploadPage } from "./pages/UploadPage";
import { SetupPage } from "./pages/SetupPage";

type Tab = "ask" | "documents" | "setup";

export default function App() {
  const auth = useAuth();
  const { workspace, workspaces, loading, reset, select } = useWorkspace();
  const [tab, setTab] = useState<Tab>("ask");
  const [healthy, setHealthy] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    const check = async () => {
      const ok = await api.health();
      if (alive) setHealthy(ok);
    };
    void check();
    const id = window.setInterval(check, 15000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  if (auth.loading || loading) {
    return <div className="flex min-h-full items-center justify-center" />;
  }

  if (!auth.authenticated) {
    return <AuthGate />;
  }

  if (!workspace) {
    return <WorkspaceGate />;
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
        <div className="flex items-center gap-3">
          <Logo className="h-9 w-9" />
          <div>
            <p className="text-sm font-semibold leading-tight text-slate-900">FlintGraph</p>
            <p className="text-xs leading-tight text-slate-500">{workspace.name}</p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <HealthDot healthy={healthy} />
          <select
            value={workspace.id}
            onChange={(event) => {
              const next = workspaces.find((item) => item.id === event.target.value);
              if (next) select(next);
            }}
            className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm text-slate-600"
          >
            {workspaces.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
          <button onClick={reset} className="text-sm text-slate-500 hover:text-slate-700">
            Switch workspace
          </button>
          {auth.mode === "oidc" && (
            <button
              onClick={() => void auth.signOut()}
              className="text-sm text-slate-500 hover:text-slate-700"
            >
              Sign out
            </button>
          )}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <nav className="flex w-52 shrink-0 flex-col gap-1 border-r border-slate-200 bg-white p-3">
          <NavItem active={tab === "ask"} onClick={() => setTab("ask")} label="Ask" icon={<AskIcon />} />
          <NavItem
            active={tab === "documents"}
            onClick={() => setTab("documents")}
            label="Documents"
            icon={<DocIcon />}
          />
          <NavItem active={tab === "setup"} onClick={() => setTab("setup")} label="Setup" icon={<SetupIcon />} />
        </nav>

        <main className="min-h-0 flex-1 overflow-hidden bg-slate-50">
          {tab === "ask" ? <AskPage /> : tab === "documents" ? <UploadPage /> : <SetupPage />}
        </main>
      </div>
    </div>
  );
}

function NavItem({
  active,
  onClick,
  label,
  icon,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  icon: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
        active ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100"
      }`}
    >
      <span className="h-5 w-5">{icon}</span>
      {label}
    </button>
  );
}

function HealthDot({ healthy }: { healthy: boolean | null }) {
  const color =
    healthy === null ? "bg-slate-300" : healthy ? "bg-emerald-500" : "bg-red-500";
  const label =
    healthy === null ? "Checking API…" : healthy ? "API connected" : "API unreachable";
  return (
    <span className="flex items-center gap-1.5 text-xs text-slate-500" title={label}>
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {label}
    </span>
  );
}

function AskIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" aria-hidden="true">
      <path
        d="M21 12a8 8 0 01-11.3 7.3L4 21l1.7-5.7A8 8 0 1121 12z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function DocIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" aria-hidden="true">
      <path
        d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8l-5-5z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M14 3v5h5" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}

function SetupIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" aria-hidden="true">
      <path
        d="M12 15.5a3.5 3.5 0 100-7 3.5 3.5 0 000 7z"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M19.4 15a8 8 0 000-6l2-1.5-2-3.4-2.4 1a8 8 0 00-5.2-3l-.4-2.6h-4l-.4 2.6a8 8 0 00-5.2 3l-2.4-1-2 3.4L4.6 9a8 8 0 000 6l-2 1.5 2 3.4 2.4-1a8 8 0 005.2 3l.4 2.6h4l.4-2.6a8 8 0 005.2-3l2.4 1 2-3.4L19.4 15z"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
    </svg>
  );
}
