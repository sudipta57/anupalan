"""The scan processing task.

    celery -A app.worker worker -l info

Deliberately thin. Everything this does beyond wiring is in ``app.services.pipeline``, which is
importable and testable with no broker, no database and no network — the golden-file test in
``tests/test_pipeline_golden.py`` runs the whole ten-stage pipeline that way.

``acks_late`` is set on the app (TRD NFR-04), so a worker killed mid-scan has its message
redelivered and the scan reprocessed. ``process_scan`` recomputes from the same inputs and
replaces the previous outcome, so a redelivery is safe rather than duplicating findings.
"""

from __future__ import annotations

from typing import Any

from app.worker import celery_app


@celery_app.task(bind=True, name="scan.process", max_retries=3)
def process_scan_task(self: Any, scan_id: str) -> dict[str, str]:
    """Process one scan. Retries on an unexpected error, with the app's backoff."""
    # The concrete ScanStore is the database adapter from B12. Until that lands this task has no
    # store to hand the pipeline, which is why it is resolved here rather than at import time.
    from app.repositories.scans import ScanRepository  # type: ignore[import-not-found]
    from app.services.llm.provider import get_provider
    from app.services.pipeline import process_scan
    from app.services.rules.loader import active_pack
    from app.services.storage import get_store
    from app.services.vision.ocr import get_engine

    try:
        outcome = process_scan(
            scan_id,
            store=ScanRepository(),
            storage=get_store(),
            ocr=get_engine(),
            pack=active_pack(),
            llm=get_provider(),
        )
    except Exception as exc:
        raise self.retry(exc=exc) from exc

    return {"scan_id": outcome.scan_id, "status": outcome.status}


__all__ = ["process_scan_task"]
