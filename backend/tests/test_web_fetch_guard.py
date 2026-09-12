"""The guarded fetcher — B29, plan §7.

This is the one place in the backend that requests a URL it did not construct itself. Bulk listing
(B21) refuses to fetch caller-supplied URLs outright, calling it "a server-side request forgery
with a CSV interface"; this module has to fetch, so every property that keeps it from becoming one
is pinned here, each with the attack it closes:

* only ``https`` on 443, only hosts in the reviewed registry for this brand;
* every resolved address public — no loopback, private, link-local (the cloud metadata address),
  CGNAT, multicast, reserved or IPv4-mapped-private;
* the connection goes to the address that was validated, so a DNS answer that changes between check
  and connect (rebinding) cannot redirect it;
* every redirect hop re-runs every check;
* a byte cap, a content-type allow-list, and robots.txt honoured.

No test here opens a socket: the resolver and the transport are injected, and ``no_network`` fails
any path that falls back to the real ones.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

import httpx
import pytest

from app.services.ingredients.fetch import (
    XML_TYPES,
    FetchLimits,
    FetchRefusedError,
    GuardedFetcher,
    HttpxTransport,
    RawResponse,
    ResponseTooLargeError,
    TransportFailureError,
    is_public_address,
)

pytestmark = pytest.mark.usefixtures("no_network")

DOMAINS = ("sunfield.example",)
PUBLIC_IP = "93.184.216.34"
LIMITS = FetchLimits(
    timeout_seconds=5.0,
    max_bytes=10_000,
    max_redirects=2,
    user_agent="Anupalan/1.0 (+https://anupalan.example/bot)",
)
HTML = {"content-type": "text/html; charset=utf-8"}
NOT_FOUND = RawResponse(status=404, headers={"content-type": "text/html"}, body=b"")


class FakeTransport:
    def __init__(self, responses: Mapping[str, RawResponse | Exception]) -> None:
        self.responses = dict(responses)
        self.calls: list[dict[str, object]] = []

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
        self.calls.append(
            {
                "url": url,
                "connect_ip": connect_ip,
                "host": host,
                "headers": dict(headers),
                "max_bytes": max_bytes,
            }
        )
        response = self.responses.get(url)
        if response is None:
            if url.endswith("/robots.txt"):
                return NOT_FOUND
            raise AssertionError(f"unexpected request to {url}")
        if isinstance(response, Exception):
            raise response
        return response

    def urls(self) -> list[str]:
        return [str(call["url"]) for call in self.calls]


class FakeResolver:
    def __init__(
        self,
        answers: Mapping[str, Sequence[str]] | None = None,
        default: Sequence[str] = (PUBLIC_IP,),
    ) -> None:
        self.answers = dict(answers or {})
        self.default = tuple(default)
        self.calls: list[str] = []

    def __call__(self, host: str) -> Sequence[str]:
        self.calls.append(host)
        return self.answers.get(host, self.default)


def page(body: bytes = b"<title>Oats</title>", headers: Mapping[str, str] = HTML) -> RawResponse:
    return RawResponse(status=200, headers=dict(headers), body=body)


def redirect(location: str, status: int = 302) -> RawResponse:
    return RawResponse(status=status, headers={"location": location}, body=b"")


def fetcher(
    transport: FakeTransport, resolver: FakeResolver | None = None, limits: FetchLimits = LIMITS
) -> GuardedFetcher:
    return GuardedFetcher(limits=limits, resolver=resolver or FakeResolver(), transport=transport)


def refusal(call: object) -> FetchRefusedError:
    with pytest.raises(FetchRefusedError) as caught:
        call()  # type: ignore[operator]
    return caught.value


# --------------------------------------------------------------------------- the happy path


def test_a_registry_page_is_fetched_through_the_validated_address() -> None:
    body = b"<title>Sunfield Masala Oats</title>"
    transport = FakeTransport({"https://sunfield.example/oats": page(body)})

    result = fetcher(transport).fetch("https://sunfield.example/oats", allowed_domains=DOMAINS)

    assert result.status == 200
    assert result.body == body
    assert result.sha256 == hashlib.sha256(body).hexdigest()
    assert result.final_url == "https://sunfield.example/oats"
    assert result.content_type == "text/html; charset=utf-8"

    page_call = transport.calls[-1]
    assert page_call["connect_ip"] == PUBLIC_IP
    assert page_call["host"] == "sunfield.example"
    headers = page_call["headers"]
    assert isinstance(headers, dict)
    assert headers["User-Agent"] == LIMITS.user_agent
    assert not {"cookie", "authorization"} & {key.lower() for key in headers}


def test_a_subdomain_of_a_registry_domain_is_allowed() -> None:
    transport = FakeTransport({"https://www.sunfield.example/oats": page()})
    assert (
        fetcher(transport)
        .fetch("https://www.sunfield.example/oats", allowed_domains=DOMAINS)
        .status
        == 200
    )


# --------------------------------------------------------------------------- the URL itself


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://sunfield.example/oats", "scheme_not_allowed"),
        ("ftp://sunfield.example/oats", "scheme_not_allowed"),
        ("https://sunfield.example:8443/oats", "port_not_allowed"),
        ("https://user:pw@sunfield.example/oats", "host_not_allowed"),
        ("https://evil.example/oats", "host_not_allowed"),
        ("https://sunfield.example.evil.com/oats", "host_not_allowed"),
        ("https://notsunfield.example/oats", "host_not_allowed"),
        ("https://93.184.216.34/oats", "host_not_allowed"),
        ("https://[::1]/oats", "host_not_allowed"),
        ("https:///oats", "host_not_allowed"),
    ],
)
def test_a_url_outside_the_registry_is_refused_before_any_lookup(url: str, reason: str) -> None:
    transport = FakeTransport({})
    resolver = FakeResolver()
    refused = refusal(lambda: fetcher(transport, resolver).fetch(url, allowed_domains=DOMAINS))

    assert refused.reason == reason
    assert resolver.calls == []
    assert transport.calls == []


def test_an_explicit_443_is_allowed() -> None:
    transport = FakeTransport({"https://sunfield.example:443/oats": page()})
    assert (
        fetcher(transport)
        .fetch("https://sunfield.example:443/oats", allowed_domains=DOMAINS)
        .status
        == 200
    )


# --------------------------------------------------------------------------- addresses


PRIVATE = [
    "127.0.0.1",
    "10.1.2.3",
    "172.16.0.5",
    "192.168.1.1",
    "169.254.169.254",
    "100.64.0.1",
    "0.0.0.0",  # noqa: S104 — a refused address under test, not a bind
    "224.0.0.1",
    "240.0.0.1",
    "255.255.255.255",
    "::1",
    "::",
    "fe80::1",
    "fc00::1",
    "ff02::1",
    "::ffff:127.0.0.1",
    "::ffff:10.0.0.1",
    "2002:7f00:0001::1",  # 6to4 wrapping 127.0.0.1
]


@pytest.mark.parametrize("address", PRIVATE)
def test_non_public_addresses_are_not_public(address: str) -> None:
    assert is_public_address(address) is False


@pytest.mark.parametrize("address", [PUBLIC_IP, "8.8.8.8", "2606:4700:4700::1111"])
def test_public_addresses_are_public(address: str) -> None:
    assert is_public_address(address) is True


@pytest.mark.parametrize("address", PRIVATE)
def test_a_host_resolving_to_a_non_public_address_is_never_contacted(address: str) -> None:
    transport = FakeTransport({})
    resolver = FakeResolver(default=(address,))
    refused = refusal(
        lambda: fetcher(transport, resolver).fetch(
            "https://sunfield.example/oats", allowed_domains=DOMAINS
        )
    )

    assert refused.reason == "address_not_allowed"
    assert transport.calls == []


def test_one_private_address_in_the_answer_refuses_the_whole_host() -> None:
    """A mixed answer is how rebinding is usually staged. Picking the public one and hoping is not a
    defence."""
    transport = FakeTransport({})
    resolver = FakeResolver(default=(PUBLIC_IP, "10.0.0.7"))
    refused = refusal(
        lambda: fetcher(transport, resolver).fetch(
            "https://sunfield.example/oats", allowed_domains=DOMAINS
        )
    )
    assert refused.reason == "address_not_allowed"


def test_a_resolution_failure_is_refused() -> None:
    def broken(host: str) -> Sequence[str]:
        raise OSError("no such host")

    transport = FakeTransport({})
    guarded = GuardedFetcher(limits=LIMITS, resolver=broken, transport=transport)
    assert (
        refusal(
            lambda: guarded.fetch("https://sunfield.example/oats", allowed_domains=DOMAINS)
        ).reason
        == "dns_failed"
    )


def test_an_empty_resolution_is_refused() -> None:
    transport = FakeTransport({})
    resolver = FakeResolver(default=())
    refused = refusal(
        lambda: fetcher(transport, resolver).fetch(
            "https://sunfield.example/oats", allowed_domains=DOMAINS
        )
    )
    assert refused.reason == "dns_failed"


def test_rebinding_cannot_move_the_connection_after_the_check() -> None:
    """The first answer is public and is validated; every later answer is private. The connection
    must go to the address that was checked, and the name must not be looked up a second time."""
    answers = iter([[PUBLIC_IP]])

    class Rebinding:
        calls = 0

        def __call__(self, host: str) -> Sequence[str]:
            Rebinding.calls += 1
            return next(answers, ["127.0.0.1"])

    transport = FakeTransport({"https://sunfield.example/oats": page()})
    guarded = GuardedFetcher(limits=LIMITS, resolver=Rebinding(), transport=transport)

    guarded.fetch("https://sunfield.example/oats", allowed_domains=DOMAINS, check_robots=False)

    assert Rebinding.calls == 1
    assert transport.calls[0]["connect_ip"] == PUBLIC_IP


# --------------------------------------------------------------------------- redirects


def test_a_relative_redirect_is_followed() -> None:
    transport = FakeTransport(
        {
            "https://sunfield.example/oats": redirect("/v2/oats", 301),
            "https://sunfield.example/v2/oats": page(),
        }
    )
    result = fetcher(transport).fetch("https://sunfield.example/oats", allowed_domains=DOMAINS)
    assert result.url == "https://sunfield.example/oats"
    assert result.final_url == "https://sunfield.example/v2/oats"


@pytest.mark.parametrize(
    ("location", "answers", "reason"),
    [
        (
            "https://internal.sunfield.example/admin",
            {"internal.sunfield.example": ["10.0.0.1"]},
            "address_not_allowed",
        ),
        ("https://evil.example/", {}, "host_not_allowed"),
        ("http://sunfield.example/oats", {}, "scheme_not_allowed"),
        ("https://169.254.169.254/latest/meta-data/", {}, "host_not_allowed"),
    ],
)
def test_every_redirect_hop_is_checked_again(
    location: str, answers: Mapping[str, Sequence[str]], reason: str
) -> None:
    transport = FakeTransport({"https://sunfield.example/oats": redirect(location)})
    resolver = FakeResolver(answers)
    refused = refusal(
        lambda: fetcher(transport, resolver).fetch(
            "https://sunfield.example/oats", allowed_domains=DOMAINS
        )
    )

    assert refused.reason == reason
    assert location not in transport.urls()


def test_redirects_are_capped() -> None:
    transport = FakeTransport(
        {
            "https://sunfield.example/a": redirect("/b"),
            "https://sunfield.example/b": redirect("/c"),
            "https://sunfield.example/c": redirect("/d"),
            "https://sunfield.example/d": page(),
        }
    )
    refused = refusal(
        lambda: fetcher(transport).fetch("https://sunfield.example/a", allowed_domains=DOMAINS)
    )
    assert refused.reason == "too_many_redirects"


def test_redirects_up_to_the_cap_are_followed() -> None:
    transport = FakeTransport(
        {
            "https://sunfield.example/a": redirect("/b"),
            "https://sunfield.example/b": redirect("/c"),
            "https://sunfield.example/c": page(),
        }
    )
    assert (
        fetcher(transport)
        .fetch("https://sunfield.example/a", allowed_domains=DOMAINS)
        .final_url.endswith("/c")
    )


def test_a_redirect_without_a_location_is_an_http_error() -> None:
    transport = FakeTransport(
        {"https://sunfield.example/oats": RawResponse(status=302, headers={}, body=b"")}
    )
    refused = refusal(
        lambda: fetcher(transport).fetch("https://sunfield.example/oats", allowed_domains=DOMAINS)
    )
    assert refused.reason == "http_error"


# --------------------------------------------------------------------------- the response


def test_the_transport_is_given_the_byte_cap() -> None:
    transport = FakeTransport({"https://sunfield.example/oats": page()})
    fetcher(transport).fetch("https://sunfield.example/oats", allowed_domains=DOMAINS)
    assert transport.calls[-1]["max_bytes"] == LIMITS.max_bytes


def test_an_oversized_body_is_refused() -> None:
    transport = FakeTransport(
        {"https://sunfield.example/oats": ResponseTooLargeError("stream passed the cap")}
    )
    refused = refusal(
        lambda: fetcher(transport).fetch("https://sunfield.example/oats", allowed_domains=DOMAINS)
    )
    assert refused.reason == "too_large"


def test_the_cap_is_enforced_even_if_a_transport_ignores_it() -> None:
    transport = FakeTransport(
        {"https://sunfield.example/oats": page(b"x" * (LIMITS.max_bytes + 1))}
    )
    refused = refusal(
        lambda: fetcher(transport).fetch("https://sunfield.example/oats", allowed_domains=DOMAINS)
    )
    assert refused.reason == "too_large"


@pytest.mark.parametrize(
    "content_type", ["application/pdf", "image/png", "application/javascript", ""]
)
def test_a_content_type_outside_the_allow_list_is_refused(content_type: str) -> None:
    headers = {"content-type": content_type} if content_type else {}
    transport = FakeTransport({"https://sunfield.example/oats": page(headers=headers)})
    refused = refusal(
        lambda: fetcher(transport).fetch("https://sunfield.example/oats", allowed_domains=DOMAINS)
    )
    assert refused.reason == "content_type_not_allowed"


def test_content_type_matching_ignores_case_and_parameters() -> None:
    transport = FakeTransport(
        {
            "https://sunfield.example/oats": page(
                headers={"content-type": "Text/HTML; Charset=UTF-8"}
            )
        }
    )
    assert (
        fetcher(transport).fetch("https://sunfield.example/oats", allowed_domains=DOMAINS).status
        == 200
    )


def test_the_accept_list_is_per_call() -> None:
    xml = page(b"<urlset/>", headers={"content-type": "application/xml"})
    transport = FakeTransport({"https://sunfield.example/sitemap.xml": xml})
    guarded = fetcher(transport)
    assert (
        guarded.fetch(
            "https://sunfield.example/sitemap.xml", allowed_domains=DOMAINS, accept=XML_TYPES
        ).status
        == 200
    )
    refused = refusal(
        lambda: guarded.fetch("https://sunfield.example/sitemap.xml", allowed_domains=DOMAINS)
    )
    assert refused.reason == "content_type_not_allowed"


def test_a_non_200_status_is_an_http_error_with_the_status() -> None:
    transport = FakeTransport(
        {"https://sunfield.example/oats": RawResponse(status=404, headers=HTML, body=b"")}
    )
    refused = refusal(
        lambda: fetcher(transport).fetch("https://sunfield.example/oats", allowed_domains=DOMAINS)
    )
    assert refused.reason == "http_error"
    assert refused.status == 404


@pytest.mark.parametrize("reason", ["timeout", "connection_failed"])
def test_a_transport_failure_keeps_its_reason(reason: str) -> None:
    transport = FakeTransport({"https://sunfield.example/oats": TransportFailureError(reason)})  # type: ignore[arg-type]
    refused = refusal(
        lambda: fetcher(transport).fetch("https://sunfield.example/oats", allowed_domains=DOMAINS)
    )
    assert refused.reason == reason


# --------------------------------------------------------------------------- robots.txt


def robots(body: str, status: int = 200) -> RawResponse:
    return RawResponse(
        status=status, headers={"content-type": "text/plain"}, body=body.encode("utf-8")
    )


def test_a_path_disallowed_by_robots_is_never_requested() -> None:
    transport = FakeTransport(
        {
            "https://sunfield.example/robots.txt": robots("User-agent: *\nDisallow: /oats\n"),
            "https://sunfield.example/oats": page(),
        }
    )
    refused = refusal(
        lambda: fetcher(transport).fetch("https://sunfield.example/oats", allowed_domains=DOMAINS)
    )
    assert refused.reason == "robots_disallowed"
    assert "https://sunfield.example/oats" not in transport.urls()


def test_a_rule_naming_this_agent_applies() -> None:
    transport = FakeTransport(
        {
            "https://sunfield.example/robots.txt": robots(
                "User-agent: Anupalan\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
            ),
            "https://sunfield.example/oats": page(),
        }
    )
    refused = refusal(
        lambda: fetcher(transport).fetch("https://sunfield.example/oats", allowed_domains=DOMAINS)
    )
    assert refused.reason == "robots_disallowed"


def test_a_missing_robots_file_allows_everything() -> None:
    transport = FakeTransport({"https://sunfield.example/oats": page()})
    assert (
        fetcher(transport).fetch("https://sunfield.example/oats", allowed_domains=DOMAINS).status
        == 200
    )


def test_an_unreachable_robots_file_disallows_everything() -> None:
    """RFC 9309 §2.3.1.4: a server error on robots.txt means assume complete disallow."""
    transport = FakeTransport(
        {
            "https://sunfield.example/robots.txt": robots("", status=503),
            "https://sunfield.example/oats": page(),
        }
    )
    refused = refusal(
        lambda: fetcher(transport).fetch("https://sunfield.example/oats", allowed_domains=DOMAINS)
    )
    assert refused.reason == "robots_disallowed"


def test_robots_is_read_once_per_host() -> None:
    transport = FakeTransport(
        {
            "https://sunfield.example/robots.txt": robots("User-agent: *\nAllow: /\n"),
            "https://sunfield.example/a": page(),
            "https://sunfield.example/b": page(),
        }
    )
    guarded = fetcher(transport)
    guarded.fetch("https://sunfield.example/a", allowed_domains=DOMAINS)
    guarded.fetch("https://sunfield.example/b", allowed_domains=DOMAINS)
    assert transport.urls().count("https://sunfield.example/robots.txt") == 1


def test_sitemaps_are_read_from_robots() -> None:
    transport = FakeTransport(
        {
            "https://sunfield.example/robots.txt": robots(
                "User-agent: *\nAllow: /\nSitemap: https://sunfield.example/sitemap_index.xml\n"
            )
        }
    )
    assert fetcher(transport).sitemaps_for("sunfield.example", allowed_domains=DOMAINS) == (
        "https://sunfield.example/sitemap_index.xml",
    )


# --------------------------------------------------------------------------- the httpx adapter


def test_the_httpx_adapter_connects_to_the_ip_but_verifies_the_hostname() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"<title>ok</title>"
        )

    adapter = HttpxTransport(mock=httpx.MockTransport(handler))
    response = adapter.get(
        url="https://sunfield.example/oats?size=500g",
        connect_ip=PUBLIC_IP,
        host="sunfield.example",
        headers={"User-Agent": LIMITS.user_agent},
        timeout_seconds=5.0,
        max_bytes=10_000,
    )

    assert response.status == 200
    assert response.body == b"<title>ok</title>"
    request = seen[0]
    assert request.url.host == PUBLIC_IP
    assert request.url.path == "/oats"
    assert request.url.query == b"size=500g"
    assert request.headers["host"] == "sunfield.example"
    assert request.extensions["sni_hostname"] == "sunfield.example"


def test_the_httpx_adapter_brackets_an_ipv6_address() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"")

    HttpxTransport(mock=httpx.MockTransport(handler)).get(
        url="https://sunfield.example/",
        connect_ip="2606:4700:4700::1111",
        host="sunfield.example",
        headers={},
        timeout_seconds=5.0,
        max_bytes=100,
    )
    assert seen[0].url.host == "2606:4700:4700::1111"


def test_the_httpx_adapter_does_not_follow_redirects_itself() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://127.0.0.1/"})

    response = HttpxTransport(mock=httpx.MockTransport(handler)).get(
        url="https://sunfield.example/",
        connect_ip=PUBLIC_IP,
        host="sunfield.example",
        headers={},
        timeout_seconds=5.0,
        max_bytes=100,
    )
    assert response.status == 302
    assert response.headers["location"] == "https://127.0.0.1/"


def test_the_httpx_adapter_stops_reading_past_the_cap() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"x" * 5_000)

    with pytest.raises(ResponseTooLargeError):
        HttpxTransport(mock=httpx.MockTransport(handler)).get(
            url="https://sunfield.example/",
            connect_ip=PUBLIC_IP,
            host="sunfield.example",
            headers={},
            timeout_seconds=5.0,
            max_bytes=1_000,
        )


def test_the_httpx_adapter_maps_a_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(TransportFailureError) as caught:
        HttpxTransport(mock=httpx.MockTransport(handler)).get(
            url="https://sunfield.example/",
            connect_ip=PUBLIC_IP,
            host="sunfield.example",
            headers={},
            timeout_seconds=5.0,
            max_bytes=1_000,
        )
    assert caught.value.reason == "timeout"
