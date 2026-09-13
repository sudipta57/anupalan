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
from app.routers import admin as admin_router
from app.routers import auth as auth_router
from app.routers import dashboard as dashboard_router
from app.routers import prefill as prefill_router
from app.routers import products as products_router
from app.routers import reports as reports_router
from app.routers import sahayak as sahayak_router
from app.routers import scans as scans_router
from app.schemas.base import BodyOrgIdError
from app.services import ratelimit
from app.services.auth.rbac import PermissionDeniedError
from app.services.auth.tokens import TokenError, read_access_token

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


# --------------------------------------------------------------------- rate limiting


@app.middleware("http")
async def rate_limit(request: Request, call_next: Any) -> Any:
    """Refuse a caller who is sending too fast, on both the IP and the org axis (NFR-01, B23).

    Wiring, not logic: the decision is ``services/ratelimit.check`` and this maps it onto HTTP.
    It is middleware rather than a dependency because the per-IP half has to cover requests that
    never reach a handler — an unauthenticated flood at ``/v1/auth/otp/request`` is exactly the
    traffic a per-endpoint dependency would miss.

    The token is read here as well as in ``current_principal``, through the same function, so the
    org bucket exists for authenticated traffic. A token that does not verify is simply not an
    org: an unauthenticated flood is charged to its address, never to the tenant whose id it
    claimed, or anyone could exhaust another org's quota by guessing one.
    """
    path = request.url.path
    if any(path.startswith(prefix) for prefix in settings.RATE_LIMIT_EXEMPT_PATHS):
        return await call_next(request)

    org_id: str | None = None
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        try:
            org_id = str(read_access_token(authorization.split(" ", 1)[1].strip()).org_id)
        except TokenError:
            org_id = None

    client = request.client
    decision = ratelimit.check(ip=client.host if client else None, org_id=org_id)

    if not decision.allowed:
        return error_response(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="rate_limited",
            message=(
                f"too many requests for this {decision.scope}. "
                f"Retry in {decision.retry_after} seconds."
            ),
            details={"scope": decision.scope, "limit": decision.limit},
            headers={
                "Retry-After": str(decision.retry_after),
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": "0",
            },
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(decision.limit)
    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
    return response


# --------------------------------------------------------------------- error envelope


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the single error envelope every endpoint returns (TRD NFR-07).

    The shape is fixed: ``{"error": {"code", "message", "details"}}``. ``mobile/`` parses
    exactly this, so do not add or rename top-level keys.

    ``headers`` exists because some errors are not only a body. A 401 has to carry
    ``WWW-Authenticate`` to be a well-formed 401, and a 429 will want ``Retry-After``; an envelope
    that dropped them would turn a protocol-correct response into a merely informative one.
    """
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}},
        headers=headers,
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
        headers=getattr(exc, "headers", None),
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


@app.exception_handler(BodyOrgIdError)
async def body_org_id_handler(request: Request, exc: BodyOrgIdError) -> JSONResponse:
    """Render a body-supplied ``org_id`` as 400.

    A request that tries to name its own tenant is rejected outright rather than having the field
    quietly dropped. Dropping it would be just as safe and would hide the attempt — and an attempt
    to set ``org_id`` is worth seeing in a log.
    """
    return error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        code="org_id_not_accepted",
        message=str(exc),
        details={"field": exc.field},
    )


@app.exception_handler(PermissionDeniedError)
async def permission_denied_handler(
    request: Request, exc: PermissionDeniedError
) -> JSONResponse:
    """Render an RBAC refusal as 403 in the envelope.

    403 and not 404, deliberately. The 404-not-403 rule (CLAUDE.md §3.7) is about *another org's*
    rows, where the existence of the row is itself the secret. Inside your own org, being told
    your role is insufficient reveals nothing an attacker could not guess and is the only way a
    user learns what to ask their administrator for.
    """
    return error_response(
        status_code=status.HTTP_403_FORBIDDEN,
        code="permission_denied",
        message=str(exc),
        details={"permission": exc.permission.value, "role": exc.role},
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


# --------------------------------------------------------------------------- routers

# Registered as they land. Everything a router needs beyond validation and response shaping lives
# in app/services/ so the Celery worker shares it (CLAUDE.md §2).
app.include_router(auth_router.router)
app.include_router(scans_router.router)
app.include_router(admin_router.router)
app.include_router(dashboard_router.router)
app.include_router(sahayak_router.router)
app.include_router(products_router.router)
app.include_router(reports_router.router)
app.include_router(prefill_router.router)


__all__ = ["app", "error_response"]
