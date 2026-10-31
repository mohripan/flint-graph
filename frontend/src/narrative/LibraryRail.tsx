import { useState } from "react";
import type { FormEvent } from "react";
import { canHoldFolders, folderNameProblem, folderRows, railGroups, sameView } from "./assetFolders";
import type { AssetFolder, LibraryIndex, LibraryView, RailItem } from "./assetFolders";

// The Assets tab's side rail (ADR 0043): automatic groups by kind and character, plus
// the creator's folders. Nothing here changes asset bytes or stories.
export function LibraryRail({ index, names, view, onView, canWrite, onCreate, references }: {
  index: LibraryIndex | null; names: Record<string, string>; view: LibraryView;
  onView: (view: LibraryView) => void; canWrite: boolean;
  onCreate: (name: string, parent: string | null) => Promise<boolean>;
  references?: number;
}) {
  const groups = index ? railGroups(index, names) : null;
  const item = (entry: RailItem, depth = 0) => <li key={JSON.stringify(entry.view)}>
    <button type="button" aria-current={sameView(entry.view, view) ? "true" : undefined}
      aria-label={`${entry.label}, ${entry.count}`} className={sameView(entry.view, view) ? "selected" : ""} style={depth ? { paddingLeft: 10 + depth * 14 } : undefined}
      onClick={() => onView(entry.view)}><span>{entry.label}</span><small>{entry.count}</small></button></li>;
  return <nav className="studio-library-rail" aria-label="Asset groups">
    <ul>{(groups?.library ?? [{ view: { type: "all" }, label: "All assets", count: 0 }]).map(entry => item(entry))}</ul>
    {groups && groups.kinds.length > 0 && <><h3>By kind</h3><ul>{groups.kinds.map(entry => item(entry))}</ul></>}
    {groups && groups.characters.length > 0 && <><h3>By character</h3><ul>{groups.characters.map(entry => item(entry))}</ul></>}
    {canWrite && <><h3>Private</h3><ul>{item({ view: { type: "references" }, label: "Voice references", count: references ?? 0 })}</ul></>}
    <h3>Folders</h3>
    <ul>{folderRows(index?.folders ?? []).map(({ folder, depth }) =>
      item({ view: { type: "folder", id: folder.id }, label: folder.name, count: folder.asset_count }, depth))}</ul>
    {index && !index.folders.length && <p className="studio-hint">Make folders to sort assets your way.</p>}
    {canWrite && <FolderNameForm folders={index?.folders ?? []} parent={null} label="New folder"
      onSubmit={name => onCreate(name, null)} />}
  </nav>;
}

export function FolderNameForm({ folders, parent, self, label, initial = "", onSubmit, onCancel }: {
  folders: AssetFolder[]; parent: string | null; self?: string; label: string; initial?: string;
  onSubmit: (name: string) => Promise<boolean>; onCancel?: () => void;
}) {
  const [open, setOpen] = useState(Boolean(onCancel));
  const [name, setName] = useState(initial);
  const [busy, setBusy] = useState(false);
  const problem = name ? folderNameProblem(name, folders, parent, self) : null;
  const close = () => { setOpen(false); setName(initial); onCancel?.(); };
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !name.trim() || problem) return;
    setBusy(true);
    try { if (await onSubmit(name.trim())) close(); } finally { setBusy(false); }
  }
  if (!open) return <button type="button" className="studio-link" onClick={() => setOpen(true)}>+ {label}</button>;
  return <form className="studio-folder-form" onSubmit={event => void submit(event)}>
    <input aria-label={label} autoFocus value={name} maxLength={80} placeholder="Folder name"
      onChange={event => setName(event.target.value)} onKeyDown={event => { if (event.key === "Escape") close(); }} />
    <button type="submit" className="studio-secondary" disabled={busy || !name.trim() || Boolean(problem)}>Save</button>
    <button type="button" className="studio-link" onClick={close}>Cancel</button>
    {problem && <p className="studio-error" role="alert">{problem}</p>}
  </form>;
}

/** Folder actions shown above the grid while a folder is open. */
export function FolderActions({ folder, folders, depth, onCreate, onRename, onDelete }: {
  folder: AssetFolder; folders: AssetFolder[]; depth: number;
  onCreate: (name: string, parent: string | null) => Promise<boolean>;
  onRename: (name: string) => Promise<boolean>; onDelete: () => void;
}) {
  const [renaming, setRenaming] = useState(false);
  return <div className="studio-folder-actions">
    {canHoldFolders(depth) && <FolderNameForm folders={folders} parent={folder.id} label="New folder inside"
      onSubmit={name => onCreate(name, folder.id)} />}
    {renaming ? <FolderNameForm folders={folders} parent={folder.parent_id} self={folder.id} label="Rename folder"
      initial={folder.name} onSubmit={onRename} onCancel={() => setRenaming(false)} />
      : <button type="button" className="studio-link" onClick={() => setRenaming(true)}>Rename folder</button>}
    <button type="button" className="studio-link studio-danger" onClick={onDelete}>Delete folder</button>
  </div>;
}

/** Shown while assets are selected: file them into a folder or back to Unsorted. */
export function MoveBar({ count, folders, onMove, onClear }: {
  count: number; folders: AssetFolder[]; onMove: (folder: string | null) => void; onClear: () => void;
}) {
  return <div className="studio-move-bar" role="group" aria-label="Selected assets">
    <strong>{count} selected</strong>
    <label>Move to <select value="" onChange={event => {
      if (event.target.value) onMove(event.target.value === "none" ? null : event.target.value);
    }}>
      <option value="">Choose a folder…</option>
      <option value="none">Unsorted (no folder)</option>
      {folderRows(folders).map(({ folder, depth }) =>
        <option key={folder.id} value={folder.id}>{" ".repeat(depth * 3)}{folder.name}</option>)}
    </select></label>
    <button type="button" className="studio-link" onClick={onClear}>Clear selection</button>
  </div>;
}
