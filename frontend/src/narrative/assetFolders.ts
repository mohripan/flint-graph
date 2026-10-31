// Asset folders and automatic groups for the Assets tab (ADR 0043). Folders are editor
// organization only; generated items are also grouped by kind and character for free.

export interface AssetFolder { id: string; parent_id: string | null; name: string; asset_count: number }
export interface LibraryIndex {
  folders: AssetFolder[]; unfiled: number; to_review: number; total: number;
  kinds: Record<string, number>; characters: Record<string, number>;
}
export type LibraryView =
  | { type: "all" } | { type: "review" } | { type: "unfiled" }
  | { type: "kind"; kind: string } | { type: "character"; id: string } | { type: "folder"; id: string };
export interface RailItem { view: LibraryView; label: string; count: number }

export const MAX_DEPTH = 3;
const NAME_LIMIT = 80;
const KIND_ORDER: Array<[string, string]> = [
  ["background", "Backgrounds"], ["sprite", "Sprites"], ["character_portrait", "Portraits"],
  ["image", "CGs"], ["font", "Fonts"], ["voice", "Voice clips"],
];
const byName = (left: string, right: string) => left.localeCompare(right, undefined, { sensitivity: "base" });

/** Upload into the kind the creator is viewing (master's CG section opens with "image"). */
export function uploadKindForView(view: LibraryView): "background" | "sprite" | "image" | "font" | "voice" {
  return view.type === "kind" && ["sprite", "image", "font", "voice"].includes(view.kind)
    ? view.kind as "sprite" | "image" | "font" | "voice" : "background";
}

export function viewQuery(view: LibraryView): { kind?: string; status?: string; folder?: string; character_id?: string } {
  switch (view.type) {
    case "all": return {};
    case "review": return { status: "candidate" };
    case "unfiled": return { folder: "none" };
    case "kind": return { kind: view.kind };
    case "character": return { character_id: view.id };
    case "folder": return { folder: view.id };
  }
}

export function sameView(left: LibraryView, right: LibraryView): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

/** Depth-first rows, children under their parent, siblings by name ignoring case. */
export function folderRows(folders: AssetFolder[]): Array<{ folder: AssetFolder; depth: number }> {
  const rows: Array<{ folder: AssetFolder; depth: number }> = [];
  const visit = (parent: string | null, depth: number) => {
    for (const folder of folders.filter(item => item.parent_id === parent).sort((a, b) => byName(a.name, b.name))) {
      rows.push({ folder, depth });
      if (depth < MAX_DEPTH) visit(folder.id, depth + 1);
    }
  };
  visit(null, 0);
  return rows;
}

export function canHoldFolders(depth: number): boolean {
  return depth + 1 < MAX_DEPTH;
}

export function folderPath(folders: AssetFolder[], id: string): string {
  const names: string[] = [];
  for (let current = folders.find(item => item.id === id); current && names.length <= MAX_DEPTH;
    current = folders.find(item => item.id === current?.parent_id)) names.unshift(current.name);
  return names.join(" / ");
}

export function railGroups(index: LibraryIndex, names: Record<string, string>): {
  library: RailItem[]; kinds: RailItem[]; characters: RailItem[];
} {
  return {
    library: [
      { view: { type: "all" }, label: "All assets", count: index.total },
      { view: { type: "review" }, label: "To review", count: index.to_review },
      { view: { type: "unfiled" }, label: "Unsorted", count: index.unfiled },
    ],
    // CGs stay listed while empty: that view is where they are generated and uploaded.
    kinds: KIND_ORDER.filter(([kind]) => index.kinds[kind] || kind === "image")
      .map(([kind, label]) => ({ view: { type: "kind", kind }, label, count: index.kinds[kind] ?? 0 })),
    characters: Object.entries(index.characters)
      .map(([id, count]): RailItem => ({ view: { type: "character", id }, label: names[id] ?? id, count }))
      .sort((a, b) => byName(a.label, b.label)),
  };
}

export function viewTitle(view: LibraryView, index: LibraryIndex | null, names: Record<string, string>): string {
  switch (view.type) {
    case "all": return "All assets";
    case "review": return "To review";
    case "unfiled": return "Unsorted";
    case "kind": return KIND_ORDER.find(([kind]) => kind === view.kind)?.[1] ?? view.kind;
    case "character": return names[view.id] ?? view.id;
    case "folder": return folderPath(index?.folders ?? [], view.id) || "Folder";
  }
}

/** Mirrors the server: 1–80 characters, unique among siblings ignoring case. */
export function folderNameProblem(name: string, folders: AssetFolder[], parent: string | null, self?: string): string | null {
  const clean = name.split(/\s+/).filter(Boolean).join(" ");
  if (!clean) return "Give the folder a name.";
  if (clean.length > NAME_LIMIT) return `Folder names can have at most ${NAME_LIMIT} characters.`;
  const taken = folders.find(item => item.parent_id === parent && item.id !== self && byName(item.name, clean) === 0);
  return taken ? `A folder named “${taken.name}” is already here.` : null;
}
