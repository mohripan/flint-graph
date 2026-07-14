from enum import StrEnum


class DocumentVersionStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DELETED = "deleted"


class IngestionJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OutboxMessageStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"


class SourceType(StrEnum):
    UPLOAD = "upload"
    URL = "url"
    CONNECTOR = "connector"


class DocumentArtifactType(StrEnum):
    RAW = "raw"
    NORMALIZED = "normalized"
    CHUNK_MANIFEST = "chunk_manifest"
    EXTRACTION = "extraction"


class EntityType(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"
    PLACE = "place"
    CONCEPT = "concept"
    OTHER = "other"


class EntityStatus(StrEnum):
    ACTIVE = "active"
    MERGED = "merged"
    DEPRECATED = "deprecated"


class AliasSource(StrEnum):
    EXTRACTION = "extraction"
    MERGE = "merge"
    MANUAL = "manual"


class MentionResolutionStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    REVIEW = "review"
    REJECTED = "rejected"


class ClaimStatus(StrEnum):
    PENDING = "pending"
    LINKED = "linked"
    REJECTED = "rejected"


class RelationshipStatus(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class MergeCandidateBand(StrEnum):
    AUTO = "auto"
    REVIEW = "review"
    REJECT = "reject"


class MergeCandidateStatus(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class MergeDecisionType(StrEnum):
    ATTACH = "attach"
    MERGE = "merge"
    NO_MERGE = "no_merge"
    SPLIT = "split"


class MergeDecisionSource(StrEnum):
    AUTO = "auto"
    HUMAN = "human"


class ExtractionRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExtractionInvocationStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class StagedProposalStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class StagedResolutionStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    REVIEW = "review"
    REJECTED = "rejected"


class CandidateTargetKind(StrEnum):
    CANONICAL_ENTITY = "canonical_entity"
    EXTRACTED_ENTITY = "extracted_entity"


class CandidateOutcome(StrEnum):
    AUTO = "auto"
    REVIEW = "review"
    REJECT = "reject"


class RetrievalIndexScope(StrEnum):
    GLOBAL = "global"
    TENANT = "tenant"


class RetrievalIndexVersionStatus(StrEnum):
    BUILDING = "building"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    FAILED = "failed"


class DocumentIndexCoverageStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IndexBackfillJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
