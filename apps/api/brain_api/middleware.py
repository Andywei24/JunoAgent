"""HTTP middleware: correlation-ID + request logging."""

from __future__ import annotations

import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from brain_api.logging_setup import bind_request_context, clear_request_context, get_logger
from brain_core.ids import new_correlation_id, new_trace_id

_log = get_logger("brain_api.http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach correlation + trace IDs to every request and log timing."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        correlation_id = request.headers.get("x-correlation-id") or new_correlation_id()
        trace_id = request.headers.get("x-trace-id") or new_trace_id()

        bind_request_context(correlation_id=correlation_id, trace_id=trace_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            _log.exception(
                "http.request.error", method=request.method, path=request.url.path
            )
            clear_request_context()
            raise

        duration_ms = (time.perf_counter() - started) * 1000.0
        response.headers["x-correlation-id"] = correlation_id
        response.headers["x-trace-id"] = trace_id
        _log.info(
            "http.request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        clear_request_context()
        return response
