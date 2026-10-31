import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../lib/api";
import type { NarrativeImage, VoiceJob, VoiceOption } from "../lib/api";
import { CharacterProfilesContext } from "./characterImages";
import { libraryAsset, refreshLibrary, useApprovedAssets } from "./libraryAssets";
import type { StoryDraft } from "./types";
import {
  VOCALIZATION_EXAMPLES, VOCALIZATION_LIMIT, clipIsStale, missingClips, setLineClip, setLineVoice, spokenText, voiceChoice,
} from "./voiceModel";
import type { VoiceChoice } from "./voiceModel";

// Voiced lines in the script (ADR 0043): pick silent, full voice or a vocalization per
// line, generate clips with the speaker's Kokoro voice, and bind an approved clip.
const message = (error: unknown, fallback: string) => error instanceof Error && error.message ? error.message : fallback;
const active = (job: VoiceJob) => job.status === "queued" || job.status === "running";
const ERRORS: Record<string, string> = {
  empty_speech: "Kokoro could not say this. Try other words or a different sound.",
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
  start: (character: string, items: Array<{ mode: "full" | "vocalization"; text: string; node_id: string }>) => Promise<void>;
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
  const start = useCallback(async (character: string, items: Array<{ mode: "full" | "vocalization"; text: string; node_id: string }>) => {
    const job = await api.createVoiceJob(tenantId, projectId, character, items);
    setJobs(current => [job, ...current.filter(item => item.id !== job.id)]);
  }, [tenantId, projectId]);
  const value = useMemo(() => ({ jobs, refresh, start }), [jobs, refresh, start]);
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
  const silent = missing.filter(([speaker]) => !profiles[speaker]?.voice).map(([speaker]) => story.characters[speaker]?.name ?? speaker);
  return <div className="studio-scene-voices">
    <button type="button" className="studio-secondary" disabled={silent.length === missing.length} onClick={() => void (async () => {
      try {
        for (const [speaker, items] of missing) {
          if (!profiles[speaker]?.voice) continue;
          for (let index = 0; index < items.length; index += 24) await jobs.start(speaker, items.slice(index, index + 24));
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
  const voiceId = context?.profiles[speaker]?.voice;
  const choices = (assets ?? []).filter(asset => asset.kind === "voice" && (!asset.character_id || asset.character_id === speaker));
  const use = (asset: NarrativeImage) => void (async () => {
    try {
      const approved = asset.status === "approved" ? asset : await api.approveNarrativeAsset(tenantId, projectId, asset.id);
      refreshLibrary();
      jobs?.refresh();
      onChange(setLineClip(story, id, approved), `${id}:voice-clip`);
    } catch (error) { onError(message(error, "Could not use this clip.")); }
  })();
  const generate = () => void jobs?.start(speaker, [{ mode: voice.mode, text, node_id: id }])
    .catch(error => onError(message(error, "Could not start generating the voice.")));
  return <div className="studio-line-voice">
    {select}
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

let catalog: Promise<{ available: boolean; voices: VoiceOption[] }> | null = null;

export function CharacterVoice({ id, name, readOnly, onError }: {
  id: string; name: string; readOnly: boolean; onError: (message: string) => void;
}) {
  const context = useContext(CharacterProfilesContext);
  const tenantId = context?.tenantId ?? "", projectId = context?.projectId ?? "";
  const profile = context?.profiles[id];
  const [voices, setVoices] = useState<{ available: boolean; voices: VoiceOption[] } | null>(null);
  const [sample, setSample] = useState<VoiceJob | null>(null);
  useEffect(() => {
    if (!projectId) return;
    catalog ??= api.getVoiceCatalog(tenantId, projectId);
    catalog.then(setVoices, () => { catalog = null; });
  }, [tenantId, projectId]);
  const sampleId = sample && active(sample) ? sample.id : null;
  useEffect(() => {
    if (!sampleId) return;
    const timer = window.setInterval(() => {
      api.getVoiceJob(tenantId, projectId, sampleId).then(setSample).catch(() => undefined);
    }, 1200);
    return () => window.clearInterval(timer);
  }, [sampleId, tenantId, projectId]);
  if (!voices) return null;
  const choose = (voice: string | null) => void api.setCharacterVoice(tenantId, projectId, id, profile?.version ?? 0, voice)
    .then(updated => context?.put(updated), error => onError(message(error, "Could not choose the voice.")));
  const groups = ["American", "British"].map(accent => [accent, voices.voices.filter(voice => voice.accent === accent)] as const);
  const clip = sample?.assets[0];
  return <div className="studio-character-voice">
    <label className="studio-field"><span>Voice</span>
      <select value={profile?.voice ?? ""} disabled={readOnly} onChange={event => choose(event.target.value || null)}>
        <option value="">No voice (lines stay silent)</option>
        {groups.map(([accent, items]) => <optgroup key={accent} label={`${accent} English`}>
          {items.map(voice => <option key={voice.id} value={voice.id}>{voice.name} ({voice.gender})</option>)}</optgroup>)}
      </select></label>
    {profile?.voice && !readOnly && voices.available && <span className="studio-voice-clip">
      <button type="button" className="studio-link" disabled={Boolean(sampleId)} onClick={() => void api.createVoiceJob(
        tenantId, projectId, id, [{ mode: "full", text: `Hello. I'm ${name.trim() || "here"}. Shall we begin?` }],
      ).then(setSample, error => onError(message(error, "Could not try the voice.")))}>
        {sampleId ? "Speaking…" : "Try this voice"}</button>
      {clip && sample?.voice === profile.voice && <ClipPlayButton assetId={clip.id} label="Play sample" />}
    </span>}
    {!voices.available && <p className="studio-hint">Voice generation is not set up on this server; you can still upload voice clips.</p>}
  </div>;
}
