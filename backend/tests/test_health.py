"""GET /health — the contract in CLAUDE.md §4.

    {"status": "ok", "db": "ok", "redis": "ok", "rulepack": "LM-2011-v1.0"}

The rule pack assertion is the load-bearing one. ``rulepack`` is read from the loaded pack's
``meta`` block, never from a literal in code, so this test failing means the pack on disk is not
the version the system thinks it is — and every finding is stamped with that version
(CLAUDE.md §3.6).

``db`` and ``redis`` are not asserted: this suite runs in CI with no Postgres and no Redis, and
/health answers 200 with a degraded status rather than failing closed. Dependency connectivity is
covered where it belongs, in the integration suite.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

EXPECTED_RULEPACK = "LM-2011-v1.0"


def test_health_returns_200_and_active_rulepack_version(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200

    body = response.json()
    assert body["rulepack"] == EXPECTED_RULEPACK
    assert set(body) == {"status", "db", "redis", "rulepack"}
    assert body["status"] in {"ok", "degraded"}
