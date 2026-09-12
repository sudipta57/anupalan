"""Pipeline and domain services — the code the API and the Celery worker share.

Everything under this package is held to a stricter standard than the rest of the backend
(CLAUDE.md §5): ``mypy --strict`` and full annotations, because this is where a wrong
millimetre is indistinguishable from a right one. ``services/rules/`` and ``services/vision/``
additionally carry an 80% coverage floor.
"""
