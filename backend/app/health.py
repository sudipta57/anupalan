"""Dependency checks behind ``GET /health``.

Contract (CLAUDE.md §4):

    {"status": "ok", "db": "ok", "redis": "ok", "rulepack": "LM-2011-v1.0"}

The endpoint always answers 200, even with a dependency down — it is a report, not a gate.
A load balancer reads ``status``; a human reads the rest. ``status`` is ``ok`` only when every
dependency is ``ok``, otherwise ``degraded``.

``rulepack`` comes from the loaded pack's ``meta``, never from a literal, so a mismatch here
means the file on disk is not the pack you think it is.
"""

from __future__ import annotations

import logging
from typing import Literal

import redis
from pydantic import BaseModel, Field

from app import db
from app.config import settings
from app.services.rules.loader import RulePackError, active_pack

logger = logging.getLogger(__name__)

ComponentStatus = Literal["ok", "error"]


class HealthReport(BaseModel):
    """Response model for ``GET /health``."""

    status: Literal["ok", "degraded"] = Field(description="ok only when every component is ok")
    db: ComponentStatus
    redis: ComponentStatus
    rulepack: str = Field(
        description="Active rule pack as CODE-vVERSION, read from the pack's meta block",
        examples=["LM-2011-v1.0"],
    )


def _check_db() -> ComponentStatus:
    try:
        db.ping()
    except Exception as exc:  # noqa: BLE001 — a health probe reports, it never raises
        logger.warning("health: database unreachable: %s", exc)
        return "error"
    return "ok"


def _check_redis() -> ComponentStatus:
    try:
        client: redis.Redis = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2)
        try:
            client.ping()
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001 — a health probe reports, it never raises
        logger.warning("health: redis unreachable: %s", exc)
        return "error"
    return "ok"


def _check_rulepack() -> str:
    try:
        return active_pack().version_label
    except RulePackError as exc:
        logger.error("health: rule pack unavailable: %s", exc)
        return "error"


def check_health() -> HealthReport:
    """Probe every dependency and assemble the report."""
    db_status = _check_db()
    redis_status = _check_redis()
    rulepack = _check_rulepack()

    healthy = db_status == "ok" and redis_status == "ok" and rulepack != "error"
    return HealthReport(
        status="ok" if healthy else "degraded",
        db=db_status,
        redis=redis_status,
        rulepack=rulepack,
    )
