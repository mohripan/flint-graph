import type { ImageJob, NarrativeImage } from "../lib/api";

// Event CGs drawn from approved images of one or two characters (ADR 0041 slice C).
// The server builds the prompts; the Studio picks the characters, their references and
// the scene. A second character stands on the right.
export const CG_COUNT = 4;
export const CG_SCENE_LIMIT = 600;
export const CG_MAX_CHARACTERS = 2;
const REFERENCE_KINDS = ["character_portrait", "sprite", "image"];

export interface CgPick { character: string; reference: string | null }

// Two characters keep both looks in about 7 renders of 12 (ADR 0041; M40 #185 owns
// improving it), so the Studio says so and starts two jobs of four. Jobs stay within
// the four-image cap and run one at a time on the GPU.
export const TWO_CHARACTER_NOTE = "Experimental: the two characters may swap hair or clothes. Generate a few and keep the best.";

export function cgJobCount(picks: CgPick[]): number {
  return picks.length === 2 ? 2 : 1;
}

export function cgCandidates(picks: CgPick[]): number {
  return cgJobCount(picks) * CG_COUNT;
}

/** Approved images that can stand for a character: its chosen portrait first, then
 *  portraits, sprites and other images. Generated CGs never do: they carry a scene. */
export function referenceChoices(assets: NarrativeImage[], portraitId: string | null | undefined): NarrativeImage[] {
  const rank = (asset: NarrativeImage) => asset.id === portraitId ? 0 : 1 + REFERENCE_KINDS.indexOf(asset.kind);
  return assets
    .filter((asset, index) => assets.findIndex(other => other.id === asset.id) === index)
    .filter(asset => asset.status === "approved" && asset.media_type === "image/png"
      && REFERENCE_KINDS.includes(asset.kind) && !asset.provenance.ip_adapter)
    .sort((left, right) => rank(left) - rank(right));
}

export function defaultReference(choices: NarrativeImage[], current: string | null): string | null {
  if (current && choices.some(choice => choice.id === current)) return current;
  return choices[0]?.id ?? null;
}

/** Characters the second picker offers: everyone but the first pick. */
export function otherCharacters(ids: string[], taken: string): string[] {
  return ids.filter(id => id !== taken);
}

const cleanScene = (scene: string) => scene.replace(/\s+/g, " ").trim();

export function cgProblem({ picks, scene }: { picks: CgPick[]; scene: string }): string | null {
  if (!picks.length || picks.some(pick => !pick.character)) return "Choose a character.";
  if (picks.length > CG_MAX_CHARACTERS) return "A CG shows at most two characters.";
  if (new Set(picks.map(pick => pick.character)).size !== picks.length) return "Choose two different characters.";
  if (picks.some(pick => !pick.reference)) return "Approve a portrait or sprite of each character first.";
  const text = cleanScene(scene);
  if (!text) return "Describe the scene.";
  if (text.length > CG_SCENE_LIMIT) return `Keep the scene shorter than ${CG_SCENE_LIMIT} characters.`;
  return null;
}

export function cgRequest({ picks, scene }: { picks: CgPick[]; scene: string }) {
  return {
    scene: cleanScene(scene),
    characters: picks.map(pick => ({ character_id: pick.character, reference_asset_id: pick.reference ?? "" })),
    count: CG_COUNT,
  };
}

/** Who a CG job draws, by display name: "Quen and Lina". */
export function cgSubject(job: Pick<ImageJob, "character_id" | "reference_assets">, names: Record<string, string>): string {
  const ids = job.reference_assets?.map(item => item.character_id) ?? [job.character_id ?? ""];
  return ids.map(id => names[id] || id).join(" and ");
}
