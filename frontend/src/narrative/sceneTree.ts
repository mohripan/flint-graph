// Editor-only scene hierarchy (routes, chapters, folders) shared through the layout API.
// Paths are index arrays from the root; every operation returns a new tree.
export interface LayoutScene { type: "scene"; id: string }
export interface LayoutGroup { type: "group"; id: string; name: string; collapsed: boolean; items: LayoutItem[] }
export type LayoutItem = LayoutScene | LayoutGroup;
export type Path = number[];
export interface TreeRow { key: string; depth: number; path: Path; item: LayoutItem }

export const MAX_DEPTH = 4;
// Godot-like density for mouse and keyboard; 44 px rows when the pointer is a finger.
export const treeRowHeight = (coarsePointer: boolean) => coarsePointer ? 44 : 34;

function clone(items: LayoutItem[]): LayoutItem[] {
  return items.map(item => item.type === "group" ? { ...item, items: clone(item.items) } : { ...item });
}
function at(items: LayoutItem[], path: Path): LayoutItem | undefined {
  let level = items, found: LayoutItem | undefined;
  for (const index of path) {
    found = level[index];
    if (!found) return undefined;
    level = found.type === "group" ? found.items : [];
  }
  return found;
}
function children(items: LayoutItem[], parent: Path): LayoutItem[] | undefined {
  if (!parent.length) return items;
  const group = at(items, parent);
  return group?.type === "group" ? group.items : undefined;
}
function groupDepth(item: LayoutItem): number {
  return item.type === "group" ? 1 + Math.max(0, ...item.items.map(groupDepth)) : 0;
}
function parentDepth(items: LayoutItem[], parent: Path): number {
  return parent.filter((_, index) => at(items, parent.slice(0, index + 1))?.type === "group").length;
}

export function normalizeLayout(items: LayoutItem[], sceneIds: string[], anchors = new Map<string, string>()): LayoutItem[] {
  const known = new Set(sceneIds), placed = new Set<string>();
  const keep = (level: LayoutItem[]): LayoutItem[] => level.flatMap((item): LayoutItem[] => {
    if (item.type === "group") return [{ ...item, items: keep(item.items) }];
    if (!known.has(item.id) || placed.has(item.id)) return [];
    placed.add(item.id); return [{ type: "scene", id: item.id }];
  });
  let result = keep(items);
  for (const id of sceneIds) {
    if (placed.has(id)) continue;
    const anchor = anchors.get(id);
    const path = anchor ? findScene(result, anchor) : null;
    if (path) result = insertAt(result, path.slice(0, -1), path[path.length - 1] + 1, { type: "scene", id });
    else result = [...result, { type: "scene", id }];
    placed.add(id);
  }
  return result;
}

export function findScene(items: LayoutItem[], id: string, prefix: Path = []): Path | null {
  for (const [index, item] of items.entries()) {
    if (item.type === "scene" && item.id === id) return [...prefix, index];
    if (item.type === "group") {
      const found = findScene(item.items, id, [...prefix, index]);
      if (found) return found;
    }
  }
  return null;
}

export function flattenTree(items: LayoutItem[], options: { query?: string; titles?: Map<string, string> } = {}): TreeRow[] {
  const query = options.query?.trim().toLowerCase() ?? "";
  const matches = (item: LayoutItem): boolean => item.type === "scene"
    ? `${item.id} ${options.titles?.get(item.id) ?? ""}`.toLowerCase().includes(query)
    : item.name.toLowerCase().includes(query) || item.items.some(matches);
  const rows: TreeRow[] = [];
  const visit = (level: LayoutItem[], depth: number, prefix: Path) => {
    level.forEach((item, index) => {
      if (query && !matches(item)) return;
      const path = [...prefix, index];
      rows.push({ key: `${item.type}:${item.id}`, depth, path, item });
      if (item.type === "group" && (!item.collapsed || query)) visit(item.items, depth + 1, path);
    });
  };
  visit(items, 0, []);
  return rows;
}

function insertAt(items: LayoutItem[], parent: Path, index: number, item: LayoutItem): LayoutItem[] {
  const next = clone(items), level = children(next, parent);
  if (!level) return items;
  level.splice(Math.max(0, Math.min(index, level.length)), 0, item);
  return next;
}

export function canDrop(items: LayoutItem[], from: Path, parent: Path): boolean {
  const moving = at(items, from);
  if (!moving || !children(items, parent)) return false;
  const inside = parent.length >= from.length && from.every((value, index) => parent[index] === value);
  return !inside && parentDepth(items, parent) + groupDepth(moving) <= MAX_DEPTH;
}

// The target index refers to the destination list before the item is removed.
export function moveItem(items: LayoutItem[], from: Path, to: { parent: Path; index: number }): LayoutItem[] {
  if (!canDrop(items, from, to.parent)) return items;
  const next = clone(items), source = children(next, from.slice(0, -1))!;
  const [moving] = source.splice(from[from.length - 1], 1);
  let parent = to.parent, index = to.index;
  const sameLevel = from.length - 1 <= parent.length && from.slice(0, -1).every((value, i) => parent[i] === value);
  if (sameLevel && parent.length >= from.length && parent[from.length - 1] > from[from.length - 1]) {
    parent = [...parent]; parent[from.length - 1] -= 1;
  } else if (sameLevel && parent.length === from.length - 1 && index > from[from.length - 1]) index -= 1;
  const level = children(next, parent);
  if (!level) return items;
  level.splice(Math.max(0, Math.min(index, level.length)), 0, moving);
  return next;
}

function update(items: LayoutItem[], id: string, change: (group: LayoutGroup) => LayoutItem[]): LayoutItem[] {
  return items.flatMap(item => item.type !== "group" ? [item]
    : item.id === id ? change(item) : [{ ...item, items: update(item.items, id, change) }]);
}
export function toggleGroup(items: LayoutItem[], id: string, collapsed?: boolean): LayoutItem[] {
  return update(items, id, group => [{ ...group, collapsed: collapsed ?? !group.collapsed }]);
}
export function renameGroup(items: LayoutItem[], id: string, name: string): LayoutItem[] {
  const clean = name.trim().slice(0, 80);
  return clean ? update(items, id, group => [{ ...group, name: clean }]) : items;
}
export function removeGroup(items: LayoutItem[], id: string): LayoutItem[] {
  return update(items, id, group => group.items);
}
export function addGroup(items: LayoutItem[], group: { id: string; name: string }, parent: Path = [], index = 0): LayoutItem[] {
  if (parentDepth(items, parent) + 1 > MAX_DEPTH) return items;
  return insertAt(items, parent, index, { type: "group", id: group.id, name: group.name, collapsed: false, items: [] });
}
export function newGroupId(items: LayoutItem[]): string {
  const used = new Set<string>();
  const collect = (level: LayoutItem[]) => level.forEach(item => { if (item.type === "group") { used.add(item.id); collect(item.items); } });
  collect(items);
  let id = "";
  do id = "folder_" + Math.random().toString(36).slice(2, 10); while (used.has(id));
  return id;
}
export function parentPath(path: Path): Path { return path.slice(0, -1); }
