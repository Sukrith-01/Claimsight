"""
Global error handling for ClaimSight.

Day 11 scope: catch unhandled exceptions at the FastAPI level and return
structured JSON errors instead of raw stack traces. In production, a raw
500 with a Python traceback in the response body is both a security risk
(leaks internal paths and library versions) and useless to a client
integration team debugging why their upload failed.
"""

from __future__ import annotations

import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("claimsight")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Unhandled exception on %s %s: %s",
            request.method,
            request.url.path,
            traceback.format_exc(),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "detail": "An unexpected error occurred. If this persists, contact support.",
            },
        )
