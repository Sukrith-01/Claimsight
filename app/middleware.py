"""
Centralized error handling for the API.

Day 11: the unglamorous 80% of real deployment work. Every endpoint
already handles its own expected errors (TenantNotFoundError, bad file
types, etc.), but UNEXPECTED failures — a corrupted PDF that crashes
PyMuPDF, a ChromaDB internal error, an unhandled exception in the
confidence scorer — currently produce raw 500s with tracebacks that
leak implementation details to the caller. This middleware catches those
and returns a structured, safe error response instead.
"""

from __future__ import annotations

import logging
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("claimsight")


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            logger.error(
                "Unhandled exception on %s %s: %s\n%s",
                request.method,
                request.url.path,
                exc,
                traceback.format_exc(),
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_server_error",
                    "detail": "An unexpected error occurred. This has been logged.",
                },
            )
