import { useEffect, useMemo, useRef, useState } from "react";
import { attachmentKind, isAttached, libraryChoices, MAX_ATTACHMENTS, toggleAttachment } from "./assistantLibrary";
import type { Attachment, LibraryTab } from "./assistantLibrary";
import { CharacterAvatar } from "./characterImages";
import { AssetThumb, useApprovedAssets } from "./libraryAssets";
import { ClipPlayButton } from "./VoiceControls";
import type { StoryDraft } from "./types";

const TABS: Array<[LibraryTab, string]> = [["characters", "Characters"], ["pictures", "Pictures"], ["voices", "Voices"]];
const EMPTY: Record<LibraryTab, string> = {
  characters: "No characters yet. Ask the assistant to add one.",
  pictures: "No approved pictures yet. Approve one to use it here.",
  voices: "No approved voice clips yet.",
};

// The project's characters and approved files, to attach to the next message (ADR 0062).
export function LibraryPicker({ tenantId, projectId, story, attached, onChange, onClose }: {
  tenantId: string; projectId: string; story: StoryDraft | null; attached: Attachment[];
  onChange: (attached: Attachment[]) => void; onClose: () => void;
}) {
  const { assets, failed } = useApprovedAssets(tenantId, projectId);
  const [tab, setTab] = useState<LibraryTab>("characters");
  const [search, setSearch] = useState("");
  const panel = useRef<HTMLDivElement>(null), input = useRef<HTMLInputElement>(null);
  const choices = useMemo(() => libraryChoices(story, assets, tab, search), [story, assets, tab, search]);
  const byId = useMemo(() => new Map((assets ?? []).map(asset => [asset.id, asset])), [assets]);
  const full = attached.length >= MAX_ATTACHMENTS;
  useEffect(() => { input.current?.focus(); }, []);
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [onClose]);
  return <div ref={panel} className="assistant-library" role="dialog" aria-label="Library">
    <div className="assistant-library-head">
      <strong>Library</strong>
      <input ref={input} type="search" aria-label="Search the library" placeholder="Search…" value={search}
        onChange={event => setSearch(event.target.value)} />
      <button type="button" className="studio-link" onClick={onClose}>Done</button>
    </div>
    <div className="assistant-library-tabs" role="tablist" aria-label="Library sections">
      {TABS.map(([id, label]) => <button type="button" key={id} role="tab" aria-selected={tab === id}
        className={tab === id ? "selected" : ""} onClick={() => setTab(id)}>{label}</button>)}
    </div>
    {failed && <p className="studio-error" role="alert">The library couldn't be loaded.</p>}
    {tab !== "characters" && assets === null && <p className="studio-hint">Loading…</p>}
    {(tab === "characters" || assets !== null) && !choices.length && !failed
      && <p className="studio-hint">{search.trim() ? "Nothing matches that." : EMPTY[tab]}</p>}
    <ul className="assistant-library-items">{choices.map(item => {
      const selected = isAttached(attached, item), asset = byId.get(item.id);
      return <li key={`${item.kind}:${item.id}`} className={selected ? "selected" : ""}>
        <button type="button" aria-pressed={selected} disabled={!selected && full}
          onClick={() => onChange(toggleAttachment(attached, item))}>
          {item.kind === "character" ? <CharacterAvatar characterId={item.id} name={item.name} size={44} />
            : item.asset_kind === "voice" ? <span className="assistant-library-clip" aria-hidden="true">♪</span>
            : <AssetThumb tenantId={tenantId} projectId={projectId} asset={asset} label={item.name} />}
          <span><strong>{item.name}</strong><small>{attachmentKind(item)}</small></span>
        </button>
        {item.asset_kind === "voice" && <ClipPlayButton assetId={item.id} />}
      </li>;
    })}</ul>
    {full && <p className="studio-hint">You can attach up to {MAX_ATTACHMENTS} items to one message.</p>}
  </div>;
}
