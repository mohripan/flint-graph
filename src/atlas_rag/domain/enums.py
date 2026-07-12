from enum import StrEnum


class DocumentVersionStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    FAILED = "failed"
    DELETED = "deleted"
    
class IngestionJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    
class SourceType(StrEnum):
    UPLOAD = "upload"
    URL = "url"
    CONNECTOR = "connector"