import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api } from "./api";
import type { Tenant } from "./types";

// A "workspace" is a tenant. Non-technical users never see the tenant concept:
// we create one on first use and remember it in localStorage. No auth yet.

const STORAGE_KEY = "atlasrag.workspace";

interface StoredWorkspace {
  id: string;
  name: string;
}

interface WorkspaceContextValue {
  workspace: StoredWorkspace | null;
  loading: boolean;
  create: (name: string) => Promise<void>;
  reset: () => void;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

function load(): StoredWorkspace | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredWorkspace;
    return parsed?.id ? parsed : null;
  } catch {
    return null;
  }
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [workspace, setWorkspace] = useState<StoredWorkspace | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setWorkspace(load());
    setLoading(false);
  }, []);

  const create = useCallback(async (name: string) => {
    const tenant: Tenant = await api.createTenant(name);
    const stored: StoredWorkspace = { id: tenant.id, name: tenant.name };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
    setWorkspace(stored);
  }, []);

  const reset = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setWorkspace(null);
  }, []);

  const value = useMemo<WorkspaceContextValue>(
    () => ({ workspace, loading, create, reset }),
    [workspace, loading, create, reset],
  );

  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used within WorkspaceProvider");
  return ctx;
}
