import type { ImageJob, NarrativeImage } from "../lib/api";
import type {StyleJob} from "./styleModel";
import type { CharacterLook } from "./lookModel";
export type PoseView = "front" | "side" | "back" | "detail";
export interface PoseReference {asset_id:string;sha256:string;view:string;name:string}
export interface AdditionalPoseView {asset:NarrativeImage;view:PoseView;confirmed:boolean}
export interface PoseAdapter {id:string;name:string;strength:number;weights_sha256:string;kind?:"project_style"|"character_look"}
export interface BodyGuide {id:string;label:string;width:number;height:number;points:number[][];sha256?:string;control_manifest_sha256?:string}
export interface PoseJob {
  pose_guide?:BodyGuide|null;
  repair?:{source_asset_id:string;source_sha256:string;box:number[];source_box:number[]|null;width:number;height:number;instruction:string}|null;
  references?:PoseReference[];
  style_adapter?:PoseAdapter|null;
  character_adapter?:PoseAdapter|null;
  operation: "pose"; model_id: string; model_manifest_sha256: string; pose: string;
  look: { id: string; name: string; asset_id: string; source_sha256: string; sha256: string };
  job: ImageJob;
}
export interface PoseHistory { jobs: PoseJob[]; capabilities: {available:boolean; transparent:boolean; model_id:string; max_references?:number;max_adapters?:number;styles?:boolean;character_training?:boolean;repairs?:boolean;body_guides?:BodyGuide[]} }
export const POSE_PRESETS = ["standing, arms relaxed", "sitting on a chair, hands in lap", "walking, three-quarter view", "back view, looking over shoulder"];
export function poseBody(look: CharacterLook | null, instruction:string, count:number, transparent:boolean, key:string, extra?:AdditionalPoseView, selected?:{style:StyleJob;strength:number}, character?:{style:StyleJob;strength:number},guide?:string) {
  if(guide&&(guide!=="seated-front-v1"||extra))throw new Error("Choose a body guide or an additional character view, one at a time.");
  const pose=instruction.replace(/\s+/g," ").trim();
  if (!look || look.asset.status!=="approved") throw new Error("Choose an approved reviewed look first.");
  if (!pose || pose.length>300 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(pose)) throw new Error("Describe the pose in 1–300 characters.");
  if (!Number.isInteger(count) || count<1 || count>4) throw new Error("Choose 1–4 candidates.");
  if(extra&&(!extra.confirmed||extra.asset.status!=="approved"||extra.asset.media_type!=="image/png"
    ||extra.asset.id===look.asset.id||extra.asset.sha256===look.source_sha256
    ||!["front","side","back","detail"].includes(extra.view)))throw new Error("Choose another approved view and confirm it shows the same character and outfit.");
  for(const chosen of [selected,character]){
    if(chosen?.style.kind==="character_look"&&(chosen.style.look?.id!==look.id||chosen.style.look.sha256!==look.sha256))throw new Error("Choose a trained version for this exact reviewed character look.");
    if(chosen&&(chosen.style.status!=="completed"||!chosen.style.weights_sha256||!Number.isFinite(chosen.strength)||chosen.strength<0.1||chosen.strength>1))throw new Error("Choose a ready trained version and a strength from 0.1 to 1.");
  }
  if(character&&(character.style.kind!=="character_look"||(selected&&selected.style.kind==="character_look")))throw new Error("Choose a character version for Character and a project style for Style.");
  if(character&&selected&&(character.style.id===selected.style.id||character.strength+selected.strength>1+1e-9))throw new Error("Combined character and style strengths must total at most 1.");
  return {look_id:look.id,pose,count,transparent,idempotency_key:key,
    ...(guide?{pose_guide:guide}:{}),
    ...(character?{character_adapter:{id:character.style.id,strength:character.strength}}:{}),
    ...(selected?{style_adapter:{id:selected.style.id,strength:selected.strength}}:{}),
    ...(extra?{additional_references:[{asset_id:extra.asset.id,view:extra.view}]}:{})};
}
export function poseStatus(job:ImageJob):string {
  if (job.cancel_requested && ["queued","running"].includes(job.status)) return "Cancelling…";
  if (job.status==="queued") return "Waiting for the pose worker…";
  if (job.status==="running") return job.progress ? `Generated ${job.progress} of ${job.count}…` : "Loading the pose model…";
  if (job.status==="completed") return `${job.assets.length} pose${job.assets.length===1?"":"s"} ready`;
  if (job.status==="cancelled") return "Cancelled.";
  const errors:Record<string,string>={pose_control_unavailable:"This job’s body-guide model is unavailable or changed. Ask the operator to restore its pinned version.",repair_preservation_failed:"The repair changed pixels outside the selected area and was rejected. Try a new repair.",host_memory_busy:"Not enough system memory was available. Try again when other work finishes.",gpu_busy:"The GPU was busy. Try again when other work finishes.",out_of_memory:"The pose model ran out of memory. Try again when other work finishes.",prompt_too_long:"The look and pose are too long for the model. Shorten the pose or choose a shorter reviewed look.",model_pin_mismatch:"The installed model changed. Ask the operator to restore this job's model, or start a new job.",reference_unavailable:"The approved reference is unavailable. Choose another reviewed look.",cutout_failed:"No clean sprite could be cut out. Try another pose or turn off transparency."};
  return errors[job.error_code??""]??"Pose generation failed. Try again.";
}

export function portraitJobs(jobs:ImageJob[],poses:PoseJob[]):ImageJob[]{
  const ids=new Set(poses.map(item=>item.job.id));
  return jobs.filter(job=>!ids.has(job.id));
}
