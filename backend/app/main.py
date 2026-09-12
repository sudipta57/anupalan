"""FastAPI entrypoint for the Anupalan API.

Wires CORS, the one error envelope every response must use (TRD NFR-07), and ``GET /health``.
Feature routers are registered here as they land; see ``app/routers/``.

Scaffolding note: no business logic belongs in this module. The pipeline lives in
``app/services/`` so the Celery worker can import it (CLAUDE.md §2).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.health import HealthReport, check_health

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Anupalan API",
    version="0.1.0",
    summary="Compliance engine for packaged commodities in India",
    description=(
        "Advisory pre-audit tool. Output is not a certification and carries no legal force. "
        "The rule pack is an engineering transcription pending legal review."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------- error envelope


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    """Build the single error envelope every endpoint returns (TRD NFR-07).

    The shape is fixed: ``{"error": {"code", "message", "details"}}``. ``mobile/`` parses
    exactly this, so do not add or rename top-level keys.
    """
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Render HTTP errors — including 404s raised for cross-org access — in the envelope."""
    detail = exc.detail
    message = detail if isinstance(detail, str) else "Request failed"
    return error_response(
        status_code=exc.status_code,
        code=f"http_{exc.status_code}",
        message=message,
        details=None if isinstance(detail, str) else detail,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Render request-validation failures in the envelope, keeping per-field detail."""
    return error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="validation_error",
        message="Request validation failed",
        details=exc.errors(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all, so an unexpected failure still returns the envelope and never a stack trace."""
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal_error",
        message="An unexpected error occurred",
        details=None,
    )


# --------------------------------------------------------------------- health


@app.get(
    "/health",
    response_model=HealthReport,
    summary="Liveness and dependency check",
    tags=["meta"],
)
async def health() -> HealthReport:
    """Report process health plus the state of each dependency and the active rule pack.

    ``rulepack`` is read from the loaded pack's ``meta`` (never hardcoded), so this endpoint
    doubles as proof that the pack on disk parsed and is the version you expect.
    """
    return check_health()


__all__ = ["app", "error_response"]
