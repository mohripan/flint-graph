// Library filters, upload checks and naming for the Assets tab (ADR 0040).

export type AssetFilter = "all" | "background" | "sprite" | "image" | "font" | "character_portrait" | "candidates";
export type UploadKind = "background" | "sprite" | "image" | "font" | "voice" | "music" | "sound";

export const FILTERS: Array<[AssetFilter, string]> = [
  ["all", "All"], ["background", "Backgrounds"], ["sprite", "Sprites"], ["image", "CGs"],
  ["font", "Fonts"], ["character_portrait", "Portraits"], ["candidates", "To review"],
];
export const UPLOAD_KINDS: Array<[UploadKind, string]> = [
  ["background", "Background"], ["sprite", "Character sprite"], ["image", "CG / image"], ["font", "Font"],
  ["voice", "Voice clip (WAV)"], ["music", "Music or ambience (Ogg Vorbis)"], ["sound", "Sound effect (WAV)"],
];
export const KIND_LABELS: Record<string, string> = {
  background: "Background", sprite: "Sprite", image: "CG / image", font: "Font", character_portrait: "Portrait",
  voice: "Voice clip", music: "Music", sound: "Sound effect",
};
const MB = 1024 * 1024;

export interface AssetSet<T> { key: string; title: string | null; options: number; created_at: string | null; assets: T[] }

/**
 * The options from one Generate belong together, so they are compared as a set rather than found
 * scattered among others with the same names. Everything else keeps its place between the sets.
 */
export function assetSets<T extends { id: string; kind: string; character_id: string | null; job_id: string | null; created_at: string }>(
  assets: readonly T[], names: Record<string, string> = {},
): AssetSet<T>[] {
  const sizes = new Map<string, number>();
  for (const asset of assets) if (asset.job_id) sizes.set(asset.job_id, (sizes.get(asset.job_id) ?? 0) + 1);
  const sets: AssetSet<T>[] = [], byJob = new Map<string, AssetSet<T>>();
  let loose: AssetSet<T> | null = null;
  for (const asset of assets) {
    if (asset.job_id && sizes.get(asset.job_id)! > 1) {
      let set = byJob.get(asset.job_id);
      if (!set) {
        const person = asset.character_id ? names[asset.character_id] : undefined;
        const kind = KIND_LABELS[asset.kind] ?? asset.kind;
        set = { key: `job:${asset.job_id}`, title: person ? `${person} · ${kind}` : kind, options: sizes.get(asset.job_id)!, created_at: asset.created_at, assets: [] };
        byJob.set(asset.job_id, set); sets.push(set); loose = null;
      }
      set.assets.push(asset);
    } else {
      if (!loose) { loose = { key: `loose:${asset.id}`, title: null, options: 0, created_at: null, assets: [] }; sets.push(loose); }
      loose.assets.push(asset); loose.options += 1;
    }
  }
  return sets;
}

export function filterQuery(filter: AssetFilter): { kind?: string; status?: string } {
  if (filter === "all") return {};
  if (filter === "candidates") return { status: "candidate" };
  return { kind: filter };
}

/** Upload into the library section the creator is viewing. */
export function uploadKindForFilter(filter: AssetFilter): UploadKind {
  return filter === "image" || filter === "sprite" || filter === "font" ? filter : "background";
}

// Mirrors the server's limits so creators hear about a wrong file before uploading.
export function uploadProblem(file: { name: string; size: number }, kind: UploadKind): string | null {
  const extension = file.name.toLowerCase().split(".").pop() ?? "";
  if (kind === "music") {
    if (extension !== "ogg") return "Music must be an Ogg Vorbis file (.ogg). Audio editors such as Audacity can export one.";
    if (file.size > 10 * MB) return "Music can be at most 10 MB.";
    return null;
  }
  if (kind === "sound") {
    if (extension !== "wav") return "Sound effects must be WAV files (16-bit PCM).";
    if (file.size > 10 * MB) return "Sound effects can be at most 10 MB.";
    return null;
  }
  if (kind === "voice") {
    if (extension !== "wav") return "Voice clips must be WAV files (16-bit PCM).";
    if (file.size > 10 * MB) return "Voice clips can be at most 10 MB.";
    return null;
  }
  if (kind === "font") {
    if (!["ttf", "otf"].includes(extension)) return "Fonts must be TTF or OTF files.";
    if (file.size > 8 * MB) return "Fonts can be at most 8 MB.";
    return null;
  }
  if (extension !== "png") return "Images must be PNG files (transparency is kept).";
  if (file.size > 10 * MB) return "Images can be at most 10 MB.";
  return null;
}

export function kindForFile(name: string): UploadKind {
  return /\.(ttf|otf)$/i.test(name) ? "font" : /\.wav$/i.test(name) ? "voice" : /\.ogg$/i.test(name) ? "music" : "image";
}

export function suggestName(fileName: string): string {
  return fileName.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 120);
}

export function fontFamily(assetId: string): string {
  return `flint-asset-${assetId.replace(/[^a-z0-9-]/gi, "")}`;
}
