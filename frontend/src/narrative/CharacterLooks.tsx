import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { NarrativeImage } from "../lib/api";
import { useNarrativeImage } from "./characterImages";
import { Field } from "./FormFields";
import { useApprovedAssets } from "./libraryAssets";
import { lookReferences, lookRequest } from "./lookModel";
import type { LookList } from "./lookModel";
import "./looks.css";

const LOOKS_CHANGED = "flint-character-looks-changed";
export const refreshLooks = () => window.dispatchEvent(new Event(LOOKS_CHANGED));

export function useCharacterLooks(tenantId: string, projectId: string, characterId: string) {
  const [state, setState] = useState<LookList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const reload = () => setVersion(value => value + 1);
  useEffect(() => { window.addEventListener(LOOKS_CHANGED, reload); return () => window.removeEventListener(LOOKS_CHANGED, reload); }, []);
  useEffect(() => {
    const controller = new AbortController();
    setState(null); setError(null);
    if (!tenantId || !projectId || !characterId) return () => controller.abort();
    api.listCharacterLooks(tenantId, projectId, characterId, controller.signal).then(value => {
      if (!controller.signal.aborted) setState(value);
    }).catch(() => { if (!controller.signal.aborted) setError("Could not load reviewed looks. Retry before generating images."); });
    return () => controller.abort();
  }, [tenantId, projectId, characterId, version]);
  const look = state?.looks.find(item => item.id === state.selection.look_id) ?? null;
  return { state, look, ready: state !== null, error, reload };
}

export function LookImage({ tenantId, projectId, asset, label }: { tenantId: string; projectId: string; asset: NarrativeImage; label: string }) {
  const url = useNarrativeImage(tenantId, projectId, asset.id, "image");
  return <figure className="studio-look-image">{url ? <img src={url} alt={label} /> : <span>Image unavailable or loading…</span>}
    <figcaption>{label}</figcaption></figure>;
}

export function CharacterLooks({ tenantId, projectId, characterId, readOnly }: {
  tenantId: string; projectId: string; characterId: string; readOnly: boolean;
}) {
  const { state, look, error, reload } = useCharacterLooks(tenantId, projectId, characterId);
  const library = useApprovedAssets(tenantId, projectId);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [assetId, setAssetId] = useState("");
  const [identity, setIdentity] = useState("");
  const [clothes, setClothes] = useState("");
  const [parentId, setParentId] = useState<string | null>(null);
  const [observationId, setObservationId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const choices = lookReferences(library.assets ?? [], characterId);
  const source = choices.find(item => item.id === assetId) ?? null;
  async function select(id: string | null) {
    if (!state || readOnly || busy) return;
    setBusy(true); setNotice(null);
    try { await api.selectCharacterLook(tenantId, projectId, characterId, { look_id: id, base_version: state.selection.version }); refreshLooks(); }
    catch (failure) { setNotice(failure instanceof Error ? failure.message : "Could not choose this look."); if (failure instanceof ApiError && failure.status === 409) refreshLooks(); }
    finally { setBusy(false); }
  }
  async function lock() {
    if (!state || !source || readOnly || busy) return;
    setBusy(true); setNotice(null);
    try {
      await api.lockCharacterLook(tenantId, projectId, characterId, lookRequest({ name, assetId, identity, clothes,
        parentId, baseVersion: state.selection.version, key: crypto.randomUUID(), observationId }));
      refreshLooks(); setOpen(false); setNotice("Look locked for new image requests.");
    } catch (failure) { setNotice(failure instanceof Error ? failure.message : "Could not lock this look."); if (failure instanceof ApiError && failure.status === 409) refreshLooks(); }
    finally { setBusy(false); }
  }
  async function suggest() {
    if (!source || readOnly || busy) return;
    setBusy(true); setNotice(null);
    try {
      const result = await api.suggestCharacterLookTags(tenantId, projectId, characterId, source.id);
      setIdentity(result.identity_tags.join(", ")); setClothes(result.clothing_tags.join(", ")); setObservationId(result.observation_id);
      setNotice("Tags suggested. Check them against the image and edit anything missing or wrong before locking.");
    } catch (failure) { setNotice(failure instanceof Error ? failure.message : "Tag suggestions are unavailable. Enter the look manually."); }
    finally { setBusy(false); }
  }
  return <section className="studio-look-panel" aria-label="Reviewed looks">
    <div className="studio-section-heading"><h3>Reviewed looks</h3>
      {!readOnly && <button type="button" className="studio-secondary" disabled={!state || busy} onClick={() => {
        setOpen(true); setName(""); setObservationId(null); setParentId(look?.id ?? null); setAssetId(look?.asset.id ?? choices[0]?.id ?? "");
        setIdentity(look?.identity_tags.join(", ") ?? ""); setClothes(look?.clothing_tags.join(", ") ?? "");
      }}>New look</button>}</div>
    <p className="studio-hint">Lock an approved image with the hair, eyes and clothes you reviewed. A different outfit becomes a new named look.</p>
    {error ? <p role="alert" className="studio-error">{error} <button type="button" className="studio-link" onClick={reload}>Retry</button></p>
      : !state ? <p role="status">Loading looks…</p> : <>
        <Field label="Use for new images"><select value={state.selection.look_id ?? ""} disabled={readOnly || busy}
          onChange={event => void select(event.target.value || null)}>
          <option value="">Use the character description</option>
          {state.looks.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}
        </select></Field>
        {look && <div className="studio-look-summary">
          <LookImage tenantId={tenantId} projectId={projectId} asset={look.asset} label={look.name} />
          <div><h4>{look.name}</h4><p><strong>Hair and eyes:</strong> {look.identity_tags.join(", ") || "Not specified"}</p>
            <p><strong>Clothes:</strong> {look.clothing_tags.join(", ") || "Not specified"}</p>
            <p className="studio-hint">New portraits use these words. Expressions and CGs also use the approved reference. Details still need your review.</p>
            {look.asset.status !== "approved" && <p className="studio-error">This reference is no longer approved. Choose another look before generating.</p>}
          </div></div>}
      </>}
    {open && <fieldset disabled={busy || readOnly} className="studio-reviewed-look-form"><legend>Review a new look</legend>
      <Field label="Look name"><input maxLength={80} value={name} placeholder="Travel coat" onChange={event => setName(event.target.value)} /></Field>
      <Field label="Approved reference"><select value={assetId} onChange={event => {setAssetId(event.target.value);setObservationId(null);setIdentity("");setClothes("");}}>
        <option value="">Choose an image…</option>{choices.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></Field>
      {library.failed && <p role="alert">Approved images could not be loaded.</p>}
      {!choices.length && <p className="studio-hint">Approve a portrait or sprite first. CG scenes cannot be used as a single-character look.</p>}
      {source && <LookImage tenantId={tenantId} projectId={projectId} asset={source} label="Reference to review" />}
      <button type="button" className="studio-secondary" disabled={!source} onClick={() => void suggest()}>Suggest tags from image</button>
      <Field label="Hair, eyes and other visible traits" hint="Comma-separated. Leave details you cannot see unspecified."><textarea value={identity} maxLength={600} rows={2} onChange={event => setIdentity(event.target.value)} /></Field>
      <Field label="Clothes" hint="Describe the visible cut, colors and accessories; check these against the reference."><textarea value={clothes} maxLength={600} rows={2} onChange={event => setClothes(event.target.value)} /></Field>
      <div className="studio-actions"><button type="button" className="studio-primary" disabled={!source || !name.trim() || (!identity.trim() && !clothes.trim())} onClick={() => void lock()}>Lock reviewed look</button>
        <button type="button" className="studio-link" onClick={() => setOpen(false)}>Cancel</button></div>
    </fieldset>}
    {notice && <p role="status" className="studio-notice">{notice}</p>}
  </section>;
}
