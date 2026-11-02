import type { NarrativeImage } from "../lib/api";

export interface CharacterLook {
  id: string; name: string; asset: NarrativeImage; source_sha256: string;
  identity_tags: string[]; clothing_tags: string[]; character_type: string;
  parent_look_id: string | null; sha256: string; created_at: string; reviewed_by_user_id: string;
  tagger_observation?: Record<string,unknown> | null;
}
export interface LookList { looks: CharacterLook[]; selection: { look_id: string | null; version: number } }
export type LookVerdict = "same" | "drifted" | "unknown";
export type AnatomyVerdict = "acceptable" | "flawed" | "unknown";
export interface LookFeedback { version: number; identity: LookVerdict; clothes: LookVerdict; anatomy?:AnatomyVerdict;anatomy_version?:number; notes: string }
export interface LookFlag { asset_id: string; look_id: string; look_name: string; identity: LookVerdict; clothes: LookVerdict;anatomy?:AnatomyVerdict;candidate_sha256?:string }
export interface ClothingComparison { clothing_overlap:number|null; identity:null; automatic_verdict:null; reference_tags:Record<string,number>; candidate_tags:Record<string,number>; reason:string }

export const splitLookTags = (value: string): string[] => [...new Set(value.split(",")
  .map(tag => tag.replaceAll("_", " ").replace(/\s+/g, " ").trim().toLowerCase()).filter(Boolean))];

export function reviewWarnings(asset:Pick<NarrativeImage,"id"|"sha256">,flags:LookFlag[]){
  return flags.flatMap(flag=>{
    const exact=flag.asset_id===asset.id;
    const anatomy=flag.anatomy==="flawed"&&(exact||flag.candidate_sha256===asset.sha256);
    const reasons=[...(exact&&flag.identity==="drifted"?["Review character"]:[]),...(exact&&flag.clothes==="drifted"?["Review clothes"]:[]),...(anatomy?["Review anatomy"]:[])];
    return reasons.length?[{...flag,reasons}]:[];
  });
}

export function anatomyFailures(assets:Pick<NarrativeImage,"id"|"sha256">[],flags:LookFlag[]):Set<string>{
  const ids=new Set(flags.filter(flag=>flag.anatomy==="flawed").map(flag=>flag.asset_id));
  const hashes=new Set(flags.filter(flag=>flag.anatomy==="flawed").map(flag=>flag.candidate_sha256).filter(Boolean));
  return new Set(assets.filter(asset=>ids.has(asset.id)||hashes.has(asset.sha256)).map(asset=>asset.id));
}

export function feedbackBody(feedback:LookFeedback){
  return {base_version:feedback.version,identity:feedback.identity,clothes:feedback.clothes,notes:feedback.notes,
    ...(feedback.anatomy!==undefined?{anatomy:feedback.anatomy,anatomy_base_version:feedback.anatomy_version??0}:{})};
}

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
