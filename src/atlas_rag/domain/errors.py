from dataclasses import dataclass

@dataclass(slots=True)
class DomainError(Exception):
    status_code: int
    title: str
    detail: str
    error_type: str
    
class NotFoundError(DomainError):
    def __init__(self, detail: str) -> None:
        super().__init__(404, "Resource not found", detail, "not-found")
        
class ConflictError(DomainError):
    def __init__(self, detail: str) -> None:
        super().__init__(409, "Conflict", detail, "conflict")