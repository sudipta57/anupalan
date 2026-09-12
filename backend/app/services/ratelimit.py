"""Rate limiting — B23, TRD NFR-01, architecture §10.

Two buckets, and both are needed for the same reason the OTP limiter needs two
(``services/auth/otp.py``): **per-IP alone lets one org exhaust the service from many addresses,
and per-org alone lets one address sweep many orgs.** A limit on either axis by itself is a limit
with a documented way round it.

The decision is here, as a function over a key. The HTTP part — reading the client address,
turning a refusal into a 429 with ``Retry-After`` — is in ``main.py``, so this module can be
tested without a request and reused by anything that needs a quota.

**Fixed window, not a sliding log.** A fixed window admits up to twice the limit across a window
boundary, and that is the right trade here: the purpose is to stop a runaway client and a cheap
denial of service, not to meter billing to the request. A sliding log costs a sorted set per key
and a round trip per member, which is real money at the request rate this is supposed to survive.

**Failing open is deliberate.** If Redis is unreachable the limiter admits the request and logs
it. A rate limiter that takes the API down when its own backing store blinks has converted a
partial outage into a total one, and this system's actual abuse risk — an inspector's phone
retrying a scan — is not what a hard fail protects against.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Decision:
    """The outcome of one check."""

    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    """Seconds until the window resets. Sent as ``Retry-After`` on a 429, because a client that is
    not told when to come back either gives up or hammers."""

    scope: str = ""
    """Which bucket refused — ``ip`` or ``org``. On the response so a caller can tell "you are
    sending too fast" from "your organisation is", which are different problems with different
    fixes."""


@runtime_checkable
class RateLimiter(Protocol):
    """Counts hits against a key inside a window."""

    name: str

    def hit(self, key: str, *, limit: int, window_seconds: int) -> Decision: ...


class InMemoryRateLimiter:
    """Per-process counters.

    Correct for a single worker and for tests, and **wrong across a fleet**: four uvicorn workers
    each admit the full limit, so the effective ceiling is four times what was configured. That is
    fine for local development and a demo, and it is why ``get_limiter`` refuses this backend in
    production rather than letting a deployment discover the multiplication under load.
    """

    name = "memory"

    def __init__(self) -> None:
        self._counts: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, *, limit: int, window_seconds: int) -> Decision:
        now = time.monotonic()
        with self._lock:
            count, expires = self._counts.get(key, (0, 0.0))
            if now >= expires:
                count, expires = 0, now + window_seconds

            count += 1
            self._counts[key] = (count, expires)

        retry_after = max(1, int(expires - now))
        return Decision(
            allowed=count <= limit,
            limit=limit,
            remaining=max(0, limit - count),
            retry_after=retry_after,
        )

    def reset(self) -> None:
        """Drop every counter. For tests; there is no operational reason to clear a limiter."""
        with self._lock:
            self._counts.clear()


class RedisRateLimiter:
    """Counters in Redis, so the limit is the limit across every instance.

    ``INCR`` then ``EXPIRE`` on the first hit, in one pipeline. The two commands are not atomic
    with each other and do not need to be: the worst case is a key that outlives its window by one
    round trip, which costs a few requests of accuracy and no correctness.
    """

    name = "redis"

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def _connect(self) -> Any | None:
        if self._client is None:
            try:
                import redis

                self._client = redis.Redis.from_url(
                    settings.REDIS_URL, socket_timeout=1.0, socket_connect_timeout=1.0
                )
            except Exception as exc:  # noqa: BLE001 — see the module docstring on failing open
                logger.warning("rate limiter has no Redis: %s", exc)
                return None
        return self._client

    def hit(self, key: str, *, limit: int, window_seconds: int) -> Decision:
        client = self._connect()
        if client is None:
            return Decision(allowed=True, limit=limit, remaining=limit, retry_after=0)

        try:
            pipeline = client.pipeline()
            pipeline.incr(key)
            pipeline.ttl(key)
            count, ttl = pipeline.execute()
            count = int(count)
            if int(ttl) < 0:
                client.expire(key, window_seconds)
                ttl = window_seconds
        except Exception as exc:  # noqa: BLE001 — fail open, loudly
            logger.warning("rate limiter degraded, admitting request: %s", exc)
            return Decision(allowed=True, limit=limit, remaining=limit, retry_after=0)

        return Decision(
            allowed=count <= limit,
            limit=limit,
            remaining=max(0, limit - count),
            retry_after=max(1, int(ttl)),
        )


class NullRateLimiter:
    """Admits everything. What ``RATE_LIMIT_ENABLED=false`` selects."""

    name = "off"

    def hit(self, key: str, *, limit: int, window_seconds: int) -> Decision:
        return Decision(allowed=True, limit=limit, remaining=limit, retry_after=0)


_REGISTRY: dict[str, Callable[[], RateLimiter]] = {
    "memory": InMemoryRateLimiter,
    "redis": RedisRateLimiter,
    "off": NullRateLimiter,
}

_ACTIVE: RateLimiter | None = None
_ACTIVE_LOCK = threading.Lock()


class UnknownLimiterError(LookupError):
    """The configured backend name is not registered."""


def get_limiter(name: str | None = None) -> RateLimiter:
    """Return the process-wide limiter.

    Cached, because an in-memory limiter rebuilt per request counts nothing, and a Redis client
    rebuilt per request opens a connection per request.

    Raises:
        UnknownLimiterError: unknown backend, or ``memory`` selected in production — which would
            silently multiply the configured ceiling by the worker count. Checked against ``ENV``
            rather than trusting the setting, the same way OTP echo is.
    """
    global _ACTIVE
    resolved = name or settings.RATE_LIMIT_BACKEND

    if not settings.RATE_LIMIT_ENABLED:
        resolved = "off"

    if resolved == "memory" and settings.ENV.lower() == "production":
        raise UnknownLimiterError(
            "the in-memory rate limiter counts per process, so with N workers the effective "
            "limit is N times the configured one. Use RATE_LIMIT_BACKEND=redis in production."
        )

    factory = _REGISTRY.get(resolved)
    if factory is None:
        raise UnknownLimiterError(
            f"no rate limiter registered as {resolved!r}; "
            f"available: {', '.join(sorted(_REGISTRY))}"
        )

    with _ACTIVE_LOCK:
        if _ACTIVE is None or _ACTIVE.name != resolved:
            _ACTIVE = factory()
    return _ACTIVE


def reset_limiter() -> None:
    """Drop the cached limiter. For tests and for a config reload."""
    global _ACTIVE
    with _ACTIVE_LOCK:
        _ACTIVE = None


def check(*, ip: str | None, org_id: str | None, bucket: str = "api") -> Decision:
    """Check both axes for one request, IP first.

    IP first because it is the axis that is present on every request, including the unauthenticated
    ones an attacker would prefer to use. The org bucket is checked only when a verified token
    named one — an unauthenticated flood is an IP problem, and charging it to an org would let
    anyone exhaust a tenant's quota by sending their id.
    """
    limiter = get_limiter()
    window = settings.RATE_LIMIT_WINDOW_SECONDS

    if ip:
        decision = limiter.hit(
            f"rl:{bucket}:ip:{ip}", limit=settings.RATE_LIMIT_PER_IP, window_seconds=window
        )
        if not decision.allowed:
            return Decision(
                allowed=False,
                limit=decision.limit,
                remaining=0,
                retry_after=decision.retry_after,
                scope="ip",
            )

    if org_id:
        decision = limiter.hit(
            f"rl:{bucket}:org:{org_id}",
            limit=settings.RATE_LIMIT_PER_ORG,
            window_seconds=window,
        )
        if not decision.allowed:
            return Decision(
                allowed=False,
                limit=decision.limit,
                remaining=0,
                retry_after=decision.retry_after,
                scope="org",
            )
        return Decision(
            allowed=True,
            limit=decision.limit,
            remaining=decision.remaining,
            retry_after=decision.retry_after,
            scope="org",
        )

    return Decision(
        allowed=True,
        limit=settings.RATE_LIMIT_PER_IP,
        remaining=settings.RATE_LIMIT_PER_IP,
        retry_after=0,
        scope="ip",
    )


__all__ = [
    "Decision",
    "InMemoryRateLimiter",
    "NullRateLimiter",
    "RateLimiter",
    "RedisRateLimiter",
    "UnknownLimiterError",
    "check",
    "get_limiter",
    "reset_limiter",
]
