import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, setAccessTokenProvider } from "./api";
import { useAuth } from "./auth";
import type { Workspace } from "./types";

const STORAGE_KEY = "flintgraph.workspace";

interface WorkspaceContextValue {
  workspace: Workspace | null;
  workspaces: Workspace[];
  loading: boolean;
  create: (name: string) => Promise<void>;
  select: (workspace: Workspace) => void;
  reset: () => void;
  refresh: () => Promise<void>;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

function loadSelectedId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function saveSelectedId(id: string | null) {
  if (id) localStorage.setItem(STORAGE_KEY, id);
  else localStorage.removeItem(STORAGE_KEY);
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setAccessTokenProvider(() => auth.getAccessToken());
    return () => setAccessTokenProvider(null);
  }, [auth]);

  const refresh = useCallback(async () => {
    if (!auth.authenticated) {
      setWorkspace(null);
      setWorkspaces([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const rows = await api.listWorkspaces();
      setWorkspaces(rows);
      const selectedId = loadSelectedId();
      const selected = rows.find((item) => item.id === selectedId) ?? rows[0] ?? null;
      setWorkspace(selected);
      saveSelectedId(selected?.id ?? null);
    } finally {
      setLoading(false);
    }
  }, [auth.authenticated]);

  useEffect(() => {
    if (auth.loading) return;
    void refresh();
  }, [auth.loading, refresh]);

  const create = useCallback(async (name: string) => {
    const created = await api.createWorkspace(name);
    setWorkspaces((prev) => [created, ...prev.filter((item) => item.id !== created.id)]);
    setWorkspace(created);
    saveSelectedId(created.id);
  }, []);

  const select = useCallback((next: Workspace) => {
    setWorkspace(next);
    saveSelectedId(next.id);
  }, []);

  const reset = useCallback(() => {
    setWorkspace(null);
    saveSelectedId(null);
  }, []);

  const value = useMemo<WorkspaceContextValue>(
    () => ({ workspace, workspaces, loading, create, select, reset, refresh }),
    [workspace, workspaces, loading, create, select, reset, refresh],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used within WorkspaceProvider");
  return ctx;
}
