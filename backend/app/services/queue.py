"""Handing work to the worker (B14).

One function, and a small one, but it earns its own module for two reasons.

**The API must not import the task at module scope.** ``app.tasks.scan`` is the worker's
composition root: importing it resolves the object store, the OCR engine and the LLM provider.
The API needs none of those, and a misconfigured OCR engine must not stop the API starting. The
import happens inside the call.

**Enqueueing has to be substitutable in a test.** FR-20 requires ``submit`` to return 202 inside
300 ms, and the test that checks it must not need a broker. Routers take the enqueuer as a
dependency, so a test overrides it with a function that records the call.

The task id is returned when the broker gives one. It is useful in a log and meaningless to the
client, which polls ``GET /v1/scans/{id}`` for status — the scan row is the source of truth about
a scan, not a Celery result.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def enqueue_scan(scan_id: str) -> str | None:
    """Queue a scan for processing. Returns the task id, or None if the broker did not give one.

    Raises whatever the broker raises. A submit that could not enqueue must fail loudly: answering
    202 for work nobody will do leaves a scan queued forever and a user waiting for a result that
    is not coming.
    """
    from app.tasks.scan import process_scan_task

    result = process_scan_task.delay(scan_id)
    task_id = getattr(result, "id", None)
    logger.info("queued scan %s as task %s", scan_id, task_id)
    return str(task_id) if task_id is not None else None


__all__ = ["enqueue_scan"]
