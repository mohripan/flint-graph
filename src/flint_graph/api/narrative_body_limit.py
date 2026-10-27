"""Bound narrative wire bodies before JSON decoding, including streamed requests."""

from fastapi import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from flint_graph.api.middleware import problem_response
from flint_graph.config import Settings
from flint_graph.observability import metrics


class NarrativeBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        configured = max(settings.max_upload_bytes or 0, settings.max_url_intake_bytes or 0)
        self.limit = min(configured or 16 * 1024 * 1024, 16 * 1024 * 1024)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in {"POST", "PUT", "PATCH"}
            or not scope["path"].startswith("/v1/narrative/")
        ):
            await self.app(scope, receive, send)
            return
        request = Request(scope)

        async def reject(status: int) -> None:
            if status == 413:
                metrics.record_request_size_rejection(route="/v1/narrative")
            response = problem_response(
                status_code=status,
                title="Payload too large" if status == 413 else "Bad request",
                detail=(
                    "Request body exceeds the configured size limit."
                    if status == 413
                    else "Invalid Content-Length header."
                ),
                error_type="payload-too-large" if status == 413 else "bad-request",
                request=request,
            )
            await response(scope, receive, send)

        length = request.headers.get("content-length")
        if length is not None:
            try:
                announced = int(length)
            except ValueError:
                await reject(400)
                return
            if announced < 0:
                await reject(400)
                return
            if announced > self.limit:
                await reject(413)
                return
        buffer = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(buffer) + len(chunk) > self.limit:
                await reject(413)
                return
            buffer.extend(chunk)
            if not message.get("more_body", False):
                break
        body = bytes(buffer)
        buffer.clear()
        replayed = False

        async def replay() -> Message:
            nonlocal body, replayed
            if not replayed:
                replayed = True
                result: Message = {"type": "http.request", "body": body, "more_body": False}
                body = b""
                return result
            return await receive()

        await self.app(scope, replay, send)
