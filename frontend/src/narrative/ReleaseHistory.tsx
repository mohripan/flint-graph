import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { releaseEventLabel, releaseStatus } from "./releaseModel";
import { releaseErrorMessage } from "./releaseRequests";
import type { ReleaseRun } from "./releaseRequests";
import type { ReleaseEvent, ReleaseJob } from "./types";

const PAGE = 25;

// Runs inside the dialog's request scope, so access loss or closing the dialog
// invalidates history requests together with item, action and download work.
export function ReleaseHistory({ tenantId, projectId, releaseId, latestJob, run }: {
  tenantId: string; projectId: string; releaseId: string; latestJob: ReleaseJob; run: ReleaseRun;
}) {
  const [jobs, setJobs] = useState<ReleaseJob[]>([]), [jobId, setJobId] = useState(latestJob.id);
  const jobsRef = useRef(jobs); jobsRef.current = jobs;
  const [events, setEvents] = useState<ReleaseEvent[]>([]), [moreJobs, setMoreJobs] = useState(false);
  const [olderBusy, setOlderBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [eventsBusy, setEventsBusy] = useState(false), [refresh, setRefresh] = useState(0);
  const firstPage = useRef(true);
  const failure = (value: unknown) => setError(releaseErrorMessage(value));
  function loadJobs(older = false) {
    if (older && olderBusy) return;
    const loaded = jobsRef.current;
    if (older) setOlderBusy(true);
    void run(older ? "history:older" : "history:jobs", signal => api.listNarrativeReleaseJobs(tenantId, projectId, releaseId, {
      signal, limit: PAGE, beforeId: older ? loaded[loaded.length - 1]?.id : undefined,
    }), rows => {
      setJobs(previous => older ? [...previous, ...rows.filter(row => !previous.some(item => item.id === row.id))]
        : [...rows, ...previous.filter(row => !rows.some(item => item.id === row.id))]);
      // Refreshes never re-offer pages that an older load already exhausted.
      if (older || firstPage.current) { setMoreJobs(rows.length === PAGE); firstPage.current = false; }
      setError(null);
    }, failure, () => { if (older) setOlderBusy(false); });
  }
  useEffect(() => { loadJobs(); }, [latestJob.updated_at]);
  const shownJob = useRef(jobId);
  useEffect(() => {
    // Polling refreshes keep the visible timeline; only another attempt clears it.
    if (shownJob.current !== jobId) { shownJob.current = jobId; setEvents([]); }
    setEventsBusy(true);
    void run("history:events", signal => api.listNarrativeReleaseEvents(tenantId, projectId, releaseId, jobId, { signal }),
      rows => {
        if (rows.some(row => row.release_id !== releaseId || row.job_id !== jobId)) {
          setError("This history did not match the selected build."); return;
        }
        setEvents(rows); setError(null);
      }, failure, () => setEventsBusy(false));
  }, [jobId, latestJob.updated_at, refresh, run, tenantId, projectId, releaseId]);
  return <section className="studio-release-history" aria-label="Build history">
    <div className="studio-section-heading"><h4>Build history</h4>
      <button type="button" className="studio-link" onClick={() => { loadJobs(); setRefresh(value => value + 1); }}>Refresh history</button></div>
    {error && <p className="studio-error" role="status">{error}</p>}
    <label className="studio-field">Build attempt<select value={jobId} onChange={event => setJobId(event.target.value)}>
      {(jobs.length ? jobs : [latestJob]).map(job => <option key={job.id} value={job.id}>
        Attempt {job.attempt_number} · {releaseStatus(job)}</option>)}
    </select></label>
    <ol className="studio-release-events">{events.map(event => <li key={event.id}>
      <span>{releaseEventLabel(event.code)}</span><time dateTime={event.created_at}>{new Date(event.created_at).toLocaleString()}</time>
    </li>)}</ol>
    {!events.length && <p className="studio-hint">{eventsBusy ? "Loading build events…" : "No events to show for this attempt yet."}</p>}
    {moreJobs && <button type="button" className="studio-secondary" aria-disabled={olderBusy} onClick={() => loadJobs(true)}>
      {olderBusy ? "Loading older attempts…" : "Load older attempts"}</button>}
  </section>;
}
