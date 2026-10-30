// Drafts may contain invalid intermediate scalar values; the server validates saves.
export type Scalar = string | number | boolean | null;
export type Condition =
  | { op: "eq" | "ne" | "lt" | "le" | "gt" | "ge"; variable: string; value: Scalar }
  | { op: "all" | "any"; children: Condition[] }
  | { op: "not"; child: Condition };
export interface VariableDeclaration {
  type: "bool" | "int" | "enum";
  initial: Scalar;
  values?: string[];
}
export interface ChoiceOption {
  id: string;
  text_id: string;
  text: string;
  target: string;
  condition?: Condition;
}
type Display = { text_id: string; text: string };
export type StoryNode =
  | (Display & { type: "line"; next: string; speaker?: string; background?: string; portrait?: string })
  | (Display & { type: "choice"; options: ChoiceOption[] })
  | { type: "set"; next: string; operations: Array<{ op: "set" | "increment"; variable: string; value: Scalar }> }
  | { type: "branch"; condition: Condition; if_true: string; if_false: string }
  | (Display & { type: "end"; ending: string });
export interface StoryDraft {
  schema_version: "1";
  id: string;
  title: string;
  language: string;
  entry: string;
  characters: Record<string, { name: string }>;
  variables: Record<string, VariableDeclaration>;
  assets: Record<string, { path: string; sha256: string }>;
  nodes: Record<string, StoryNode>;
}
export interface NarrativeProject {
  id: string;
  tenant_id: string;
  name: string;
  head_revision_id: string;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}
export interface RevisionSummary {
  id: string;
  tenant_id: string;
  project_id: string;
  revision_number: number;
  parent_revision_id: string | null;
  observed_head_revision_id: string | null;
  conflicted: boolean;
  content_hash: string;
  author_user_id: string;
  created_at: string;
}
export interface NarrativeRevision extends RevisionSummary {
  story_json: string;
  notices: string;
}
export interface RevisionWrite {
  base_revision_id: string;
  idempotency_key: string;
  story_json: string;
  notices: string;
}

export type ReleaseStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type ArtifactKind = "source" | "web" | "manifest";
export interface ReleaseJob {
  id: string; attempt_number: number; status: ReleaseStatus;
  cancel_requested: boolean; error_code: string | null; created_at: string; updated_at: string;
}
export interface ReleaseArtifact {
  id: string; kind: ArtifactKind; sha256: string; size_bytes: number;
  filename: string; media_type: string;
}
export interface NarrativeRelease {
  id: string; tenant_id: string; project_id: string; revision_id: string;
  package_hash: string; created_at: string; job: ReleaseJob; artifacts: ReleaseArtifact[];
  build_identity: { compiler_version: string; runtime_version: string; godot_version: string;
    toolchain_sha256: string; builder_image_digest: string };
}
export interface ReleaseEvent {
  id: string; release_id: string; job_id: string; sequence: number;
  code: string; payload: Record<string, string>; created_at: string;
}
