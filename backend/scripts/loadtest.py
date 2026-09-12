"""Load test — B23, TRD NFR-01.

    python -m scripts.loadtest --base-url https://api.example --image ../eval/e1/sample.jpg \
        --phone +919000000001 --concurrency 50 --total 50

NFR-01 is **capture to findings**, p50 ≤ 10 s and p95 ≤ 20 s at 50 concurrent scans. So this
drives the whole path a phone drives — create, upload to the presigned URL, submit, poll until the
verdict exists — and times it from the first call to the moment findings are readable. Timing the
API's own handlers instead would measure the part of the system that was never the slow part: the
worker does the OCR, the homography and the metrology.

**The first request is included in the percentiles, and reported separately as well.**
``01-architecture.md`` §11 charges Neon's scale-to-zero cold start against NFR-01, so excluding it
would be measuring a system that has already been warmed up by somebody else — which is not the
system an inspector opens at nine in the morning.

This is a driver, not a harness: it needs a deployment, a worker, and one real capture with a
marker in it. Run it against staging, never against a database anybody is relying on — it creates
real scans in the org the phone number belongs to.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.common import percent, print_header


@dataclass
class Attempt:
    """One scan, start to verdict."""

    index: int
    seconds: float
    status: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "complete" and self.error is None


async def sign_in(client: Any, base_url: str, phone: str) -> str:
    """OTP request + verify. Needs ``OTP_ECHO_IN_RESPONSE`` on the target, which is refused in
    production — so this runs against staging, which is the intent anyway."""
    requested = await client.post(f"{base_url}/v1/auth/otp/request", json={"phone": phone})
    requested.raise_for_status()
    body = requested.json()
    code = body.get("code")
    if not code:
        raise SystemExit(
            "the target did not echo the OTP, so this script cannot sign in. Set "
            "OTP_ECHO_IN_RESPONSE=true on a staging deployment; it is refused in production."
        )

    verified = await client.post(
        f"{base_url}/v1/auth/otp/verify",
        json={"request_id": body["request_id"], "code": code},
    )
    verified.raise_for_status()
    return str(verified.json()["access"])


async def one_scan(
    client: Any,
    base_url: str,
    token: str,
    image: bytes,
    sha256: str,
    index: int,
    *,
    timeout_s: float,
    poll_s: float,
) -> Attempt:
    """Create, upload, submit, and poll until the findings exist."""
    headers = {"Authorization": f"Bearer {token}"}
    started = time.perf_counter()

    try:
        created = await client.post(
            f"{base_url}/v1/scans",
            headers={**headers, "Idempotency-Key": f"loadtest-{index}-{started}"},
            json={
                "marker_type": "aruco_4x4_50",
                "marker_mm": 40.0,
                "profile": {"surface": "printed"},
                "assets": [
                    {
                        "content_type": "image/jpeg",
                        "size_bytes": len(image),
                        "sha256": sha256,
                    }
                ],
            },
        )
        created.raise_for_status()
        body = created.json()
        scan_id = body["scan_id"]

        upload = body["uploads"][0]
        put = await client.put(upload["url"], content=image, headers=upload.get("headers") or {})
        put.raise_for_status()

        submitted = await client.post(f"{base_url}/v1/scans/{scan_id}/submit", headers=headers)
        submitted.raise_for_status()

        deadline = started + timeout_s
        while time.perf_counter() < deadline:
            findings = await client.get(
                f"{base_url}/v1/scans/{scan_id}/findings", headers=headers
            )
            if findings.status_code == 200:
                return Attempt(index, time.perf_counter() - started, "complete")

            scan = await client.get(f"{base_url}/v1/scans/{scan_id}", headers=headers)
            state = scan.json().get("status") if scan.status_code == 200 else "unknown"
            if state in {"failed", "no_marker"}:
                # Not a timing failure. A no-marker capture completes correctly and quickly and
                # would flatter the percentiles if it were counted as a successful scan.
                return Attempt(index, time.perf_counter() - started, state)

            await asyncio.sleep(poll_s)

        return Attempt(index, time.perf_counter() - started, "timeout")
    except Exception as exc:  # noqa: BLE001 — one failed scan is a data point, not a crashed run
        return Attempt(index, time.perf_counter() - started, "error", error=str(exc))


async def run(args: argparse.Namespace) -> list[Attempt]:
    import hashlib

    import httpx

    image: bytes = args.image_bytes
    sha256 = hashlib.sha256(image).hexdigest()

    limits = httpx.Limits(max_connections=args.concurrency * 2)
    async with httpx.AsyncClient(timeout=args.timeout, limits=limits) as client:
        token = await sign_in(client, args.base_url, args.phone)

        gate = asyncio.Semaphore(args.concurrency)

        async def bounded(index: int) -> Attempt:
            async with gate:
                return await one_scan(
                    client,
                    args.base_url,
                    token,
                    image,
                    sha256,
                    index,
                    timeout_s=args.timeout,
                    poll_s=args.poll,
                )

        return list(await asyncio.gather(*(bounded(index) for index in range(args.total))))


def quantile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
    return ordered[index]


def report(attempts: Sequence[Attempt]) -> bool:
    """Print the numbers and return whether NFR-01 was met."""
    successes = [attempt for attempt in attempts if attempt.ok]
    latencies = [attempt.seconds for attempt in successes]

    print(f"scans: {len(attempts)}   completed: {len(successes)}")
    if not latencies:
        print("no scan completed — nothing to report against NFR-01")
        return False

    p50 = quantile(latencies, 0.50)
    p95 = quantile(latencies, 0.95)
    print(
        f"capture to findings — p50 {p50:.1f} s  |  p95 {p95:.1f} s  |  "
        f"p99 {quantile(latencies, 0.99):.1f} s  |  max {max(latencies):.1f} s"
    )
    print(f"mean {statistics.fmean(latencies):.1f} s   first (cold) {attempts[0].seconds:.1f} s")

    failures: dict[str, int] = {}
    for attempt in attempts:
        if not attempt.ok:
            failures[attempt.status] = failures.get(attempt.status, 0) + 1
    if failures:
        print(
            "not completed: "
            + ", ".join(f"{status} {count}" for status, count in sorted(failures.items()))
        )

    met = p50 <= 10.0 and p95 <= 20.0
    print()
    print(
        f"NFR-01: p50 <=10 s and p95 <=20 s at {len(attempts)} scans — "
        f"{'PASS' if met else 'FAIL'}"
    )
    print(
        f"completion rate {percent(len(successes), len(attempts)):.0f}% "
        "(the cold start is included in the percentiles above, per architecture §11)"
    )
    return met


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NFR-01 load test — capture to findings")
    parser.add_argument("--base-url", required=True, help="e.g. https://staging.example")
    parser.add_argument("--image", type=Path, required=True, help="one capture with a marker in it")
    parser.add_argument("--phone", required=True, help="a user on the target deployment")
    parser.add_argument("--concurrency", type=int, default=50, help="NFR-01 says 50")
    parser.add_argument("--total", type=int, default=50)
    parser.add_argument("--timeout", type=float, default=120.0, help="per-scan ceiling, seconds")
    parser.add_argument("--poll", type=float, default=1.0, help="findings poll interval, seconds")
    args = parser.parse_args(argv)

    if not args.image.is_file():
        print(f"no image at {args.image}", file=sys.stderr)
        return 2

    # Read before the event loop starts: an async function doing blocking file I/O stalls every
    # other scan in flight, which is exactly what this script is trying to measure.
    args.image_bytes = args.image.read_bytes()

    print_header(
        "NFR-01 load test",
        corpus=args.image,
        extra=[f"target: {args.base_url}   concurrency: {args.concurrency}"],
    )

    attempts = asyncio.run(run(args))
    return 0 if report(attempts) else 1


if __name__ == "__main__":  # pragma: no cover — module entrypoint
    sys.exit(main())
