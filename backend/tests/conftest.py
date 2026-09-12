"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A TestClient over the real app, with exception handlers active.

    ``raise_server_exceptions=False`` so handler behaviour is what the client sees — an
    unhandled error must surface as the error envelope, not as a propagated exception.
    """
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
