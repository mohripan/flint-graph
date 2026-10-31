// Library filters, upload checks and naming for the Assets tab (ADR 0040).

export type AssetFilter = "all" | "background" | "sprite" | "image" | "font" | "character_portrait" | "candidates";
export type UploadKind = "background" | "sprite" | "image" | "font";

export const FILTERS: Array<[AssetFilter, string]> = [
  ["all", "All"], ["background", "Backgrounds"], ["sprite", "Sprites"], ["image", "Images"],
  ["font", "Fonts"], ["character_portrait", "Portraits"], ["candidates", "To review"],
];
export const UPLOAD_KINDS: Array<[UploadKind, string]> = [
  ["background", "Background"], ["sprite", "Character sprite"], ["image", "Image / CG"], ["font", "Font"],
];
export const KIND_LABELS: Record<string, string> = {
  background: "Background", sprite: "Sprite", image: "Image", font: "Font", character_portrait: "Portrait",
};
const MB = 1024 * 1024;

export function filterQuery(filter: AssetFilter): { kind?: string; status?: string } {
  if (filter === "all") return {};
  if (filter === "candidates") return { status: "candidate" };
  return { kind: filter };
}

// Mirrors the server's limits so creators hear about a wrong file before uploading.
export function uploadProblem(file: { name: string; size: number }, kind: UploadKind): string | null {
  const extension = file.name.toLowerCase().split(".").pop() ?? "";
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
  return /\.(ttf|otf)$/i.test(name) ? "font" : "image";
}

export function suggestName(fileName: string): string {
  return fileName.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 120);
}

export function fontFamily(assetId: string): string {
  return `flint-asset-${assetId.replace(/[^a-z0-9-]/gi, "")}`;
}
