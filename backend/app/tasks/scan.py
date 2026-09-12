"""The scan processing task.

    celery -A app.worker worker -l info

Deliberately thin. Everything this does beyond wiring is in ``app.services.pipeline``, which is
importable and testable with no broker, no database and no network — the golden-file test in
``tests/test_pipeline.py`` runs the whole ten-stage pipeline that way.

This module is the composition root for the worker: it is where the database, object storage, the
OCR engine, the rule pack and the LLM are resolved and handed to a function that has no idea any
of them are configurable. Resolving them at import time rather than inside the task is deliberate
— a misconfigured worker should fail when it starts, in front of whoever started it, not on the
first scan of the day.

``acks_late`` is set on the app (TRD NFR-04), so a worker killed mid-scan has its message
redelivered and the scan reprocessed. ``process_scan`` recomputes from the same inputs and
``ScanStoreAdapter`` recognises an identical result by its findings digest, so a redelivery
records nothing new rather than duplicating a verdict set.
"""

from __future__ import annotations

from typing import Any

from app.db import session_scope
from app.repositories.scans import ScanStoreAdapter
from app.services.llm.provider import get_provider
from app.services.pipeline import process_scan
from app.services.rules.loader import active_pack
from app.services.storage import get_store
from app.services.vision.ocr import get_engine
from app.worker import celery_app


@celery_app.task(bind=True, name="scan.process", max_retries=3)
def process_scan_task(self: Any, scan_id: str) -> dict[str, str]:
    """Process one scan. Retries on an unexpected error, with the app's backoff."""
    try:
        with session_scope() as session:
            outcome = process_scan(
                scan_id,
                store=ScanStoreAdapter(session),
                storage=get_store(),
                ocr=get_engine(),
                pack=active_pack(),
                llm=get_provider(),
            )
    except Exception as exc:
        raise self.retry(exc=exc) from exc

    return {"scan_id": outcome.scan_id, "status": outcome.status}


__all__ = ["process_scan_task"]
