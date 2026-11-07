import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { StudioDialog } from "./StudioDialog";
import { deletionBlocked, deletionList } from "./trashModel";
import type { ProjectContents } from "./trashModel";
import type { NarrativeProject } from "./types";

const problem = (error: unknown, fallback: string) => error instanceof Error && error.message ? error.message : fallback;

/** One story on the project list: opens it, and offers what can be done to it from outside. */
export function ProjectCard({ project, disabled, canWrite, canDelete, onOpen, onRename, onTrash }: {
  project: NarrativeProject; disabled: boolean; canWrite: boolean; canDelete: boolean;
  onOpen: () => void; onRename: () => void; onTrash: () => void;
}) {
  return <article className="studio-project">
    <button type="button" className="studio-project-open" disabled={disabled} onClick={onOpen}>
      <span>Authored story</span><h3>{project.name}</h3>
      <p>Open the writing desk <span aria-hidden="true">↗</span></p>
    </button>
    {(canWrite || canDelete) && <div className="studio-project-actions">
      {canWrite && <button type="button" className="studio-link" disabled={disabled} aria-label={`Rename ${project.name}`} onClick={onRename}>Rename</button>}
      {canDelete && <button type="button" className="studio-link" disabled={disabled} aria-label={`Move ${project.name} to the trash`} onClick={onTrash}>Move to trash</button>}
    </div>}
  </article>;
}

export function RenameDialog({ tenantId, project, onDone, onClose }: {
  tenantId: string; project: NarrativeProject; onDone: (project: NarrativeProject) => void; onClose: () => void;
}) {
  const [name, setName] = useState(project.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const clean = name.trim();
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!clean || busy) return;
    if (clean === project.name) { onClose(); return; }
    setBusy(true); setError(null);
    try { onDone(await api.renameNarrativeProject(tenantId, project.id, clean)); }
    catch (failure) { setError(problem(failure, "The project could not be renamed.")); setBusy(false); }
  }
  return <StudioDialog label="Rename project" onClose={onClose}>
    <form className="studio-peek-body studio-small-dialog" onSubmit={event => void submit(event)}>
      <h2>Rename project</h2>
      <p className="studio-hint">This is the name you see in the Studio. The title players see is under Details.</p>
      <label className="studio-field"><span>Name</span>
        <input value={name} maxLength={200} autoFocus onChange={event => setName(event.target.value)} /></label>
      {error && <p role="alert" className="studio-error">{error}</p>}
      <div className="studio-dialog-buttons">
        <button type="button" className="studio-secondary" disabled={busy} onClick={onClose}>Cancel</button>
        <button type="submit" className="studio-primary" disabled={!clean || busy}>{busy ? "Saving…" : "Rename"}</button>
      </div>
    </form>
  </StudioDialog>;
}

/** The warning before a project is gone for good. It says what will be lost, in counts. */
function DeleteForeverDialog({ tenantId, project, onDeleted, onClose }: {
  tenantId: string; project: NarrativeProject; onDeleted: () => void; onClose: () => void;
}) {
  const [contents, setContents] = useState<ProjectContents | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api.narrativeProjectContents(tenantId, project.id).then(
      next => { if (alive) setContents(next); },
      failure => { if (alive) setError(problem(failure, "What this project holds could not be loaded.")); });
    return () => { alive = false; };
  }, [tenantId, project.id]);
  const blocked = contents && deletionBlocked(contents);
  async function confirm() {
    setBusy(true); setError(null);
    try { await api.deleteNarrativeProject(tenantId, project.id); onDeleted(); }
    catch (failure) { setError(problem(failure, "The project could not be deleted. It is still in the trash, so you can try again.")); setBusy(false); }
  }
  return <StudioDialog label={`Delete ${project.name} forever`} onClose={onClose}>
    <div className="studio-peek-body studio-small-dialog">
      <h2>Delete &ldquo;{project.name}&rdquo; forever?</h2>
      <p><strong>This cannot be undone.</strong> Nothing can bring it back.</p>
      {contents && deletionList(contents).length > 0 && <>
        <p>This will permanently delete:</p>
        <ul className="studio-delete-list">{deletionList(contents).map(line => <li key={line}>{line}</li>)}</ul>
      </>}
      {!contents && !error && <p role="status" className="studio-hint">Checking what this project holds…</p>}
      <p className="studio-hint">Games you already downloaded keep working. Credits already spent are not refunded.</p>
      {blocked && <p role="status" className="studio-gpu-notice">{blocked}</p>}
      {error && <p role="alert" className="studio-error">{error}</p>}
      <div className="studio-dialog-buttons">
        <button type="button" className="studio-secondary" disabled={busy} onClick={onClose}>Keep it</button>
        <button type="button" className="studio-danger-button" disabled={busy || !contents || Boolean(blocked)}
          onClick={() => void confirm()}>{busy ? "Deleting…" : "Delete forever"}</button>
      </div>
    </div>
  </StudioDialog>;
}

/** Projects moved to the trash: nothing here is lost until someone chooses Delete forever. */
export function TrashView({ tenantId, onBack, onChanged }: {
  tenantId: string; onBack: () => void; onChanged: () => void;
}) {
  const [rows, setRows] = useState<NarrativeProject[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<NarrativeProject | null>(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const load = useCallback(async () => {
    try {
      const next = await api.listNarrativeProjects(tenantId, { trashed: true, limit: 100 });
      if (alive.current) { setRows(next); setError(null); }
    } catch (failure) { if (alive.current) setError(problem(failure, "The trash could not be loaded.")); }
  }, [tenantId]);
  useEffect(() => { void load(); }, [load]);
  async function restore(project: NarrativeProject) {
    setBusyId(project.id); setError(null);
    try {
      await api.trashNarrativeProject(tenantId, project.id, project.head_revision_id, false);
      await load(); onChanged();
    } catch (failure) { if (alive.current) setError(problem(failure, "The project could not be restored.")); }
    finally { if (alive.current) setBusyId(null); }
  }
  return <section aria-label="Trash">
    <button type="button" className="studio-back-link" onClick={onBack}><span aria-hidden="true">←</span> Your stories</button>
    <div className="studio-section-heading"><h2>Trash</h2></div>
    <p className="studio-hint">Projects here keep all their files until you delete them forever. Restore one to pick up where you left off.</p>
    {error && <p role="alert" className="studio-error">{error}</p>}
    <div className="studio-projects">{(rows ?? []).map(project => <article className="studio-project is-trashed" key={project.id}>
      <div className="studio-project-open"><span>In the trash</span><h3>{project.name}</h3></div>
      <div className="studio-project-actions">
        <button type="button" className="studio-link" disabled={busyId !== null || Boolean(project.purge_started_at)}
          aria-label={`Restore ${project.name}`}
          title={project.purge_started_at ? "Deleting already started, so this project can only be deleted now." : undefined}
          onClick={() => void restore(project)}>{busyId === project.id ? "Restoring…" : "Restore"}</button>
        <button type="button" className="studio-link studio-danger" disabled={busyId !== null}
          aria-label={`Delete ${project.name} forever`} onClick={() => setDeleting(project)}>
          {project.purge_started_at ? "Finish deleting" : "Delete forever"}</button>
      </div>
    </article>)}</div>
    {rows && !rows.length && <p className="studio-empty">The trash is empty.</p>}
    {!rows && !error && <p role="status" className="studio-empty">Opening the trash…</p>}
    {deleting && <DeleteForeverDialog tenantId={tenantId} project={deleting} onClose={() => setDeleting(null)}
      onDeleted={() => { setDeleting(null); void load(); onChanged(); }} />}
  </section>;
}
