import type {
  NarrativeProject,
  NarrativeRevision,
  RevisionSummary,
  RevisionWrite,
  NarrativeRelease,
  ReleaseArtifact,
  ReleaseJob,
  ReleaseEvent,
  AssistantProposal,
  AssistantThread,
  AssistantTurn,
  TurnWrite,
} from "../narrative/types";
import type { LayoutItem } from "../narrative/sceneTree";

export interface SceneLayout { project_id: string; version: number; items: LayoutItem[] }
export type CharacterType = "girl" | "boy" | "woman" | "man" | "other";
export type CharacterFraming = "portrait" | "full_body";
export interface NarrativeImage {
  id: string; character_id: string | null; kind: string; source: "generated" | "uploaded"; name: string;
  status: "candidate" | "approved" | "discarded"; media_type: "image/png" | "font/ttf" | "font/otf";
  width: number | null; height: number | null; sha256: string; size_bytes: number;
  thumbnail_width: number | null; thumbnail_height: number | null; seed: number | null; job_id: string | null;
  license: string; notice: string | null; provenance: Record<string, unknown>; created_at: string;
  approved_at: string | null; rights_declared_at: string | null;
}
export interface AssetUpload {
  file: File; kind: "background" | "sprite" | "image" | "font"; name: string; license: string; notice: string;
}
export interface CharacterProfile {
  character_id: string; appearance: string; character_type: CharacterType; framing: CharacterFraming;
  portrait: NarrativeImage | null; version: number;
}
export interface ImageJob {
  id: string; purpose: "character_portrait" | "background" | "character_expression"; character_id: string | null;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: number; count: number; cancel_requested: boolean; error_code: string | null; appearance: string;
  character_type: CharacterType; framing: CharacterFraming; prompt: string; negative_prompt: string;
  width: number; height: number; steps: number; guidance: number; seeds: number[]; model: string | null;
  prompt_tokens: number | null; truncated: boolean | null; created_at: string; started_at: string | null;
  finished_at: string | null; assets: NarrativeImage[];
  // Transparent stage sprites: the segmenter and its ONNX SHA-256 once the cutout ran.
  transparent: boolean; cutout: { model: string; sha256: string } | null;
  // Expressions repainted from a base image (ADR 0041): one expression and prompt per image.
  base_asset_id?: string | null; face_box?: number[] | null; strength?: number | null;
  expressions?: string[] | null; prompts?: string[] | null;
  // High resolution: width × height is the base render, upscaled to the output size.
  hires: { scale: number; strength: number } | null; output_width: number; output_height: number;
}
import type {
  AnswerProvenance,
  Conversation,
  ConversationTurn,
  DocumentDeleteResponse,
  DocumentIntakeResponse,
  DocumentListItem,
  DocumentProjectionCleanup,
  IndexBackfillJob,
  IngestionJobResponse,
  ProblemDetail,
  QueryRunResponse,
  SearchReadiness,
  SystemReadiness,
  Tenant,
  UsageSummary,
  Workspace,
} from "./types";

// All requests are same-origin; the Vite dev server proxies /v1 and /health to
// the API. In a production build these paths are served behind the same origin.
const BASE = "";
let accessTokenProvider: (() => Promise<string | null>) | null = null;

export function setAccessTokenProvider(provider: (() => Promise<string | null>) | null) {
  accessTokenProvider = provider;
}

export async function authHeaders(): Promise<HeadersInit> {
  const token = accessTokenProvider ? await accessTokenProvider() : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export class ApiError extends Error {
  status: number;
  problem?: ProblemDetail;
  constructor(message: string, status: number, problem?: ProblemDetail) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let problem: ProblemDetail | undefined;
  let message = `${res.status} ${res.statusText}`;
  try {
    const body = (await res.json()) as ProblemDetail;
    problem = body;
    if (body?.detail) message = body.detail;
    else if (body?.title) message = body.title;
  } catch {
    /* non-JSON body */
  }
  return new ApiError(message, res.status, problem);
}

function tenantHeaders(tenantId: string): HeadersInit {
  return { "X-Tenant-ID": tenantId };
}

async function jsonRequest<T>(
  path: string,
  init: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const { json, headers, ...rest } = init;
  const res = await fetch(`${BASE}${path}`, {
    ...rest,
    headers: {
      ...(await authHeaders()),
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(headers ?? {}),
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// Idempotency-Key must be 8..200 chars; a UUID satisfies that comfortably.
function idempotencyKey(): string {
  return crypto.randomUUID();
}

function narrativePage(options: { limit?: number; beforeId?: string; includeArchived?: boolean }): string {
  const query = new URLSearchParams({ limit: String(options.limit ?? 25) });
  if (options.beforeId) query.set("before_id", options.beforeId);
  if (options.includeArchived) query.set("include_archived", "true");
  return query.toString();
}

function assistantPath(projectId: string): string {
  return `/v1/narrative/projects/${encodeURIComponent(projectId)}/assistant`;
}

function projectPath(projectId: string): string {
  return `/v1/narrative/projects/${encodeURIComponent(projectId)}`;
}

function releasePath(projectId: string, releaseId?: string): string {
  return `/v1/narrative/projects/${encodeURIComponent(projectId)}/releases`
    + (releaseId ? `/${encodeURIComponent(releaseId)}` : "");
}

async function verifiedAttachment(tenantId: string, projectId: string, releaseId: string,
  artifact: ReleaseArtifact, signal?: AbortSignal): Promise<Blob> {
  const cap = artifact.kind === "manifest" ? 1048576 : 67108864;
  const mediaType = artifact.kind === "manifest" ? "application/json" : "application/zip";
  const invalid = () => new ApiError("The downloaded file could not be verified. Refresh this release and try again.", 502);
  const filename = `game-${releaseId.replaceAll("-", "")}-${artifact.kind}.${artifact.kind === "manifest" ? "json" : "zip"}`;
  if (!["source", "web", "manifest"].includes(artifact.kind) || !Number.isSafeInteger(artifact.size_bytes)
    || artifact.size_bytes < 1 || artifact.size_bytes > cap || !/^[a-f0-9]{64}$/.test(artifact.sha256)
    || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(releaseId)
    || artifact.filename !== filename || artifact.media_type !== mediaType) throw invalid();
  const headers = { ...(await authHeaders()), ...tenantHeaders(tenantId) };
  signal?.throwIfAborted();
  const response = await fetch(`${BASE}${releasePath(projectId, releaseId)}/artifacts/${artifact.kind}`, {
    headers, signal, cache: "no-store", credentials: "same-origin", redirect: "error",
  });
  if (!response.ok) throw await parseError(response);
  const reader = response.body?.getReader();
  if (!reader) throw invalid();
  try {
    if (response.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== mediaType) throw invalid();
    const length = response.headers.get("content-length");
    if (length !== null && !response.headers.get("content-encoding") && Number(length) !== artifact.size_bytes) throw invalid();
    // Allocate once: arbitrarily small stream chunks cannot amplify metadata memory.
    const bytes = new Uint8Array(artifact.size_bytes);
    let offset = 0;
    while (true) {
      signal?.throwIfAborted();
      const { value, done } = await reader.read();
      if (done) break;
      if (offset + value.length > bytes.length) throw invalid();
      bytes.set(value, offset); offset += value.length;
    }
    if (offset !== bytes.length) throw invalid();
    const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)))
      .map(value => value.toString(16).padStart(2, "0")).join("");
    signal?.throwIfAborted();
    if (digest !== artifact.sha256) throw invalid();
    return new Blob([bytes], { type: mediaType });
  } finally {
    try { await reader.cancel(); } catch { /* Abort/closed streams need no further reads. */ }
    reader.releaseLock();
  }
}

export const api = {
  async health(): Promise<boolean> {
    try {
      const res = await fetch(`${BASE}/health/live`);
      return res.ok;
    } catch {
      return false;
    }
  },

  createTenant(name: string): Promise<Tenant> {
    return jsonRequest<Tenant>("/v1/tenants", {
      method: "POST",
      json: { name },
    });
  },

  listWorkspaces(): Promise<Workspace[]> {
    return jsonRequest<Workspace[]>("/v1/workspaces");
  },

  createWorkspace(name: string): Promise<Workspace> {
    return jsonRequest<Workspace>("/v1/workspaces", {
      method: "POST",
      json: { name },
    });
  },

  listNarrativeProjects(tenantId: string, options: {
    limit?: number; beforeId?: string; includeArchived?: boolean; signal?: AbortSignal;
  } = {}): Promise<NarrativeProject[]> {
    return jsonRequest(`/v1/narrative/projects?${narrativePage(options)}`, {
      headers: tenantHeaders(tenantId), signal: options.signal,
    });
  },

  createNarrativeProject(tenantId: string, name: string, key: string,
    signal?: AbortSignal): Promise<NarrativeProject> {
    return jsonRequest("/v1/narrative/projects", {
      method: "POST", headers: tenantHeaders(tenantId), signal,
      json: { name, idempotency_key: key },
    });
  },

  getNarrativeProject(tenantId: string, projectId: string,
    signal?: AbortSignal): Promise<NarrativeProject> {
    return jsonRequest(`/v1/narrative/projects/${encodeURIComponent(projectId)}`, {
      headers: tenantHeaders(tenantId), signal,
    });
  },

  listNarrativeRevisions(tenantId: string, projectId: string, options: {
    limit?: number; beforeId?: string; includeArchived?: boolean; signal?: AbortSignal;
  } = {}): Promise<RevisionSummary[]> {
    return jsonRequest(`/v1/narrative/projects/${encodeURIComponent(projectId)}/revisions?${narrativePage(options)}`, {
      headers: tenantHeaders(tenantId), signal: options.signal,
    });
  },

  getNarrativeRevision(tenantId: string, projectId: string, revisionId: string,
    signal?: AbortSignal): Promise<NarrativeRevision> {
    return jsonRequest(`/v1/narrative/projects/${encodeURIComponent(projectId)}/revisions/${encodeURIComponent(revisionId)}`, {
      headers: tenantHeaders(tenantId), signal,
    });
  },

  saveNarrativeRevision(tenantId: string, projectId: string, payload: RevisionWrite,
    signal?: AbortSignal): Promise<NarrativeRevision> {
    return jsonRequest(`/v1/narrative/projects/${encodeURIComponent(projectId)}/revisions`, {
      method: "POST", headers: tenantHeaders(tenantId), signal, json: payload,
    });
  },

  // Explicit, idempotent move of a format 1 story to stage and theme (ADR 0040).
  upgradeNarrativeProject(tenantId: string, projectId: string, baseRevisionId: string, key: string,
    signal?: AbortSignal): Promise<NarrativeRevision> {
    return jsonRequest(`/v1/narrative/projects/${encodeURIComponent(projectId)}/upgrade`, {
      method: "POST", headers: tenantHeaders(tenantId), signal,
      json: { base_revision_id: baseRevisionId, idempotency_key: key },
    });
  },

  listNarrativeReleases(tenantId: string, projectId: string, options: {
    limit?: number; beforeId?: string; signal?: AbortSignal;
  } = {}): Promise<NarrativeRelease[]> {
    return jsonRequest(`${releasePath(projectId)}?${narrativePage(options)}`, {
      headers: tenantHeaders(tenantId), signal: options.signal, cache: "no-store",
    });
  },

  createNarrativeRelease(tenantId: string, projectId: string, revisionId: string, key: string,
    signal?: AbortSignal): Promise<NarrativeRelease> {
    return jsonRequest(releasePath(projectId), { method: "POST", headers: tenantHeaders(tenantId),
      signal, json: { revision_id: revisionId, idempotency_key: key } });
  },

  getNarrativeRelease(tenantId: string, projectId: string, releaseId: string,
    signal?: AbortSignal): Promise<NarrativeRelease> {
    return jsonRequest(releasePath(projectId, releaseId), { headers: tenantHeaders(tenantId), signal, cache: "no-store" });
  },

  retryNarrativeRelease(tenantId: string, projectId: string, releaseId: string, key: string,
    signal?: AbortSignal): Promise<NarrativeRelease> {
    return jsonRequest(`${releasePath(projectId, releaseId)}/retry`, { method: "POST",
      headers: tenantHeaders(tenantId), signal, json: { idempotency_key: key } });
  },

  cancelNarrativeRelease(tenantId: string, projectId: string, releaseId: string, jobId: string,
    signal?: AbortSignal): Promise<ReleaseJob> {
    return jsonRequest(`${releasePath(projectId, releaseId)}/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST", headers: tenantHeaders(tenantId), signal,
    });
  },

  listNarrativeReleaseJobs(tenantId: string, projectId: string, releaseId: string, options: {
    limit?: number; beforeId?: string; signal?: AbortSignal;
  } = {}): Promise<ReleaseJob[]> {
    return jsonRequest(`${releasePath(projectId, releaseId)}/jobs?${narrativePage(options)}`, {
      headers: tenantHeaders(tenantId), signal: options.signal, cache: "no-store",
    });
  },

  listNarrativeReleaseEvents(tenantId: string, projectId: string, releaseId: string, jobId: string, options: {
    limit?: number; afterSequence?: number; signal?: AbortSignal;
  } = {}): Promise<ReleaseEvent[]> {
    const query = new URLSearchParams({ limit: String(options.limit ?? 100), after_sequence: String(options.afterSequence ?? 0) });
    return jsonRequest(`${releasePath(projectId, releaseId)}/jobs/${encodeURIComponent(jobId)}/events?${query}`, {
      headers: tenantHeaders(tenantId), signal: options.signal, cache: "no-store",
    });
  },

  downloadNarrativeArtifact: verifiedAttachment,

  getNarrativeLayout(tenantId: string, projectId: string, signal?: AbortSignal): Promise<SceneLayout> {
    return jsonRequest(`/v1/narrative/projects/${encodeURIComponent(projectId)}/layout`, {
      headers: tenantHeaders(tenantId), signal, cache: "no-store",
    });
  },

  // Optimistic version: a 409 means someone else reorganized the scenes first.
  saveNarrativeLayout(tenantId: string, projectId: string, baseVersion: number, items: LayoutItem[],
    signal?: AbortSignal): Promise<SceneLayout> {
    return jsonRequest(`/v1/narrative/projects/${encodeURIComponent(projectId)}/layout`, {
      method: "PUT", headers: tenantHeaders(tenantId), signal, json: { base_version: baseVersion, items },
    });
  },

  // Characters (ADR 0039): editor-only appearance, local portrait jobs and approved images.
  listCharacterProfiles(tenantId: string, projectId: string, signal?: AbortSignal):
    Promise<{ project_id: string; profiles: CharacterProfile[] }> {
    return jsonRequest(`${projectPath(projectId)}/characters`, {
      headers: tenantHeaders(tenantId), signal, cache: "no-store",
    });
  },

  saveCharacterProfile(tenantId: string, projectId: string, characterId: string, body: {
    base_version: number; appearance: string; character_type: CharacterType; framing: CharacterFraming;
  }, signal?: AbortSignal): Promise<CharacterProfile> {
    return jsonRequest(`${projectPath(projectId)}/characters/${encodeURIComponent(characterId)}`, {
      method: "PUT", headers: tenantHeaders(tenantId), signal, json: body,
    });
  },

  chooseCharacterPortrait(tenantId: string, projectId: string, characterId: string, baseVersion: number,
    assetId: string | null, signal?: AbortSignal): Promise<CharacterProfile> {
    return jsonRequest(`${projectPath(projectId)}/characters/${encodeURIComponent(characterId)}/portrait`, {
      method: "PUT", headers: tenantHeaders(tenantId), signal,
      json: { base_version: baseVersion, asset_id: assetId },
    });
  },

  createPortraitJob(tenantId: string, projectId: string, characterId: string, body: {
    appearance: string; character_type: CharacterType; framing: CharacterFraming; count: number;
    idempotency_key: string; transparent?: boolean; hires?: boolean;
  }, signal?: AbortSignal): Promise<ImageJob> {
    return jsonRequest(`${projectPath(projectId)}/characters/${encodeURIComponent(characterId)}/portrait-jobs`, {
      method: "POST", headers: tenantHeaders(tenantId), signal, json: body,
    });
  },

  createExpressionJob(tenantId: string, projectId: string, characterId: string, body: {
    base_asset_id: string; face_box: number[]; expressions: string[]; idempotency_key: string;
  }, signal?: AbortSignal): Promise<ImageJob> {
    return jsonRequest(`${projectPath(projectId)}/characters/${encodeURIComponent(characterId)}/expression-jobs`, {
      method: "POST", headers: tenantHeaders(tenantId), signal, json: body,
    });
  },

  listExpressionJobs(tenantId: string, projectId: string, characterId: string, signal?: AbortSignal):
    Promise<{ jobs: ImageJob[] }> {
    return jsonRequest(`${projectPath(projectId)}/characters/${encodeURIComponent(characterId)}/expression-jobs`, {
      headers: tenantHeaders(tenantId), signal, cache: "no-store",
    });
  },

  listPortraitJobs(tenantId: string, projectId: string, characterId: string, signal?: AbortSignal):
    Promise<{ jobs: ImageJob[] }> {
    return jsonRequest(`${projectPath(projectId)}/characters/${encodeURIComponent(characterId)}/portrait-jobs`, {
      headers: tenantHeaders(tenantId), signal, cache: "no-store",
    });
  },

  getImageJob(tenantId: string, projectId: string, jobId: string, signal?: AbortSignal): Promise<ImageJob> {
    return jsonRequest(`${projectPath(projectId)}/image-jobs/${encodeURIComponent(jobId)}`, {
      headers: tenantHeaders(tenantId), signal, cache: "no-store",
    });
  },

  cancelImageJob(tenantId: string, projectId: string, jobId: string, signal?: AbortSignal): Promise<ImageJob> {
    return jsonRequest(`${projectPath(projectId)}/image-jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST", headers: tenantHeaders(tenantId), signal,
    });
  },

  discardNarrativeImage(tenantId: string, projectId: string, assetId: string, signal?: AbortSignal):
    Promise<NarrativeImage> {
    return jsonRequest(`${projectPath(projectId)}/assets/${encodeURIComponent(assetId)}/discard`, {
      method: "POST", headers: tenantHeaders(tenantId), signal,
    });
  },

  // Immutable bytes behind authorization: fetched with auth headers, shown as blob URLs.
  async getNarrativeImage(tenantId: string, projectId: string, assetId: string,
    variant: "image" | "thumbnail", signal?: AbortSignal): Promise<Blob> {
    const response = await fetch(
      `${BASE}${projectPath(projectId)}/assets/${encodeURIComponent(assetId)}/content?variant=${variant}`,
      { headers: { ...(await authHeaders()), ...tenantHeaders(tenantId) }, signal, redirect: "error" },
    );
    if (!response.ok) throw await parseError(response);
    const blob = await response.blob();
    if (blob.type !== "image/png") throw new ApiError("The image could not be loaded.", 502);
    return blob;
  },

  async getNarrativeFont(tenantId: string, projectId: string, assetId: string, signal?: AbortSignal):
    Promise<ArrayBuffer> {
    const response = await fetch(`${BASE}${projectPath(projectId)}/assets/${encodeURIComponent(assetId)}/content`,
      { headers: { ...(await authHeaders()), ...tenantHeaders(tenantId) }, signal, redirect: "error" });
    if (!response.ok) throw await parseError(response);
    if (!["font/ttf", "font/otf"].includes(response.headers.get("content-type") ?? ""))
      throw new ApiError("The font could not be loaded.", 502);
    return response.arrayBuffer();
  },

  // A saved revision's asset bytes as bound when it was saved (playtests, ADR 0040).
  async getRevisionAsset(tenantId: string, projectId: string, revisionId: string, key: string,
    signal?: AbortSignal): Promise<ArrayBuffer> {
    const response = await fetch(`${BASE}${projectPath(projectId)}/revisions/${encodeURIComponent(revisionId)}`
      + `/assets/${encodeURIComponent(key)}`,
      { headers: { ...(await authHeaders()), ...tenantHeaders(tenantId) }, signal, redirect: "error" });
    if (!response.ok) throw await parseError(response);
    return response.arrayBuffer();
  },

  // Asset library (ADR 0040): uploads with a rights declaration, generated backgrounds.
  listNarrativeAssets(tenantId: string, projectId: string, query: {
    kind?: string; status?: string; limit?: number; before?: string;
  } = {}, signal?: AbortSignal): Promise<{ assets: NarrativeImage[]; next_before: string | null }> {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) if (value !== undefined) params.set(key, String(value));
    return jsonRequest(`${projectPath(projectId)}/assets?${params}`, {
      headers: tenantHeaders(tenantId), signal, cache: "no-store",
    });
  },

  async uploadNarrativeAsset(tenantId: string, projectId: string, upload: AssetUpload, signal?: AbortSignal):
    Promise<NarrativeImage> {
    const form = new FormData();
    form.set("file", upload.file);
    form.set("kind", upload.kind);
    form.set("name", upload.name);
    form.set("license", upload.license);
    form.set("notice", upload.notice);
    form.set("rights_declared", "true");
    const response = await fetch(`${BASE}${projectPath(projectId)}/assets`, {
      method: "POST", body: form, signal, headers: { ...(await authHeaders()), ...tenantHeaders(tenantId) },
    });
    if (!response.ok) throw await parseError(response);
    return (await response.json()) as NarrativeImage;
  },

  renameNarrativeAsset(tenantId: string, projectId: string, assetId: string, name: string, signal?: AbortSignal):
    Promise<NarrativeImage> {
    return jsonRequest(`${projectPath(projectId)}/assets/${encodeURIComponent(assetId)}`, {
      method: "PATCH", headers: tenantHeaders(tenantId), signal, json: { name },
    });
  },

  approveNarrativeAsset(tenantId: string, projectId: string, assetId: string, signal?: AbortSignal):
    Promise<NarrativeImage> {
    return jsonRequest(`${projectPath(projectId)}/assets/${encodeURIComponent(assetId)}/approve`, {
      method: "POST", headers: tenantHeaders(tenantId), signal,
    });
  },

  createBackgroundJob(tenantId: string, projectId: string, description: string, count: number,
    signal?: AbortSignal): Promise<ImageJob> {
    return jsonRequest(`${projectPath(projectId)}/assets/background-jobs`, {
      method: "POST", headers: tenantHeaders(tenantId), signal,
      json: { description, count, idempotency_key: crypto.randomUUID() },
    });
  },

  listBackgroundJobs(tenantId: string, projectId: string, signal?: AbortSignal): Promise<{ jobs: ImageJob[] }> {
    return jsonRequest(`${projectPath(projectId)}/assets/background-jobs`, {
      headers: tenantHeaders(tenantId), signal, cache: "no-store",
    });
  },

  listAssistantThreads(tenantId: string, projectId: string, options: {
    limit?: number; beforeId?: string; signal?: AbortSignal;
  } = {}): Promise<AssistantThread[]> {
    return jsonRequest(`${assistantPath(projectId)}/threads?${narrativePage(options)}`, {
      headers: tenantHeaders(tenantId), signal: options.signal, cache: "no-store",
    });
  },

  getAssistantThread(tenantId: string, projectId: string, threadId: string,
    signal?: AbortSignal): Promise<AssistantThread> {
    return jsonRequest(`${assistantPath(projectId)}/threads/${encodeURIComponent(threadId)}`, {
      headers: tenantHeaders(tenantId), signal, cache: "no-store",
    });
  },

  createAssistantThread(tenantId: string, projectId: string, title: string, key: string,
    signal?: AbortSignal): Promise<AssistantThread> {
    return jsonRequest(`${assistantPath(projectId)}/threads`, { method: "POST",
      headers: tenantHeaders(tenantId), signal, json: { title, idempotency_key: key } });
  },

  listAssistantTurns(tenantId: string, projectId: string, threadId: string, options: {
    signal?: AbortSignal;
  } = {}): Promise<AssistantTurn[]> {
    return jsonRequest(`${assistantPath(projectId)}/threads/${encodeURIComponent(threadId)}/turns?limit=100`, {
      headers: tenantHeaders(tenantId), signal: options.signal, cache: "no-store",
    });
  },

  postAssistantTurn(tenantId: string, projectId: string, threadId: string, payload: TurnWrite,
    signal?: AbortSignal): Promise<AssistantTurn> {
    return jsonRequest(`${assistantPath(projectId)}/threads/${encodeURIComponent(threadId)}/turns`, {
      method: "POST", headers: tenantHeaders(tenantId), signal, json: payload,
    });
  },

  cancelAssistantTurn(tenantId: string, projectId: string, threadId: string, turnId: string,
    signal?: AbortSignal): Promise<AssistantTurn> {
    return jsonRequest(`${assistantPath(projectId)}/threads/${encodeURIComponent(threadId)}/turns/${encodeURIComponent(turnId)}/cancel`, {
      method: "POST", headers: tenantHeaders(tenantId), signal,
    });
  },

  getAssistantProposal(tenantId: string, projectId: string, proposalId: string,
    signal?: AbortSignal): Promise<AssistantProposal> {
    return jsonRequest(`${assistantPath(projectId)}/proposals/${encodeURIComponent(proposalId)}`, {
      headers: tenantHeaders(tenantId), signal, cache: "no-store",
    });
  },

  // A stale base still commits a conflict revision; callers read it from the 409 problem.
  acceptAssistantProposal(tenantId: string, projectId: string, proposalId: string, key: string,
    signal?: AbortSignal): Promise<NarrativeRevision> {
    return jsonRequest(`${assistantPath(projectId)}/proposals/${encodeURIComponent(proposalId)}/accept`, {
      method: "POST", headers: tenantHeaders(tenantId), signal, json: { idempotency_key: key },
    });
  },

  rejectAssistantProposal(tenantId: string, projectId: string, proposalId: string,
    signal?: AbortSignal): Promise<AssistantProposal> {
    return jsonRequest(`${assistantPath(projectId)}/proposals/${encodeURIComponent(proposalId)}/reject`, {
      method: "POST", headers: tenantHeaders(tenantId), signal,
    });
  },

  listDocuments(tenantId: string): Promise<DocumentListItem[]> {
    return jsonRequest<DocumentListItem[]>("/v1/documents", {
      headers: tenantHeaders(tenantId),
    });
  },

  uploadDocument(
    tenantId: string,
    args: { title: string; file: File; externalId?: string },
  ): Promise<DocumentIntakeResponse> {
    const form = new FormData();
    form.append("title", args.title);
    form.append("file", args.file);
    if (args.externalId) form.append("external_id", args.externalId);
    return jsonRequest<DocumentIntakeResponse>("/v1/documents/uploads", {
      method: "POST",
      headers: {
        ...tenantHeaders(tenantId),
        "Idempotency-Key": idempotencyKey(),
      },
      body: form,
    });
  },

  ingestUrl(
    tenantId: string,
    args: { title: string; sourceUrl: string; externalId?: string },
  ): Promise<DocumentIntakeResponse> {
    return jsonRequest<DocumentIntakeResponse>("/v1/documents/from-url", {
      method: "POST",
      headers: {
        ...tenantHeaders(tenantId),
        "Idempotency-Key": idempotencyKey(),
      },
      json: {
        title: args.title,
        source_url: args.sourceUrl,
        ...(args.externalId ? { external_id: args.externalId } : {}),
      },
    });
  },

  getJob(tenantId: string, jobId: string): Promise<IngestionJobResponse> {
    return jsonRequest<IngestionJobResponse>(`/v1/ingestion-jobs/${jobId}`, {
      headers: tenantHeaders(tenantId),
    });
  },

  getSearchReadiness(tenantId: string, signal?: AbortSignal): Promise<SearchReadiness> {
    return jsonRequest<SearchReadiness>("/v1/search-readiness", {
      headers: tenantHeaders(tenantId),
      signal,
    });
  },

  getSystemReadiness(tenantId: string, signal?: AbortSignal): Promise<SystemReadiness> {
    return jsonRequest<SystemReadiness>("/v1/system-readiness", {
      headers: tenantHeaders(tenantId),
      signal,
    });
  },

  // Admin/owner only; a viewer gets 403.
  getUsage(
    tenantId: string,
    groupBy: UsageSummary["group_by"] = "operation",
  ): Promise<UsageSummary> {
    return jsonRequest<UsageSummary>(`/v1/usage?group_by=${groupBy}`, {
      headers: tenantHeaders(tenantId),
    });
  },

  bootstrapRetrievalIndex(tenantId: string): Promise<unknown> {
    return jsonRequest<unknown>("/v1/retrieval-index/bootstrap", {
      method: "POST",
      headers: tenantHeaders(tenantId),
    });
  },

  backfillActiveIndex(tenantId: string): Promise<IndexBackfillJob> {
    return jsonRequest<IndexBackfillJob>("/v1/retrieval-index/backfill-active", {
      method: "POST",
      headers: tenantHeaders(tenantId),
    });
  },

  listIndexBackfills(tenantId: string): Promise<IndexBackfillJob[]> {
    return jsonRequest<IndexBackfillJob[]>("/v1/index-backfills", {
      headers: tenantHeaders(tenantId),
    });
  },

  deleteDocument(tenantId: string, documentId: string): Promise<DocumentDeleteResponse> {
    return jsonRequest<DocumentDeleteResponse>(`/v1/documents/${documentId}`, {
      method: "DELETE",
      headers: tenantHeaders(tenantId),
    });
  },

  getProjectionCleanups(
    tenantId: string,
    documentId: string,
  ): Promise<DocumentProjectionCleanup[]> {
    return jsonRequest<DocumentProjectionCleanup[]>(
      `/v1/documents/${documentId}/projection-cleanups`,
      { headers: tenantHeaders(tenantId) },
    );
  },

  retryProjectionCleanups(
    tenantId: string,
    documentId: string,
  ): Promise<DocumentProjectionCleanup[]> {
    return jsonRequest<DocumentProjectionCleanup[]>(
      `/v1/documents/${documentId}/projection-cleanups/retry`,
      { method: "POST", headers: tenantHeaders(tenantId) },
    );
  },

  cancelJob(tenantId: string, jobId: string): Promise<IngestionJobResponse> {
    return jsonRequest<IngestionJobResponse>(
      `/v1/ingestion-jobs/${jobId}/cancel`,
      { method: "POST", headers: tenantHeaders(tenantId) },
    );
  },

  listConversations(tenantId: string, options: {
    limit?: number; beforeId?: string; query?: string; signal?: AbortSignal;
  } = {}): Promise<Conversation[]> {
    const params = new URLSearchParams();
    if (options.limit) params.set("limit", String(options.limit));
    if (options.beforeId) params.set("before_id", options.beforeId);
    if (options.query?.trim()) params.set("q", options.query.trim());
    return jsonRequest<Conversation[]>(`/v1/conversations${params.size ? `?${params}` : ""}`, {
      headers: tenantHeaders(tenantId), signal: options.signal,
    });
  },

  getConversation(tenantId: string, id: string, signal?: AbortSignal): Promise<Conversation> {
    return jsonRequest<Conversation>(`/v1/conversations/${id}`, { headers: tenantHeaders(tenantId), signal });
  },

  createConversation(tenantId: string, title: string, signal?: AbortSignal): Promise<Conversation> {
    return jsonRequest<Conversation>("/v1/conversations", {
      method: "POST", headers: tenantHeaders(tenantId), json: { title }, signal,
    });
  },

  renameConversation(tenantId: string, id: string, title: string, signal?: AbortSignal): Promise<Conversation> {
    return jsonRequest<Conversation>(`/v1/conversations/${id}`, {
      method: "PATCH", headers: tenantHeaders(tenantId), json: { title }, signal,
    });
  },

  listConversationTurns(tenantId: string, id: string, options: {
    afterId?: string; limit?: number; signal?: AbortSignal;
  } = {}): Promise<ConversationTurn[]> {
    const params = new URLSearchParams();
    if (options.limit) params.set("limit", String(options.limit));
    if (options.afterId) params.set("after_id", options.afterId);
    return jsonRequest<ConversationTurn[]>(`/v1/conversations/${id}/turns${params.size ? `?${params}` : ""}`, {
      headers: tenantHeaders(tenantId), signal: options.signal,
    });
  },

  createConversationTurn(tenantId: string, id: string, query: string, retryKey: string, signal?: AbortSignal): Promise<ConversationTurn> {
    return jsonRequest<ConversationTurn>(`/v1/conversations/${id}/turns`, {
      method: "POST", headers: tenantHeaders(tenantId), json: { query, idempotency_key: retryKey, stream: true }, signal,
    });
  },

  cancelQueuedConversationTurn(tenantId: string, id: string, turnId: string, signal?: AbortSignal): Promise<ConversationTurn> {
    return jsonRequest<ConversationTurn>(`/v1/conversations/${id}/turns/${turnId}/cancel`, {
      method: "POST", headers: tenantHeaders(tenantId), signal,
    });
  },

  createQueryRun(tenantId: string, query: string, signal?: AbortSignal): Promise<QueryRunResponse> {
    return jsonRequest<QueryRunResponse>("/v1/query-runs", {
      method: "POST",
      headers: tenantHeaders(tenantId),
      json: { query, stream: true },
      signal,
    });
  },

  getQueryRun(tenantId: string, queryRunId: string, signal?: AbortSignal): Promise<QueryRunResponse> {
    return jsonRequest<QueryRunResponse>(`/v1/query-runs/${queryRunId}`, {
      headers: tenantHeaders(tenantId),
      signal,
    });
  },

  listQueryRuns(tenantId: string, options: {
    limit?: number; beforeId?: string; query?: string; signal?: AbortSignal;
  } = {}): Promise<QueryRunResponse[]> {
    const params = new URLSearchParams();
    if (options.limit) params.set("limit", String(options.limit));
    if (options.beforeId) params.set("before_id", options.beforeId);
    if (options.query?.trim()) params.set("q", options.query.trim());
    const suffix = params.size ? `?${params}` : "";
    return jsonRequest<QueryRunResponse[]>(`/v1/query-runs${suffix}`, {
      headers: tenantHeaders(tenantId),
      signal: options.signal,
    });
  },

  getAnswerProvenance(
    tenantId: string,
    queryRunId: string,
    signal?: AbortSignal,
  ): Promise<AnswerProvenance> {
    return jsonRequest<AnswerProvenance>(
      `/v1/query-runs/${queryRunId}/provenance`,
      { headers: tenantHeaders(tenantId), signal },
    );
  },
};

export { idempotencyKey, tenantHeaders };
