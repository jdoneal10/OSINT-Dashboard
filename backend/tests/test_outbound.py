"""Outbound allowlist (ADR 0008 §2): listed domains, active feed hosts and loopback only."""

from __future__ import annotations

import httpx
import pytest

from app.core import outbound
from app.core.outbound import OutboundBlockedError
from app.enrich.llm.client import API_BASE_URL
from app.ingest import acled, cbp, designations, news
from app.ingest.feeds import active
from app.ingest.http import PoliteClient
from app.reference import inegi

PRODUCTION_ALLOWED = outbound.allowed_domains  # captured before conftest's per-test patch


@pytest.fixture
def strict(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop conftest's reserved test domains: the production list only."""
    monkeypatch.setattr(outbound, "allowed_domains", PRODUCTION_ALLOWED)


def test_every_hard_coded_endpoint_is_listed(strict: None) -> None:
    for url in (
        API_BASE_URL,
        acled.BASE,
        cbp.BASE,
        news.GDELT_URL,
        designations.SDN_URL,
        f"https://{designations.SDN_DOWNLOAD_HOST}/Published/x/SDN.XML?X-Amz-Expires=3600",
        designations.FR_API,
        inegi.BASE,
        "http://127.0.0.1:11434",
        "http://localhost:11434",
    ):
        assert outbound.is_allowed(url), url


def test_active_feed_hosts_are_allowed(strict: None) -> None:
    feeds = active()
    assert feeds
    for feed in feeds:
        assert outbound.is_allowed(f"https://{feed.domain}/any/path"), feed.slug
        if feed.url:
            assert outbound.is_allowed(str(feed.url)), feed.slug


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/",
        "https://acleddata.com.evil.example/",  # suffix trick
        "https://notacleddata.com/",
        "https://api.anthropic.com.attacker.example/",
        "https://other-bucket.s3.us-gov-west-1.amazonaws.com/",  # only the OFAC bucket
        "https://s3.us-gov-west-1.amazonaws.com/wc2h-sls-prod-public-published/",
        "http://10.0.0.5/",  # private, not loopback
        "file:///etc/passwd",
        "not a url",
    ],
)
def test_unlisted_hosts_are_blocked(strict: None, url: str) -> None:
    assert not outbound.is_allowed(url)
    with pytest.raises(OutboundBlockedError):
        outbound.check(url)


def test_subdomains_and_www_are_allowed(strict: None) -> None:
    assert outbound.is_allowed("https://www.federalregister.gov/api/v1/documents.json")
    assert outbound.is_allowed("https://gaia.inegi.org.mx/wscatgeo/v2")
    assert outbound.is_allowed("https://ACLEDDATA.com/api")


def test_polite_client_blocks_requests_and_redirect_hops(strict: None) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/hop":
            return httpx.Response(302, headers={"Location": "https://tracker.example.net/x"})
        return httpx.Response(200, text="ok")

    with PoliteClient(transport=httpx.MockTransport(handler), sleep=lambda _: None) as client:
        with pytest.raises(OutboundBlockedError, match=r"elsewhere\.example\.org"):
            client.get("https://elsewhere.example.org/", crawl=False)
        assert client.get(f"{acled.BASE}/ok", crawl=False).status_code == 200
        with pytest.raises(OutboundBlockedError, match=r"tracker\.example\.net"):
            client.get(f"{acled.BASE}/hop", crawl=False)
    # Blocked hosts are never contacted; the redirect target was refused before sending.
    assert seen == [f"{acled.BASE}/ok", f"{acled.BASE}/hop"]
