import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type { ImageJob } from "../lib/api";
import { mergeImageJobs } from "./imageJobModel";

type Listener = (tenant: string, project: string, job: ImageJob) => void;
const listeners = new Set<Listener>();
/** Status is persisted by the API; this notification only closes the list/start race. */
export function imageJobStarted(tenantId: string, projectId: string, job: ImageJob): void {
  for (const listener of listeners) listener(tenantId, projectId, job);
}

export function useBackgroundJobs(tenantId: string, projectId: string) {
  const [jobs, setJobs] = useState<ImageJob[]>([]);
  const [failed, setFailed] = useState(false);
  const put = useCallback((job: ImageJob) => {
    if (job.purpose === "background") setJobs(current => mergeImageJobs(current, [job]));
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let pending = false;
    const listener: Listener = (tenant, project, job) => {
      if (tenant === tenantId && project === projectId) put(job);
    };
    listeners.add(listener);
    setJobs([]); setFailed(false);
    const load = async () => {
      if (pending) return;
      pending = true;
      try {
        const listed = await api.listBackgroundJobs(tenantId, projectId, controller.signal);
        if (!controller.signal.aborted) { setJobs(current => mergeImageJobs(current, listed.jobs)); setFailed(false); }
      } catch { if (!controller.signal.aborted) setFailed(true); }
      finally { pending = false; }
    };
    void load();
    // Discover jobs started in Assistant, another view or another tab even when no
    // active job was known at mount. Never start work as a side effect of a read.
    const timer = window.setInterval(() => void load(), 1500);
    return () => { controller.abort(); window.clearInterval(timer); listeners.delete(listener); };
  }, [tenantId, projectId, put]);
  return { jobs, failed, put };
}
