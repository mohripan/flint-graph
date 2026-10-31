import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, api } from "../lib/api";
import type { ImageJob, NarrativeImage } from "../lib/api";
import { FolderActions, LibraryRail, MoveBar } from "./LibraryRail";
import { folderPath, folderRows, uploadKindForView, viewQuery, viewTitle } from "./assetFolders";
import type { LibraryIndex, LibraryView } from "./assetFolders";
import { KIND_LABELS, UPLOAD_KINDS, kindForFile, suggestName, uploadProblem } from "./assetModel";
import type { UploadKind } from "./assetModel";
import { useNarrativeImage } from "./characterImages";
import { refreshLibrary, useAssetFont } from "./libraryAssets";
import { isActive, jobStatus } from "./characterModel";
import { imageJobStarted, useBackgroundJobs, useLibraryJobs } from "./imageJobs";
import { CgGenerator } from "./CgGenerator";
import { cgSubject } from "./cgModel";
import { Viewer } from "./CharacterStudio";
import { Field } from "./FormFields";
import { StudioDialog } from "./StudioDialog";
import { ClipPlayButton } from "./VoiceControls";
import { VoiceReferences, useVoiceReferences } from "./VoiceReferences";

const PAGE = 48;
const message = (error: unknown, fallback: string) => error instanceof Error && error.message ? error.message : fallback;

// The project's art, fonts and voice clips: uploads with a rights declaration and
// generated items. Only approved assets can be used by the story. Folders and the
// automatic groups only organize the library (ADR 0043).
export function AssetLibrary({ tenantId, projectId, canWrite, characterNames = {} }: {
  tenantId: string; projectId: string; canWrite: boolean; characterNames?: Record<string, string>;
}) {
  const [view, setView] = useState<LibraryView>({ type: "all" });
  const [index, setIndex] = useState<LibraryIndex | null>(null);
  const [assets, setAssets] = useState<NarrativeImage[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [viewing, setViewing] = useState<NarrativeImage | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const { jobs, failed: jobsFailed, put } = useBackgroundJobs(tenantId, projectId);
  const { references } = useVoiceReferences(tenantId, projectId, canWrite);
  const private_ = view.type === "references";
  const active = jobs.find(isActive) ?? null;
  // Event CGs of a character (ADR 0041 slice C) run as their own library jobs.
  const scenes = useLibraryJobs(tenantId, projectId, "scene_art");
  const activeScene = scenes.jobs.find(isActive) ?? null;
  const [generatingCgs, setGeneratingCgs] = useState(false);

  const reindex = useCallback(() => {
    api.getAssetIndex(tenantId, projectId).then(setIndex).catch(() => undefined);
  }, [tenantId, projectId]);
  const load = useCallback(async (before?: string) => {
    try {
      const page = await api.listNarrativeAssets(tenantId, projectId, { ...viewQuery(view), limit: PAGE, before });
      setAssets(current => before && current ? [...current, ...page.assets] : page.assets);
      setNext(page.next_before);
    } catch (error) { setNotice(message(error, "Could not load assets.")); setAssets(current => current ?? []); }
  }, [tenantId, projectId, view]);
  useEffect(() => {
    setAssets(null); setSelected(new Set());
    if (view.type !== "references") void load();
  }, [load, view.type]);
  useEffect(() => { reindex(); }, [reindex]);
  // Background jobs are shared with the assistant; reload the grid when one finishes.
  const completedJobs = [...jobs, ...scenes.jobs].filter(job => job.status === "completed").map(job => job.id).sort().join(",");
  useEffect(() => {
    if (completedJobs) { void load(); refreshLibrary(); reindex(); }
  }, [completedJobs, load, reindex]);

  const replace = (asset: NarrativeImage) => setAssets(current => current?.map(item => item.id === asset.id ? asset : item) ?? null);
  async function act(run: () => Promise<void>, fallback: string) {
    setNotice(null);
    try { await run(); refreshLibrary(); reindex(); } catch (error) { setNotice(message(error, fallback)); }
  }
  async function folderChange(run: () => Promise<unknown>, fallback: string): Promise<boolean> {
    setNotice(null);
    try { await run(); reindex(); return true; } catch (error) { setNotice(message(error, fallback)); return false; }
  }
  const cgs = view.type === "kind" && view.kind === "image";
  const folders = index?.folders ?? [];
  const openFolder = view.type === "folder" ? folders.find(item => item.id === view.id) : undefined;
  const depth = openFolder ? folderRows(folders).find(row => row.folder.id === openFolder.id)?.depth ?? 0 : 0;
  const create = (name: string, parent: string | null) => folderChange(async () => {
    const made = await api.createAssetFolder(tenantId, projectId, name, parent);
    setView({ type: "folder", id: made.id });
  }, "Could not create the folder.");
  const toggle = (id: string) => setSelected(current => {
    const updated = new Set(current);
    if (updated.has(id)) updated.delete(id); else updated.add(id);
    return updated;
  });
  const move = (folder: string | null) => void act(async () => {
    const moved = await api.moveNarrativeAssets(tenantId, projectId, [...selected], folder);
    // Assets that no longer belong to the open folder or Unsorted leave the grid.
    const still = (asset: NarrativeImage) => view.type === "folder" ? asset.folder_id === view.id
      : view.type === "unfiled" ? !asset.folder_id : true;
    const changed = new Map(moved.assets.map(asset => [asset.id, asset]));
    setAssets(current => current?.map(item => changed.get(item.id) ?? item).filter(still) ?? null);
    setSelected(new Set());
    setNotice(`Moved ${moved.assets.length} ${moved.assets.length === 1 ? "asset" : "assets"}.`);
  }, "Could not move the assets.");

  return <section className="studio-assets" aria-label="Assets">
    <div className="studio-section-heading"><h2>Assets</h2>
      {canWrite && <button type="button" className="studio-primary" onClick={() => setUploading(true)}>Upload</button>}</div>
    <p className="studio-hint">Backgrounds, character sprites, CGs, fonts and voice clips for this story. Uploads keep transparency; generated items wait here for your approval. Folders only organize the library: stories and games stay the same.</p>
    {canWrite && !cgs && <BackgroundGenerator tenantId={tenantId} projectId={projectId} active={active}
      onStarted={job => { imageJobStarted(tenantId, projectId, job); setView({ type: "review" }); }}
      onCancel={job => void act(async () => {
        const next = await api.cancelImageJob(tenantId, projectId, job.id);
        put(next);
      }, "Could not cancel.")} />}
    {(jobsFailed || scenes.failed) && <p className="studio-notice" role="status">Image status could not be refreshed. Retrying…</p>}
    {jobs.filter(isActive).map(job => <section key={job.id} className="studio-asset-generate" aria-label="Background generation">
      <strong>Generating backgrounds</strong>
      <p role="status">{jobStatus(job)}</p>
      <progress max={job.count} value={job.progress} aria-label="Generated backgrounds" />
      {canWrite && !job.cancel_requested && <button type="button" className="studio-link" onClick={() => void act(async () => {
        put(await api.cancelImageJob(tenantId, projectId, job.id));
      }, "Could not cancel.")}>Cancel background generation</button>}
    </section>)}
    {scenes.jobs.filter(isActive).map(job => <section key={job.id} className="studio-asset-generate" aria-label="CG generation">
      <strong>Generating CGs of {cgSubject(job, characterNames)}</strong>
      <p role="status">{jobStatus(job)}</p>
      <progress max={job.count} value={job.progress} aria-label="Generated CGs" />
      {canWrite && !job.cancel_requested && <button type="button" className="studio-link" onClick={() => void act(async () => {
        scenes.put(await api.cancelImageJob(tenantId, projectId, job.id));
      }, "Could not cancel.")}>Cancel CG generation</button>}
    </section>)}
    <div className="studio-library">
      <LibraryRail index={index} names={characterNames} view={view} onView={setView} canWrite={canWrite} onCreate={create}
        references={references?.length} />
      <div className="studio-library-main">
        <div className="studio-library-head"><h3>{viewTitle(view, index, characterNames)}</h3>
          {canWrite && openFolder && <FolderActions folder={openFolder} folders={folders} depth={depth} onCreate={create}
            onRename={name => folderChange(() => api.updateAssetFolder(tenantId, projectId, openFolder.id, { name }), "Could not rename the folder.")}
            onDelete={() => {
              if (!window.confirm(`Delete the folder “${openFolder.name}”? Its assets and folders move up one level.`)) return;
              void folderChange(async () => {
                await api.deleteAssetFolder(tenantId, projectId, openFolder.id);
                setView(openFolder.parent_id ? { type: "folder", id: openFolder.parent_id } : { type: "all" });
              }, "Could not delete the folder.");
            }} />}</div>
        {cgs && <section className="studio-asset-generate" aria-label="CGs">
          <div className="studio-section-heading"><h3>Event CGs</h3>
            {canWrite && <span className="studio-actions">
              <button type="button" className="studio-secondary" aria-expanded={generatingCgs}
                onClick={() => setGeneratingCgs(open => !open)}>Generate CGs</button>
              <button type="button" className="studio-secondary" onClick={() => setUploading(true)}>Upload CG</button></span>}</div>
          <p className="studio-hint">Full-scene illustrations cover the stage while dialogue continues.
            Choose an approved image in Write → Stage → Event CG. Other image uploads also appear here.</p>
          {canWrite && generatingCgs && <CgGenerator tenantId={tenantId} projectId={projectId} characterNames={characterNames}
            active={activeScene} latest={scenes.jobs[0] ?? null}
            onStarted={job => imageJobStarted(tenantId, projectId, job)}
            onCancel={job => void act(async () => { scenes.put(await api.cancelImageJob(tenantId, projectId, job.id)); }, "Could not cancel.")} />}
        </section>}
        {private_ && <VoiceReferences tenantId={tenantId} projectId={projectId} canWrite={canWrite} />}
        {!private_ && canWrite && selected.size > 0 && <MoveBar count={selected.size} folders={folders}
          onClear={() => setSelected(new Set())} onMove={move} />}
        {notice && <p className="studio-notice" role="status">{notice}</p>}
        {private_ ? null : assets === null ? <p className="studio-hint">Loading assets…</p>
          : !assets.length ? <p className="studio-empty">{view.type === "review" ? "Nothing waiting for review." : cgs ? "No CGs here yet." : "No assets here yet."}</p>
          : <div className="studio-asset-grid">{assets.map(asset => <AssetCard key={asset.id} tenantId={tenantId}
              projectId={projectId} asset={asset} canWrite={canWrite} onView={() => setViewing(asset)}
              selected={selected.has(asset.id)} onSelect={() => toggle(asset.id)}
              folder={asset.folder_id ? folderPath(folders, asset.folder_id) : ""}
              onRename={name => act(async () => replace(await api.renameNarrativeAsset(tenantId, projectId, asset.id, name)), "Could not rename.")}
              onApprove={() => act(async () => {
                const approved = await api.approveNarrativeAsset(tenantId, projectId, asset.id);
                // Under "To review" an approved asset leaves the list; elsewhere it updates in place.
                if (view.type === "review") setAssets(current => current?.filter(item => item.id !== asset.id) ?? null);
                else replace(approved);
              }, "Could not approve.")}
              onDiscard={() => act(async () => {
                await api.discardNarrativeImage(tenantId, projectId, asset.id);
                setAssets(current => current?.filter(item => item.id !== asset.id) ?? null);
              }, "Could not discard.")} />)}</div>}
        {!private_ && next && <button type="button" className="studio-secondary" onClick={() => void load(next)}>Show more</button>}
      </div>
    </div>
    {uploading && <UploadDialog tenantId={tenantId} projectId={projectId} initialKind={uploadKindForView(view)} onClose={() => setUploading(false)}
      onUploaded={asset => { setUploading(false); setNotice(`Added “${asset.name}”.`); refreshLibrary(); reindex(); void load(); }} />}
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

function AssetCard({ tenantId, projectId, asset, canWrite, onView, onRename, onApprove, onDiscard, selected, onSelect, folder }: {
  tenantId: string; projectId: string; asset: NarrativeImage; canWrite: boolean;
  onView: () => void; onRename: (name: string) => Promise<void>; onApprove: () => Promise<void>; onDiscard: () => Promise<void>;
  selected: boolean; onSelect: () => void; folder: string;
}) {
  const [editing, setEditing] = useState(false);
  const image = asset.media_type === "image/png";
  const url = useNarrativeImage(tenantId, projectId, image ? asset.id : null, "thumbnail");
  return <figure className={`studio-asset ${asset.status === "candidate" ? "candidate" : ""} ${selected ? "selected" : ""}`}>
    {canWrite && <label className="studio-asset-select"><input type="checkbox" aria-label={`Select ${asset.name}`} checked={selected} onChange={onSelect} />
      <span className="studio-visually-hidden">Select {asset.name}</span></label>}
    {image ? <button type="button" className={`studio-asset-preview ${asset.kind}`} onClick={onView} aria-label={`View ${asset.name}`}>
      {url ? <img src={url} alt="" /> : <span>Loading…</span>}</button>
      : asset.media_type === "audio/wav" ? <div className="studio-asset-preview audio">
        <span aria-hidden="true">♪</span>
        {asset.provenance.text ? <p>“{String(asset.provenance.text)}”</p> : null}
        <ClipPlayButton assetId={asset.id} label="Listen" /></div>
      : <FontSample tenantId={tenantId} projectId={projectId} asset={asset} />}
    <figcaption>
      {editing ? <input className="studio-asset-rename" autoFocus defaultValue={asset.name} maxLength={120} aria-label="Asset name"
        onKeyDown={event => {
          if (event.key === "Enter") { event.preventDefault(); void onRename(event.currentTarget.value); setEditing(false); }
          if (event.key === "Escape") setEditing(false);
        }} onBlur={event => { if (event.currentTarget.value.trim() !== asset.name) void onRename(event.currentTarget.value); setEditing(false); }} />
        : <strong title={asset.name} onDoubleClick={() => canWrite && setEditing(true)}>{asset.name}</strong>}
      <small>{KIND_LABELS[asset.kind] ?? asset.kind}{asset.width ? ` · ${asset.width}×${asset.height}` : ""}{asset.duration_ms ? ` · ${(asset.duration_ms / 1000).toFixed(1)} s` : ""} · {asset.license}</small>
      {folder && <small title={folder}>In {folder}</small>}
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
      <Field label="File" hint="PNG images up to 10 MB (transparency kept), TTF/OTF fonts up to 8 MB, or 16-bit WAV voice clips up to 60 seconds.">
        <input type="file" accept=".png,.ttf,.otf,.wav,image/png,font/ttf,font/otf,audio/wav" onChange={event => {
          const chosen = event.target.files?.[0] ?? null;
          setFile(chosen);
          if (chosen) { setName(suggestName(chosen.name)); const detected = kindForFile(chosen.name);
            if (detected !== "image") setKind(detected);
            else if (kind === "font" || kind === "voice") setKind(initialKind === "font" || initialKind === "voice" ? "image" : initialKind); }
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
