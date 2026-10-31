import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../lib/api";
import type {
  CharacterProfile, NarrativeImage, VoiceCatalog, VoiceJob, VoiceJobItem, VoiceLicenseText, VoiceModelOption,
} from "../lib/api";
import { CharacterProfilesContext } from "./characterImages";
import { libraryAsset, refreshLibrary, useApprovedAssets } from "./libraryAssets";
import type { StoryDraft } from "./types";
import {
  VOCALIZATION_EXAMPLES, VOCALIZATION_LIMIT, clipIsStale, missingClips, setLineClip, setLineVoice, spokenText, voiceChoice,
} from "./voiceModel";
import type { VoiceChoice } from "./voiceModel";
import { StudioDialog } from "./StudioDialog";
import { useVoiceReferences } from "./VoiceReferences";
import { DELIVERIES, DELIVERY_LABELS, TAG_LABELS, lineDelivery, spokenDelivery } from "./voiceDelivery";
import type { Delivery, DeliveryName } from "./voiceDelivery";

// Voiced lines in the script (ADR 0043/0044): pick silent, full voice or a vocalization per
// line and how it is delivered, generate clips with the speaker's voice model (a stock
// voice or a cloned reference), and bind an approved clip.
const message = (error: unknown, fallback: string) => error instanceof Error && error.message ? error.message : fallback;
const active = (job: VoiceJob) => job.status === "queued" || job.status === "running";
const ERRORS: Record<string, string> = {
  empty_speech: "The model could not say this. Try other words or a different sound.",
  gpu_busy: "The GPU is busy with other work. Try again when image generation finishes.",
  reference_deleted: "The voice reference was deleted. Choose another one in Characters.",
  reference_invalid: "The model could not use this voice reference. Try another recording.",
  reference_unavailable: "The voice reference could not be read. Try again.",
  generation_timeout: "Voice generation took too long. Try again.",
  voice_generation_unavailable: "The voice worker is not running.",
  cancelled: "Cancelled.",
};

// ---- Audio playback ---------------------------------------------------------------------

const audioUrls = new Map<string, Promise<string>>();
let playing: HTMLAudioElement | null = null;

export function ClipPlayButton({ assetId, label = "Play" }: { assetId: string; label?: string }) {
  const context = useContext(CharacterProfilesContext);
  const [state, setState] = useState<"idle" | "loading" | "playing" | "failed">("idle");
  const audio = useRef<HTMLAudioElement | null>(null);
  useEffect(() => () => { audio.current?.pause(); }, []);
  async function toggle() {
    if (state === "playing") { audio.current?.pause(); setState("idle"); return; }
    if (!context) return;
    const key = `${context.tenantId}:${context.projectId}:${assetId}`;
    let pending = audioUrls.get(key);
    if (!pending) {
      pending = api.getNarrativeAudio(context.tenantId, context.projectId, assetId).then(blob => URL.createObjectURL(blob));
      audioUrls.set(key, pending);
      pending.catch(() => audioUrls.delete(key));
    }
    setState("loading");
    try {
      const element = audio.current ?? new Audio();
      audio.current = element;
      element.src = await pending;
      element.onended = () => setState("idle");
      playing?.pause();
      playing = element;
      await element.play();
      setState("playing");
    } catch { setState("failed"); }
  }
  return <button type="button" className="studio-link studio-play" aria-label={`${state === "playing" ? "Stop" : label} clip`}
    onClick={() => void toggle()}>
    {state === "playing" ? "■ Stop" : state === "loading" ? "Loading…" : state === "failed" ? "Can't play" : `▶ ${label}`}</button>;
}

// ---- Voice jobs for the open scene --------------------------------------------------------

interface VoiceJobs {
  jobs: VoiceJob[]; refresh: () => void;
  start: (character: string, items: VoiceJobItem[]) => Promise<void>;
  catalog: VoiceCatalog | null;
  deliveries: Record<string, Delivery>;
  setDelivery: (nodeId: string, delivery: Delivery | null) => Promise<void>;
}

/** Whether a character can speak: a stock voice or a reference to clone. */
export const hasVoice = (profile: CharacterProfile | undefined) => Boolean(profile?.voice || profile?.voice_reference_id);

/** The model a character's clips are made with (Kokoro when only a voice ID is stored). */
export function speakerModel(catalog: VoiceCatalog | null, profile: CharacterProfile | undefined): VoiceModelOption | undefined {
  const id = profile?.voice_model ?? (profile?.voice ? "kokoro-82m" : undefined);
  return id ? catalog?.models.find(model => model.id === id) : undefined;
}
const VoiceJobsContext = createContext<VoiceJobs | null>(null);

export function VoiceJobsProvider({ children }: { children: ReactNode }) {
  const context = useContext(CharacterProfilesContext);
  const tenantId = context?.tenantId ?? "", projectId = context?.projectId ?? "";
  const [jobs, setJobs] = useState<VoiceJob[]>([]);
  const refresh = useCallback(() => {
    if (!projectId) return;
    api.listVoiceJobs(tenantId, projectId).then(listed => setJobs(listed.jobs)).catch(() => undefined);
  }, [tenantId, projectId]);
  useEffect(() => { refresh(); }, [refresh]);
  const running = jobs.filter(active).map(job => job.id).join(",");
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      for (const id of running.split(",")) {
        api.getVoiceJob(tenantId, projectId, id).then(job => {
          setJobs(current => current.map(item => item.id === job.id ? job : item));
          if (!active(job)) refreshLibrary();
        }).catch(() => undefined);
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [running, tenantId, projectId]);
  const { catalog } = useVoiceCatalog(tenantId, projectId);
  const [deliveries, setDeliveries] = useState<Record<string, Delivery>>({});
  useEffect(() => {
    if (!projectId) return;
    api.listLineDeliveries(tenantId, projectId).then(listed => setDeliveries(Object.fromEntries(
      listed.deliveries.map(item => [item.node_id, { emotion: item.emotion as DeliveryName, intensity: item.intensity, tag: item.tag }]),
    ))).catch(() => undefined);
  }, [tenantId, projectId]);
  const setDelivery = useCallback(async (nodeId: string, delivery: Delivery | null) => {
    if (delivery) await api.setLineDelivery(tenantId, projectId, nodeId, delivery);
    else await api.clearLineDelivery(tenantId, projectId, nodeId);
    setDeliveries(current => {
      const { [nodeId]: _, ...rest } = current;
      return delivery ? { ...rest, [nodeId]: delivery } : rest;
    });
  }, [tenantId, projectId]);
  const start = useCallback(async (character: string, items: VoiceJobItem[]) => {
    const job = await api.createVoiceJob(tenantId, projectId, character, items);
    setJobs(current => [job, ...current.filter(item => item.id !== job.id)]);
  }, [tenantId, projectId]);
  const value = useMemo(() => ({ jobs, refresh, start, catalog, deliveries, setDelivery }),
    [jobs, refresh, start, catalog, deliveries, setDelivery]);
  return <VoiceJobsContext.Provider value={value}>{children}</VoiceJobsContext.Provider>;
}

/** Queue one job per speaker for the voiced lines of a scene that have no clip yet. */
export function SceneVoices({ story, ids, readOnly, onError }: {
  story: StoryDraft; ids: string[]; readOnly: boolean; onError: (message: string) => void;
}) {
  const jobs = useContext(VoiceJobsContext);
  const profiles = useContext(CharacterProfilesContext)?.profiles ?? {};
  const pending = new Set(jobs?.jobs.filter(active).flatMap(job => job.items.map(item => item.node_id)) ?? []);
  const missing = Object.entries(missingClips(story, ids))
    .map(([speaker, items]) => [speaker, items.filter(item => !pending.has(item.node_id))] as const)
    .filter(([, items]) => items.length);
  const count = missing.reduce((total, [, items]) => total + items.length, 0);
  if (readOnly || !jobs || !count) return null;
  const silent = missing.filter(([speaker]) => !hasVoice(profiles[speaker])).map(([speaker]) => story.characters[speaker]?.name ?? speaker);
  const delivered = (speaker: string, item: { mode: "full" | "vocalization"; text: string; node_id: string }): VoiceJobItem => {
    const node = story.nodes[item.node_id];
    const wanted = lineDelivery(jobs.deliveries[item.node_id], node?.type === "line" ? node.expression : undefined).delivery;
    return { ...item, delivery: spokenDelivery(speakerModel(jobs.catalog, profiles[speaker]), wanted).delivery };
  };
  return <div className="studio-scene-voices">
    <button type="button" className="studio-secondary" disabled={silent.length === missing.length} onClick={() => void (async () => {
      try {
        for (const [speaker, items] of missing) {
          if (!hasVoice(profiles[speaker])) continue;
          const spoken = items.map(item => delivered(speaker, item));
          for (let index = 0; index < spoken.length; index += 24) await jobs.start(speaker, spoken.slice(index, index + 24));
        }
      } catch (error) { onError(message(error, "Could not start generating voices.")); }
    })()}>Generate {count} missing {count === 1 ? "voice" : "voices"}</button>
    {silent.length > 0 && <span className="studio-hint">Choose a voice for {silent.join(", ")} in Characters.</span>}
  </div>;
}

// ---- One line's voice ----------------------------------------------------------------------

export function LineVoiceControls({ story, id, readOnly, onChange, onError }: {
  story: StoryDraft; id: string; readOnly: boolean;
  onChange: (story: StoryDraft, group?: string) => void; onError: (message: string) => void;
}) {
  const context = useContext(CharacterProfilesContext);
  const jobs = useContext(VoiceJobsContext);
  const tenantId = context?.tenantId ?? "", projectId = context?.projectId ?? "";
  const { assets } = useApprovedAssets(tenantId, projectId);
  const node = story.nodes[id];
  const voice = node?.type === "line" ? node.voice : undefined;
  const [sound, setSound] = useState(voice?.text ?? "");
  useEffect(() => { setSound(voice?.text ?? ""); }, [voice?.text]);
  if (node?.type !== "line" || !node.speaker) return null;
  const speaker = node.speaker;
  const choice = voiceChoice(node);
  const run = (action: () => void) => { try { action(); } catch (error) { onError(message(error, "Could not change the voice.")); } };
  const choose = (next: VoiceChoice) => run(() => onChange(setLineVoice(story, id, next), `${id}:voice`));
  const commitSound = () => { if (voice?.mode === "vocalization" && sound.trim() !== voice.text) run(() => onChange(setLineVoice(story, id, "vocalization", sound), `${id}:voice-text`)); };
  const select = <select aria-label="Voice" className="studio-script-voice" disabled={readOnly} value={choice}
    onChange={event => choose(event.target.value as VoiceChoice)}>
    <option value="silent">Silent</option><option value="full">Full voice</option><option value="vocalization">Vocalization only</option>
  </select>;
  if (!voice) return <div className="studio-line-voice">{select}</div>;

  const bound = voice.audio ? libraryAsset(assets, story.assets[voice.audio]?.sha256) : undefined;
  const text = spokenText(story, id);
  const lineJobs = jobs?.jobs.filter(job => job.character_id === speaker && job.items.some(item => item.node_id === id)) ?? [];
  const running = lineJobs.find(active);
  const candidates = lineJobs.flatMap(job => job.assets).filter(asset => asset.status === "candidate"
    && asset.provenance.node_id === id && asset.provenance.mode === voice.mode && asset.provenance.text === text);
  const failed = !running && !candidates.length && lineJobs[0]?.status === "failed" ? lineJobs[0] : undefined;
  const voiceId = hasVoice(context?.profiles[speaker]);
  const model = speakerModel(jobs?.catalog ?? null, context?.profiles[speaker]);
  const chosen = lineDelivery(jobs?.deliveries[id], node.expression);
  const spoken = spokenDelivery(model, chosen.delivery);
  const choices = (assets ?? []).filter(asset => asset.kind === "voice" && (!asset.character_id || asset.character_id === speaker));
  const use = (asset: NarrativeImage) => void (async () => {
    try {
      const approved = asset.status === "approved" ? asset : await api.approveNarrativeAsset(tenantId, projectId, asset.id);
      refreshLibrary();
      jobs?.refresh();
      onChange(setLineClip(story, id, approved), `${id}:voice-clip`);
    } catch (error) { onError(message(error, "Could not use this clip.")); }
  })();
  const generate = () => void jobs?.start(speaker, [{ mode: voice.mode, text, node_id: id, delivery: spoken.delivery }])
    .catch(error => onError(message(error, "Could not start generating the voice.")));
  const deliver = (next: Delivery | null) => void jobs?.setDelivery(id, next)
    .catch(error => onError(message(error, "Could not save the delivery.")));
  const delivery = <span className="studio-line-delivery">
    <select aria-label="Delivery" disabled={readOnly} value={chosen.delivery.emotion} onChange={event =>
      deliver({ ...chosen.delivery, emotion: event.target.value as DeliveryName })}>
      {DELIVERIES.map(name => <option key={name} value={name}>
        {DELIVERY_LABELS[name]}{model && !model.deliveries[name] ? ` (not with ${model.name})` : ""}</option>)}
    </select>
    {chosen.delivery.emotion !== "neutral" && <input type="range" aria-label="Intensity" min={0} max={1} step={0.1}
      disabled={readOnly} value={chosen.delivery.intensity}
      onChange={event => deliver({ ...chosen.delivery, intensity: Number(event.target.value) })} />}
    {model && model.tags.length > 0 && <select aria-label="Sound before the line" disabled={readOnly} value={chosen.delivery.tag ?? ""}
      onChange={event => deliver({ ...chosen.delivery, tag: event.target.value || null })}>
      <option value="">No sound</option>
      {model.tags.map(tag => <option key={tag} value={tag}>{TAG_LABELS[tag] ?? tag}</option>)}
    </select>}
    {chosen.source === "expression" && <span className="studio-voice-note">from the expression</span>}
    {chosen.source === "override" && !readOnly && <button type="button" className="studio-link" onClick={() => deliver(null)}>
      Use expression</button>}
    {spoken.note && <span className="studio-voice-note" role="note">{spoken.note}</span>}
  </span>;
  return <div className="studio-line-voice">
    {select}
    {delivery}
    {voice.mode === "vocalization" && <input aria-label="Sound" className="studio-script-sound" readOnly={readOnly}
      maxLength={VOCALIZATION_LIMIT} value={sound} list="studio-vocalizations" placeholder="fufu"
      onChange={event => setSound(event.target.value)} onBlur={commitSound}
      onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); commitSound(); } }} />}
    <datalist id="studio-vocalizations">{VOCALIZATION_EXAMPLES.map(item => <option key={item} value={item} />)}</datalist>
    {bound ? <span className="studio-voice-clip">
      <ClipPlayButton assetId={bound.id} />
      {clipIsStale(story, id, bound) && <span className="studio-voice-note">The words changed since this clip was made.</span>}
      {!readOnly && <>
        {voiceId && <button type="button" className="studio-link" disabled={Boolean(running)} onClick={generate}>
          {running ? "Generating…" : "Regenerate"}</button>}
        <button type="button" className="studio-link studio-danger" onClick={() => run(() => onChange(setLineClip(story, id, null), `${id}:voice-clip`))}>Remove clip</button>
      </>}
      {candidates.filter(asset => asset.id !== bound.id).slice(0, 2).map(asset => <span key={asset.id} className="studio-voice-clip candidate">
        <span className="studio-voice-note">New take</span>
        <ClipPlayButton assetId={asset.id} label="Listen" />
        {!readOnly && <>
          <button type="button" className="studio-secondary" onClick={() => use(asset)}>Use this take</button>
          <button type="button" className="studio-link studio-danger" onClick={() => void api.discardNarrativeImage(tenantId, projectId, asset.id)
            .then(() => jobs?.refresh(), error => onError(message(error, "Could not discard.")))}>Discard</button>
        </>}
      </span>)}
    </span>
    : voice.audio ? <span className="studio-voice-note">Clip bound: {voice.audio}</span>
    : candidates.length ? candidates.slice(0, 2).map(asset => <span key={asset.id} className="studio-voice-clip candidate">
      <ClipPlayButton assetId={asset.id} label="Listen" />
      {!readOnly && <>
        <button type="button" className="studio-secondary" onClick={() => use(asset)}>Use this clip</button>
        <button type="button" className="studio-link studio-danger" onClick={() => void api.discardNarrativeImage(tenantId, projectId, asset.id)
          .then(() => jobs?.refresh(), error => onError(message(error, "Could not discard.")))}>Discard</button>
      </>}
    </span>)
    : running ? <span className="studio-voice-note" role="status">Generating voice… {running.progress}/{running.count}</span>
    : !readOnly && <span className="studio-voice-clip">
      {voiceId ? <button type="button" className="studio-link" onClick={generate}>Generate voice</button>
        : <span className="studio-voice-note">Choose a voice for {story.characters[speaker]?.name ?? speaker} in Characters to generate clips.</span>}
      {choices.length > 0 && <select aria-label="Use a voice clip" value="" onChange={event => {
        const picked = choices.find(asset => asset.id === event.target.value);
        if (picked) use(picked);
      }}><option value="">Choose a clip…</option>
        {choices.map(asset => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</select>}
      {failed && <span className="studio-voice-note">{ERRORS[failed.error_code ?? ""] ?? "Voice generation failed."}</span>}
    </span>}
  </div>;
}

// ---- A character's voice -----------------------------------------------------------------

const catalogs = new Map<string, Promise<VoiceCatalog>>();

/** The server's installed voice models, with this creator's license acceptances. */
export function useVoiceCatalog(tenantId: string, projectId: string) {
  const [catalog, setCatalog] = useState<VoiceCatalog | null>(null);
  const load = useCallback((fresh = false) => {
    if (!projectId) return;
    const key = `${tenantId}:${projectId}`;
    if (fresh) catalogs.delete(key);
    let pending = catalogs.get(key);
    if (!pending) {
      pending = api.getVoiceCatalog(tenantId, projectId);
      catalogs.set(key, pending);
      pending.catch(() => catalogs.delete(key));
    }
    // A server from before ADR 0044 sends no models: offer none until it is restarted.
    pending.then(found => setCatalog({ ...found, models: found.models ?? [] }), () => undefined);
  }, [tenantId, projectId]);
  useEffect(() => { load(); }, [load]);
  return { catalog, reload: () => load(true) };
}

/** The license of a model whose audio carries duties, accepted before first use (#178). */
export function LicenseDialog({ tenantId, model, onAccepted, onClose }: {
  tenantId: string; model: VoiceModelOption; onAccepted: () => void; onClose: () => void;
}) {
  const [license, setLicense] = useState<VoiceLicenseText | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.getVoiceLicense(tenantId, model.license.id).then(setLicense, failure => setError(message(failure, "Could not load the license.")));
  }, [tenantId, model.license.id]);
  async function accept() {
    if (!license || busy) return;
    setBusy(true);
    try { await api.acceptVoiceLicense(tenantId, model.id, license.sha256); onAccepted(); }
    catch (failure) { setError(message(failure, "Could not record your acceptance.")); }
    finally { setBusy(false); }
  }
  const duties = model.license.obligations === "player_terms"
    ? "Every game that ships this model's audio will carry the license in its NOTICES and show players a one-time license screen."
    : model.license.obligations === "attribution" ? "Every game that ships this model's audio will carry the license in its NOTICES." : "";
  return <StudioDialog label={`${model.license.name} for ${model.name}`} onClose={onClose}>
    <div className="studio-peek-body studio-license">
      <h2>Accept the {model.license.name}?</h2>
      <p><strong>{model.name}</strong> puts duties on the audio you make with it. In short:</p>
      <p>{model.license.summary}</p>
      {duties && <p className="studio-hint">{duties} You can regenerate a line with another model to drop its duties from a release.</p>}
      {error && <p className="studio-notice" role="alert">{error}</p>}
      {license ? <pre className="studio-license-text" tabIndex={0} aria-label="License text">{license.text}</pre>
        : !error && <p className="studio-hint">Loading the license…</p>}
      <p className="studio-hint">Your acceptance is recorded for you in this workspace with the license's fingerprint
        ({model.license.sha256.slice(0, 12)}…). A changed license asks again.</p>
      <div className="studio-actions">
        <button type="button" className="studio-primary" disabled={!license || busy} onClick={() => void accept()}>
          {busy ? "Recording…" : "I accept this license"}</button>
        <button type="button" className="studio-secondary" onClick={onClose}>Cancel</button>
      </div>
    </div>
  </StudioDialog>;
}

export function CharacterVoice({ id, name, readOnly, onError }: {
  id: string; name: string; readOnly: boolean; onError: (message: string) => void;
}) {
  const context = useContext(CharacterProfilesContext);
  const tenantId = context?.tenantId ?? "", projectId = context?.projectId ?? "";
  const profile = context?.profiles[id];
  const { catalog, reload } = useVoiceCatalog(tenantId, projectId);
  const { references } = useVoiceReferences(tenantId, projectId, !readOnly);
  const saved = profile?.voice_model ?? (profile?.voice ? "kokoro-82m" : "");
  const [modelId, setModelId] = useState(saved);
  useEffect(() => { setModelId(saved); }, [saved]);
  const [licenseFor, setLicenseFor] = useState<VoiceModelOption | null>(null);
  const [sample, setSample] = useState<VoiceJob | null>(null);
  const sampleId = sample && active(sample) ? sample.id : null;
  useEffect(() => {
    if (!sampleId) return;
    const timer = window.setInterval(() => {
      api.getVoiceJob(tenantId, projectId, sampleId).then(setSample).catch(() => undefined);
    }, 1200);
    return () => window.clearInterval(timer);
  }, [sampleId, tenantId, projectId]);
  if (!catalog) return null;
  const model = catalog.models.find(item => item.id === modelId);
  const save = (choice: { voice?: string | null; reference_id?: string | null; model?: string | null }) => void api.setCharacterVoice(
    tenantId, projectId, id, profile?.version ?? 0, choice.voice ?? null, undefined,
    { model: choice.model ?? null, reference_id: choice.reference_id ?? null },
  ).then(updated => context?.put(updated), error => onError(message(error, "Could not choose the voice.")));
  const pickModel = (next: string) => {
    if (!next) { setModelId(""); save({}); return; }
    const picked = catalog.models.find(item => item.id === next);
    if (picked && !picked.accepted) { setLicenseFor(picked); return; }
    setModelId(next);
  };
  const current = profile?.voice_reference_id ? `reference:${profile.voice_reference_id}` : profile?.voice ? `voice:${profile.voice}` : "";
  const choosable = model && model.id === saved ? current : "";
  const groups = model?.default
    ? ["American", "British"].map(accent => [`${accent} English`, catalog.voices.filter(voice => voice.accent === accent)
      .map(voice => ({ id: voice.id, name: `${voice.name} (${voice.gender})` }))] as const)
    : model ? [[model.name, model.stock_voices.map(voice => ({ id: voice.id, name: `${voice.name}: ${voice.description}` }))] as const] : [];
  const ready = Boolean(model && model.id === saved && (profile?.voice || profile?.voice_reference_id));
  const clip = sample?.assets[0];
  return <div className="studio-character-voice">
    <label className="studio-field"><span>Voice model</span>
      <select value={modelId} disabled={readOnly} onChange={event => pickModel(event.target.value)}>
        <option value="">No voice (lines stay silent)</option>
        {catalog.models.map(item => <option key={item.id} value={item.id}>
          {item.name}{item.cloning ? " · clones a voice" : ""}{item.license.obligations !== "none" ? " · license duties" : ""}</option>)}
      </select></label>
    {model && <p className="studio-hint">{model.description} License: {model.license.name}.
      {model.watermark === "perth" ? " Clips carry an inaudible watermark." : ""}</p>}
    {model && <label className="studio-field"><span>{model.cloning ? "Voice to clone" : "Voice"}</span>
      <select value={choosable} disabled={readOnly} onChange={event => {
        const [kind, value] = event.target.value.split(/:(.*)/s);
        if (kind === "voice") save({ voice: value, model: model.id });
        else if (kind === "reference") save({ reference_id: value, model: model.id });
      }}>
        <option value="">{model.cloning ? "Choose a reference…" : "Choose a voice…"}</option>
        {model.cloning ? (references ?? []).map(reference => <option key={reference.id} value={`reference:${reference.id}`}>
          {reference.name} ({reference.consent === "self" ? "own voice" : "with permission"})</option>)
          : groups.map(([label, items]) => <optgroup key={label} label={label}>
            {items.map(voice => <option key={voice.id} value={`voice:${voice.id}`}>{voice.name}</option>)}</optgroup>)}
      </select></label>}
    {model?.cloning && references !== null && !references.length && <p className="studio-hint">
      Add a voice reference in Assets → Voice references first.</p>}
    {ready && !readOnly && catalog.available && <span className="studio-voice-clip">
      <button type="button" className="studio-link" disabled={Boolean(sampleId)} onClick={() => void api.createVoiceJob(
        tenantId, projectId, id, [{ mode: "full", text: `Hello. I'm ${name.trim() || "here"}. Shall we begin?` }],
      ).then(setSample, error => onError(message(error, "Could not try the voice.")))}>
        {sampleId ? "Speaking…" : "Try this voice"}</button>
      {sample?.error_code && <span className="studio-voice-note">{ERRORS[sample.error_code] ?? "Voice generation failed."}</span>}
      {clip && sample?.voice_model === saved && <ClipPlayButton assetId={clip.id} label="Play sample" />}
    </span>}
    {!catalog.available && <p className="studio-hint">Voice generation is not set up on this server; you can still upload voice clips.</p>}
    {licenseFor && <LicenseDialog tenantId={tenantId} model={licenseFor} onClose={() => setLicenseFor(null)}
      onAccepted={() => { reload(); setModelId(licenseFor.id); setLicenseFor(null); }} />}
  </div>;
}
