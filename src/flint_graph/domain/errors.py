from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DomainError(Exception):
    status_code: int
    title: str
    detail: str
    error_type: str
    errors: list[dict[str, Any]] | None = field(default=None)
    
class NotFoundError(DomainError):
    def __init__(self, detail: str) -> None:
        super().__init__(404, "Resource not found", detail, "not-found")
        
class ConflictError(DomainError):
    def __init__(self, detail: str, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(409, "Conflict", detail, "conflict", errors)


class BadRequestError(DomainError):
    def __init__(self, detail: str) -> None:
        super().__init__(400, "Bad request", detail, "bad-request")
