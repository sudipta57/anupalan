"""Anupalan backend — FastAPI API and Celery worker over one codebase.

Two entrypoints, one package: ``app.main`` (API) and ``app.worker`` (worker). Both import
from ``app.services``, so pipeline code is written once. See CLAUDE.md §2.
"""
