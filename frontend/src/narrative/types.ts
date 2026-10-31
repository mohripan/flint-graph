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
export type StagePosition = "left" | "center" | "right";
// ``x`` (runtime 0.4.0) is the placement's horizontal centre as % of the screen width.
export interface StageShow { character: string; sprite: string; position: StagePosition; x?: number }
export type StoryNode =
  | (Display & { type: "line"; next: string; speaker?: string; background?: string; portrait?: string; expression?: string })
  | { type: "stage"; next: string; background?: string | null; show?: StageShow[]; hide?: string[] }
  | (Display & { type: "choice"; options: ChoiceOption[] })
  | { type: "set"; next: string; operations: Array<{ op: "set" | "increment"; variable: string; value: Scalar }> }
  | { type: "branch"; condition: Condition; if_true: string; if_false: string }
  | (Display & { type: "end"; ending: string });
// Version 2 (ADR 0040) adds the stage, expressions, character sprites and a theme.
export interface StoryTheme {
  textbox?: { position?: "bottom" | "middle" | "top"; width?: number; background?: string; text?: string; border?: string; radius?: number };
  name?: { show?: boolean; background?: string; text?: string };
  choices?: { background?: string; text?: string; border?: string };
  font?: { asset?: string | null; size?: number };
}
// ``stage`` framing: drawn height as % of the screen and the top edge as % of its height.
export interface CharacterFraming { scale?: number; top?: number }
export interface StoryCharacter { name: string; color?: string; sprites?: Record<string, string>; stage?: CharacterFraming }
export interface StoryDraft {
  schema_version: "1" | "2";
  id: string;
  title: string;
  language: string;
  entry: string;
  characters: Record<string, StoryCharacter>;
  variables: Record<string, VariableDeclaration>;
  assets: Record<string, { kind?: "image" | "font"; path: string; sha256: string }>;
  theme?: StoryTheme;
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

export type TurnStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type ProposalStatus = "ready" | "invalid" | "accepted" | "rejected";
export interface AssistantThread {
  id: string; tenant_id: string; project_id: string; title: string;
  archived_at: string | null; created_at: string; updated_at: string;
}
export interface AssistantProposalSummary {
  id: string; status: ProposalStatus; summary: string; touched: string[]; accepted_revision_id: string | null;
}
export interface AssistantTurn {
  id: string; thread_id: string; sequence: number; request: string; base_revision_id: string;
  focus_node: string | null; status: TurnStatus; cancel_requested: boolean; reply: string | null;
  error_code: string | null; model: string | null; attempts: number | null;
  created_at: string; updated_at: string; finished_at: string | null; proposal: AssistantProposalSummary | null;
}
export type StoryOperation =
  | { op: "upsert_node"; id: string; node: Partial<StoryNode> & { type: StoryNode["type"] } }
  | { op: "delete_node" | "delete_character" | "delete_variable" | "set_entry"; id: string }
  | { op: "upsert_character"; id: string; name: string; color?: string | null;
      sprites?: Record<string, string> | null; stage?: CharacterFraming | null }
  | { op: "upsert_variable"; id: string; declaration: VariableDeclaration }
  | { op: "set_title"; title: string }
  | { op: "set_theme"; theme: StoryTheme | null }
  | { op: "add_asset"; id: string; asset: { kind: "image" | "font"; path: string; sha256: string } }
  | AssistantAction;
// Suggested image jobs (story format 2): never applied with the proposal, started by the creator.
export type AssistantAction =
  | { op: "generate_character_images"; character: string; appearance: string;
      character_type: "girl" | "boy" | "woman" | "man" | "other"; framing: "portrait" | "full_body"; transparent: boolean }
  | { op: "generate_backgrounds"; description: string };
export interface AssistantProposal extends AssistantProposalSummary {
  turn_id: string; thread_id: string; base_revision_id: string; operations: StoryOperation[];
  diagnostics: Array<{ code: string; location: string }>; warnings: Array<{ code: string; location: string }>;
  decided_at: string | null; created_at: string;
}
export interface TurnWrite { request: string; base_revision_id: string; focus_node: string | null; idempotency_key: string }