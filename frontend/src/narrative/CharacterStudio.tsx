import { useContext, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../lib/api";
import type { CharacterFraming, CharacterProfile, CharacterType, ImageJob, NarrativeImage } from "../lib/api";
import { CharacterAvatar, CharacterProfilesContext, useNarrativeImage } from "./characterImages";
import {
  CHARACTER_TYPES, FRAMINGS, MAX_APPEARANCE, PORTRAITS_PER_JOB, canCutOut, cleanAppearance, generateLabel, isActive,
  jobStatus,
} from "./characterModel";
import { Field } from "./FormFields";
import { addCharacter, deleteCharacter } from "./model";
import type { StoryDraft } from "./types";

interface Props {
  story: StoryDraft; readOnly: boolean;
  onChange: (story: StoryDraft, group?: string) => void; onError: (message: string) => void;
}

const message = (error: unknown, fallback: string) => error instanceof Error && error.message ? error.message : fallback;

// Characters: who speaks, what they look like and the portrait the creator approved.
// Names live in the story; appearance and portraits are shared editor metadata.
export function CharacterStudio({ story, readOnly, onChange, onError }: Props) {
  const ids = Object.keys(story.characters);
  const [selected, setSelected] = useState<string | null>(ids[0] ?? null);
  const current = selected && story.characters[selected] ? selected : ids[0] ?? null;
  return <div className="studio-characters-frame"><div className="studio-characters">
    <aside className="studio-character-list" aria-label="Characters">
      <div className="studio-section-heading"><h2>Characters</h2>
        {!readOnly && <button type="button" className="studio-secondary" onClick={() => {
          try { const added = addCharacter(story); onChange(added.story); setSelected(added.id); }
          catch (error) { onError(message(error, "Could not add a character.")); }
        }}>Add character</button>}</div>
      {!ids.length && <p className="studio-empty">No characters yet. Narration works without one.</p>}
      {ids.map(id => <button type="button" key={id} aria-pressed={id === current}
        className={`studio-character-item ${id === current ? "selected" : ""}`} onClick={() => setSelected(id)}>
        <CharacterAvatar characterId={id} name={story.characters[id].name} size={40} />
        <span><strong>{story.characters[id].name || "Unnamed character"}</strong><code>{id}</code></span>
      </button>)}
    </aside>
    {current ? <CharacterSheet key={current} id={current} story={story} readOnly={readOnly}
      onChange={onChange} onError={onError} /> : null}
  </div></div>;
}

function CharacterSheet({ id, story, readOnly, onChange, onError }: Props & { id: string }) {
  const context = useContext(CharacterProfilesContext);
  const profile: CharacterProfile = context?.profiles[id] ?? {
    character_id: id, appearance: "", character_type: "other", framing: "portrait", portrait: null, version: 0,
  };
  const [appearance, setAppearance] = useState(profile.appearance);
  const [type, setType] = useState<CharacterType>(profile.character_type);
  const [framing, setFraming] = useState<CharacterFraming>(profile.framing);
  // Cut-out stage sprites instead of portraits; a per-request choice, not profile data.
  const [transparent, setTransparent] = useState(false);
  const sprite = transparent && canCutOut(framing);
  const [jobs, setJobs] = useState<ImageJob[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [viewing, setViewing] = useState<NarrativeImage | null>(null);
  const [busy, setBusy] = useState(false);
  const saved = useRef(profile);
  saved.current = profile;
  const tenantId = context?.tenantId ?? "", projectId = context?.projectId ?? "";
  const character = story.characters[id];
  const active = jobs.find(isActive) ?? null;
  const dirty = cleanAppearance(appearance) !== profile.appearance || type !== profile.character_type
    || framing !== profile.framing;

  async function persist(): Promise<CharacterProfile | null> {
    if (!context || readOnly) return saved.current;
    const body = { base_version: saved.current.version, appearance: cleanAppearance(appearance),
      character_type: type, framing };
    try {
      const next = await api.saveCharacterProfile(tenantId, projectId, id, body);
      context.put(next); saved.current = next; return next;
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        await context.reload();
        setNotice("Someone else changed this character. Their description is shown now.");
        return null;
      }
      setNotice(message(error, "Could not save this character."));
      return null;
    }
  }
  // Save the description shortly after the creator stops typing.
  useEffect(() => {
    if (!dirty || readOnly || !context) return;
    const timer = window.setTimeout(() => void persist(), 700);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appearance, type, framing, dirty]);
  // Adopt a newer shared profile (another tab, a conflict reload) when nothing local is pending.
  useEffect(() => {
    if (dirty) return;
    setAppearance(profile.appearance); setType(profile.character_type); setFraming(profile.framing);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile.version]);

  useEffect(() => {
    if (!context) return;
    const controller = new AbortController();
    api.listPortraitJobs(tenantId, projectId, id, controller.signal)
      .then(listed => setJobs(listed.jobs))
      .catch(error => { if (!controller.signal.aborted) setNotice(message(error, "Could not load portraits.")); });
    return () => controller.abort();
  }, [context, tenantId, projectId, id]);

  // Poll only the running job; finished jobs never change again.
  const activeId = active?.id;
  useEffect(() => {
    if (!activeId || !context) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      api.getImageJob(tenantId, projectId, activeId, controller.signal)
        .then(job => setJobs(current => current.map(item => item.id === job.id ? job : item)))
        .catch(() => undefined);
    }, 1500);
    return () => { window.clearInterval(timer); controller.abort(); };
  }, [activeId, context, tenantId, projectId]);

  async function generate() {
    if (!context || busy || active || !cleanAppearance(appearance)) return;
    setBusy(true); setNotice(null);
    try {
      if (dirty && !(await persist())) return;
      const job = await api.createPortraitJob(tenantId, projectId, id, {
        appearance: cleanAppearance(appearance), character_type: type, framing, count: PORTRAITS_PER_JOB,
        idempotency_key: crypto.randomUUID(), transparent: sprite,
      });
      setJobs(current => [job, ...current.filter(item => item.id !== job.id)]);
    } catch (error) { setNotice(message(error, "Could not start generating portraits.")); }
    finally { setBusy(false); }
  }

  async function choose(asset: NarrativeImage | null) {
    if (!context) return;
    try {
      const next = await api.chooseCharacterPortrait(tenantId, projectId, id, saved.current.version, asset?.id ?? null);
      context.put(next); saved.current = next;
      setNotice(asset ? "Portrait chosen." : "Portrait removed.");
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) await context.reload();
      setNotice(message(error, "Could not choose this portrait."));
    }
  }

  // Sprites are library assets: approving keeps one for the character's expression sprites.
  async function approve(asset: NarrativeImage) {
    try {
      const next = await api.approveNarrativeAsset(tenantId, projectId, asset.id);
      setJobs(current => current.map(job => ({
        ...job, assets: job.assets.map(item => item.id === next.id ? next : item),
      })));
      setNotice("Sprite approved. It is in the asset library.");
    } catch (error) { setNotice(message(error, "Could not approve this sprite.")); }
  }

  async function discard(asset: NarrativeImage) {
    try {
      await api.discardNarrativeImage(tenantId, projectId, asset.id);
      setJobs(current => current.map(job => ({ ...job, assets: job.assets.filter(item => item.id !== asset.id) })));
    } catch (error) { setNotice(message(error, "Could not discard this image.")); }
  }

  async function cancel(job: ImageJob) {
    try {
      const next = await api.cancelImageJob(tenantId, projectId, job.id);
      setJobs(current => current.map(item => item.id === next.id ? next : item));
    } catch (error) { setNotice(message(error, "Could not cancel.")); }
  }

  const candidates = jobs.flatMap(job => job.assets.map(asset => ({ asset, job })));
  const latest = jobs[0];
  return <section className="studio-character-sheet" aria-label={`Character ${character.name}`}>
    <div className="studio-character-hero">
      <Portrait tenantId={tenantId} projectId={projectId} asset={profile.portrait} name={character.name}
        onView={setViewing} />
      <fieldset disabled={readOnly} className="studio-form">
        <div className="studio-section-heading"><h3>{character.name || "Unnamed character"}</h3><code>{id}</code></div>
        <Field label="Name"><input value={character.name} onChange={event => onChange({
          ...story, characters: { ...story.characters, [id]: { ...character, name: event.target.value } },
        }, `character:${id}:name`)} /></Field>
        <Field label="Appearance" hint="Describe looks: hair, eyes, clothing, expression. Not real people or existing characters.">
          <textarea rows={4} maxLength={MAX_APPEARANCE} value={appearance}
            placeholder="silver hair in a low ponytail, amber eyes, weathered navy coat, calm smile"
            onChange={event => setAppearance(event.target.value)} /></Field>
        <div className="studio-character-choices">
          <Field label="Character type"><select value={type} onChange={event => setType(event.target.value as CharacterType)}>
            {CHARACTER_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></Field>
          <Field label="Framing"><select value={framing} onChange={event => setFraming(event.target.value as CharacterFraming)}>
            {FRAMINGS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></Field>
        </div>
        <label className="studio-check"><input type="checkbox" checked={sprite} disabled={!canCutOut(framing)}
          onChange={event => setTransparent(event.target.checked)} />
          <span>Transparent background: cut the character out as a stage sprite
            {canCutOut(framing) ? "." : " (needs full-body framing)."}</span></label>
        {!readOnly && <div className="studio-actions">
          <button type="button" className="studio-primary" disabled={busy || Boolean(active) || !cleanAppearance(appearance)}
            onClick={() => void generate()}>{active ? "Generating…" : generateLabel(sprite)}</button>
          {profile.portrait && <button type="button" className="studio-link" onClick={() => void choose(null)}>Remove portrait</button>}
          <button type="button" className="studio-link studio-danger" onClick={() => {
            try { onChange(deleteCharacter(story, id)); }
            catch (error) { onError(message(error, "Could not remove a character.")); }
          }}>Remove character</button>
        </div>}
        <p className="studio-hint" role="status">{notice ?? (dirty ? "Saving…" : "")}</p>
      </fieldset>
    </div>
    {active && <div className="studio-job" role="status">
      <div className="studio-job-bar"><span style={{ width: `${Math.max(4, (active.progress / active.count) * 100)}%` }} /></div>
      <span>{jobStatus(active)}</span>
      {!readOnly && !active.cancel_requested && <button type="button" className="studio-link" onClick={() => void cancel(active)}>Cancel</button>}
    </div>}
    {latest && !isActive(latest) && latest.status !== "completed" && <p className="studio-notice">{jobStatus(latest)}</p>}
    {latest?.truncated && <p className="studio-notice">This description is long; the model only read its first part. Shorter descriptions follow more closely.</p>}
    <h3 className="studio-candidates-title">Generated portraits</h3>
    {!candidates.length && !active && <p className="studio-empty">Describe this character, then generate portraits to choose from. Images are made on this computer's GPU.</p>}
    <div className="studio-candidates">
      {candidates.map(({ asset }) => <Candidate key={asset.id} tenantId={tenantId} projectId={projectId} asset={asset}
        chosen={profile.portrait?.id === asset.id} readOnly={readOnly} onChoose={() => void choose(asset)}
        onApprove={() => void approve(asset)} onDiscard={() => void discard(asset)} onView={() => setViewing(asset)} />)}
    </div>
    {latest && <details className="studio-character-details"><summary>How the latest images were made</summary>
      <dl>
        <dt>Prompt</dt><dd>{latest.prompt}</dd>
        <dt>Model</dt><dd>{latest.model ?? "Not run yet"}</dd>
        {latest.transparent && <><dt>Cutout</dt><dd>{latest.cutout
          ? `${latest.cutout.model}, SHA-256 ${latest.cutout.sha256.slice(0, 12)}…` : "Not run yet"}</dd></>}
        <dt>Settings</dt><dd>{latest.width}×{latest.height}, {latest.steps} steps, guidance {latest.guidance}</dd>
      </dl></details>}
    {viewing && <Viewer tenantId={tenantId} projectId={projectId} asset={viewing} onClose={() => setViewing(null)} />}
  </section>;
}

function Portrait({ tenantId, projectId, asset, name, onView }: {
  tenantId: string; projectId: string; asset: NarrativeImage | null; name: string; onView: (asset: NarrativeImage) => void;
}) {
  const url = useNarrativeImage(tenantId, projectId, asset?.id ?? null, "thumbnail");
  if (!asset) return <div className="studio-portrait empty">No portrait yet</div>;
  return <button type="button" className="studio-portrait" onClick={() => onView(asset)} aria-label={`View ${name}'s portrait`}>
    {url ? <img src={url} alt="" /> : <span>Loading…</span>}
  </button>;
}

function Candidate({ tenantId, projectId, asset, chosen, readOnly, onChoose, onApprove, onDiscard, onView }: {
  tenantId: string; projectId: string; asset: NarrativeImage; chosen: boolean; readOnly: boolean;
  onChoose: () => void; onApprove: () => void; onDiscard: () => void; onView: () => void;
}) {
  const url = useNarrativeImage(tenantId, projectId, asset.id, "thumbnail");
  const sprite = asset.kind === "sprite";
  const approved = asset.status === "approved";
  return <figure className={`studio-candidate ${chosen ? "chosen" : ""} ${sprite ? "sprite" : ""}`}>
    <button type="button" className="studio-candidate-image" onClick={onView} aria-label="View full size">
      {url ? <img src={url} alt="" width={asset.thumbnail_width ?? undefined} height={asset.thumbnail_height ?? undefined} /> : <span>Loading…</span>}
    </button>
    <figcaption>
      {sprite
        ? approved ? <strong>Approved sprite</strong>
          : !readOnly && <button type="button" className="studio-secondary" onClick={onApprove}>Approve sprite</button>
        : chosen ? <strong>Current portrait</strong>
          : !readOnly && <button type="button" className="studio-secondary" onClick={onChoose}>Use as portrait</button>}
      {!chosen && !readOnly && <button type="button" className="studio-link studio-danger" onClick={onDiscard}>Discard</button>}
      <small>{sprite ? "Transparent sprite · " : ""}Seed {asset.seed}</small>
    </figcaption>
  </figure>;
}

export function Viewer({ tenantId, projectId, asset, onClose }: {
  tenantId: string; projectId: string; asset: NarrativeImage; onClose: () => void;
}) {
  const url = useNarrativeImage(tenantId, projectId, asset.id, "image");
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);
  return <div className="studio-viewer" role="dialog" aria-modal="true" aria-label="Portrait" onClick={onClose}>
    {url ? <img src={url} alt="" width={asset.width ?? undefined} height={asset.height ?? undefined}
      className={asset.kind === "sprite" ? "studio-transparent" : undefined} /> : <span>Loading…</span>}
    <button type="button" className="studio-secondary" onClick={onClose}>Close</button>
  </div>;
}
