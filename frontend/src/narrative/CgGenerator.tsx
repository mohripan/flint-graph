import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../lib/api";
import type { CharacterProfile, ImageJob, NarrativeImage } from "../lib/api";
import {
  CG_MAX_CHARACTERS, CG_SCENE_LIMIT, TWO_CHARACTER_NOTE, cgCandidates, cgJobCount, cgProblem, cgRequest, defaultReference,
  otherCharacters, referenceChoices,
} from "./cgModel";
import type { CgPick } from "./cgModel";
import { useNarrativeImage } from "./characterImages";
import { jobStatus } from "./characterModel";
import { Field } from "./FormFields";

const message = (error: unknown, fallback: string) => error instanceof Error && error.message ? error.message : fallback;
const REFERENCES_SHOWN = 12;

// Event CGs of one or two existing characters (ADR 0041 slice C): an approved image of
// each keeps their look, the scene text says the rest. Results wait among the CGs.
export function CgGenerator({ tenantId, projectId, characterNames, active, latest, onStarted, onCancel }: {
  tenantId: string; projectId: string; characterNames: Record<string, string>;
  active: ImageJob | null; latest: ImageJob | null;
  onStarted: (job: ImageJob) => void; onCancel: (job: ImageJob) => void;
}) {
  const ids = Object.keys(characterNames);
  const [picks, setPicks] = useState<CgPick[]>([{ character: ids[0] ?? "", reference: null }]);
  const [profiles, setProfiles] = useState<CharacterProfile[] | null>(null);
  const [scene, setScene] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    api.listCharacterProfiles(tenantId, projectId, controller.signal)
      .then(listed => setProfiles(listed.profiles))
      .catch(() => { if (!controller.signal.aborted) setProfiles([]); });
    return () => controller.abort();
  }, [tenantId, projectId]);

  const name = (id: string) => characterNames[id] || id;
  const change = (index: number, pick: CgPick) => setPicks(current => current.map((item, at) => at === index ? pick : item));
  const problem = cgProblem({ picks, scene });
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (problem || busy || active) return;
    setBusy(true); setError(null); setNotice(null);
    // Two characters start two jobs; the workspace's job limit may refuse the second.
    let started = 0;
    try {
      for (; started < cgJobCount(picks); started += 1) {
        onStarted(await api.createSceneArtJob(tenantId, projectId, cgRequest({ picks, scene })));
      }
    } catch (failure) {
      if (started) setNotice("Started 4 CGs. Generate more when they are done.");
      else setError(message(failure, "Could not start generating CGs."));
    } finally { setBusy(false); }
  }

  if (!ids.length) return <p className="studio-hint">Add a character in the Characters tab first: a CG is drawn from an approved image of them.</p>;
  const failed = !active && latest?.status === "failed" ? jobStatus(latest) : null;
  const two = picks.length === 2;
  const subject = picks.map(pick => name(pick.character).split(" ")[0]).join(" and ");
  return <form className="studio-asset-generate studio-cg-generate" aria-label="Generate CGs" onSubmit={event => void submit(event)}>
    {picks.map((pick, index) => <CharacterPick key={index} tenantId={tenantId} projectId={projectId} pick={pick}
      label={two ? (index === 0 ? "Left character" : "Right character") : "Character"}
      options={index === 0 ? ids : otherCharacters(ids, picks[0].character)} names={characterNames}
      portraitId={profiles?.find(profile => profile.character_id === pick.character)?.portrait?.id ?? null}
      onChange={next => { change(index, next); setError(null); }}
      onRemove={index > 0 ? () => setPicks(current => current.slice(0, 1)) : undefined}
      onLoadError={() => setError("Could not load this character's images.")} />)}
    {picks.length < CG_MAX_CHARACTERS && ids.length > 1 && <button type="button" className="studio-link"
      onClick={() => setPicks(current => [...current, { character: otherCharacters(ids, current[0].character)[0], reference: null }])}>
      Add a second character</button>}
    {two && <p className="studio-notice studio-cg-two" role="note">{TWO_CHARACTER_NOTE}</p>}
    <Field label="Scene" hint={`Where they are, what they are doing, the time of day and the mood.${two ? " The first character stands on the left." : ""}`}>
      <textarea rows={2} maxLength={CG_SCENE_LIMIT} value={scene}
        placeholder={`${subject} sitting on the couch by the window at night`}
        onChange={event => setScene(event.target.value)} /></Field>
    <div className="studio-actions">
      <button type="submit" className="studio-primary" disabled={busy || Boolean(active) || Boolean(problem)}>
        {active ? "Generating…" : `Generate ${cgCandidates(picks)} CGs`}</button>
      {active && <><span role="status" className="studio-hint">{jobStatus(active)}</span>
        {!active.cancel_requested && <button type="button" className="studio-link" onClick={() => onCancel(active)}>Cancel</button>}</>}
    </div>
    {notice && <p className="studio-hint" role="status">{notice}</p>}
    {(error || failed) && <p className="studio-error" role="alert">{error ?? failed}</p>}
  </form>;
}

function CharacterPick({ tenantId, projectId, pick, label, options, names, portraitId, onChange, onRemove, onLoadError }: {
  tenantId: string; projectId: string; pick: CgPick; label: string; options: string[]; names: Record<string, string>;
  portraitId: string | null; onChange: (pick: CgPick) => void; onRemove?: () => void; onLoadError: () => void;
}) {
  const [choices, setChoices] = useState<NarrativeImage[] | null>(null);
  const { character, reference } = pick;
  useEffect(() => {
    if (!character) { setChoices([]); return; }
    const controller = new AbortController();
    setChoices(null);
    api.listNarrativeAssets(tenantId, projectId, { character_id: character, status: "approved", limit: 48 }, controller.signal)
      .then(page => setChoices(page.assets))
      .catch(() => { if (!controller.signal.aborted) { setChoices([]); onLoadError(); } });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId, projectId, character]);
  // The chosen portrait may arrive after the images; it only reorders them.
  const ordered = choices && referenceChoices(choices, portraitId);
  const preferred = ordered ? defaultReference(ordered, reference) : null;
  useEffect(() => {
    if (ordered && preferred !== reference) onChange({ character, reference: preferred });
  }, [ordered, preferred, reference, character, onChange]);
  const name = names[character] || character;
  return <div className="studio-cg-pick">
    <div className="studio-cg-pick-head">
      <Field label={label}><select value={character} onChange={event => onChange({ character: event.target.value, reference: null })}>
        {options.map(id => <option key={id} value={id}>{names[id] || id}</option>)}</select></Field>
      {onRemove && <button type="button" className="studio-link" onClick={onRemove}>Remove</button>}
    </div>
    <fieldset className="studio-cg-references">
      <legend>Look from</legend>
      <p className="studio-hint">The CG keeps {name}’s look from this approved image. A plain portrait or sprite works best: effects and backdrops in it carry into the scene.</p>
      {ordered === null ? <p className="studio-hint">Loading images…</p>
        : !ordered.length ? <p className="studio-hint">Approve a portrait or sprite of {name} first, in Characters or under To review.</p>
        : <div className="studio-cg-reference-list" role="radiogroup" aria-label={`Reference image for ${name}`}>
          {ordered.slice(0, REFERENCES_SHOWN).map(choice => <ReferenceOption key={choice.id} tenantId={tenantId} projectId={projectId}
            group={`cg-reference-${label}`} asset={choice} checked={choice.id === reference}
            onPick={() => onChange({ character, reference: choice.id })} />)}</div>}
    </fieldset>
  </div>;
}

function ReferenceOption({ tenantId, projectId, group, asset, checked, onPick }: {
  tenantId: string; projectId: string; group: string; asset: NarrativeImage; checked: boolean; onPick: () => void;
}) {
  const url = useNarrativeImage(tenantId, projectId, asset.id, "thumbnail");
  return <label className={`studio-cg-reference ${checked ? "selected" : ""}`} title={asset.name}>
    <input type="radio" name={group} className="studio-visually-hidden" checked={checked} onChange={onPick} />
    {url ? <img src={url} alt="" /> : <span aria-hidden="true">…</span>}
    <small>{asset.name}</small>
  </label>;
}
