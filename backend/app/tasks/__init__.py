"""Celery task bindings.

Each module here is a thin wrapper over a function in ``app/services/``. Task modules hold no
pipeline logic: the worker and the API import the same service code, so the two cannot drift
(CLAUDE.md §2), and the pipeline stays testable without a broker.
"""
