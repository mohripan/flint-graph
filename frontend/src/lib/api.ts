import type {
  AnswerProvenance,
  DocumentIntakeResponse,
  IngestionJobResponse,
  ProblemDetail,
  QueryRunResponse,
  SearchReadiness,
  Tenant,
} from "./types";

// All requests are same-origin; the Vite dev server proxies /v1 and /health to
// the API. In a production build these paths are served behind the same origin.
const BASE = "";

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

export const api = {
  async health(): Promise<boolean> {
    try {
      const res = await fetch(`${BASE}/health/ready`);
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

  getSearchReadiness(tenantId: string): Promise<SearchReadiness> {
    return jsonRequest<SearchReadiness>("/v1/search-readiness", {
      headers: tenantHeaders(tenantId),
    });
  },

  cancelJob(tenantId: string, jobId: string): Promise<IngestionJobResponse> {
    return jsonRequest<IngestionJobResponse>(
      `/v1/ingestion-jobs/${jobId}/cancel`,
      { method: "POST", headers: tenantHeaders(tenantId) },
    );
  },

  createQueryRun(tenantId: string, query: string): Promise<QueryRunResponse> {
    return jsonRequest<QueryRunResponse>("/v1/query-runs", {
      method: "POST",
      headers: tenantHeaders(tenantId),
      json: { query, stream: true },
    });
  },

  getQueryRun(tenantId: string, queryRunId: string): Promise<QueryRunResponse> {
    return jsonRequest<QueryRunResponse>(`/v1/query-runs/${queryRunId}`, {
      headers: tenantHeaders(tenantId),
    });
  },

  getAnswerProvenance(
    tenantId: string,
    queryRunId: string,
  ): Promise<AnswerProvenance> {
    return jsonRequest<AnswerProvenance>(
      `/v1/query-runs/${queryRunId}/provenance`,
      { headers: tenantHeaders(tenantId) },
    );
  },
};

export { idempotencyKey, tenantHeaders };
