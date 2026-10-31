import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, api } from "../lib/api";
import type { ImageJob, NarrativeImage } from "../lib/api";
import { FILTERS, KIND_LABELS, UPLOAD_KINDS, filterQuery, kindForFile, suggestName, uploadKindForFilter, uploadProblem } from "./assetModel";
import type { AssetFilter, UploadKind } from "./assetModel";
import { useNarrativeImage } from "./characterImages";
import { refreshLibrary, useAssetFont } from "./libraryAssets";
import { isActive, jobStatus } from "./characterModel";
import { imageJobStarted, useBackgroundJobs } from "./imageJobs";
import { Viewer } from "./CharacterStudio";
import { Field } from "./FormFields";
import { StudioDialog } from "./StudioDialog";

const PAGE = 48;
const message = (error: unknown, fallback: string) => error instanceof Error && error.message ? error.message : fallback;

// The project's art and fonts: uploads with a rights declaration and generated
// backgrounds. Only approved assets can be used by the story.
export function AssetLibrary({ tenantId, projectId, canWrite }: { tenantId: string; projectId: string; canWrite: boolean }) {
  const [filter, setFilter] = useState<AssetFilter>("all");
  const [assets, setAssets] = useState<NarrativeImage[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [viewing, setViewing] = useState<NarrativeImage | null>(null);
  const { jobs, failed: jobsFailed, put } = useBackgroundJobs(tenantId, projectId);
  const active = jobs.find(isActive) ?? null;

  const load = useCallback(async (before?: string) => {
    try {
      const page = await api.listNarrativeAssets(tenantId, projectId, { ...filterQuery(filter), limit: PAGE, before });
      setAssets(current => before && current ? [...current, ...page.assets] : page.assets);
      setNext(page.next_before);
    } catch (error) { setNotice(message(error, "Could not load assets.")); setAssets(current => current ?? []); }
  }, [tenantId, projectId, filter]);
  useEffect(() => { setAssets(null); void load(); }, [load]);
  const completedJobs = jobs.filter(job => job.status === "completed").map(job => job.id).sort().join(",");
  useEffect(() => {
    if (completedJobs) { void load(); refreshLibrary(); }
  }, [completedJobs, load]);

  const replace = (asset: NarrativeImage) => setAssets(current => current?.map(item => item.id === asset.id ? asset : item) ?? null);
  async function act(run: () => Promise<void>, fallback: string) {
    setNotice(null);
    try { await run(); refreshLibrary(); } catch (error) { setNotice(message(error, fallback)); }
  }

  return <section className="studio-assets" aria-label="Assets">
    <div className="studio-section-heading"><h2>Assets</h2>
      {canWrite && <button type="button" className="studio-primary" onClick={() => setUploading(true)}>Upload</button>}</div>
    <p className="studio-hint">Backgrounds, character sprites, CGs and fonts for this story. Uploads keep transparency; generated images wait here for your approval.</p>
    {canWrite && filter !== "image" && <BackgroundGenerator tenantId={tenantId} projectId={projectId} active={active}
      onStarted={job => { imageJobStarted(tenantId, projectId, job); setFilter("candidates"); }}
      onCancel={job => void act(async () => {
        const next = await api.cancelImageJob(tenantId, projectId, job.id);
        put(next);
      }, "Could not cancel.")} />}
    <div className="studio-asset-filters" role="group" aria-label="Show">
      {FILTERS.map(([id, label]) => <button type="button" key={id} aria-pressed={filter === id}
        className={filter === id ? "selected" : ""} onClick={() => setFilter(id)}>{label}</button>)}
    </div>
    {jobsFailed && <p className="studio-notice" role="status">Image status could not be refreshed. Retrying…</p>}
    {jobs.filter(isActive).map(job => <section key={job.id} className="studio-asset-generate" aria-label="Background generation">
      <strong>Generating backgrounds</strong>
      <p role="status">{jobStatus(job)}</p>
      <progress max={job.count} value={job.progress} aria-label="Generated backgrounds" />
      {canWrite && !job.cancel_requested && <button type="button" className="studio-link" onClick={() => void act(async () => {
        put(await api.cancelImageJob(tenantId, projectId, job.id));
      }, "Could not cancel.")}>Cancel background generation</button>}
    </section>)}
    {filter === "image" && <section className="studio-asset-generate" aria-label="CGs">
      <div className="studio-section-heading"><h3>Event CGs</h3>
        {canWrite && <button type="button" className="studio-secondary" onClick={() => setUploading(true)}>Upload CG</button>}</div>
      <p className="studio-hint">Full-scene illustrations cover the stage while dialogue continues.
        Choose an approved image in Write → Stage → Event CG. Other image uploads also appear here.</p>
    </section>}
    {notice && <p className="studio-notice" role="status">{notice}</p>}
    {assets === null ? <p className="studio-hint">Loading assets…</p>
      : !assets.length ? <p className="studio-empty">{filter === "candidates" ? "Nothing waiting for review." : filter === "image" ? "No CGs here yet." : "No assets here yet."}</p>
      : <div className="studio-asset-grid">{assets.map(asset => <AssetCard key={asset.id} tenantId={tenantId}
          projectId={projectId} asset={asset} canWrite={canWrite} onView={() => setViewing(asset)}
          onRename={name => act(async () => replace(await api.renameNarrativeAsset(tenantId, projectId, asset.id, name)), "Could not rename.")}
          onApprove={() => act(async () => {
            const approved = await api.approveNarrativeAsset(tenantId, projectId, asset.id);
            // Under "To review" an approved asset leaves the list; elsewhere it updates in place.
            if (filter === "candidates") setAssets(current => current?.filter(item => item.id !== asset.id) ?? null);
            else replace(approved);
          }, "Could not approve.")}
          onDiscard={() => act(async () => {
            await api.discardNarrativeImage(tenantId, projectId, asset.id);
            setAssets(current => current?.filter(item => item.id !== asset.id) ?? null);
          }, "Could not discard.")} />)}</div>}
    {next && <button type="button" className="studio-secondary" onClick={() => void load(next)}>Show more</button>}
    {uploading && <UploadDialog tenantId={tenantId} projectId={projectId} initialKind={uploadKindForFilter(filter)} onClose={() => setUploading(false)}
      onUploaded={asset => { setUploading(false); setNotice(`Added “${asset.name}”.`); refreshLibrary();
        setAssets(current => filter === "all" || filter === asset.kind ? [asset, ...(current ?? [])] : current); }} />}
    {viewing && viewing.media_type === "image/png" && <Viewer tenantId={tenantId} projectId={projectId}
      asset={viewing} onClose={() => setViewing(null)} />}
  </section>;
}

function BackgroundGenerator({ tenantId, projectId, active, onStarted, onCancel }: {
  tenantId: string; projectId: string; active: ImageJob | null;
  onStarted: (job: ImageJob) => void; onCancel: (job: ImageJob) => void;
}) {
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!description.trim() || busy || active) return;
    setBusy(true); setError(null);
    try { onStarted(await api.createBackgroundJob(tenantId, projectId, description.trim(), 4)); }
    catch (failure) { setError(message(failure, "Could not start generating backgrounds.")); }
    finally { setBusy(false); }
  }
  return <form className="studio-asset-generate" onSubmit={event => void submit(event)}>
    <Field label="Generate backgrounds" hint="Describe a place without people: where, time of day, weather, mood.">
      <textarea rows={2} maxLength={600} value={description} placeholder="old harbor at dusk, fog over the water, lanterns on the pier"
        onChange={event => setDescription(event.target.value)} /></Field>
    <div className="studio-actions">
      <button type="submit" className="studio-secondary" disabled={busy || Boolean(active) || !description.trim()}>
        {active ? "Generating…" : "Generate 4 backgrounds"}</button>
      {active && <><span role="status" className="studio-hint">{jobStatus(active).replace("portrait", "background")}</span>
        {!active.cancel_requested && <button type="button" className="studio-link" onClick={() => onCancel(active)}>Cancel</button>}</>}
    </div>
    {error && <p className="studio-error" role="alert">{error}</p>}
  </form>;
}

function AssetCard({ tenantId, projectId, asset, canWrite, onView, onRename, onApprove, onDiscard }: {
  tenantId: string; projectId: string; asset: NarrativeImage; canWrite: boolean;
  onView: () => void; onRename: (name: string) => Promise<void>; onApprove: () => Promise<void>; onDiscard: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const image = asset.media_type === "image/png";
  const url = useNarrativeImage(tenantId, projectId, image ? asset.id : null, "thumbnail");
  return <figure className={`studio-asset ${asset.status === "candidate" ? "candidate" : ""}`}>
    {image ? <button type="button" className={`studio-asset-preview ${asset.kind}`} onClick={onView} aria-label={`View ${asset.name}`}>
      {url ? <img src={url} alt="" /> : <span>Loading…</span>}</button>
      : <FontSample tenantId={tenantId} projectId={projectId} asset={asset} />}
    <figcaption>
      {editing ? <input className="studio-asset-rename" autoFocus defaultValue={asset.name} maxLength={120} aria-label="Asset name"
        onKeyDown={event => {
          if (event.key === "Enter") { event.preventDefault(); void onRename(event.currentTarget.value); setEditing(false); }
          if (event.key === "Escape") setEditing(false);
        }} onBlur={event => { if (event.currentTarget.value.trim() !== asset.name) void onRename(event.currentTarget.value); setEditing(false); }} />
        : <strong title={asset.name} onDoubleClick={() => canWrite && setEditing(true)}>{asset.name}</strong>}
      <small>{KIND_LABELS[asset.kind] ?? asset.kind}{asset.width ? ` · ${asset.width}×${asset.height}` : ""} · {asset.license}</small>
      {asset.status === "candidate" && <span className="studio-asset-badge">To review</span>}
      {canWrite && <span className="studio-asset-actions">
        {asset.status === "candidate" && <button type="button" className="studio-secondary" onClick={() => void onApprove()}>Approve</button>}
        <button type="button" className="studio-link" onClick={() => setEditing(true)}>Rename</button>
        <button type="button" className="studio-link studio-danger" onClick={() => void onDiscard()}>Discard</button>
      </span>}
    </figcaption>
  </figure>;
}

function FontSample({ tenantId, projectId, asset }: { tenantId: string; projectId: string; asset: NarrativeImage }) {
  const family = useAssetFont(tenantId, projectId, asset.id);
  return <div className="studio-asset-preview font" style={family ? { fontFamily: `"${family}"` } : undefined}>
    {family === false ? "This font could not be previewed." : <><span>Aa</span><p>The bell rang once across the harbor.</p></>}
  </div>;
}

function UploadDialog({ tenantId, projectId, initialKind, onClose, onUploaded }: {
  tenantId: string; projectId: string; initialKind: UploadKind; onClose: () => void; onUploaded: (asset: NarrativeImage) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<UploadKind>(initialKind);
  const [name, setName] = useState("");
  const [license, setLicense] = useState("Own work");
  const [notice, setNotice] = useState("");
  const [declared, setDeclared] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const problem = file ? uploadProblem(file, kind) : null;
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || problem || !declared || busy) return;
    setBusy(true); setError(null);
    try {
      onUploaded(await api.uploadNarrativeAsset(tenantId, projectId, { file, kind, name: name.trim(), license: license.trim(), notice }));
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 413 ? "This file is too large." : message(failure, "Could not upload."));
    } finally { setBusy(false); }
  }
  const title = initialKind === "image" ? "Upload a CG" : "Upload an asset";
  return <StudioDialog label={title} onClose={onClose}>
    <form className="studio-peek-body studio-form" onSubmit={event => void submit(event)}>
      <div className="studio-section-heading"><h2>{title}</h2>
        <button type="button" className="studio-secondary" onClick={onClose}>Close</button></div>
      <Field label="File" hint="PNG images up to 10 MB (transparency kept), or TTF/OTF fonts up to 8 MB.">
        <input type="file" accept=".png,.ttf,.otf,image/png,font/ttf,font/otf" onChange={event => {
          const chosen = event.target.files?.[0] ?? null;
          setFile(chosen);
          if (chosen) { setName(suggestName(chosen.name)); if (kindForFile(chosen.name) === "font") setKind("font");
            else if (kind === "font") setKind(initialKind === "font" ? "image" : initialKind); }
        }} /></Field>
      <Field label="Kind"><select value={kind} onChange={event => setKind(event.target.value as UploadKind)}>
        {UPLOAD_KINDS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
      <Field label="Name"><input value={name} maxLength={120} onChange={event => setName(event.target.value)} /></Field>
      <Field label="License" hint="For example: Own work, CC BY 4.0, OFL-1.1."><input value={license} maxLength={120}
        onChange={event => setLicense(event.target.value)} /></Field>
      <Field label="Credit or notice" hint="Shipped with your game when this asset is used. Optional.">
        <textarea rows={2} maxLength={4000} value={notice} onChange={event => setNotice(event.target.value)} /></Field>
      <label className="studio-check"><input type="checkbox" checked={declared} onChange={event => setDeclared(event.target.checked)} />
        <span>I made this file or have the right to use it in my game.</span></label>
      {(problem || error) && <p className="studio-error" role="alert">{problem ?? error}</p>}
      <div className="studio-actions"><button type="submit" className="studio-primary"
        disabled={!file || Boolean(problem) || !declared || !name.trim() || !license.trim() || busy}>{busy ? "Uploading…" : "Upload"}</button></div>
    </form>
  </StudioDialog>;
}
