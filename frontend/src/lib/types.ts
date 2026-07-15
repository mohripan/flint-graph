// TypeScript mirrors of the AtlasRAG API contracts we consume.
// Only the fields the UI reads are typed; unknown extras are tolerated.

export interface Tenant {
  id: string;
  name: string;
  created_at: string;
}

export type IngestionJobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface DocumentIntakeResponse {
  document_id: string;
  document_version_id: string;
  ingestion_job_id: string;
  tenant_id: string;
  title: string;
  source_type: string;
  source_uri: string | null;
  external_id: string | null;
  version_number: number;
  job_status: IngestionJobStatus;
  idempotency_key: string;
  object_uri: string;
  content_hash: string;
  created_at: string;
}

export interface IngestionJobResponse {
  id: string;
  tenant_id: string;
  document_id: string;
  document_version_id: string;
  version_number: number;
  status: IngestionJobStatus;
  idempotency_key: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_code: string | null;
  error_message: string | null;
}

export type QueryRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface QueryRunResponse {
  id: string;
  tenant_id: string;
  retrieval_index_version_id: string;
  query_text: string;
  status: QueryRunStatus;
  answer_text: string | null;
  answer_citations: Array<Record<string, unknown>>;
  created_at: string;
  updated_at: string;
}

// A persisted query-run event as delivered over SSE.
export interface QueryRunEvent {
  id: string;
  query_run_id: string;
  tenant_id: string;
  sequence: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface CitationClaimProvenance {
  claim_index: number;
  text: string;
  support_status: string;
  support_score: number;
  support_reason: string;
  method: string;
}

export interface CitationProvenance {
  query_run_id: string;
  tenant_id: string;
  citation_id: string;
  context_id: string;
  candidate_id: string;
  text: string;
  token_count: number;
  source_ids: Record<string, string>;
  metadata: Record<string, unknown>;
  claims: CitationClaimProvenance[];
}

export interface AnswerProvenance {
  query_run_id: string;
  tenant_id: string;
  answer_text: string | null;
  answer_citations: Array<Record<string, unknown>>;
  abstained: boolean;
  abstain_reason: string | null;
  supported_claim_count: number;
  unsupported_claim_count: number;
  support_method: string | null;
  answer_provider: string | null;
  claims: Array<{
    claim_index: number;
    text: string;
    citation_ids: string[];
    support_status: string;
    support_score: number;
    support_reason: string;
    method: string;
  }>;
  citations: CitationProvenance[];
}

// RFC 7807 problem+json shape the API returns on error.
export interface ProblemDetail {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance: string;
  request_id?: string | null;
  errors?: Array<Record<string, unknown>> | null;
}
