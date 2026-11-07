import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import type { MusicJob } from "../lib/api";
import { CreditCost } from "../components/CreditCost";
import { DEFAULT_LENGTH, DESCRIPTION_LIMIT, TRACK_LENGTHS, descriptionProblem, lengthLabel, musicJobActive, musicJobText } from "./musicModel";

const POLL_MS = 2000;
const text = (error: unknown, fallback: string) => error instanceof Error && error.message ? error.message : fallback;

// Generated music (ADR 0067): describe a track and get a candidate to review in the library.
export function MusicGenerator({ tenantId, projectId, canWrite, onFinished }: {
  tenantId: string; projectId: string; canWrite: boolean; onFinished: () => void;
}) {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [jobs, setJobs] = useState<MusicJob[]>([]);
  const [description, setDescription] = useState("");
  const [seconds, setSeconds] = useState<number>(DEFAULT_LENGTH);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const known = useRef(new Set<string>());
  const finished = useRef(onFinished);
  finished.current = onFinished;

  const load = useCallback(async (signal?: AbortSignal) => {
    const listed = await api.listMusicJobs(tenantId, projectId, signal);
    setAvailable(listed.available);
    setJobs(listed.jobs);
    // Tell the library once when a track this panel saw running has arrived.
    let arrived = false;
    for (const job of listed.jobs) {
      if (musicJobActive(job)) known.current.add(job.id);
      else if (known.current.delete(job.id) && job.status === "completed") arrived = true;
    }
    if (arrived) finished.current();
  }, [tenantId, projectId]);

  const active = jobs.some(musicJobActive);
  useEffect(() => {
    const request = new AbortController();
    void load(request.signal).catch(() => { if (!request.signal.aborted) setAvailable(current => current ?? false); });
    return () => request.abort();
  }, [load]);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => { void load().catch(() => undefined); }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [active, load]);

  if (available === null) return null;
  if (!available) {
    return <p className="studio-hint">Music generation isn&rsquo;t turned on for this Studio. You can upload Ogg Vorbis music instead.</p>;
  }
  const problem = descriptionProblem(description);
  async function start() {
    if (problem || busy) return;
    setBusy(true); setError(null);
    try {
      const job = await api.createMusicJob(tenantId, projectId, description.trim(), seconds);
      known.current.add(job.id);
      setDescription("");
      await load();
    } catch (failure) { setError(text(failure, "This music couldn't be started.")); }
    finally { setBusy(false); }
  }
  async function cancel(job: MusicJob) {
    setError(null);
    try { await api.cancelMusicJob(tenantId, projectId, job.id); await load(); }
    catch (failure) { setError(text(failure, "Could not cancel.")); }
  }
  // The latest job's message stays until its track is approved or the next one starts.
  const recent = jobs.filter(job => musicJobActive(job)
    || (job === jobs[0] && !(job.assets.length > 0 && job.assets.every(asset => asset.status === "approved"))));
  return <section className="studio-asset-generate" aria-label="Generate music">
    {canWrite && <>
      <label className="studio-field"><strong>Generate music</strong>
        <textarea rows={2} maxLength={DESCRIPTION_LIMIT} value={description} onChange={event => setDescription(event.target.value)}
          placeholder="gentle piano, soft strings, melancholy, slow" /></label>
      <p className="studio-hint">Describe the mood, instruments and pace. Tracks are instrumental and loop, and you review each one before it can be used.</p>
      <div className="studio-actions">
        <label className="studio-stage-motion-field"><span className="studio-stage-label">Length</span>
          <select value={seconds} onChange={event => setSeconds(Number(event.target.value))}>
            {TRACK_LENGTHS.map(value => <option key={value} value={value}>{lengthLabel(value)}</option>)}
          </select></label>
        <CreditCost item="music.track" />
        <button type="button" className="studio-secondary" disabled={Boolean(problem) || busy} onClick={() => void start()}>
          {busy ? "Starting…" : "Generate music"}</button>
      </div>
    </>}
    {error && <p className="studio-error" role="alert">{error}</p>}
    {recent.map(job => <div key={job.id} className="studio-music-job">
      <strong>{job.description}</strong>
      <p role="status" className={job.status === "failed" ? "studio-error" : "studio-hint"}>{musicJobText(job)}</p>
      {canWrite && musicJobActive(job) && !job.cancel_requested
        && <button type="button" className="studio-link" onClick={() => void cancel(job)}>Cancel this track</button>}
    </div>)}
  </section>;
}
