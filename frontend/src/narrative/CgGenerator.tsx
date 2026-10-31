import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../lib/api";
import type { ImageJob, NarrativeImage } from "../lib/api";
import { CG_COUNT, CG_SCENE_LIMIT, cgProblem, cgRequest, defaultReference, referenceChoices } from "./cgModel";
import { useNarrativeImage } from "./characterImages";
import { jobStatus } from "./characterModel";
import { Field } from "./FormFields";

const message = (error: unknown, fallback: string) => error instanceof Error && error.message ? error.message : fallback;
const REFERENCES_SHOWN = 12;

// Event CGs of an existing character (ADR 0041 slice C): an approved image of them keeps
// their look, the scene text says the rest. Results wait among the CGs for approval.
export function CgGenerator({ tenantId, projectId, characterNames, active, latest, onStarted, onCancel }: {
  tenantId: string; projectId: string; characterNames: Record<string, string>;
  active: ImageJob | null; latest: ImageJob | null;
  onStarted: (job: ImageJob) => void; onCancel: (job: ImageJob) => void;
}) {
  const ids = Object.keys(characterNames);
  const [character, setCharacter] = useState(ids[0] ?? "");
  const [choices, setChoices] = useState<NarrativeImage[] | null>(null);
  const [reference, setReference] = useState<string | null>(null);
  const [scene, setScene] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!character) { setChoices([]); return; }
    const controller = new AbortController();
    setChoices(null);
    Promise.all([
      api.listNarrativeAssets(tenantId, projectId, { character_id: character, status: "approved", limit: 48 }, controller.signal),
      api.listCharacterProfiles(tenantId, projectId, controller.signal),
    ]).then(([page, profiles]) => {
      const portrait = profiles.profiles.find(profile => profile.character_id === character)?.portrait ?? null;
      const found = referenceChoices(portrait ? [portrait, ...page.assets] : page.assets, portrait?.id);
      setChoices(found);
      setReference(current => defaultReference(found, current));
    }).catch(() => {
      if (!controller.signal.aborted) { setChoices([]); setError("Could not load this character's images."); }
    });
    return () => controller.abort();
  }, [tenantId, projectId, character]);

  const name = characterNames[character] || character;
  const problem = cgProblem({ character, reference, scene });
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (problem || busy || active) return;
    setBusy(true); setError(null);
    try { onStarted(await api.createSceneArtJob(tenantId, projectId, cgRequest({ character, reference, scene }))); }
    catch (failure) { setError(message(failure, "Could not start generating CGs.")); }
    finally { setBusy(false); }
  }

  if (!ids.length) return <p className="studio-hint">Add a character in the Characters tab first: a CG is drawn from an approved image of them.</p>;
  const failed = !active && latest?.status === "failed" ? jobStatus(latest) : null;
  return <form className="studio-asset-generate studio-cg-generate" aria-label="Generate CGs" onSubmit={event => void submit(event)}>
    <Field label="Character"><select value={character} onChange={event => { setCharacter(event.target.value); setError(null); }}>
      {ids.map(id => <option key={id} value={id}>{characterNames[id] || id}</option>)}</select></Field>
    <fieldset className="studio-cg-references">
      <legend>Look from</legend>
      <p className="studio-hint">The CG keeps {name}’s look from this approved image. A plain portrait or sprite works best: effects and backdrops in it carry into the scene.</p>
      {choices === null ? <p className="studio-hint">Loading images…</p>
        : !choices.length ? <p className="studio-hint">Approve a portrait or sprite of {name} first, in Characters or under To review.</p>
        : <div className="studio-cg-reference-list" role="radiogroup" aria-label="Reference image">
          {choices.slice(0, REFERENCES_SHOWN).map(choice => <ReferenceOption key={choice.id} tenantId={tenantId} projectId={projectId}
            asset={choice} checked={choice.id === reference} onPick={() => setReference(choice.id)} />)}</div>}
    </fieldset>
    <Field label="Scene" hint="Where they are, what they are doing, the time of day and the mood. One character per CG.">
      <textarea rows={2} maxLength={CG_SCENE_LIMIT} value={scene} placeholder={`${name.split(" ")[0]} sitting on the couch by the window at night`}
        onChange={event => setScene(event.target.value)} /></Field>
    <div className="studio-actions">
      <button type="submit" className="studio-primary" disabled={busy || Boolean(active) || Boolean(problem)}>
        {active ? "Generating…" : `Generate ${CG_COUNT} CGs`}</button>
      {active && <><span role="status" className="studio-hint">{jobStatus(active)}</span>
        {!active.cancel_requested && <button type="button" className="studio-link" onClick={() => onCancel(active)}>Cancel</button>}</>}
    </div>
    {(error || failed) && <p className="studio-error" role="alert">{error ?? failed}</p>}
  </form>;
}

function ReferenceOption({ tenantId, projectId, asset, checked, onPick }: {
  tenantId: string; projectId: string; asset: NarrativeImage; checked: boolean; onPick: () => void;
}) {
  const url = useNarrativeImage(tenantId, projectId, asset.id, "thumbnail");
  return <label className={`studio-cg-reference ${checked ? "selected" : ""}`} title={asset.name}>
    <input type="radio" name="cg-reference" className="studio-visually-hidden" checked={checked} onChange={onPick} />
    {url ? <img src={url} alt="" /> : <span aria-hidden="true">…</span>}
    <small>{asset.name}</small>
  </label>;
}
