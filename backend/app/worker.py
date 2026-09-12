"""Celery entrypoint.

    celery -A app.worker worker -l info

The worker is **not** a separate project (CLAUDE.md §2). It imports from ``app.services``, so
pipeline code is written once and the API and the worker cannot drift.

Scans take seconds and can fail, which is why this is Celery and not FastAPI BackgroundTasks —
retries, visibility and a dead-letter path (docs/01-architecture.md §9).

The broker is managed Redis (Redis Cloud) over TLS. Celery does **not** infer TLS from a
``rediss://`` URL — it needs ``broker_use_ssl`` set explicitly, or the connection fails at
connect time rather than at startup. That is wired below off the URL scheme, so switching
between a TLS and a plaintext Redis is a config change and not a code change.

Scaffolding note: no task is registered yet. ``process_scan`` — the ten-stage pipeline of
docs/01-architecture.md §5 — arrives in P2.3.
"""

from __future__ import annotations

import ssl

from celery import Celery

from app.config import settings

celery_app = Celery(
    settings.APP_NAME,
    broker=settings.celery_broker,
    backend=settings.celery_backend,
    # Task modules are imported here as they land. app.services.* is the only place
    # pipeline code may live, so the worker and the API share one implementation.
    include=[],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # A scan must survive a worker restart mid-job (TRD NFR-04).
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=10,
    task_max_retries=3,
)

if settings.redis_is_tls:
    # Redis Cloud terminates TLS with a publicly trusted certificate, so the cert is verified
    # rather than ignored. Both the broker and the result backend need telling separately.
    _tls = {"ssl_cert_reqs": ssl.CERT_REQUIRED}
    celery_app.conf.broker_use_ssl = _tls
    celery_app.conf.redis_backend_use_ssl = _tls

__all__ = ["celery_app"]
