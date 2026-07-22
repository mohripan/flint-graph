from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from flint_graph.api.schemas import ProblemDetail
from flint_graph.domain.errors import DomainError

logger = structlog.get_logger()


def _problem_response(problem: ProblemDetail) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(mode="json", exclude_none=True),
        media_type="application/problem+json",
    )
    

def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return _problem_response(
            ProblemDetail(
                type=f"urn:flint-graph:error:{exc.error_type}",
                title=exc.title,
                status=exc.status_code,
                detail=exc.detail,
                instance=str(request.url.path),
                request_id=getattr(request.state, "request_id", None),
                errors=exc.errors,
            )
        )
        
    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors: list[dict[str, Any]] = [
            {
                "location": list(error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return _problem_response(
            ProblemDetail(
                type="urn:flint-graph:error:validation",
                title="Request validation failed",
                status=422,
                detail="One or more request fields are invalid.",
                instance=str(request.url.path),
                request_id=getattr(request.state, "request_id", None),
                errors=errors,
            )
        )
        
    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", path=request.url.path)
        return _problem_response(
            ProblemDetail(
                type="urn:flint-graph:error.internal",
                title="Internal server error",
                status=500,
                detail="The server could not complete the request.",
                instance=str(request.url.path),
                request_id=getattr(request.state, "request_id", None),
            )
        )
