import { createContext, useContext } from "react";
import type { AccessStatus } from "../lib/api";

export const AccessContext = createContext<AccessStatus | null>(null);

/** The signed-in person's access, read once when the Studio opens (ADR 0058). */
export function useAccess(): AccessStatus | null {
  return useContext(AccessContext);
}
