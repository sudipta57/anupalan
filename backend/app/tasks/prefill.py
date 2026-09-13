"""The context-prefill task — reading one label photograph to fill a form.

Thin, like ``tasks.scan``: everything but the wiring is in ``app.services.prefill``. This is the
worker's composition root for prefill, and it resolves the same OCR engine, rule pack and LLM
provider the pipeline uses, so a label read here and the same label read by the pipeline are read
by the same code.

**It never retries.** ``process_scan_task`` retries because a scan is work someone is owed: it was
accepted, it is recorded, and dropping it loses evidence. A prefill is a convenience with a person
waiting on it — by the time a retry ran they would have typed the fields themselves, and the
answer would arrive for a form that is already gone. So a failure is recorded as ``failed``, the
app stops polling, and the form stays what it always was: something you can fill in.

**The photographs are deleted as soon as they are read**, whatever happened. They are not evidence
— the scan's own full-resolution images are, and they arrive by a different path with a declared
hash (``services/prefill.py`` explains the split). Keeping them would mean holding pictures of a
stranger's shopping in object storage for no reason anyone could name.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.llm.provider import get_provider
from app.services.prefill import (
    PrefillRecord,
    get_store,
    read_label,
)
from app.services.rules.loader import active_pack
from app.services.storage import get_store as get_object_store
from app.services.vision.ocr import get_engine
from app.worker import celery_app

logger = logging.getLogger(__name__)


# Celery ships no type information for `task`; the body below is annotated.
@celery_app.task(bind=True, name="prefill.read", max_retries=0)  # type: ignore[untyped-decorator]
def read_label_task(
    self: Any, prefill_id: str, org_id: str, keys: list[str]
) -> dict[str, str]:
    """Read the photographs at ``keys`` and record what they suggest for the context form.

    Args:
        prefill_id: the id the client is polling.
        org_id: the org that asked. Part of the store key, so one org cannot collect another's
            prefill (CLAUDE.md §3.7).
        keys: object storage keys of the uploaded photographs, in capture order. All are read
            together — a pack's declarations are spread across its panels — and all are deleted
            before this returns.

    Returns:
        The id and the status recorded, for the log. The client reads the store, not this.
    """
    del self  # bound only so the task name appears in worker logs with its request id

    store = get_store()
    objects = get_object_store()

    try:
        reading = read_label(
            [objects.get_bytes(key) for key in keys],
            ocr=get_engine(),
            pack=active_pack(),
            llm=get_provider(),
        )
        record = PrefillRecord.of(prefill_id, reading)
    except Exception as exc:  # noqa: BLE001 — a prefill never fails a user's request
        logger.warning("prefill %s could not read %s: %s", prefill_id, keys, exc)
        record = PrefillRecord.failed(prefill_id)
    finally:
        # Every key, and one failure does not strand the rest.
        for key in keys:
            try:
                objects.delete(key)
            except Exception as exc:  # noqa: BLE001
                # Worth a log and nothing more: the bucket's lifecycle rule on the prefill/ prefix
                # is the backstop, and a scratch thumbnail surviving an hour is not an incident.
                logger.warning("could not delete prefill scratch object %s: %s", key, exc)

    store.put(org_id, record)
    return {"prefill_id": prefill_id, "status": record.status}


__all__ = ["read_label_task"]
