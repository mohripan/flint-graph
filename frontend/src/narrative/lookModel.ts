import type { NarrativeImage } from "../lib/api";

export interface CharacterLook {
  id: string; name: string; asset: NarrativeImage; source_sha256: string;
  identity_tags: string[]; clothing_tags: string[]; character_type: string;
  parent_look_id: string | null; sha256: string; created_at: string; reviewed_by_user_id: string;
  tagger_observation?: Record<string,unknown> | null;
}
export interface LookList { looks: CharacterLook[]; selection: { look_id: string | null; version: number } }
export type LookVerdict = "same" | "drifted" | "unknown";
export interface LookFeedback { version: number; identity: LookVerdict; clothes: LookVerdict; notes: string }
export interface LookFlag { asset_id: string; look_id: string; look_name: string; identity: LookVerdict; clothes: LookVerdict }
export interface ClothingComparison { clothing_overlap:number|null; identity:null; automatic_verdict:null; reference_tags:Record<string,number>; candidate_tags:Record<string,number>; reason:string }

export const splitLookTags = (value: string): string[] => [...new Set(value.split(",")
  .map(tag => tag.replaceAll("_", " ").replace(/\s+/g, " ").trim().toLowerCase()).filter(Boolean))];

export function lookRequest(input: { name: string; assetId: string; identity: string; clothes: string;
  baseVersion: number; parentId: string | null; key: string; observationId?: string | null }) {
  return { name: input.name.trim(), asset_id: input.assetId, identity_tags: splitLookTags(input.identity),
    clothing_tags: splitLookTags(input.clothes), base_version: input.baseVersion,
    parent_look_id: input.parentId, idempotency_key: input.key, ...(input.observationId ? { observation_id:input.observationId } : {}) };
}

export function lookReferences(assets: NarrativeImage[], characterId: string): NarrativeImage[] {
  return assets.filter(asset => asset.status === "approved" && asset.media_type === "image/png"
    && ["sprite", "character_portrait", "image"].includes(asset.kind)
    && (asset.character_id === null || asset.character_id === characterId) && !asset.provenance.ip_adapter)
    .sort((left, right) => Number(right.character_id === characterId) - Number(left.character_id === characterId));
}
