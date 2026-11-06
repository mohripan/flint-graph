import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import type { ImageJob, NarrativeImage, VoiceJob } from "../lib/api";
import { CreditCost } from "../components/CreditCost";
import { useAccessRefresh } from "../site/accessContext";
import { imageItem, voiceItem } from "../site/creditsModel";
import { actionClick, actionJob, actionState, actionWatching, clipUse, imageUse, mergeAction } from "./assistantActions";
import type { ActionStatus, ImageUse } from "./assistantActions";
import type { Attachment } from "./assistantLibrary";
import { proposalActions } from "./assistantModel";
import { CharacterProfilesContext, useNarrativeImage } from "./characterImages";
import { refreshLibrary } from "./libraryAssets";
import { bindAsset, expressionId, setSprite } from "./stageModel";
import { StudioDialog } from "./StudioDialog";
import { ClipPlayButton } from "./VoiceControls";
import { setLineClip, setLineVoice } from "./voiceModel";
import type { AssistantAction, AssistantProposal, StoryDraft } from "./types";

const message = (error: unknown, fallback: string) => error instanceof Error && error.message ? error.message : fallback;
const POLL_MS = 1500;
// Each picture action starts one job of four candidates on the server.
const CANDIDATES = 4;

function cost(action: AssistantAction, voiceModel: string | null | undefined): [string, number] {
  switch (action.op) {
    case "generate_character_images":
      return [imageItem({ purpose: "character_portrait", transparent: action.transparent, hires: action.hires ?? action.transparent }), CANDIDATES];
    case "generate_expressions": return [imageItem({ purpose: "character_expression" }), action.expressions.length];
    case "generate_cg": return [imageItem({ purpose: "scene_art" }), CANDIDATES * action.characters.length];
    case "generate_voice": return [voiceItem(voiceModel ?? "kokoro-82m"), action.lines.length];
    default: return [imageItem({ purpose: "background" }), CANDIDATES];
  }
}

function applyImageUse(story: StoryDraft, use: ImageUse, asset: NarrativeImage): StoryDraft {
  const bound = bindAsset(story, asset);
  return setSprite(bound.story, use.character, use.expression ?? expressionId(bound.story, use.character, asset.name), bound.key);
}
function applyClipUse(story: StoryDraft, node: string, asset: NarrativeImage): StoryDraft {
  const line = story.nodes[node];
  if (line?.type !== "line") throw new Error("This line no longer exists.");
  const mode = asset.provenance.mode === "vocalization" ? "vocalization" : "full";
  const voiced = line.voice?.mode === mode ? story
    : setLineVoice(story, node, mode, mode === "vocalization" ? String(asset.provenance.text ?? "") : undefined);
  return setLineClip(voiced, node, asset);
}

function Candidate({ tenantId, projectId, asset, label, cutOut }: {
  tenantId: string; projectId: string; asset: NarrativeImage; label: string; cutOut: boolean;
}) {
  const thumbnail = useNarrativeImage(tenantId, projectId, asset.id, "thumbnail");
  const [open, setOpen] = useState(false);
  const full = useNarrativeImage(tenantId, projectId, open ? asset.id : null, "image");
  return <>
    <button type="button" className={`assistant-candidate ${cutOut ? "is-cutout" : ""}`} aria-label={`View ${label}`} onClick={() => setOpen(true)}>
      {thumbnail ? <img src={thumbnail} alt="" /> : <span className="assistant-candidate-empty" />}
    </button>
    {open && <StudioDialog label={label} onClose={() => setOpen(false)}>
      <div className="studio-peek-body assistant-candidate-peek">
        {full ? <img src={full} alt={label} /> : <p className="studio-hint">Loading…</p>}
        <button type="button" className="studio-secondary" onClick={() => setOpen(false)}>Close</button>
      </div>
    </StudioDialog>}
  </>;
}

// A generation action in the chat: what it is, where it has got to, and its results to
// approve. A suggestion has a stable server identity, so remounting only reads its job.
export function ProposalActions({ proposal, story, tenantId, projectId, canWrite, dirty, onApply, onAttach }: {
  proposal: AssistantProposal; story: StoryDraft | null; tenantId: string; projectId: string; canWrite: boolean;
  dirty: boolean; onApply: (change: (story: StoryDraft) => StoryDraft, notice: string) => Promise<void>;
  onAttach?: (item: Attachment) => void;
}) {
  const profiles = useContext(CharacterProfilesContext);
  const refreshAccess = useAccessRefresh();
  const mounted = useRef(false), pending = useRef(new Set<number>());
  const [loaded, setLoaded] = useState(false);
  const [statuses, setStatuses] = useState<Record<number, ActionStatus>>({});
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const actions = proposalActions(story, proposal.operations);
  const merge = useCallback((rows: ActionStatus[]) => setStatuses(current => {
    const next = { ...current };
    for (const row of rows) next[row.index] = mergeAction(current[row.index], row);
    return next;
  }), []);
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const rows = await api.listAssistantActions(tenantId, projectId, proposal.id, signal);
      if (!mounted.current || signal?.aborted) return;
      merge(rows); setLoaded(true); setLoadError(null);
    } catch (error) {
      if (mounted.current && !signal?.aborted) setLoadError(message(error, "Couldn't read these."));
    }
  }, [tenantId, projectId, proposal.id, merge]);
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    if (actions.length) void load(controller.signal);
    return () => { mounted.current = false; controller.abort(); };
  }, [load, proposal.status, actions.length]);
  const watching = Object.values(statuses).some(actionWatching);
  useEffect(() => {
    if (!watching) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => { if (document.visibilityState !== "hidden") void load(controller.signal); }, POLL_MS);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [watching, load]);
  // The worker may start jobs on its own, so a new job is when the balance changed.
  const jobIds = Object.values(statuses).map(status => actionJob(status)?.id).filter(Boolean).sort().join(",");
  useEffect(() => { if (jobIds) refreshAccess(); }, [jobIds, refreshAccess]);
  const completed = Object.values(statuses).map(actionJob).filter(job => job?.status === "completed").map(job => job!.id).sort().join(",");
  useEffect(() => { if (completed) { refreshLibrary(); void profiles?.reload(); } }, [completed]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!actions.length || proposal.status === "rejected") return null;

  function run(key: string, work: () => Promise<void>, fallback: string) {
    setBusy(current => ({ ...current, [key]: true }));
    setErrors(current => ({ ...current, [key]: "" }));
    void work().catch(error => {
      if (mounted.current) setErrors(current => ({ ...current, [key]: message(error, fallback) }));
    }).finally(() => { if (mounted.current) setBusy(current => ({ ...current, [key]: false })); });
  }
  function start(index: number) {
    if (pending.current.has(index)) return;
    pending.current.add(index);
    run(`start:${index}`, async () => {
      try { merge([await api.startAssistantAction(tenantId, projectId, proposal.id, index)]); }
      finally { pending.current.delete(index); }
    }, "Couldn't start this.");
  }
  async function approved(asset: NarrativeImage): Promise<NarrativeImage> {
    if (asset.status === "approved") return asset;
    const saved = await api.approveNarrativeAsset(tenantId, projectId, asset.id);
    refreshLibrary();
    await load();
    return saved;
  }
  function approve(asset: NarrativeImage) {
    run(`asset:${asset.id}`, async () => { await approved(asset); }, "Couldn't approve this.");
  }
  function usePicture(asset: NarrativeImage, use: ImageUse) {
    run(`asset:${asset.id}`, async () => {
      const saved = await approved(asset);
      await onApply(current => applyImageUse(current, use, saved), `Put ${saved.name} on stage.`);
    }, "Couldn't use this picture.");
  }
  function useClip(asset: NarrativeImage, node: string) {
    run(`asset:${asset.id}`, async () => {
      const saved = await approved(asset);
      await onApply(current => applyClipUse(current, node, saved), "Added the voice to its line.");
    }, "Couldn't use this clip.");
  }

  function pictures(job: ImageJob) {
    return <ul className="assistant-candidates">{job.assets.map(asset => {
      const use = imageUse(job, asset, story), key = `asset:${asset.id}`;
      return <li key={asset.id}>
        <Candidate tenantId={tenantId} projectId={projectId} asset={asset} label={asset.name} cutOut={job.transparent} />
        {use?.done ? <small className="studio-hint">On stage</small>
          : canWrite && use ? <button type="button" className="studio-secondary" aria-disabled={dirty || busy[key]}
            title={dirty ? "Save your edits first." : undefined} onClick={() => { if (!dirty && !busy[key]) usePicture(asset, use); }}>{use.label}</button>
          : asset.status === "approved" ? <small className="studio-hint">Approved</small>
          : canWrite && <button type="button" className="studio-secondary" aria-disabled={busy[key]}
            onClick={() => { if (!busy[key]) approve(asset); }}>Approve</button>}
        {canWrite && onAttach && asset.status === "approved" && <button type="button" className="studio-link"
          onClick={() => onAttach({ kind: "asset", id: asset.id, name: asset.name, asset_kind: asset.kind })}>Attach to message</button>}
        {errors[key] && <small className="studio-error" role="alert">{errors[key]}</small>}
      </li>;
    })}</ul>;
  }
  function clips(job: VoiceJob) {
    return <ul className="assistant-clips">{job.assets.map(asset => {
      const use = clipUse(asset, story), key = `asset:${asset.id}`;
      return <li key={asset.id}>
        <ClipPlayButton assetId={asset.id} />
        <span>{String(asset.provenance.text ?? asset.name)}</span>
        {use?.done ? <small className="studio-hint">On the line</small>
          : canWrite && use ? <button type="button" className="studio-secondary" aria-disabled={dirty || busy[key]}
            title={dirty ? "Save your edits first." : undefined} onClick={() => { if (!dirty && !busy[key]) useClip(asset, use.node); }}>{use.label}</button>
          : asset.status === "approved" ? <small className="studio-hint">Approved</small> : null}
        {errors[key] && <small className="studio-error" role="alert">{errors[key]}</small>}
      </li>;
    })}</ul>;
  }

  return <div className="assistant-actions" aria-label="Generation">
    {loadError && <p className="studio-error" role="alert">{loadError} <button type="button" className="studio-link"
      onClick={() => void load()}>Refresh</button></p>}
    <ul>{actions.map(({ index, action, label }) => {
      const status = statuses[index];
      const state = status ? actionState(status) : { text: loaded ? "" : "Checking…", tone: "muted" as const };
      const click = status && canWrite ? actionClick(status) : null;
      const job = status ? actionJob(status) : null;
      const voice = action.op === "generate_voice" ? profiles?.profiles[action.character]?.voice_model : null;
      const active = job && (job.status === "queued" || job.status === "running");
      return <li key={index}>
        <span>{label}</span>
        {click && <span className="assistant-action-start">
          <CreditCost item={cost(action, voice)[0]} quantity={cost(action, voice)[1]} />
          <button type="button" className="studio-secondary" disabled={busy[`start:${index}`]}
            onClick={() => start(index)}>{busy[`start:${index}`] ? "Starting…" : click}</button></span>}
        {state.text && <small className={state.tone === "bad" ? "studio-error" : "studio-hint"} role="status">
          {state.text}{active && <progress max={job.count} value={job.progress} aria-label="Progress" />}</small>}
        {errors[`start:${index}`] && <small className="studio-error" role="alert">{errors[`start:${index}`]}</small>}
        {status?.image_job?.status === "completed" && pictures(status.image_job)}
        {status?.voice_job?.status === "completed" && clips(status.voice_job)}
      </li>;
    })}</ul>
  </div>;
}
