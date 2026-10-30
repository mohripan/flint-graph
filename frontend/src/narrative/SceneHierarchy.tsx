import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { MutableRefObject } from "react";
import { ApiError, api } from "../lib/api";
import type { Passage } from "./passages";
import { releaseErrorMessage, useReleaseRequests } from "./releaseRequests";
import {
  addGroup, canDrop, flattenTree, moveItem, newGroupId, normalizeLayout, parentPath, removeGroup, renameGroup, toggleGroup,
} from "./sceneTree";
import type { LayoutItem, Path, TreeRow } from "./sceneTree";

const ROW = 34, OVERSCAN = 12;
type Drop = { index: number; where: "before" | "after" | "inside" };
const glyph: Record<Passage["kind"], string> = { scene: "¶", choice: "⑂", branch: "◇", end: "■", state: "⚙" };

// Godot-style scene hierarchy: folders (routes, chapters) and scenes, reordered by
// dragging or with Alt+arrow keys. The layout is editor-only, shared and versioned;
// story content and gameplay never change when scenes move.
export function SceneHierarchy({ tenantId, projectId, passages, owner, from, selected, canWrite, scopeRef,
  onSelect, onAccessLost }: {
  tenantId: string; projectId: string; passages: Passage[]; owner: Map<string, string>;
  from: Map<string, string>; selected: string;
  canWrite: boolean; scopeRef: MutableRefObject<(() => void) | null>;
  onSelect: (passageId: string) => void; onAccessLost: () => void;
}) {
  const { run, invalidate } = useReleaseRequests(onAccessLost);
  useLayoutEffect(() => {
    scopeRef.current = invalidate;
    return () => { if (scopeRef.current === invalidate) scopeRef.current = null; };
  }, [scopeRef, invalidate]);
  const [items, setItems] = useState<LayoutItem[] | null>(null);
  const version = useRef(0), savedJson = useRef(""), known = useRef<Set<string> | null>(null);
  const [query, setQuery] = useState(""), [status, setStatus] = useState<string | null>(null);
  const [focusKey, setFocusKey] = useState<string | null>(null), [renaming, setRenaming] = useState<string | null>(null);
  const [drag, setDrag] = useState<{ from: Path; label: string; drop: Drop | null } | null>(null);
  const [scrollTop, setScrollTop] = useState(0), [height, setHeight] = useState(480);
  const viewport = useRef<HTMLDivElement>(null), press = useRef<{ x: number; y: number; row: TreeRow } | null>(null);
  const byId = useMemo(() => new Map(passages.map(passage => [passage.id, passage])), [passages]);
  const titles = useMemo(() => new Map(passages.map(passage => [passage.id, passage.title])), [passages]);
  // Text edits create new passage objects; only a changed set of scenes renormalizes.
  const idsKey = passages.map(passage => passage.id).join("\u0000");
  const ids = useMemo(() => idsKey ? idsKey.split("\u0000") : [], [idsKey]);
  const activeScene = owner.get(selected) ?? selected;

  useEffect(() => {
    void run("layout", signal => api.getNarrativeLayout(tenantId, projectId, signal), layout => {
      if (layout.project_id !== projectId) return;
      version.current = layout.version; savedJson.current = JSON.stringify(layout.items);
      known.current = new Set(ids);
      setItems(normalizeLayout(layout.items, ids));
    }, error => { setStatus(releaseErrorMessage(error)); known.current = new Set(ids); setItems(normalizeLayout([], ids)); });
    // Load once per project; later story edits renormalize below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run, tenantId, projectId]);
  // New scenes (added lines, splits, assistant proposals) appear beside the scene they grew from.
  useEffect(() => {
    if (!items || !known.current) return;
    const anchors = new Map<string, string>();
    for (const id of ids) if (!known.current.has(id)) anchors.set(id, from.get(id) ?? activeScene);
    known.current = new Set(ids);
    setItems(current => current && normalizeLayout(current, ids, anchors));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids]);
  // Save shortly after the last change; a conflict adopts the newer shared layout.
  useEffect(() => {
    if (!items || !canWrite) return;
    const json = JSON.stringify(items);
    if (json === savedJson.current) return;
    const timer = window.setTimeout(() => {
      void run("save", signal => api.saveNarrativeLayout(tenantId, projectId, version.current, items, signal), saved => {
        version.current = saved.version; savedJson.current = JSON.stringify(saved.items);
      }, error => {
        if (error instanceof ApiError && error.status === 409) {
          void run("layout", signal => api.getNarrativeLayout(tenantId, projectId, signal), layout => {
            version.current = layout.version; savedJson.current = JSON.stringify(layout.items);
            setItems(normalizeLayout(layout.items, ids));
            setStatus("Someone else reorganized these scenes. Showing their latest layout.");
          }, failure => setStatus(releaseErrorMessage(failure)));
        } else setStatus(releaseErrorMessage(error));
      });
    }, 500);
    return () => window.clearTimeout(timer);
  }, [items, canWrite, run, tenantId, projectId, ids]);

  const rows = useMemo(() => items ? flattenTree(items, { query, titles }) : [], [items, query, titles]);
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setHeight(element.clientHeight));
    observer.observe(element); setHeight(element.clientHeight);
    return () => observer.disconnect();
  }, []);
  const first = Math.max(0, Math.floor(scrollTop / ROW) - OVERSCAN);
  const last = Math.min(rows.length, Math.ceil((scrollTop + height) / ROW) + OVERSCAN);
  const focusIndex = Math.max(0, rows.findIndex(row => row.key === focusKey));
  const reveal = (index: number) => {
    const element = viewport.current;
    if (!element) return;
    if (index * ROW < element.scrollTop) element.scrollTop = index * ROW;
    else if ((index + 1) * ROW > element.scrollTop + element.clientHeight) element.scrollTop = (index + 1) * ROW - element.clientHeight;
  };
  const focusRow = (index: number) => {
    const row = rows[Math.max(0, Math.min(rows.length - 1, index))];
    if (!row) return;
    setFocusKey(row.key); reveal(rows.indexOf(row));
    window.requestAnimationFrame(() => viewport.current?.querySelector<HTMLElement>(`[data-key="${CSS.escape(row.key)}"]`)?.focus());
  };
  const change = useCallback((next: LayoutItem[], message?: string) => {
    setItems(next); if (message) setStatus(message);
  }, []);
  const label = (item: LayoutItem) => item.type === "group" ? item.name : titles.get(item.id) ?? item.id;

  function dropTarget(row: TreeRow, drop: Drop): { parent: Path; index: number } {
    if (drop.where === "inside") return { parent: row.path, index: 0 };
    return { parent: parentPath(row.path), index: row.path[row.path.length - 1] + (drop.where === "after" ? 1 : 0) };
  }
  // Live drag state is a ref so every pointer event sees the latest target, even when
  // a fast gesture delivers a single move before release.
  const dragging = useRef<{ from: Path; label: string; drop: Drop | null } | null>(null);
  const showDrag = (value: typeof dragging.current) => { dragging.current = value; setDrag(value); };
  function dropAt(clientY: number, from: Path): Drop | null {
    const element = viewport.current;
    if (!element || !items) return null;
    const box = element.getBoundingClientRect();
    const offset = clientY - box.top + element.scrollTop - 4;
    const index = Math.max(0, Math.min(rows.length - 1, Math.floor(offset / ROW)));
    const row = rows[index], within = (offset - index * ROW) / ROW;
    if (!row) return null;
    const where: Drop["where"] = row.item.type === "group"
      ? within < 0.25 ? "before" : within > 0.75 && (row.item.collapsed || !row.item.items.length) ? "after" : "inside"
      : within < 0.5 ? "before" : "after";
    return canDrop(items, from, dropTarget(row, { index, where }).parent) ? { index, where } : null;
  }
  function commitDrag(drop: Drop | null) {
    const current = dragging.current;
    showDrag(null);
    if (!current || !drop || !items) return;
    const row = rows[drop.index];
    if (!row) return;
    let next = moveItem(items, current.from, dropTarget(row, drop));
    if (drop.where === "inside" && row.item.type === "group") next = toggleGroup(next, row.item.id, false);
    if (next !== items) change(next, `Moved ${current.label}.`);
  }
  function pointerDown(event: React.PointerEvent, row: TreeRow) {
    if (!canWrite || query || event.button !== 0 || (event.target as HTMLElement).closest("input,button.studio-tree-toggle")) return;
    press.current = { x: event.clientX, y: event.clientY, row };
  }
  function pointerMove(event: React.PointerEvent) {
    const start = press.current;
    if (!start) return;
    if (!dragging.current) {
      if (Math.hypot(event.clientX - start.x, event.clientY - start.y) < 6) return;
      (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    }
    const element = viewport.current!;
    const box = element.getBoundingClientRect();
    if (event.clientY < box.top + 24) element.scrollTop -= 12;
    else if (event.clientY > box.bottom - 24) element.scrollTop += 12;
    showDrag({ from: start.row.path, label: label(start.row.item), drop: dropAt(event.clientY, start.row.path) });
  }
  function pointerUp(event: React.PointerEvent) {
    const start = press.current; press.current = null;
    if (dragging.current && start) { event.preventDefault(); commitDrag(dropAt(event.clientY, start.row.path)); return; }
    if (start) activate(start.row);
  }
  function activate(row: TreeRow) {
    setFocusKey(row.key);
    if (row.item.type === "scene") onSelect(row.item.id);
    else if (items) change(toggleGroup(items, row.item.id));
  }
  function keyDown(event: React.KeyboardEvent, row: TreeRow, index: number) {
    if (renaming) return;
    const item = row.item, siblings = row.path.length;
    const move = (to: { parent: Path; index: number }, message: string) => {
      if (!items || !canWrite || query) return;
      const next = moveItem(items, row.path, to);
      if (next !== items) { change(next, message); setFocusKey(row.key); window.requestAnimationFrame(() => focusRow(flattenTree(next, { query, titles }).findIndex(r => r.key === row.key))); }
    };
    if (event.key === "Escape" && dragging.current) { showDrag(null); press.current = null; return; }
    if (event.altKey && event.key === "ArrowUp") { event.preventDefault(); if (row.path[siblings - 1] > 0) move({ parent: parentPath(row.path), index: row.path[siblings - 1] - 1 }, `Moved ${label(item)} up.`); return; }
    if (event.altKey && event.key === "ArrowDown") { event.preventDefault(); move({ parent: parentPath(row.path), index: row.path[siblings - 1] + 2 }, `Moved ${label(item)} down.`); return; }
    if (event.altKey && event.key === "ArrowLeft" && siblings > 1) { event.preventDefault(); const parent = parentPath(row.path); move({ parent: parentPath(parent), index: parent[parent.length - 1] + 1 }, `Moved ${label(item)} out of its folder.`); return; }
    if (event.altKey && event.key === "ArrowRight" && items) {
      event.preventDefault();
      const previous = rows.slice(0, index).reverse().find(other => other.depth === row.depth && other.item.type === "group"
        && parentPath(other.path).join() === parentPath(row.path).join());
      if (previous && previous.item.type === "group") move({ parent: previous.path, index: previous.item.items.length }, `Moved ${label(item)} into ${previous.item.name}.`);
      return;
    }
    if (event.key === "ArrowDown") { event.preventDefault(); focusRow(index + 1); }
    else if (event.key === "ArrowUp") { event.preventDefault(); focusRow(index - 1); }
    else if (event.key === "Home") { event.preventDefault(); focusRow(0); }
    else if (event.key === "End") { event.preventDefault(); focusRow(rows.length - 1); }
    else if (event.key === "ArrowRight" && item.type === "group" && item.collapsed && items) change(toggleGroup(items, item.id, false));
    else if (event.key === "ArrowLeft" && item.type === "group" && !item.collapsed && items) change(toggleGroup(items, item.id, true));
    else if (event.key === "ArrowLeft" && siblings > 1) focusRow(rows.findIndex(other => other.path.join() === parentPath(row.path).join()));
    else if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(row); }
    else if (event.key === "F2" && item.type === "group" && canWrite) setRenaming(item.id);
    else if (event.key === "Delete" && item.type === "group" && canWrite && items) change(removeGroup(items, item.id), `Removed folder ${item.name}; its scenes stayed.`);
  }
  function newFolder() {
    if (!items || !canWrite) return;
    const id = newGroupId(items);
    const focused = rows[focusIndex];
    const parent = focused?.item.type === "group" ? focused.path : focused ? parentPath(focused.path) : [];
    change(addGroup(items, { id, name: "New folder" }, parent, 0), "Added a folder.");
    setRenaming(id); setFocusKey(`group:${id}`);
  }
  const total = passages.length, lines = passages.reduce((sum, passage) => sum + passage.lines, 0);
  const indicator = drag?.drop ? drag.drop.index * ROW + (drag.drop.where === "after" ? ROW : 0) : null;

  return <section className="studio-tree" aria-label="Scene hierarchy">
    <div className="studio-tree-head">
      <div><strong>Scenes</strong><small>{total} scenes · {lines} lines</small></div>
      {canWrite && <button type="button" className="studio-link" onClick={newFolder}>New folder</button>}
    </div>
    <label className="studio-visually-hidden" htmlFor={`tree-search-${projectId}`}>Find a scene</label>
    <input id={`tree-search-${projectId}`} className="studio-tree-search" value={query} placeholder="Find a scene or folder"
      onChange={event => setQuery(event.target.value)} />
    <div role="status" className="studio-visually-hidden">{status}</div>
    <div ref={viewport} className={`studio-tree-viewport ${drag ? "dragging" : ""}`} role="tree"
      aria-label="Scenes and folders" aria-multiselectable={false}
      onScroll={event => setScrollTop(event.currentTarget.scrollTop)}
      onPointerMove={pointerMove} onPointerUp={pointerUp}
      onPointerCancel={() => { press.current = null; showDrag(null); }}>
      {!items ? <p className="studio-hint">Loading scenes…</p> : !rows.length ? <p className="studio-hint">No matching scenes.</p> : null}
      <div style={{ height: rows.length * ROW, position: "relative" }}>
        {rows.slice(first, last).map((row, offset) => {
          const index = first + offset, item = row.item, passage = item.type === "scene" ? byId.get(item.id) : undefined;
          const current = item.type === "scene" && item.id === activeScene;
          const dropping = drag?.drop?.index === index && drag.drop.where === "inside";
          return <div key={row.key} data-key={row.key} role="treeitem" aria-level={row.depth + 1}
            aria-expanded={item.type === "group" ? !item.collapsed || Boolean(query) : undefined} aria-selected={current}
            tabIndex={index === focusIndex ? 0 : -1}
            className={`studio-tree-row ${current ? "selected" : ""} ${dropping ? "drop-inside" : ""} ${item.type}`}
            style={{ top: index * ROW, paddingLeft: 8 + row.depth * 16 }}
            onPointerDown={event => pointerDown(event, row)} onKeyDown={event => keyDown(event, row, index)}
            onFocus={() => setFocusKey(row.key)}
            onDoubleClick={() => { if (item.type === "group" && canWrite) setRenaming(item.id); }}>
            {item.type === "group" ? <>
              <button type="button" tabIndex={-1} className="studio-tree-toggle" aria-label={item.collapsed && !query ? "Expand" : "Collapse"}
                onClick={() => items && change(toggleGroup(items, item.id))}>{item.collapsed && !query ? "▸" : "▾"}</button>
              <span className="studio-tree-icon folder" aria-hidden="true">▤</span>
              {renaming === item.id ? <input className="studio-tree-rename" autoFocus defaultValue={item.name} maxLength={80}
                aria-label="Folder name"
                onKeyDown={event => {
                  if (event.key === "Enter") { event.preventDefault(); items && change(renameGroup(items, item.id, event.currentTarget.value)); setRenaming(null); focusRow(index); }
                  if (event.key === "Escape") { setRenaming(null); focusRow(index); }
                }}
                onBlur={event => { items && change(renameGroup(items, item.id, event.currentTarget.value)); setRenaming(null); }} />
                : <span className="studio-tree-label">{item.name}</span>}
              <small className="studio-tree-count">{countScenes(item)}</small>
            </> : <>
              <span className={`studio-tree-icon kind-${passage?.kind ?? "scene"}`} aria-hidden="true">{glyph[passage?.kind ?? "scene"]}</span>
              <span className="studio-tree-label">{passage?.title ?? item.id}</span>
              <small className="studio-tree-id">{passage && passage.lines > 1 ? `${passage.lines} lines` : item.id}</small>
            </>}
          </div>;
        })}
        {indicator !== null && <div className="studio-tree-drop" style={{ top: indicator - 1 }} aria-hidden="true" />}
      </div>
    </div>
    {/* Messages sit below the list so they never shift rows under the pointer. */}
    <p className="studio-tree-hint">{drag ? `Moving ${drag.label}. Release to drop, Escape to cancel.`
      : status ?? (canWrite ? "Drag to reorder, or Alt + arrow keys. F2 renames a folder." : "")}</p>
  </section>;
}

function countScenes(item: LayoutItem): number {
  return item.type === "scene" ? 1 : item.items.reduce((sum, child) => sum + countScenes(child), 0);
}
