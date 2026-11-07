import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../lib/api";
import { gpuMessage } from "./gpuModel";
import type { GpuKind, GpuStatus } from "./gpuModel";

const POLL_MS = 20_000;
const GpuContext = createContext<GpuStatus | null>(null);

// One reading for the whole Studio, so every view says the same thing and a reload keeps it.
export function GpuStatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<GpuStatus | null>(null);
  useEffect(() => {
    const request = new AbortController();
    const read = () => {
      if (document.visibilityState === "hidden") return;
      // Without a reading nothing is said: writing never depends on this.
      void api.gpuStatus(request.signal).then(setStatus).catch(() => undefined);
    };
    read();
    const timer = window.setInterval(read, POLL_MS);
    return () => { request.abort(); window.clearInterval(timer); };
  }, []);
  return <GpuContext.Provider value={status}>{children}</GpuContext.Provider>;
}

/** Tells people the GPU is not up, where they are about to wait for it. */
export function GpuNotice({ kinds }: { kinds: GpuKind[] }) {
  const message = gpuMessage(useContext(GpuContext), kinds);
  if (!message) return null;
  return <p role="status" className={`studio-gpu-notice ${message.bad ? "is-bad" : ""}`}>
    <strong>{message.title}</strong> {message.body}</p>;
}
