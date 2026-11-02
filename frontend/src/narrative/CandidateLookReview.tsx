import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, ApiError } from "../lib/api";
import type { NarrativeImage } from "../lib/api";
import { LookImage, useCharacterLooks } from "./CharacterLooks";
import { Field } from "./FormFields";
import type { AnatomyVerdict, ClothingComparison, LookFeedback, LookFlag, LookVerdict } from "./lookModel";
import {feedbackBody,reviewWarnings} from "./lookModel";
import { StudioDialog } from "./StudioDialog";

const REVIEW_CHANGED = "flint-look-review-changed";
export function useLookReviewFlags(tenantId: string, projectId: string, assets: NarrativeImage[]) {
  const [flags, setFlags] = useState<LookFlag[]>([]);
  const [failed, setFailed] = useState(false);
  const [version, setVersion] = useState(0);
  const key = assets.filter(asset => asset.media_type === "image/png").map(asset => asset.id).sort().join(",");
  useEffect(() => { const update = () => setVersion(value => value+1); window.addEventListener(REVIEW_CHANGED, update); return () => window.removeEventListener(REVIEW_CHANGED, update); }, []);
  useEffect(() => {
    setFlags([]); setFailed(false);
    if (!key) return;
    const controller = new AbortController();
    const ids = key.split(",");
    const groups = Array.from({length:Math.ceil(ids.length/100)}, (_, index) => ids.slice(index*100,index*100+100));
    Promise.all(groups.map(group => api.lookReviewFlags(tenantId, projectId, group, controller.signal)))
      .then(results => { if (!controller.signal.aborted) { setFlags(results.flatMap(result => result.reviews));setFailed(results.some(result=>result.truncated)); } })
      .catch(() => {if (!controller.signal.aborted) setFailed(true);});
    return () => controller.abort();
  }, [tenantId, projectId, key, version]);
  return { flags, failed };
}

export function CandidateLookReview({ tenantId, projectId, asset, readOnly, flags = [], names = {} }: {
  tenantId: string; projectId: string; asset: NarrativeImage; readOnly: boolean; flags?: LookFlag[]; names?: Record<string,string>;
}) {
  const [open, setOpen] = useState(false);
  if (asset.media_type !== "image/png" || !["sprite","image","character_portrait"].includes(asset.kind)) return null;
  const characters = Object.keys(names).length ? names : asset.character_id ? {[asset.character_id]:asset.character_id} : {};
  if (!Object.keys(characters).length) return null;
  const warnings = reviewWarnings(asset,flags);
  return <>
    {warnings.map(flag => <small key={`${flag.look_id}:${flag.asset_id}`} className="studio-look-warning">{flag.look_name}: {flag.reasons.join(" · ")}</small>)}
    <button type="button" className="studio-link" onClick={() => setOpen(true)}>Compare look</button>
    {open && createPortal(<ReviewDialog tenantId={tenantId} projectId={projectId} asset={asset} readOnly={readOnly} names={characters} onClose={() => setOpen(false)} />, document.body)}
  </>;
}

function ReviewDialog({ tenantId, projectId, asset, readOnly, names, onClose }: {
  tenantId:string; projectId:string; asset:NarrativeImage; readOnly:boolean; names:Record<string,string>; onClose:()=>void;
}) {
  const [character, setCharacter] = useState(asset.character_id && names[asset.character_id] ? asset.character_id : Object.keys(names)[0]);
  const looks = useCharacterLooks(tenantId, projectId, character);
  const [chosen, setChosen] = useState<string | null>(null);
  const look = looks.state?.looks.find(item => item.id === chosen) ?? looks.look ?? looks.state?.looks[0];
  const [feedback, setFeedback] = useState<LookFeedback | null>(null);
  const [feedbackFor, setFeedbackFor] = useState<string | null>(null);
  const scope = `${character}:${look?.id ?? ""}:${asset.id}`;
  const currentScope = useRef(scope); currentScope.current = scope;
  const feedbackReady = feedback !== null && feedbackFor === scope;
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [comparison, setComparison] = useState<ClothingComparison | null>(null);
  useEffect(() => {
    setFeedback(null); setError(null); setNotice(null); setComparison(null);
    if (!look) return;
    const controller = new AbortController();
    api.candidateLookFeedback(tenantId, projectId, character, look.id, asset.id, controller.signal)
      .then(value => { if (!controller.signal.aborted) {setFeedback(value);setFeedbackFor(scope);} })
      .catch(() => { if (!controller.signal.aborted) setError("Could not load feedback. Retry before saving."); });
    return () => controller.abort();
  }, [tenantId, projectId, character, look?.id, asset.id, reload]);
  async function save() {
    if (!feedback || !feedbackReady || !look || readOnly || busy) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      const result = await api.saveCandidateLookFeedback(tenantId, projectId, character, look.id, asset.id, feedbackBody(feedback));
      window.dispatchEvent(new Event(REVIEW_CHANGED));
      if (currentScope.current === scope) {setFeedback(result);setNotice("Feedback saved. You can still approve this image.");}
    } catch (failure) { setError(failure instanceof ApiError && failure.status === 409 ? "Someone else changed this review. Reload their feedback before saving." : "Could not save feedback. Your edits are still here."); }
    finally { setBusy(false); }
  }
  async function compare() {
    if (!look || busy) return;
    setBusy(true); setError(null);
    try { const result = await api.compareClothingTags(tenantId, projectId, character, look.id, asset.id); if (currentScope.current === scope) setComparison(result); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Clothing tags are unavailable. Review the images manually."); }
    finally { setBusy(false); }
  }
  const verdict = (axis:"identity"|"clothes", label:string) => <Field label={label}><select disabled={readOnly || busy || !feedbackReady} value={feedbackReady ? feedback![axis] : "unknown"}
    onChange={event => setFeedback(current => current && {...current,[axis]:event.target.value as LookVerdict})}>
    <option value="unknown">Not sure / not visible</option><option value="same">Same as the reference</option><option value="drifted">Changed — flag for review</option>
  </select></Field>;
  return <StudioDialog label="Compare character look" onClose={onClose}>
    <div className="studio-peek-body studio-look-review">
    <div className="studio-section-heading"><h3>Compare look</h3><button type="button" className="studio-secondary" onClick={onClose}>Close</button></div>
    {Object.keys(names).length > 1 && <Field label="Character"><select value={character} disabled={busy} onChange={event => {setCharacter(event.target.value);setChosen(null);}}>{Object.entries(names).map(([id,name]) => <option key={id} value={id}>{name}</option>)}</select></Field>}
    {looks.error ? <p role="alert">{looks.error} <button type="button" onClick={looks.reload}>Retry</button></p>
      : !looks.ready ? <p role="status">Loading looks…</p> : !look ? <p className="studio-hint">Lock an approved look for this character in Characters first.</p> : <>
        <Field label="Compare against"><select value={look.id} disabled={busy} onChange={event => setChosen(event.target.value)}>{looks.state?.looks.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
        <div className="studio-look-comparison"><LookImage tenantId={tenantId} projectId={projectId} asset={look.asset} label={`Reference · ${look.name}`} /><LookImage tenantId={tenantId} projectId={projectId} asset={asset} label={asset.name} /></div>
        <p><strong>Hair and eyes:</strong> {look.identity_tags.join(", ") || "Unspecified"}<br /><strong>Clothes:</strong> {look.clothing_tags.join(", ") || "Unspecified"}</p>
        <p className="studio-hint">Check the face, hair, eye color, outfit and pose separately. For a CG, check the number of people too. Your feedback never blocks approval.</p>
        {!readOnly && <button type="button" className="studio-secondary" disabled={busy} onClick={() => void compare()}>{busy ? "Working…" : "Compare clothing tags"}</button>}
        {comparison && <div className="studio-look-tags" role="status"><strong>{comparison.clothing_overlap === null ? "Clothing overlap unknown" : `${Math.round(comparison.clothing_overlap*100)}% clothing-tag overlap`}</strong>
          <p>{comparison.reason}</p><p>Reference: {Object.keys(comparison.reference_tags).join(", ") || "No garment evidence"}<br />Candidate: {Object.keys(comparison.candidate_tags).join(", ") || "No garment evidence"}</p></div>}
        <fieldset disabled={readOnly || busy || !feedbackReady} className="studio-reviewed-look-form"><legend>Your review</legend>
          {verdict("identity","Character appearance")}{verdict("clothes","Clothes")}
          {feedback?.anatomy!==undefined&&<>
            <Field label="Anatomy"><select value={feedback.anatomy} onChange={event=>setFeedback(current=>current&&{...current,anatomy:event.target.value as AnatomyVerdict})}>
              <option value="unknown">Not checked / not sure</option><option value="acceptable">Anatomy looks acceptable</option><option value="flawed">Anatomy problem — exclude from training</option>
            </select></Field>
            <p className="studio-hint">Inspect hands, feet, extra or missing limbs and body geometry. A recorded problem excludes these image bytes from new training in this project, even if approved. You can revise this review; approval stays your choice.</p>
          </>}
          <Field label="Review notes"><textarea rows={2} maxLength={1200} value={feedback?.notes ?? ""} onChange={event => setFeedback(current => current && {...current,notes:event.target.value})} /></Field>
          {!readOnly && <button type="button" className="studio-primary" onClick={() => void save()}>Save feedback</button>}
        </fieldset>
      </>}
    {error && <p className="studio-error" role="alert">{error} <button type="button" className="studio-link" disabled={busy} onClick={() => setReload(value=>value+1)}>Reload feedback</button></p>}
    {notice && <p className="studio-notice" role="status">{notice}</p>}
    </div>
  </StudioDialog>;
}
