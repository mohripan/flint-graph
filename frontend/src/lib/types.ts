// TypeScript mirrors of the FlintGraph API contracts we consume.
// Only the fields the UI reads are typed; unknown extras are tolerated.

export interface Tenant {
  id: string;
  name: string;
  created_at: string;
}

export type WorkspaceRole = "owner" | "admin" | "member" | "viewer";

export interface Workspace {
  id: string;
  name: string;
  role: WorkspaceRole;
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

export interface DocumentDeleteResponse {
  document_id: string;
  deleted_version_ids: string[];
  cleanup_count: number;
}

export interface DocumentListItem {
  id: string;
  tenant_id: string;
  title: string;
  source_type: string;
  source_uri: string | null;
  external_id: string | null;
  deleted_at: string | null;
  latest_version_id: string | null;
  latest_version_number: number | null;
  latest_version_status: string | null;
  created_at: string;
  updated_at: string;
}

export type DocumentProjectionCleanupStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed";

export interface DocumentProjectionCleanup {
  id: string;
  tenant_id: string;
  document_id: string;
  document_version_id: string;
  retrieval_index_version_id: string;
  status: DocumentProjectionCleanupStatus;
  stale_reason: string;
  chunk_count: number;
  vector_count: number;
  lexical_count: number;
  attempt_count: number;
  started_at: string | null;
  completed_at: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
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
  error_code: string | null;
  error_message: string | null;
  answer_text: string | null;
  answer_citations: Array<Record<string, unknown>>;
  query_diagnostics: QueryDiagnostics;
  created_at: string;
  updated_at: string;
}

export interface IndexBackfillJob {
  id: string;
  tenant_id: string | null;
  retrieval_index_version_id: string;
  document_id: string | null;
  document_version_id: string | null;
  status: string;
  total_count: number;
  processed_count: number;
  failed_count: number;
  checkpoint: Record<string, unknown>;
  last_error: Record<string, unknown> | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface QueryDiagnostics {
  retriever_candidate_counts?: Record<string, number>;
  failed_retrievers?: string[];
  retrieved_candidate_count?: number;
  fused_candidate_count?: number;
  reranked_candidate_count?: number;
  context_record_count?: number;
  context_token_count?: number;
  skipped_context_count?: number;
  citation_repair_counts?: Record<string, number>;
  support_status_counts?: Record<string, number>;
  abstention_reason?: string | null;
  answer_provider?: string | null;
  support_provider?: string | null;
  model_metadata?: Record<string, unknown>;
}

export interface SearchReadiness {
  ready: boolean;
  reason: string;
  active_index_version: {
    id: string;
    embedding_provider: string;
    embedding_model: string;
    vector_dimension: number;
    opensearch_index_name: string;
    neo4j_vector_index_name: string;
  } | null;
  completed_coverage_count: number;
  running_coverage_count: number;
  failed_coverage_count: number;
  cancelled_coverage_count: number;
  documents: SearchReadinessDocument[];
}

export interface SearchReadinessDocument {
  document_id: string;
  document_version_id: string;
  title: string;
  version_number: number;
  document_version_status: string;
  status: "ingesting" | "ingested" | "indexing" | "searchable" | "failed" | "cancelled" | string;
  coverage_status: string | null;
  chunk_count: number;
  embedded_count: number;
  vector_count: number;
  lexical_count: number;
  error_code: string | null;
  error_message: string | null;
  updated_at: string;
}

export interface SystemReadiness {
  auth: {
    mode: string;
    oidc_issuer: string | null;
  };
  embedding: {
    provider: string;
    model: string;
    dimensions: number;
  };
  query: {
    answer_provider: string | null;
    answer_model: string;
    support_provider: string | null;
    support_model: string;
  };
  search_readiness: SearchReadiness;
}

// Provider usage rollup. Costs are integer micros of `currency`; null means the
// provider/model has no configured price, not that it was free.
export interface UsageRollup {
  group: string;
  event_count: number;
  input_tokens: number;
  output_tokens: number;
  embedded_item_count: number;
  duration_ms: number;
  estimated_cost_micros: number | null;
  unpriced_event_count: number;
}

export interface UsageSummary {
  currency: string;
  group_by: "day" | "operation" | "model";
  rows: UsageRollup[];
  totals: UsageRollup;
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
