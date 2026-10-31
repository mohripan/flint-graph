import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../lib/api";
import type { VoiceReference } from "../lib/api";
import { MAX_SECONDS, encodeWav, referenceProblem, toReferenceSamples } from "./referenceAudio";

// Private voice references (#175, ADR 0044): a sample of your own voice, or of a speaker
// who gave you permission, that a character voice can be cloned from. References stay
// in this project: they never go into stories, playtests, releases or NOTICES.
const message = (error: unknown, fallback: string) => error instanceof Error && error.message ? error.message : fallback;
const seconds = (ms: number) => `${(ms / 1000).toFixed(1)} s`;

type Pending = { samples: Float32Array; source: "upload" | "recording"; label: string };

export function useVoiceReferences(tenantId: string, projectId: string, enabled: boolean) {
  const [references, setReferences] = useState<VoiceReference[] | null>(null);
  const reload = useCallback(() => {
    if (!enabled || !projectId) return;
    api.listVoiceReferences(tenantId, projectId).then(listed => setReferences(listed.references), () => setReferences([]));
  }, [tenantId, projectId, enabled]);
  useEffect(() => { reload(); }, [reload]);
  return { references, reload };
}

function ReferencePlayer({ tenantId, projectId, reference }: { tenantId: string; projectId: string; reference: VoiceReference }) {
  const [state, setState] = useState<"idle" | "loading" | "playing" | "failed">("idle");
  const audio = useRef<HTMLAudioElement | null>(null);
  const url = useRef<string | null>(null);
  useEffect(() => () => { audio.current?.pause(); if (url.current) URL.revokeObjectURL(url.current); }, []);
  async function toggle() {
    if (state === "playing") { audio.current?.pause(); setState("idle"); return; }
    setState("loading");
    try {
      if (!url.current) url.current = URL.createObjectURL(await api.getVoiceReferenceAudio(tenantId, projectId, reference.id));
      const element = audio.current ?? new Audio();
      audio.current = element;
      element.src = url.current;
      element.onended = () => setState("idle");
      await element.play();
      setState("playing");
    } catch { setState("failed"); }
  }
  return <button type="button" className="studio-link studio-play" onClick={() => void toggle()}>
    {state === "playing" ? "■ Stop" : state === "loading" ? "Loading…" : state === "failed" ? "Can't play" : "▶ Listen"}</button>;
}

function Recorder({ onDone, onError }: { onDone: (pending: Pending) => void; onError: (text: string) => void }) {
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<number | null>(null);
  useEffect(() => () => {
    if (timer.current) window.clearInterval(timer.current);
    recorder.current?.stream.getTracks().forEach(track => track.stop());
  }, []);
  async function start() {
    let stream: MediaStream;
    try {
      // The browser asks for permission; nothing is recorded without it.
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: true } });
    } catch { onError("The microphone is not available. Allow it in the browser, or upload a recording instead."); return; }
    const chunks: Blob[] = [];
    const media = new MediaRecorder(stream);
    media.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    media.onstop = () => {
      stream.getTracks().forEach(track => track.stop());
      if (timer.current) window.clearInterval(timer.current);
      setRecording(false);
      void new Blob(chunks, { type: media.mimeType }).arrayBuffer().then(toReferenceSamples)
        .then(samples => onDone({ samples, source: "recording", label: "Recording" }),
          () => onError("The recording could not be read. Try again."));
    };
    recorder.current = media;
    media.start();
    const began = Date.now();
    setElapsed(0);
    setRecording(true);
    timer.current = window.setInterval(() => {
      const now = (Date.now() - began) / 1000;
      setElapsed(now);
      if (now >= MAX_SECONDS) media.stop();
    }, 200);
  }
  return recording
    ? <span className="studio-voice-clip"><span className="studio-voice-note" role="status">Recording… {elapsed.toFixed(0)} s of at most {MAX_SECONDS}</span>
      <button type="button" className="studio-secondary" onClick={() => recorder.current?.stop()}>Stop</button></span>
    : <button type="button" className="studio-secondary" onClick={() => void start()}>Record with microphone</button>;
}

export function VoiceReferences({ tenantId, projectId, canWrite, onChange }: {
  tenantId: string; projectId: string; canWrite: boolean; onChange?: () => void;
}) {
  const { references, reload: reloadList } = useVoiceReferences(tenantId, projectId, canWrite);
  const reload = () => { reloadList(); onChange?.(); };
  const [pending, setPending] = useState<Pending | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [consent, setConsent] = useState<"self" | "permission">("self");
  const [speaker, setSpeaker] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  if (!canWrite) return <p className="studio-hint">Only members of this workspace can hear voice references.</p>;
  const problem = pending ? referenceProblem(pending.samples) : null;
  const preview = (picked: Pending) => { setPending(picked); setNotice(null); };
  async function upload(file: File) {
    try { preview({ samples: await toReferenceSamples(await file.arrayBuffer()), source: "upload", label: file.name }); }
    catch { setNotice("This file could not be read as audio."); }
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!pending || problem || !confirmed || !speaker.trim() || busy) return;
    setBusy(true);
    try {
      await api.uploadVoiceReference(tenantId, projectId, {
        file: new Blob([encodeWav(pending.samples)], { type: "audio/wav" }), name: name.trim(), speaker_name: speaker.trim(),
        consent, transcript: transcript.trim(), source: pending.source,
      });
      setPending(null); setConfirmed(false); setTranscript(""); setName("");
      setNotice("Reference saved. Choose it for a character in Characters → Voice.");
      reload();
    } catch (error) { setNotice(message(error, "Could not save the reference.")); }
    finally { setBusy(false); }
  }
  return <section className="studio-references" aria-label="Voice references">
    <p className="studio-hint">A 5–30 second sample of one person speaking clearly, to clone a character's voice from. References
      stay private to this project: they are never put in a story, a playtest, a release or its NOTICES.</p>
    {notice && <p className="studio-notice" role="status">{notice}</p>}
    <div className="studio-reference-add">
      <Recorder onDone={preview} onError={setNotice} />
      <label className="studio-secondary studio-file">Upload audio
        <input type="file" accept="audio/*" onChange={event => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void upload(file); }} /></label>
    </div>
    {pending && <form className="studio-reference-form" onSubmit={event => void save(event)}>
      <p><strong>{pending.label}</strong>: {(pending.samples.length / 24000).toFixed(1)} s</p>
      {problem && <p className="studio-notice" role="alert">{problem}</p>}
      <fieldset><legend>Whose voice is this?</legend>
        <label><input type="radio" name="consent" checked={consent === "self"} onChange={() => setConsent("self")} /> This is my voice</label>
        <label><input type="radio" name="consent" checked={consent === "permission"} onChange={() => setConsent("permission")} /> The speaker gave me permission to clone their voice</label>
      </fieldset>
      <label className="studio-field"><span>Speaker's name</span>
        <input required maxLength={120} value={speaker} onChange={event => setSpeaker(event.target.value)} /></label>
      <label className="studio-field"><span>What is said (optional; helps some models clone the voice)</span>
        <textarea maxLength={600} rows={2} value={transcript} onChange={event => setTranscript(event.target.value)} /></label>
      <label className="studio-field"><span>Name in the library (optional)</span>
        <input maxLength={120} value={name} placeholder={speaker || "Reference"} onChange={event => setName(event.target.value)} /></label>
      <label className="studio-check"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />
        {consent === "self" ? " I confirm this recording is my own voice and I agree to it being cloned for this project."
          : " I confirm the speaker named above gave me permission to clone their voice for this project."}</label>
      <p className="studio-hint">Your declaration is recorded with your name and the time; FlintGraph does not verify it.</p>
      <div className="studio-actions">
        <button type="submit" className="studio-primary" disabled={Boolean(problem) || !confirmed || !speaker.trim() || busy}>
          {busy ? "Saving…" : "Save reference"}</button>
        <button type="button" className="studio-link" onClick={() => setPending(null)}>Discard</button>
      </div>
    </form>}
    {references === null ? <p className="studio-hint">Loading…</p>
      : !references.length ? <p className="studio-hint">No references yet.</p>
      : <ul className="studio-reference-list">{references.map(reference => <li key={reference.id}>
        <strong>{reference.name}</strong>
        <span>{reference.speaker_name} · {reference.consent === "self" ? "own voice" : "with the speaker's permission"} · {seconds(reference.duration_ms)}</span>
        <ReferencePlayer tenantId={tenantId} projectId={projectId} reference={reference} />
        <button type="button" className="studio-link studio-danger" onClick={() => {
          if (!window.confirm(`Delete the reference “${reference.name}”? Its audio is removed; clips made from it stay usable.`)) return;
          void api.deleteVoiceReference(tenantId, projectId, reference.id).then(reload, error => setNotice(message(error, "Could not delete.")));
        }}>Delete</button>
      </li>)}</ul>}
  </section>;
}
