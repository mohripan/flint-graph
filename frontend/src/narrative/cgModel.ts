import type { NarrativeImage } from "../lib/api";

// Event CGs drawn from an approved image of a character (ADR 0041 slice C). The server
// builds the prompt; the Studio only picks the character, its reference and the scene.
export const CG_COUNT = 4;
export const CG_SCENE_LIMIT = 600;
const REFERENCE_KINDS = ["character_portrait", "sprite", "image"];

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

const cleanScene = (scene: string) => scene.replace(/\s+/g, " ").trim();

export function cgProblem({ character, reference, scene }: {
  character: string; reference: string | null; scene: string;
}): string | null {
  if (!character) return "Choose a character.";
  if (!reference) return "Approve a portrait or sprite of this character first.";
  const text = cleanScene(scene);
  if (!text) return "Describe the scene.";
  if (text.length > CG_SCENE_LIMIT) return `Keep the scene shorter than ${CG_SCENE_LIMIT} characters.`;
  return null;
}

export function cgRequest({ character, reference, scene }: { character: string; reference: string | null; scene: string }) {
  return {
    scene: cleanScene(scene),
    characters: [{ character_id: character, reference_asset_id: reference ?? "" }],
    count: CG_COUNT,
  };
}
