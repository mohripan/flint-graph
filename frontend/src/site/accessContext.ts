import { createContext, useContext } from "react";
import type { AccessStatus } from "../lib/api";

export const AccessContext = createContext<AccessStatus | null>(null);
// Reloads the status, e.g. the credit balance after paid work (ADR 0059).
export const AccessRefreshContext = createContext<() => void>(() => undefined);

/** The signed-in person's access, read when the Studio opens and after paid work (ADR 0058). */
export function useAccess(): AccessStatus | null {
  return useContext(AccessContext);
}

export function useAccessRefresh(): () => void {
  return useContext(AccessRefreshContext);
}
