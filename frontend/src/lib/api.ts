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

  listAssistantThreads(tenantId: string, projectId: string, options: {
    limit?: number; beforeId?: string; signal?: AbortSignal;
  } = {}): Promise<AssistantThread[]> {
    return jsonRequest(`${assistantPath(projectId)}/threads?${narrativePage(options)}`, {
      headers: tenantHeaders(tenantId), signal: options.signal, cache: "no-store",
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
