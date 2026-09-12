"""The guarded fetcher — B29, plan §7. The only backend code that requests an outside URL.

Bulk listing (``services/listings.py``) refuses to fetch caller-supplied URLs at all, and calls the
alternative "a server-side request forgery with a CSV interface". The cross-check has to fetch, so
this module is built around that threat. Every property below is pinned by
``tests/test_web_fetch_guard.py``:

* **scheme and port** — ``https`` on 443 only; no userinfo in the URL;
* **host** — an exact registry domain for this brand or a subdomain of one, never an IP literal. The
  registry is reviewed data (``ingredients/sources-v1.yaml``); no caller input chooses a host;
* **address** — every address the name resolves to must be public. Loopback, private, link-local
  (including ``169.254.169.254``, the cloud metadata service), CGNAT, multicast, reserved and
  IPv4-mapped or 6to4-wrapped private addresses are refused, and one bad address in an answer
  refuses the whole host;
* **rebinding** — the name is resolved once per hop, and the connection is made to *that* address.
  The TLS certificate is still verified against the hostname, through the ``sni_hostname`` request
  extension, so pinning the address costs nothing in authentication;
* **redirects** — followed here, not by the HTTP client, and every hop re-runs every check;
* **size and type** — the body is streamed with a byte cap counted after decompression, and the
  content type must be on a per-call allow-list;
* **robots.txt** — honoured (RFC 9309): a 4xx means allow, a server error or no answer means
  disallow everything.

No cookies, no ``Authorization``, and a User-Agent that names the product.
"""

from __future__ import annotations

import hashlib
import ipaddress
import socket
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.config import settings

HTML_TYPES: tuple[str, ...] = ("text/html", "application/xhtml+xml")
XML_TYPES: tuple[str, ...] = ("application/xml", "text/xml")
TEXT_TYPES: tuple[str, ...] = ("text/plain",)

_REDIRECTS = frozenset({301, 302, 303, 307, 308})

RefusalReason = Literal[
    "scheme_not_allowed",
    "port_not_allowed",
    "host_not_allowed",
    "dns_failed",
    "address_not_allowed",
    "robots_disallowed",
    "too_many_redirects",
    "http_error",
    "too_large",
    "content_type_not_allowed",
    "timeout",
    "connection_failed",
]

FailureReason = Literal["timeout", "connection_failed"]

Resolver = Callable[[str], Sequence[str]]


class FetchRefusedError(Exception):
    """A URL was not fetched, and why. Refusal is a result, not a crash."""

    def __init__(
        self, reason: RefusalReason, detail: str = "", *, status: int | None = None
    ) -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason: RefusalReason = reason
        self.detail = detail
        self.status = status


class ResponseTooLargeError(Exception):
    """The body passed the byte cap. Raised by a transport while streaming."""


class TransportFailureError(Exception):
    """The request did not complete."""

    def __init__(self, reason: FailureReason, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason: FailureReason = reason


@dataclass(frozen=True)
class FetchLimits:
    timeout_seconds: float
    max_bytes: int
    max_redirects: int
    user_agent: str

    @classmethod
    def from_settings(cls) -> FetchLimits:
        return cls(
            timeout_seconds=settings.WEB_FETCH_TIMEOUT_SECONDS,
            max_bytes=settings.WEB_FETCH_MAX_BYTES,
            max_redirects=settings.WEB_FETCH_MAX_REDIRECTS,
            user_agent=settings.WEB_FETCH_USER_AGENT,
        )


@dataclass(frozen=True)
class RawResponse:
    """What a transport returns. Header names are lowercase."""

    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    sha256: str


class Transport(Protocol):
    """One GET to an already-validated address. Must not follow redirects or read past the cap."""

    def get(
        self,
        *,
        url: str,
        connect_ip: str,
        host: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_bytes: int,
    ) -> RawResponse: ...


class Fetcher(Protocol):
    """What discovery and the orchestrator need from a fetcher."""

    def fetch(
        self,
        url: str,
        *,
        allowed_domains: Sequence[str],
        accept: Sequence[str] = HTML_TYPES,
        check_robots: bool = True,
    ) -> FetchResult: ...

    def sitemaps_for(self, domain: str, *, allowed_domains: Sequence[str]) -> tuple[str, ...]: ...


# --------------------------------------------------------------------------- checks


def is_public_address(value: str) -> bool:
    """True only for a globally routable unicast address."""
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False

    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return is_public_address(str(address.ipv4_mapped))
        if address.sixtofour is not None and not is_public_address(str(address.sixtofour)):
            return False
        if address.teredo is not None:
            return False

    return address.is_global and not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def host_allowed(host: str, domains: Sequence[str]) -> bool:
    """True when ``host`` is one of ``domains`` or a subdomain of one."""
    host = host.rstrip(".").lower()
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def system_resolver(host: str) -> list[str]:
    """Every address the system resolver returns for ``host``."""
    answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(answer[4][0]) for answer in answers))


# --------------------------------------------------------------------------- the fetcher


class GuardedFetcher:
    """Fetches registry pages under every check in the module docstring."""

    def __init__(
        self,
        *,
        limits: FetchLimits,
        resolver: Resolver = system_resolver,
        transport: Transport | None = None,
    ) -> None:
        self._limits = limits
        self._resolver = resolver
        self._transport: Transport = transport if transport is not None else HttpxTransport()
        self._robots: dict[str, RobotFileParser | None] = {}

    @property
    def robots_agent(self) -> str:
        """The product token robots.txt rules are matched against."""
        return self._limits.user_agent.split("/", 1)[0].split()[0]

    def fetch(
        self,
        url: str,
        *,
        allowed_domains: Sequence[str],
        accept: Sequence[str] = HTML_TYPES,
        check_robots: bool = True,
    ) -> FetchResult:
        """Fetch ``url``, or raise ``FetchRefusedError`` saying which check stopped it."""
        current = url
        for _hop in range(self._limits.max_redirects + 1):
            host, connect_ip = self._validate(current, allowed_domains)
            if check_robots and not self._robots_allow(current, host, allowed_domains):
                raise FetchRefusedError("robots_disallowed", current)

            response = self._get(current, host, connect_ip)
            headers = {name.lower(): value for name, value in response.headers.items()}

            if response.status in _REDIRECTS:
                location = headers.get("location", "").strip()
                if not location:
                    raise FetchRefusedError(
                        "http_error", "redirect without a Location", status=response.status
                    )
                current = urljoin(current, location)
                continue

            if response.status != 200:
                raise FetchRefusedError("http_error", current, status=response.status)
            if len(response.body) > self._limits.max_bytes:
                raise FetchRefusedError("too_large", current)

            content_type = headers.get("content-type", "")
            media_type = content_type.split(";", 1)[0].strip().lower()
            if media_type not in accept:
                raise FetchRefusedError(
                    "content_type_not_allowed", content_type or "no content type"
                )

            return FetchResult(
                url=url,
                final_url=current,
                status=response.status,
                content_type=content_type,
                body=response.body,
                sha256=hashlib.sha256(response.body).hexdigest(),
            )

        raise FetchRefusedError("too_many_redirects", url)

    def sitemaps_for(self, domain: str, *, allowed_domains: Sequence[str]) -> tuple[str, ...]:
        """Sitemap URLs a host's robots.txt declares; empty when it names none or is unreadable."""
        parser = self._robots_for(domain.lower(), allowed_domains)
        if parser is None:
            return ()
        return tuple(parser.site_maps() or ())

    # ---- internals

    def _validate(self, url: str, allowed_domains: Sequence[str]) -> tuple[str, str]:
        parts: SplitResult = urlsplit(url)
        if parts.scheme.lower() != "https":
            raise FetchRefusedError("scheme_not_allowed", url)
        try:
            port = parts.port
        except ValueError as exc:
            raise FetchRefusedError("port_not_allowed", url) from exc
        if port not in (None, 443):
            raise FetchRefusedError("port_not_allowed", url)
        if parts.username is not None or parts.password is not None:
            raise FetchRefusedError("host_not_allowed", "credentials in the URL")

        host = (parts.hostname or "").rstrip(".").lower()
        if not host:
            raise FetchRefusedError("host_not_allowed", url)
        if _is_ip_literal(host):
            raise FetchRefusedError(
                "host_not_allowed", f"{host} is an address, not a registered domain"
            )
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise FetchRefusedError("host_not_allowed", url) from exc
        if not host_allowed(host, allowed_domains):
            raise FetchRefusedError("host_not_allowed", f"{host} is not registered for this brand")

        try:
            addresses = list(self._resolver(host))
        except OSError as exc:
            raise FetchRefusedError("dns_failed", host) from exc
        if not addresses:
            raise FetchRefusedError("dns_failed", host)

        refused = [address for address in addresses if not is_public_address(address)]
        if refused:
            raise FetchRefusedError("address_not_allowed", f"{host} resolves to {refused[0]}")
        return host, addresses[0]

    def _get(self, url: str, host: str, connect_ip: str) -> RawResponse:
        headers = {
            "User-Agent": self._limits.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8",
        }
        try:
            return self._transport.get(
                url=url,
                connect_ip=connect_ip,
                host=host,
                headers=headers,
                timeout_seconds=self._limits.timeout_seconds,
                max_bytes=self._limits.max_bytes,
            )
        except ResponseTooLargeError as exc:
            raise FetchRefusedError("too_large", url) from exc
        except TransportFailureError as exc:
            raise FetchRefusedError(exc.reason, url) from exc

    def _robots_allow(self, url: str, host: str, allowed_domains: Sequence[str]) -> bool:
        parser = self._robots_for(host, allowed_domains)
        return parser is not None and parser.can_fetch(self.robots_agent, url)

    def _robots_for(self, host: str, allowed_domains: Sequence[str]) -> RobotFileParser | None:
        """The parsed robots.txt for a host, cached. ``None`` means disallow everything."""
        if host in self._robots:
            return self._robots[host]

        parser: RobotFileParser | None
        try:
            result = self.fetch(
                f"https://{host}/robots.txt",
                allowed_domains=allowed_domains,
                accept=TEXT_TYPES,
                check_robots=False,
            )
        except FetchRefusedError as exc:
            if exc.reason == "http_error" and exc.status is not None and 400 <= exc.status < 500:
                parser = _allow_everything()
            elif exc.reason == "content_type_not_allowed":
                # A soft 404 — an HTML page served at /robots.txt — is no robots file at all.
                parser = _allow_everything()
            else:
                parser = None
        else:
            parser = RobotFileParser()
            parser.parse(result.body.decode("utf-8", errors="replace").splitlines())

        self._robots[host] = parser
        return parser


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _allow_everything() -> RobotFileParser:
    parser = RobotFileParser()
    parser.parse([])
    return parser


# --------------------------------------------------------------------------- the httpx adapter


class HttpxTransport:
    """``Transport`` over httpx, connecting to the validated address.

    The request URL carries the IP; the ``Host`` header and the ``sni_hostname`` extension carry the
    hostname, so the server sees an ordinary request and the certificate is verified against the
    name that was checked. ``trust_env=False`` keeps proxy variables and ``.netrc`` credentials out.
    """

    def __init__(self, *, mock: httpx.BaseTransport | None = None) -> None:
        self._mock = mock

    def get(
        self,
        *,
        url: str,
        connect_ip: str,
        host: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_bytes: int,
    ) -> RawResponse:
        parts = urlsplit(url)
        netloc = f"[{connect_ip}]" if ":" in connect_ip else connect_ip
        target = urlunsplit(("https", netloc, parts.path or "/", parts.query, ""))
        deadline = time.monotonic() + timeout_seconds

        try:
            with httpx.Client(
                transport=self._mock,
                timeout=httpx.Timeout(timeout_seconds),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                request = client.build_request(
                    "GET",
                    target,
                    headers={**headers, "Host": host},
                    extensions={"sni_hostname": host},
                )
                response = client.send(request, stream=True)
                try:
                    declared = response.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > max_bytes:
                        raise ResponseTooLargeError(f"{url} declares {declared} bytes")

                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise ResponseTooLargeError(f"{url} passed {max_bytes} bytes")
                        if time.monotonic() > deadline:
                            raise TransportFailureError("timeout", url)
                        chunks.append(chunk)

                    return RawResponse(
                        status=response.status_code,
                        headers={name.lower(): value for name, value in response.headers.items()},
                        body=b"".join(chunks),
                    )
                finally:
                    response.close()
        except httpx.TimeoutException as exc:
            raise TransportFailureError("timeout", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise TransportFailureError("connection_failed", str(exc)) from exc


__all__ = [
    "HTML_TYPES",
    "TEXT_TYPES",
    "XML_TYPES",
    "FetchLimits",
    "FetchRefusedError",
    "FetchResult",
    "Fetcher",
    "GuardedFetcher",
    "HttpxTransport",
    "RawResponse",
    "RefusalReason",
    "Resolver",
    "ResponseTooLargeError",
    "Transport",
    "TransportFailureError",
    "host_allowed",
    "is_public_address",
    "system_resolver",
]
