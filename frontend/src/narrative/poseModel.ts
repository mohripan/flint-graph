import type { ImageJob } from "../lib/api";
import type { CharacterLook } from "./lookModel";
export interface PoseJob {
  operation: "pose"; model_id: string; model_manifest_sha256: string; pose: string;
  look: { id: string; name: string; asset_id: string; source_sha256: string; sha256: string };
  job: ImageJob;
}
export interface PoseHistory { jobs: PoseJob[]; capabilities: {available:boolean; transparent:boolean; model_id:string} }
export const POSE_PRESETS = ["standing, arms relaxed", "sitting on a chair, hands in lap", "walking, three-quarter view", "back view, looking over shoulder"];
export function poseBody(look: CharacterLook | null, instruction:string, count:number, transparent:boolean, key:string) {
  const pose=instruction.replace(/\s+/g," ").trim();
  if (!look || look.asset.status!=="approved") throw new Error("Choose an approved reviewed look first.");
  if (!pose || pose.length>300 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(pose)) throw new Error("Describe the pose in 1–300 characters.");
  if (!Number.isInteger(count) || count<1 || count>4) throw new Error("Choose 1–4 candidates.");
  return {look_id:look.id,pose,count,transparent,idempotency_key:key};
}
export function poseStatus(job:ImageJob):string {
  if (job.cancel_requested && ["queued","running"].includes(job.status)) return "Cancelling…";
  if (job.status==="queued") return "Waiting for the pose worker…";
  if (job.status==="running") return job.progress ? `Generated ${job.progress} of ${job.count}…` : "Loading the pose model…";
  if (job.status==="completed") return `${job.assets.length} pose${job.assets.length===1?"":"s"} ready`;
  if (job.status==="cancelled") return "Cancelled.";
  const errors:Record<string,string>={host_memory_busy:"Not enough system memory was available. Try again when other work finishes.",gpu_busy:"The GPU was busy. Try again when other work finishes.",out_of_memory:"The pose model ran out of memory. Try again when other work finishes.",prompt_too_long:"The look and pose are too long for the model. Shorten the pose or choose a shorter reviewed look.",model_pin_mismatch:"The installed model changed. Ask the operator to restore this job's model, or start a new job.",reference_unavailable:"The approved reference is unavailable. Choose another reviewed look.",cutout_failed:"No clean sprite could be cut out. Try another pose or turn off transparency."};
  return errors[job.error_code??""]??"Pose generation failed. Try again.";
}

export function portraitJobs(jobs:ImageJob[],poses:PoseJob[]):ImageJob[]{
  const ids=new Set(poses.map(item=>item.job.id));
  return jobs.filter(job=>!ids.has(job.id));
}
