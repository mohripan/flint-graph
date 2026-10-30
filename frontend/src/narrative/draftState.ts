import type { NarrativeProject, NarrativeRevision, RevisionWrite } from "./types";

export interface SavedConflict { revisionId: string; headId: string }
export interface SourceDiagnostic { code: string; location: string }
export interface DraftState {
  generation: number;
  project: NarrativeProject | null;
  revision: NarrativeRevision | null;
  source: string;
  notices: string;
  loading: boolean;
  saving: boolean;
  request: RevisionWrite | null;
  conflict: SavedConflict | null;
  error: string | null;
  diagnostics: SourceDiagnostic[];
}
export type DraftAction =
  | { type: "load" | "clear"; generation: number; message?: string }
  | { type: "loaded"; generation: number; project: NarrativeProject; revision: NarrativeRevision }
  | { type: "edit"; source?: string; notices?: string }
  | { type: "saving"; generation: number; request: RevisionWrite }
  | { type: "saved"; generation: number; revision: NarrativeRevision }
  | { type: "failed"; generation: number; message: string;
      conflict?: SavedConflict; diagnostics?: SourceDiagnostic[] };

export function initialDraftState(generation = 0): DraftState {
  return { generation, project: null, revision: null, source: "", notices: "", loading: false,
    saving: false, request: null, conflict: null, error: null, diagnostics: [] };
}

export function prepareSave(previous: RevisionWrite | null, base: string, source: string,
  notices: string, key: () => string = () => crypto.randomUUID()): RevisionWrite {
  if (previous && previous.base_revision_id === base && previous.story_json === source
    && previous.notices === notices) return previous;
  return { base_revision_id: base, story_json: source, notices, idempotency_key: key() };
}

export function draftReducer(state: DraftState, action: DraftAction): DraftState {
  if (action.type === "load" || action.type === "clear") {
    if (action.generation < state.generation) return state;
    return { ...initialDraftState(action.generation), loading: action.type === "load",
      error: action.message ?? null };
  }
  if (action.type === "edit") {
    if (!state.revision || state.saving || state.loading) return state;
    return { ...state, source: action.source ?? state.source, notices: action.notices ?? state.notices,
      conflict: null, error: null, diagnostics: [] };
  }
  if (action.generation !== state.generation) return state;
  switch (action.type) {
    case "loaded":
      if (action.project.id !== action.revision.project_id
        || action.project.tenant_id !== action.revision.tenant_id) return state;
      return { ...initialDraftState(state.generation), project: action.project,
        revision: action.revision, source: action.revision.story_json, notices: action.revision.notices };
    case "saving":
      if (!state.project || !state.revision || state.saving) return state;
      return { ...state, saving: true, request: action.request, error: null, diagnostics: [] };
    case "saved":
      if (!state.project || action.revision.project_id !== state.project.id
        || action.revision.tenant_id !== state.project.tenant_id) return state;
      return { ...state, revision: action.revision,
        project: { ...state.project, head_revision_id: action.revision.id },
        source: action.revision.story_json, notices: action.revision.notices,
        saving: false, request: null, conflict: null, error: null, diagnostics: [] };
    case "failed":
      return { ...state, loading: false, saving: false, error: action.message,
        conflict: action.conflict ?? null, diagnostics: action.diagnostics ?? [] };
  }
}
