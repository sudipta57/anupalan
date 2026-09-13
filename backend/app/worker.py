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

``app.tasks.scan`` registers ``process_scan``, the ten-stage pipeline of
docs/01-architecture.md §5. The task itself is a wrapper; the logic is in
``app.services.pipeline`` so it runs without a broker.
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
    include=["app.tasks.prefill", "app.tasks.scan"],
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
    # ---- Redis connection budget.
    #
    # Redis Cloud's shared tiers cap *total* clients across everything that connects, and this
    # project connects from more than one place: the API, the worker's main process, and each
    # forked child. Celery's defaults are sized for a Redis you own — `broker_pool_limit` alone is
    # 10 — and two developers running a worker each is enough to exhaust the cap. What that looks
    # like is not an error anyone would connect to the cause: scans sit in `processing`, the worker
    # burns no CPU, and every new connection is refused with "max number of clients reached",
    # including the one you open to find out why.
    #
    # A small pool costs nothing here. The worker runs `--concurrency=2` with
    # `worker_prefetch_multiplier=1`, so it is never usefully holding ten broker connections; the
    # pool just sizes how many stay open between tasks.
    broker_pool_limit=2,
    redis_max_connections=4,
    broker_transport_options={"max_connections": 4},
)

if settings.redis_is_tls:
    # Redis Cloud terminates TLS with a publicly trusted certificate, so the cert is verified
    # rather than ignored. Both the broker and the result backend need telling separately.
    _tls = {"ssl_cert_reqs": ssl.CERT_REQUIRED}
    celery_app.conf.broker_use_ssl = _tls
    celery_app.conf.redis_backend_use_ssl = _tls

__all__ = ["celery_app"]
