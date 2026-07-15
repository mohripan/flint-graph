import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { IngestionJobStatus } from "./types";

// Ingestion jobs the user has started, tracked client-side (no list endpoint yet)
// and persisted per-workspace so they survive reloads.

export interface TrackedJob {
  jobId: string;
  documentId: string;
  title: string;
  kind: "file" | "url";
  status: IngestionJobStatus;
  createdAt: string;
  error?: string | null;
}

const TERMINAL: IngestionJobStatus[] = ["completed", "failed", "cancelled"];
const storageKey = (tenantId: string) => `atlasrag.jobs.${tenantId}`;

function load(tenantId: string): TrackedJob[] {
  try {
    const raw = localStorage.getItem(storageKey(tenantId));
    return raw ? (JSON.parse(raw) as TrackedJob[]) : [];
  } catch {
    return [];
  }
}

function save(tenantId: string, jobs: TrackedJob[]) {
  localStorage.setItem(storageKey(tenantId), JSON.stringify(jobs));
}

export function useTrackedJobs(tenantId: string) {
  const [jobs, setJobs] = useState<TrackedJob[]>(() => load(tenantId));
  const jobsRef = useRef(jobs);
  jobsRef.current = jobs;

  const persist = useCallback(
    (next: TrackedJob[]) => {
      setJobs(next);
      save(tenantId, next);
    },
    [tenantId],
  );

  const add = useCallback(
    (job: TrackedJob) => persist([job, ...jobsRef.current.filter((j) => j.jobId !== job.jobId)]),
    [persist],
  );

  const remove = useCallback(
    (jobId: string) => persist(jobsRef.current.filter((j) => j.jobId !== jobId)),
    [persist],
  );

  const cancel = useCallback(
    async (jobId: string) => {
      try {
        const updated = await api.cancelJob(tenantId, jobId);
        persist(
          jobsRef.current.map((j) =>
            j.jobId === jobId ? { ...j, status: updated.status } : j,
          ),
        );
      } catch {
        /* ignore — the poll will reconcile */
      }
    },
    [persist, tenantId],
  );

  // Reload when the workspace changes.
  useEffect(() => {
    setJobs(load(tenantId));
  }, [tenantId]);

  // Poll non-terminal jobs.
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const pending = jobsRef.current.filter((j) => !TERMINAL.includes(j.status));
      if (pending.length === 0) return;
      const results = await Promise.allSettled(
        pending.map((j) => api.getJob(tenantId, j.jobId)),
      );
      if (!alive) return;
      const byId = new Map<string, { status: IngestionJobStatus; error: string | null }>();
      results.forEach((r, i) => {
        if (r.status === "fulfilled") {
          byId.set(pending[i].jobId, {
            status: r.value.status,
            error: r.value.error_message,
          });
        }
      });
      if (byId.size > 0) {
        persist(
          jobsRef.current.map((j) => {
            const u = byId.get(j.jobId);
            return u ? { ...j, status: u.status, error: u.error } : j;
          }),
        );
      }
    };
    const id = window.setInterval(tick, 2000);
    void tick();
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [tenantId, persist]);

  return { jobs, add, remove, cancel };
}
