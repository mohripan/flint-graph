import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import type { ImageJob } from "../lib/api";
import { proposalActions } from "./assistantModel";
import { CharacterProfilesContext } from "./characterImages";
import { isActive, jobStatus } from "./characterModel";
import { imageJobStarted } from "./imageJobs";
import { mergeActionJobs } from "./imageJobModel";
import { refreshLibrary } from "./libraryAssets";
import type { AssistantProposal, StoryDraft } from "./types";

const message = (error: unknown) => error instanceof Error && error.message ? error.message : "Could not start generating.";

// A suggestion has a stable server identity: remounting only reads its existing job.
export function ProposalActions({ proposal, story, tenantId, projectId, canWrite }: {
  proposal: AssistantProposal; story: StoryDraft | null; tenantId: string; projectId: string; canWrite: boolean;
}) {
  const profiles = useContext(CharacterProfilesContext);
  const mounted = useRef(false), pending = useRef(new Set<number>());
  const [loaded, setLoaded] = useState(false);
  const [jobs, setJobs] = useState<Record<number, ImageJob | null>>({});
  const [busy, setBusy] = useState<Record<number, boolean>>({});
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const actions = proposalActions(story, proposal.operations);
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const rows = await api.listAssistantImageActions(tenantId, projectId, proposal.id, signal);
      if (!mounted.current || signal?.aborted) return;
      setJobs(current => mergeActionJobs(current, rows));
      setLoaded(true); setLoadError(null);
    } catch (error) {
      if (mounted.current && !signal?.aborted) setLoadError(message(error));
    }
  }, [tenantId, projectId, proposal.id]);
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    if (actions.length && proposal.status !== "rejected") void load(controller.signal);
    return () => { mounted.current = false; controller.abort(); };
  }, [load, proposal.status, actions.length]);
  const active = Object.values(jobs).some(isActive);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => void load(controller.signal), 1500);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [active, load]);
  const completed = Object.values(jobs).filter(job => job?.status === "completed").map(job => job!.id).sort().join(",");
  useEffect(() => { if (completed) refreshLibrary(); }, [completed]);
  if (!actions.length || proposal.status === "rejected") return null;

  async function start(index: number) {
    if (pending.current.has(index) || !loaded || proposal.status !== "accepted" || jobs[index]) return;
    pending.current.add(index); setBusy(current => ({ ...current, [index]: true }));
    setErrors(current => ({ ...current, [index]: "" }));
    try {
      const job = await api.startAssistantImageAction(tenantId, projectId, proposal.id, index);
      imageJobStarted(tenantId, projectId, job);
      if (mounted.current) {
        setJobs(current => ({ ...current, [index]: job }));
        if (job.character_id) void profiles?.reload();
      }
    } catch (error) {
      if (mounted.current) setErrors(current => ({ ...current, [index]: message(error) }));
    } finally {
      pending.current.delete(index);
      if (mounted.current) setBusy(current => ({ ...current, [index]: false }));
    }
  }

  return <div className="assistant-actions" aria-label="Suggested image generation">
    <strong>Suggested pictures</strong>
    {loadError && <p className="studio-error" role="alert">{loadError} <button type="button" className="studio-link"
      onClick={() => void load()}>Refresh status</button></p>}
    <ul>{actions.map(({ index, action, label, ready }) => {
      const job = jobs[index];
      return <li key={index}>
        <span>{label}</span>
        {action.op === "generate_character_images" && <small className="studio-hint">
          {(action.hires ?? action.transparent) ? "High resolution (2×)" : "Standard resolution"}</small>}
        {job ? <small className="studio-hint" role="status">
          {jobStatus(job).replace(/portraits?/g, word => job.purpose === "background" ? word.replace("portrait", "background") : word)}
          {isActive(job) && <progress max={job.count} value={job.progress} aria-label="Generated images" />}
          {job.status === "completed" && ` · Review in ${job.purpose === "background" ? "Assets" : "Characters"}.`}
        </small> : canWrite && <button type="button" className="studio-secondary"
          disabled={!ready || proposal.status !== "accepted" || !loaded || busy[index]}
          onClick={() => void start(index)}>{busy[index] ? "Starting…" : !loaded ? "Checking…" : "Generate"}</button>}
        {proposal.status !== "accepted" && <small className="studio-hint">Accept the proposal before generating its images.</small>}
        {errors[index] && <small className="studio-error" role="alert">{errors[index]}</small>}
      </li>;
    })}</ul>
  </div>;
}
